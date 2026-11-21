"""
Trending music from Instagram's own catalog, and videos cut on its beat (step 178).

Meta's Audio API (Graph, Facebook Login, changelog 2026-06-01; checked live 2026-11-21):
`GET /ig_audio?audio_type=music|original_sound&user_id=` lists the trending audio (with
`search_query`: a search), `GET /{audio_id}` one track, each with a `download_url` to the
full track (AAC, valid ~1.5 days). A Reel container takes
`audio_configuration={audio_id, audio_volume, video_volume}` and Instagram plays its own
licensed copy. So the track is never in our file: we keep a local copy only to find its
beats and to mix the owner's review preview (render.py), and publish the clean video with
the track attached (publish.py). For a business account `music` is the royalty-free library;
the chart hits only come as `original_sound`.

- `fetch()` downloads a track once to `<media root>/music/<audio_id>.m4a` with its beat map
  (`.json`): tempo, beats, downbeats, the drop (where the drums kick in).
- `on_beats()` moves the voice lines onto that grid: every template starts a scene when a
  line starts (motion/src/lib/timeline.ts), so every template cuts on the beat.

Beat finding is stdlib + ffmpeg (no numpy): band energy flux, tempo by autocorrelation, beats
by dynamic programming (Ellis 2007), downbeat = the beat phase with the most kick energy.
ponytail: 4/4 and a steady tempo assumed (library tracks are); CPJKU/beat_this (MIT, CPU
`small0`) if the grid slips on real tracks.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import tempfile
from array import array
from operator import mul
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

import httpx

from . import ffmpeg, media, recipe

AUDIO_ID = re.compile(r"^\d{5,25}$")
AUDIO_TYPES = ("music", "original_sound")
SR = 11025
HOP = 256  # ~23 ms analysis frames
FPS = SR / HOP
MIN_BPM, MAX_BPM, PREFERRED_BPM = 60.0, 180.0, 120.0
TIGHTNESS = 100.0  # DP penalty on beat gaps away from the period (librosa's default)
DROP_RATIO = 2.0  # kick-band energy x2 over the bars before it (+3 dB) = the drums kick in
LINE_GAP_S = 0.15  # least silence between two voice lines
DOWNBEAT_WAIT_S = 0.6  # a line waits this long at most for a downbeat, else the next beat
UNDER_VOICE_LU = 15.0  # the track under a voice (memory audio-mix: voice clearly on top)
ALONE_LUFS = -14.0  # the track with no voice: the Reel's usual loudness
END_ROOM_S = 5.0  # the outro / end card after the last line, still under the track
TIMEOUT_S = 120.0
DOWNLOAD_HOSTS = (".fbcdn.net", ".cdninstagram.com")


def music_dir(media_root: Any) -> Path:
    return Path(media_root) / "music"


def check_id(audio_id: str) -> str:
    if not AUDIO_ID.match(str(audio_id)):
        raise ValueError(f"not an Instagram audio id: {audio_id!r}")
    return str(audio_id)


def brief(a: Dict[str, Any]) -> Dict[str, Any]:
    """A track as the agent sees it (no URLs)."""
    return {"audio_id": a["audio_id"], "title": a.get("title"),
            "artist": a.get("display_artist") or a.get("ig_username"),
            "type": a.get("audio_type"), "duration_s": round((a.get("duration_in_ms") or 0) / 1000)}


async def trending(client: Any, query: Optional[str] = None,
                   audio_type: str = "music") -> List[Dict[str, Any]]:
    """Instagram's trending audio (a search with `query`), briefs."""
    if audio_type not in AUDIO_TYPES:
        raise ValueError(f"audio_type must be one of {AUDIO_TYPES}")
    return [brief(a) for a in await client.search_audio(audio_type, query)]


def load(media_root: Any, audio_id: str) -> Dict[str, Any]:
    """A fetched track's metadata and beat map; ValueError when not fetched."""
    meta = music_dir(media_root) / f"{check_id(audio_id)}.json"
    if not meta.is_file():
        raise ValueError(f"track {audio_id} is not fetched: fetch_music first")
    return json.loads(meta.read_text(encoding="utf-8"))


