"""
The render QC listens (step 149): is the voice clearly above the rest of the mix, are there
harsh peaks or sudden jumps, does each point sound land on its cut. No models: ffmpeg
(`ebur128` in the QC analysis pass, PCM decoding here) and the standard library.

Earshot (github.com/Leonxlnx/earshot, MIT) does this kind of listening for agents, but it
needs PyTorch and ~1.1 GB of models and loads them for 20-40 s per CLI call; its model-free
part (`measure`: LUFS, true peak, envelope) is what ffmpeg already gives us. So the checks
are built here, on what the render has: the master and the voice track it was mixed from.

Voice above the bed: both are decoded K-weighted (the BS.1770 filter, so power ratios read as
LU), mono, 16 kHz. The voice track's own activity gives the spoken spans; each span is
placed in the master where the template plays that part of the voice (`parts`: PixelSkit and
QuizChest pause the voice, step 158; everything else plays it from 0), matched to the sample
there, the master's gain on the voice is measured span by span, and what remains of the
master's power in a span, once the voice is taken out, is the bed: music, sound effects,
original sound.
"""

from __future__ import annotations

import math
import re
import statistics
import tempfile
from array import array
from operator import mul
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import ffmpeg, media
from .ffmpeg import PathLike
from .recipe import TRUE_PEAK_MAX

SR = 16_000
HOP = SR // 100  # 10 ms envelope steps
# BS.1770 K-weighting (pre-filter shelf + RLB high-pass), close enough for power ratios
K_WEIGHT = "highpass=f=38:poles=2,highshelf=f=1681:g=4"

VOICE_ABOVE_LU = 12.0  # the bed sits at least this far under the voice while it speaks
JUMP_LU, JUMP_S = 6.0, 0.3  # a jump of more than JUMP_LU within JUMP_S ...
# ... that lands more than JUMP_LU above the video's integrated loudness (the voice level):
# speech onsets jump 10-20 LU in momentary loudness but land near it.
SYNC_S = 0.08  # a point sound starts this close to its cut
ONSET_DB = 6.0  # a sound "starts" where the 10 ms power rises this much over the 50 ms before

VOICE_ON_DB = -30.0  # voice activity: within this of the voice track's loud level
SPAN_GAP_S, SPAN_MIN_S = 0.25, 0.4  # shorter pauses stay in a span; shorter spans are dropped
FINE_S, FINE_CHUNK_S = 0.02, 0.2  # sample-exact match: lag search on a span's loudest chunk
WINDOW_STEPS = 40  # 400 ms, the momentary loudness window
MAX_LU = 40.0  # nothing else heard
MIN_MATCH = 0.5  # sample correlation of the voice with the master, else it is not in the mix

PLANNED_BANG = re.compile(r"\b(bang|burst)\b", re.IGNORECASE)  # timeline labels of planned hits
POINT_SOUND = re.compile(r"^(sting|sfx|sound):", re.IGNORECASE)  # timeline point sounds