async def fetch(client: Any, media_root: Any, audio_id: str, *,
                http: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    """Download a track (once) and map its beats; returns the stored metadata."""
    check_id(audio_id)
    try:
        return load(media_root, audio_id)
    except ValueError:
        pass
    info = await client.get_audio(audio_id)
    url = info.get("download_url") or ""
    host = urlparse(url).hostname or ""
    if urlparse(url).scheme != "https" or not host.endswith(DOWNLOAD_HOSTS):
        raise ValueError(f"track {audio_id}: no Instagram download link")
    folder = music_dir(media_root)
    folder.mkdir(parents=True, exist_ok=True)
    track = folder / f"{audio_id}.m4a"
    own = http is None
    http = http or httpx.AsyncClient(timeout=60, follow_redirects=True)
    try:  # a signed CDN link: never our token
        r = await http.get(url)
        r.raise_for_status()
    finally:
        if own:
            await http.aclose()
    track.write_bytes(r.content)
    meta = {**brief(info), "track": media.relative(media_root, track),
            **await asyncio.to_thread(measure, track)}  # ffmpeg + pure Python: off the loop
    (folder / f"{audio_id}.json").write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    return meta


# --- Beats ----------------------------------------------------------------------------------

def _band(path: Path, band: str) -> array:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "a.f32"
        ffmpeg.run(["-i", path, "-vn", "-af", band, "-ac", "1", "-ar", SR, "-f", "f32le", out],
                   timeout_s=TIMEOUT_S)
        samples = array("f")
        samples.frombytes(out.read_bytes())
    return samples


def _energy(samples: Sequence[float]) -> List[float]:
    return [sum(map(mul, samples[i:i + HOP], samples[i:i + HOP])) / HOP
            for i in range(0, len(samples) - HOP + 1, HOP)]


def _flux(energy: Sequence[float]) -> List[float]:
    """Rises of log energy: where something is struck."""
    logs = [math.log(e + 1e-10) for e in energy]
    return [0.0, *(max(0.0, b - a) for a, b in zip(logs, logs[1:]))]


def tempo_period(onset: Sequence[float]) -> int:
    """The beat period in frames: autocorrelation weighted toward PREFERRED_BPM."""
    mean = sum(onset) / len(onset)
    o = [x - mean for x in onset]
    best, period = -math.inf, 0
    for lag in range(int(FPS * 60 / MAX_BPM), int(FPS * 60 / MIN_BPM) + 1):
        ac = sum(map(mul, o[:-lag], o[lag:])) / (len(o) - lag)
        bpm = 60 * FPS / lag
        score = ac * math.exp(-0.5 * math.log2(bpm / PREFERRED_BPM) ** 2)
        if score > best:
            best, period = score, lag
    return period


def track_beats(onset: Sequence[float], period: int) -> List[int]:
    """Beat frames: each beat is a strong onset about one period after the one before."""
    n = len(onset)
    score = list(onset)
    back = [-1] * n
    for t in range(n):
        best, arg = 0.0, -1
        for prev in range(max(0, t - 2 * period), t - period // 2):
            s = score[prev] - TIGHTNESS * math.log((t - prev) / period) ** 2
            if arg < 0 or s > best:
                best, arg = s, prev
        if arg >= 0 and best > 0:
            score[t] += best
            back[t] = arg
    # the last beat: the best-scored frame in the final period
    t = max(range(max(0, n - period), n), key=score.__getitem__)
    beats = [t]
    while back[t] >= 0:
        t = back[t]
        beats.append(t)
    return beats[::-1]


def beat_map(full: Sequence[float], kick: Sequence[float]) -> Dict[str, Any]:
    """{bpm, beats, downbeats, drop_s} from the band energies (frames of HOP samples)."""
    n = min(len(full), len(kick))
    kick_flux = _flux(kick[:n])
    onset = [a + b for a, b in zip(_flux(full[:n]), kick_flux)]
    if n < 4 * FPS or not any(onset):
        return {"bpm": None, "beats": [], "downbeats": [], "drop_s": None}
    period = tempo_period(onset)
    beats = track_beats(onset, period)

    def kick_at(f: int) -> float:
        return max(kick_flux[max(0, f - 2):f + 3])

    phase = max(range(4), key=lambda k: sum(map(kick_at, beats[k::4])))
    downbeats = beats[phase::4]
    drop = None
    if len(downbeats) > 4:
        def level(a: int, b: int) -> float:
            return sum(kick[a:b]) / max(1, b - a)
        best = DROP_RATIO
        for j in range(2, len(downbeats) - 2):
            d0, d1, d2 = downbeats[j - 2], downbeats[j], downbeats[j + 2]
            ratio = level(d1, d2) / max(level(d0, d1), 1e-12)
            if ratio > best:
                best, drop = ratio, d1
    s = [round(f / FPS, 3) for f in beats]
    return {"bpm": round(60 * FPS / period, 1), "beats": s,
            "downbeats": [round(f / FPS, 3) for f in downbeats],
            "drop_s": None if drop is None else round(drop / FPS, 3)}


def measure(path: Path) -> Dict[str, Any]:
    """{duration_s, lufs, bpm, beats, downbeats, drop_s} of a track file."""
    full = _energy(_band(path, "highpass=f=40"))
    kick = _energy(_band(path, "lowpass=f=150"))
    return {"duration_s": round(len(full) / FPS, 3),
            "lufs": recipe.loudness(path, timeout_s=TIMEOUT_S)[0], **beat_map(full, kick)}


# --- The voice on the beat --------------------------------------------------------------------

def on_beats(lines: Sequence[Dict[str, Any]], grid: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The voice lines moved onto the beat grid, each keeping its length: the hook stays
    where it is, every next line starts on the drop when it is at most a bar away, else on
    a downbeat within DOWNBEAT_WAIT_S, else on the next beat, never closer than LINE_GAP_S
    to the line before."""
    beats, downbeats, drop = grid["beats"], grid["downbeats"], grid.get("drop_s")
    bar = 4 * 60 / grid["bpm"] if grid.get("bpm") else 0
    out: List[Dict[str, Any]] = []
    for i, line in enumerate(lines):
        length = line["end_s"] - line["start_s"]
        start = line["start_s"]
        if i:
            earliest = out[-1]["end_s"] + LINE_GAP_S
            nxt = [b for b in beats if b >= earliest]
            down = [d for d in downbeats if earliest <= d <= earliest + DOWNBEAT_WAIT_S]
            if drop is not None and earliest <= drop <= earliest + bar:
                start = drop
            elif down:
                start = down[0]
            else:
                start = nxt[0] if nxt else earliest
        out.append({**line, "start_s": round(start, 3), "end_s": round(start + length, 3)})
    return out


def retime_voice(src: Path, old: Sequence[Dict[str, Any]], new: Sequence[Dict[str, Any]],
                 dest_dir: Path) -> Path:
    """The voice file with each line moved from its `old` to its `new` start (one ffmpeg
    call; the pauses between lines become silence). Written once per timing."""
    key = hashlib.sha256(json.dumps([src.name, list(old), list(new)]).encode()).hexdigest()[:12]
    out = dest_dir / f"{src.stem}.beat-{key}.wav"
    if out.is_file():
        return out
    parts, labels = [], []
    for i, (a, b) in enumerate(zip(old, new)):
        end = old[i + 1]["start_s"] if i + 1 < len(old) else a["end_s"] + 0.3
        end = min(end, a["end_s"] + 0.3)  # the line and its breath, not the next line
        parts.append(f"[0:a]atrim=start={a['start_s']}:end={end},asetpts=PTS-STARTPTS,"
                     f"adelay={round(b['start_s'] * 1000)}:all=1[l{i}]")
        labels.append(f"[l{i}]")
    graph = ";".join(parts) + f";{''.join(labels)}amix=inputs={len(labels)}:normalize=0[a]"
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest_dir) as work:
        tmp = Path(work) / "voice.wav"
        ffmpeg.run(["-i", src, "-filter_complex", graph, "-map", "[a]",
                    "-ar", recipe.SAMPLE_RATE, "-c:a", "pcm_s16le", tmp], timeout_s=TIMEOUT_S)
        tmp.replace(out)
    return out


def apply(props: Dict[str, Any], media_root: Any, audio_id: str) -> tuple:
    """Props cut on the track's beat with the template's own bed off, and the recipe's
    `ig_audio` (what publish attaches, what the preview mixes). ValueError when the track
    is not fetched or has no beat."""
    meta = load(media_root, audio_id)
    if not meta.get("beats"):
        raise ValueError(f"track {audio_id}: no beat found, pick another track")
    props = {**props, "music": "none"}
    voice = props.get("voice")
    voiced = bool(voice and voice.get("audioSrc"))
    if voice and voice.get("lines"):
        lines = on_beats(voice["lines"], meta)
        if lines[-1]["end_s"] + END_ROOM_S > meta["duration_s"]:
            raise ValueError(f"track {audio_id} ({meta['duration_s']:g} s) is shorter than "
                             "the video: pick a longer one")
        voice = {**voice, "lines": lines}
        if voiced:
            src = media.resolve(media_root, voice["audioSrc"])
            moved = retime_voice(src, props["voice"]["lines"], lines, src.parent)
            voice["audioSrc"] = media.relative(media_root, moved)
        props["voice"] = voice
    target = recipe.VOICE_REF_LUFS - UNDER_VOICE_LU if voiced else ALONE_LUFS
    gain = 100 if meta.get("lufs") is None else 100 * 10 ** ((target - meta["lufs"]) / 20)
    ig_audio = {"audio_id": audio_id, "title": meta.get("title"), "artist": meta.get("artist"),
                "track": meta["track"], "audio_volume": max(1, min(100, round(gain))),
                "video_volume": 100}
    return props, ig_audio


def preview_args(ig_audio: Dict[str, Any], has_audio: bool) -> List[str]:
    """ffmpeg arguments (after the video input) that mix the track into the review preview
    the way Instagram's volumes will (input 1 = the track)."""
    m = f"[1:a]volume={ig_audio['audio_volume'] / 100:.3f}"
    if not has_audio:
        return ["-filter_complex", f"{m}[a]", "-map", "0:v", "-map", "[a]", "-shortest"]
    v = f"[0:a]volume={ig_audio['video_volume'] / 100:.3f}[v]"
    return ["-filter_complex", f"{m}[m];{v};[v][m]amix=inputs=2:duration=first:normalize=0[a]",
            "-map", "0:v", "-map", "[a]"]