def pcm(path: PathLike, *, timeout_s: float) -> array:
    """The audio of `path`, K-weighted, mono, SR Hz, as float samples."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "audio.f32"
        ffmpeg.run(["-i", path, "-vn", "-af", K_WEIGHT, "-ac", "1", "-ar", SR,
                    "-f", "f32le", out], timeout_s=timeout_s)
        samples = array("f")
        samples.frombytes(out.read_bytes())
    return samples


def envelope(samples: Sequence[float]) -> List[float]:
    """Mean power of each 10 ms step."""
    return [sum(map(mul, samples[i:i + HOP], samples[i:i + HOP])) / HOP
            for i in range(0, len(samples) - HOP + 1, HOP)]


def _db(power: float) -> float:
    return 10 * math.log10(power) if power > 0 else -200.0


def speech_spans(env: Sequence[float]) -> List[Tuple[int, int]]:
    """Spans [start, end) in steps where the voice track speaks."""
    loud = sorted(env)[int(0.95 * (len(env) - 1))] if env else 0.0
    if loud <= 0:
        return []
    on = loud * 10 ** (VOICE_ON_DB / 10)
    gap, least = round(SPAN_GAP_S * 100), round(SPAN_MIN_S * 100)
    spans: List[Tuple[int, int]] = []
    start = last = None
    for i, p in enumerate(env):
        if p <= on:
            continue
        if start is None or i - last > gap:
            if start is not None:
                spans.append((start, last + 1))
            start = i
        last = i
    if start is not None:
        spans.append((start, last + 1))
    return [(a, b) for a, b in spans if b - a >= least]


def _match(v: Sequence[float], m: Sequence[float], ev: Sequence[float], a: int, b: int,
           lag: int) -> Tuple[float, float]:
    """(correlation of the voice with the master on the span's loudest FINE_CHUNK_S, the
    voice's LU above the rest of the master in span [a, b)), `lag` (steps) refined to the
    sample on that chunk. Over the span the master is the voice at its gain there (its
    projection, so a dynamic loudnorm is followed span by span) plus the rest; the span's
    figure is the median over 400 ms windows (momentary loudness), so a short sound effect
    does not decide it (harsh_jumps() hears the loud ones)."""
    n = round(FINE_CHUNK_S * 100)
    top = max(range(a, max(b - n, a) + 1), key=lambda i: sum(ev[i:i + n]))
    chunk = v[top * HOP:(top + n) * HOP]
    pc = sum(map(mul, chunk, chunk))

    def corr(o: int) -> float:
        seg = m[o:o + len(chunk)]
        pm = sum(map(mul, seg, seg))
        return sum(map(mul, chunk, seg)) / math.sqrt(pc * pm) if pc > 0 and pm > 0 else 0.0

    base, reach, last = (top + lag) * HOP, round(FINE_S * SR), len(m) - len(chunk)
    at = max(range(max(base - reach, 0), min(base + reach, last) + 1), key=corr, default=base)
    shift = at - top * HOP
    lo, hi = max(a * HOP, -shift), min(b * HOP, len(m) - shift)
    x, y = v[lo:hi], m[lo + shift:hi + shift]
    px = sum(map(mul, x, x))
    g = sum(map(mul, x, y)) / px if px > 0 else 0.0
    voice = envelope([g * s for s in x])
    rest = envelope([s - g * t for s, t in zip(y, x)])
    w = WINDOW_STEPS
    ratios = [_db(sum(voice[i:i + w])) - _db(sum(rest[i:i + w]))
              for i in range(0, max(len(voice) - w, 0) + 1, 10)]
    lu = min(statistics.median(ratios), MAX_LU) if ratios else 0.0  # capped: nothing else heard
    return corr(at), lu


Parts = Sequence[Mapping[str, float]]  # [{audio_s, at_s}]: the voice from audio_s plays at at_s
VOICE_FROM_START: Parts = [{"audio_s": 0.0, "at_s": 0.0}]  # the whole voice file from 0


def placed(spans: Sequence[Tuple[int, int]], parts: Optional[Parts]
           ) -> List[Tuple[int, int, int]]:
    """(start, end, lag) in steps: `spans` (voice time) cut where a part of the voice starts,
    each piece with its part's lag (video minus voice time). No parts: the voice from 0."""
    edges = sorted((round(p["audio_s"] * 100), round(p["at_s"] * 100) - round(p["audio_s"] * 100))
                   for p in parts or VOICE_FROM_START)
    out = []
    for a, b in spans:
        for k, (start, lag) in enumerate(edges):
            stop = edges[k + 1][0] if k + 1 < len(edges) else b
            lo, hi = max(a, start), min(b, stop)
            if hi - lo >= round(SPAN_MIN_S * 100):  # a piece too short to measure is left out
                out.append((lo, hi, lag))
    return out


def voice_above_bed(master: Sequence[float], voice: Sequence[float],
                    parts: Optional[Parts] = None) -> Optional[List[Dict[str, float]]]:
    """Per spoken span {t (master seconds), d, lu: voice above the rest of the mix}, the
    voice placed by `parts` (see placed()); [] when the voice track never speaks, None when
    it is not heard where it should play."""
    ev = envelope(voice)
    spans = speech_spans(ev)
    if not spans:
        return []
    out, matches, steps = [], [], len(master) // HOP
    for a, b, lag in placed(spans, parts):
        if not 0 <= a + lag < steps:  # a voice longer than the video is cut
            continue
        match, lu = _match(voice, master, ev, a, b, lag)
        matches.append(match)
        out.append({"t": (a + lag) / 100, "d": (b - a) / 100, "lu": round(lu, 1)})
    return out if matches and statistics.median(matches) >= MIN_MATCH else None


def harsh_jumps(momentary: Sequence[Tuple[float, float]], integrated: float,
                planned: Sequence[Tuple[float, float]] = ()) -> List[Tuple[float, float]]:
    """(t, jump LU) where the momentary loudness (one value per 100 ms) jumps more than
    JUMP_LU within JUMP_S to more than JUMP_LU above `integrated`, outside the `planned`
    [start, end] windows. One entry per burst (its biggest jump)."""
    back = round(JUMP_S / 0.1)
    found: List[Tuple[float, float]] = []
    for i in range(back, len(momentary)):
        t, level = momentary[i]
        # -70: the meter's floor (it reads -120 while it fills, at the start of the video)
        jump = level - max(min(m for _, m in momentary[i - back:i]), -70.0)
        if jump <= JUMP_LU or level - integrated <= JUMP_LU:
            continue
        if any(s - JUMP_S <= t <= e + JUMP_S for s, e in planned):
            continue
        if found and t - found[-1][0] <= 1.0:  # same burst
            if jump > found[-1][1]:
                found[-1] = (t, jump)
            continue
        found.append((t, jump))
    return [(round(t, 1), round(j, 1)) for t, j in found]


def onset_near(env: Sequence[float], t: float, reach_s: float = 0.5) -> Optional[float]:
    """When (s) the strongest sound start within `reach_s` of `t` happens, or None when
    nothing rises ONSET_DB there."""
    best, at = ONSET_DB, None
    for i in range(max(round((t - reach_s) * 100), 5), min(round((t + reach_s) * 100),
                                                          len(env) - 1) + 1):
        before = sum(env[i - 5:i]) / 5
        rise = _db(env[i]) - _db(before)
        if rise > best:
            best, at = rise, i / 100
    return at


def voice_track(recipe: Optional[Dict[str, Any]], media_root: PathLike) -> Optional[Path]:
    """The voice file the render mixed in: a motion video's `props.voice.audioSrc` or a
    remix's voice_over input. None without one (or when the file is gone)."""
    env = recipe or {}
    if env.get("kind") == "motion":
        src = ((env.get("props") or {}).get("voice") or {}).get("audioSrc")
    else:
        ops = (env.get("recipe") or {}).get("ops") or []
        name = next((op.get("input", "voice") for op in ops if op.get("op") == "voice_over"),
                    None)
        src = (env.get("inputs") or {}).get(name) if name else None
    if not src or "://" in src:
        return None
    try:
        path = media.resolve(media_root, src)
    except ValueError:
        return None
    return path if path.is_file() else None


def checks(master: Path, voice: Optional[Path], timeline: Optional[Sequence[Dict[str, Any]]],
           analysis: Dict[str, Any], *, timeout_s: float, voice_parts: Optional[Parts] = None
           ) -> List[Tuple[str, bool, str]]:
    """The listening checks (name, ok, detail) for a master with audio. `analysis` is
    qc.analyze()'s result (true peak, momentary loudness, integrated loudness);
    `voice_parts` where the template plays the voice (voice_above_bed())."""
    out: List[Tuple[str, bool, str]] = []
    events = [e for e in timeline or [] if e.get("t") is not None]
    peak = analysis.get("true_peak")
    if peak is not None:
        out.append(("true_peak", peak <= TRUE_PEAK_MAX,
                    f"true peak {peak:g} dBTP (want <= {TRUE_PEAK_MAX:g})"))
    lufs = analysis.get("loudness")
    if lufs is not None and analysis.get("momentary"):
        planned = [(e["t"], e["t"] + e.get("d", 0)) for e in events
                   if PLANNED_BANG.search(e["e"])]
        jumps = harsh_jumps(analysis["momentary"], lufs, planned)
        out.append(("jumps", not jumps, "; ".join(
            f"sudden jump of {j:g} LU at {t:g} s (a sound far above the voice)"
            for t, j in jumps) or f"no jump over {JUMP_LU:g} LU above the voice level"))
    points = [e for e in events if POINT_SOUND.match(e["e"])]
    if not voice and not points:
        return out
    mixed = pcm(master, timeout_s=timeout_s)
    if voice:
        spans = voice_above_bed(mixed, pcm(voice, timeout_s=timeout_s), voice_parts)
        if spans is None:
            out.append(("voice_above_bed", False, "the voice track is not heard in the mix"))
        elif spans:
            ranked = sorted(spans, key=lambda s: s["lu"])
            low = [s for s in ranked if s["lu"] < VOICE_ABOVE_LU]
            detail = "; ".join(
                f"voice only {s['lu']:g} LU above the bed at {s['t']:.1f} s (bed"
                f" {VOICE_ABOVE_LU - s['lu']:.1f} dB too loud)" for s in low[:3])
            if len(low) > 3:
                detail += f"; {len(low) - 3} more spans under {VOICE_ABOVE_LU:g} LU"
            out.append(("voice_above_bed", not low, detail or (
                f"voice {ranked[0]['lu']:g} LU or more above the bed (want >= "
                f"{VOICE_ABOVE_LU:g}, closest at {ranked[0]['t']:.1f} s)")))
    if points:
        env = envelope(mixed)
        late = []
        for e in points:
            at = onset_near(env, e["t"])
            if at is None:
                late.append(f"{e['e']} at {e['t']:g} s: no sound starts there")
            elif abs(at - e["t"]) > SYNC_S:
                late.append(f"{e['e']} starts {round((at - e['t']) * 1000):+d} ms off its cut"
                            f" at {e['t']:g} s")
        out.append(("sound_sync", not late, "; ".join(late)
                    or f"{len(points)} point sound(s) within {SYNC_S * 1000:g} ms of their cut"))
    return out
