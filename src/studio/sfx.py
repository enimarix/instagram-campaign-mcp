"""
Sound-effects library (step 150): real recorded sounds from Openverse, legally clean, picked
per scene.

- Search: Openverse's audio search (https://api.openverse.org/v1/audio/), anonymous, from
  Freesound only (`source=freesound`): Openverse's `category=sound_effect` filter returns
  nothing today (Freesound records carry no category), and Freesound is the sound-effects
  source of the three. Licences **CC0 and CC BY only** (`license=cc0,by`), checked again on
  every result: NC, ND and SA (and anything else) are refused. Under 30 s (`length=shortest`).
- Cache: `SFX_DIR/<openverse id>.wav`, 48 kHz mono, silence trimmed off both ends, at most
  MAX_S, its loudest moment set to PEAK_LUFS (peak momentary loudness, as steps 158-159
  measured the synthesized sounds; a limiter keeps it from clipping, so it can only end up
  quieter). The motion side plays every library sound from that one level
  (LIBRARY_PEAK_LUFS in motion/src/lib/duck.ts, checked equal by a test), under the voice.
- Manifest: `SFX_DIR/manifest.json` {"sounds": {id: entry}}: title, creator, licence + URL,
  source URL, Openverse's attribution text, our short `credit` line (CC BY only), tags,
  duration, the measured peak. Written under a file lock (the CLI and the MCP server).
- Use: a template's sfx prop takes `ov:<id>` (REF) next to the synthesized names; a render
  copies the files into the bundle (`stage`). A CC BY sound's credit goes into the caption
  (queue_motion_render keeps the credits in the recipe; submit_asset adds them, the publish
  guard refuses a caption without them). CC0 needs none.

Network only in `seed` (`ig-campaign sfx seed`) and in `find_sfx` when nothing cached fits.
Openverse allows anonymous clients 20 requests a minute and 200 a day (its rate-limit
headers): `seed` waits PAUSE_S between searches and stops on a 429.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx

from ..config import APP_HOME
from ..store import to_iso, utcnow
from . import ffmpeg, gpu_lock
from .recipe import SAMPLE_RATE, _limiter

SFX_DIR = APP_HOME / "data" / "sfx"  # git-ignored, runtime only
MANIFEST = "manifest.json"
API = "https://api.openverse.org/v1/audio/"
USER_AGENT = "growth-studio-sfx/1.0"  # generic on purpose: no name, no e-mail (GOAL privacy)
LICENCES = ("cc0", "by")
PAGE_SIZE = 20  # the anonymous maximum
MAX_SOURCE_S = 20.0  # a longer recording is a scene, not a sound effect
MAX_S = 6.0  # cached length
MAX_BYTES = 10 * 2**20
PEAK_LUFS = -20.0  # = LIBRARY_PEAK_LUFS in motion/src/lib/duck.ts
SILENCE_DB = -50
PAUSE_S = 3.5  # between Openverse searches: under the anonymous 20 a minute
FETCH_MAX = 3  # sounds find_sfx downloads when nothing cached fits
TIMEOUT_S = 60.0
REF = re.compile(r"^ov:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")
BUNDLE_DIR = "ov-sfx"  # under the bundle's public/: motion/src/components/Sfx.tsx reads it
# Tags of a recording that carries music or a bed, not a sound (MUSICAL categories allow it).
MUSIC_TAGS = {"music", "song", "melody", "loop", "soundtrack", "ambient", "ambience", "beat"}

# The starter pack: category -> (query, how many). Built for the skits (owner 2026-11-19:
# cartoon sounds, cutlery falling, crowd gasps).
SEED: Dict[str, tuple] = {
    "whoosh": ("whoosh", 2), "swoosh": ("swoosh", 1), "impact": ("punch impact", 2),
    "pop": ("pop", 2), "boing": ("boing", 2), "crunch": ("crunch bite", 2),
    "fork drop": ("fork drop", 1), "cutlery drop": ("cutlery drop", 1),
    "plate clatter": ("plate clatter", 1), "gasp": ("gasp", 1),
    "crowd gasp": ("crowd gasp", 1), "crowd laugh": ("crowd laugh", 1),
    "applause": ("applause", 1), "cheer": ("crowd cheer", 1),
    "record scratch": ("record scratch", 1), "cash register": ("cash register", 1),
    "ding": ("ding", 2), "buzzer": ("wrong buzzer", 1), "heartbeat": ("heartbeat", 1),
    "gulp": ("gulp", 1), "chewing": ("chewing", 1), "sizzle": ("sizzle", 1),
    "door slam": ("door slam", 1), "footsteps": ("footsteps", 1),
    "weight drop": ("dumbbell drop", 1), "whistle": ("referee whistle", 1),
    "sad trombone": ("sad trombone", 1), "tada": ("tada", 1),
    "slide whistle": ("slide whistle", 1), "splash": ("splash", 1),
    "glass clink": ("glass clink", 1),
}
MUSICAL = {"sad trombone", "tada", "slide whistle", "record scratch"}


class RateLimited(RuntimeError):
    """Openverse answered 429: wait (an hour, or a day) before searching again."""


# --- Openverse -----------------------------------------------------------------------------
def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT_S, follow_redirects=True,
                        headers={"User-Agent": USER_AGENT})


def _entry(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Our manifest entry for an Openverse result, or None when we may not use it."""
    licence = str(r.get("license") or "").lower()
    if licence not in LICENCES or r.get("mature") or not REF.match(f"ov:{r.get('id')}"):
        return None
    url = str(r.get("url") or "")
    if not url.startswith("https://"):
        return None
    title = re.sub(r"\.(wav|mp3|flac|ogg|aiff?)$", "", str(r.get("title") or ""), flags=re.I)
    title = " ".join(title.replace("#", "").split()) or "untitled"  # no stray hashtags
    creator = str(r.get("creator") or "").strip() or "unknown"
    version = str(r.get("license_version") or "").strip()
    landing = str(r.get("foreign_landing_url") or "")
    credit = None
    if licence == "by":  # TASL: title, author, source, licence
        where = re.sub(r"^https?://(www\.)?", "", landing)
        credit = (f'Son : "{title}" par {creator}'
                  f"{f' ({where})' if where else ''}, CC BY {version}".rstrip())
    return {
        "id": r["id"], "title": title, "creator": creator,
        "creator_url": r.get("creator_url"), "licence": licence, "licence_version": version,
        "licence_url": r.get("license_url"), "source_url": landing,
        "provider": r.get("provider"), "url": url, "attribution": r.get("attribution"),
        "credit": credit,
        "tags": [t["name"] for t in r.get("tags") or [] if isinstance(t, dict) and t.get("name")],
        "source_duration_s": (r.get("duration") or 0) / 1000,
    }


def search(query: str, *, client: httpx.Client) -> List[Dict[str, Any]]:
    """One Openverse search: the usable results (CC0 / CC BY, short), best first."""
    q = " ".join(str(query).split())[:200]
    if not q:
        raise ValueError("say what sound you want")
    r = client.get(API, params={"q": q, "source": "freesound", "license": ",".join(LICENCES),
                                "length": "shortest", "page_size": PAGE_SIZE})
    if r.status_code == 429:
        raise RateLimited("Openverse rate limit reached (anonymous: 20 a minute, 200 a day)")
    r.raise_for_status()
    found = [_entry(x) for x in r.json().get("results") or []]
    return [e for e in found if e and 0 < e["source_duration_s"] <= MAX_SOURCE_S]


# --- cache ---------------------------------------------------------------------------------
def manifest_path() -> Path:
    return SFX_DIR / MANIFEST


def load() -> Dict[str, Dict[str, Any]]:
    """id -> entry of every cached sound ({} before the first fetch)."""
    try:
        data = json.loads(manifest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    sounds = data.get("sounds") if isinstance(data, dict) else None
    return sounds if isinstance(sounds, dict) else {}


def _save(entry: Dict[str, Any]) -> None:
    """Add one entry to the manifest (read-modify-write under the lock, atomic replace)."""
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    with gpu_lock.file_lock(SFX_DIR / ".manifest.lock", timeout_s=60):
        sounds = load()
        sounds[entry["id"]] = entry
        tmp = manifest_path().with_suffix(".tmp")
        tmp.write_text(json.dumps({"sounds": sounds}, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(manifest_path())


def peak_lufs(path: Path, *, timeout_s: float = TIMEOUT_S) -> Optional[float]:
    """The sound's loudest momentary loudness (ffmpeg ebur128), None when silent."""
    with tempfile.TemporaryDirectory() as work:
        log = Path(work) / "peak.log"
        ffmpeg.run(["-i", path, "-map", "0:a:0", "-af",
                    "ebur128=metadata=1,ametadata=mode=print:key=lavfi.r128.M",
                    "-f", "null", "-"], timeout_s=timeout_s, log_path=log)
        text = log.read_text(encoding="utf-8")
    values = [float(m) for m in re.findall(r"lavfi\.r128\.M=(-?[\d.]+)", text)]
    peak = max(values, default=-120.0)
    return peak if peak > -70 else None


def convert(src: Path, out: Path, *, timeout_s: float = TIMEOUT_S) -> float:
    """`src` as the library keeps it at `out` (48 kHz mono WAV, silence trimmed, at most
    MAX_S, peak at PEAK_LUFS or under); returns the measured peak. ValueError when silent."""
    trim = f"silenceremove=start_periods=1:start_threshold={SILENCE_DB}dB"
    pcm = ["-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le"]
    with tempfile.TemporaryDirectory(dir=out.parent) as work:
        cut, final = Path(work) / "cut.wav", Path(work) / "final.wav"
        ffmpeg.run(["-i", src, "-map", "0:a:0", "-af",
                    f"{trim},atrim=end={MAX_S},afade=t=in:d=0.005,"
                    f"afade=t=out:st={MAX_S - 0.15}:d=0.15,areverse,{trim},areverse",
                    *pcm, cut], timeout_s=timeout_s)
        peak = peak_lufs(cut, timeout_s=timeout_s)
        if peak is None:
            raise ValueError("the recording is silent")
        ffmpeg.run(["-i", cut, "-af", f"volume={PEAK_LUFS - peak:.2f}dB,{_limiter(-1.0)}",
                    *pcm, final], timeout_s=timeout_s)
        peak = peak_lufs(final, timeout_s=timeout_s)
        if peak is None:
            raise ValueError("the recording is silent")
        final.replace(out)
    return peak


def fetch(entry: Dict[str, Any], *, client: httpx.Client, category: Optional[str] = None
          ) -> Dict[str, Any]:
    """Download one search result, convert it into the cache and record it; the cached
    entry when it is there already."""
    if entry.get("licence") not in LICENCES:  # never trust the caller with the rule
        raise ValueError(f"licence {entry.get('licence')!r} refused: CC0 and CC BY only")
    known = load().get(entry["id"])
    if known and (SFX_DIR / known["file"]).is_file():
        return known
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=SFX_DIR) as work:
        raw = Path(work) / "source"
        with client.stream("GET", entry["url"]) as r:
            if r.status_code != 200:
                raise ValueError(f"download failed: HTTP {r.status_code}")
            size = 0
            with raw.open("wb") as f:
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError(f"bigger than {MAX_BYTES // 2**20} MB")
                    f.write(chunk)
        out = SFX_DIR / f"{entry['id']}.wav"
        peak = convert(raw, out)
    saved = {k: v for k, v in entry.items() if k != "url"}
    saved.update(file=out.name, download_url=entry["url"], category=category,
                 duration_s=round(ffmpeg.probe(out).duration or 0, 3),
                 peak_lufs=round(peak, 1), fetched_at=to_iso(utcnow()))
    _save(saved)
    return saved


def _clean(entry: Dict[str, Any], musical: bool) -> bool:
    words = {w for t in entry["tags"] for w in re.split(r"[\s_-]+", t.lower())}
    return musical or not (words & MUSIC_TAGS)


def seed(*, only: Optional[Iterable[str]] = None, force: bool = False,
         client: Optional[httpx.Client] = None, pause_s: float = PAUSE_S) -> Dict[str, Any]:
    """The starter pack: for each SEED category its best clean results (CC0 first), unless
    the category is cached already. Returns {fetched, kept, failed: [{category, error}]}."""
    wanted = list(only) if only else list(SEED)
    unknown = sorted(set(wanted) - set(SEED))
    if unknown:
        raise ValueError(f"unknown categories: {', '.join(unknown)} (known: {', '.join(SEED)})")
    result: Dict[str, Any] = {"fetched": 0, "kept": 0, "failed": []}
    own = client is None
    client = client or _client()
    searched, limited = False, None
    try:
        for name in wanted:
            query, n = SEED[name]
            have = [e for e in load().values() if e.get("category") == name]
            if len(have) >= n and not force:
                result["kept"] += len(have)
                continue
            if limited:  # no more searches today: the rest waits for the next seed
                result["failed"].append({"category": name, "error": limited})
                continue
            if searched:
                time.sleep(pause_s)
            searched = True
            try:
                found = [e for e in search(query, client=client) if _clean(e, name in MUSICAL)]
            except RateLimited as e:
                limited = str(e)
                result["failed"].append({"category": name, "error": limited})
                continue
            except (httpx.HTTPError, ValueError) as e:
                result["failed"].append({"category": name, "error": str(e)})
                continue
            found.sort(key=lambda e: e["licence"] != "cc0")  # stable: CC0 first, then relevance
            got = 0
            for e in found:
                if got == n:
                    break
                try:
                    fetch(e, client=client, category=name)
                    got += 1
                except (httpx.HTTPError, OSError, ValueError, ffmpeg.FFmpegError):
                    continue  # the next candidate
            result["fetched"] += got
            if got < n:
                result["failed"].append({"category": name,
                                         "error": f"{got} of {n}: no more clean matches"})
    finally:
        if own:
            client.close()
    return result


# --- the agent's view ----------------------------------------------------------------------
def _brief(e: Dict[str, Any]) -> Dict[str, Any]:
    return {"ref": f"ov:{e['id']}", "title": e["title"], "category": e.get("category"),
            "duration_s": e.get("duration_s"), "licence": e["licence"],
            "credit": e.get("credit"), "creator": e["creator"], "tags": e["tags"][:8],
            "source_url": e.get("source_url")}


def _matches(query: str, limit: int) -> tuple:
    """(cached sounds with every word of the query, cached sounds with some), best first."""
    words = [w for w in re.split(r"\W+", query.lower()) if w]
    full, part = [], []
    for e in load().values():
        if not (SFX_DIR / e.get("file", "")).is_file():
            continue
        hay = " ".join([e["title"], e.get("category") or "", *e["tags"]]).lower()
        hits = sum(w in hay for w in words)
        if hits:
            (full if hits == len(words) else part).append((-hits, e["licence"] != "cc0", e))
    order = lambda xs: [_brief(e) for *_, e in sorted(xs, key=lambda x: x[:2])][:limit]  # noqa: E731
    return order(full), order(part)


def find_sfx(query: str, limit: int = 5, *, client: Optional[httpx.Client] = None
             ) -> Dict[str, Any]:
    """Library sounds for `query`: cached ones with every word of it; when none, up to
    FETCH_MAX fetched from Openverse now (CC0 / CC BY only), else the closest cached ones.
    {sounds: [{ref, title, category, duration_s, licence, credit, creator, tags,
    source_url}], fetched, note}."""
    limit = max(1, min(int(limit), 20))
    if not " ".join(str(query).split()):
        raise ValueError("say what sound you want")
    full, part = _matches(query, limit)
    note = ("Use `ref` as a sound in a template's sfx props (PixelSkit beat `sfx`, `sting`)."
            " A CC BY sound's credit is added to the caption by submit_asset; CC0 needs none.")
    if full:
        return {"sounds": full, "fetched": 0, "note": note}
    own = client is None
    client = client or _client()
    fetched: List[Dict[str, Any]] = []
    try:
        for e in sorted(search(query, client=client), key=lambda e: e["licence"] != "cc0"):
            if len(fetched) == min(limit, FETCH_MAX):
                break
            try:
                fetched.append(fetch(e, client=client, category=None))
            except (httpx.HTTPError, OSError, ValueError, ffmpeg.FFmpegError):
                continue
    except (RateLimited, httpx.HTTPError) as e:
        if not part:
            raise ValueError(f"nothing cached fits and Openverse failed: {e}") from e
    finally:
        if own:
            client.close()
    if fetched:
        return {"sounds": [_brief(e) for e in fetched], "fetched": len(fetched), "note": note}
    return {"sounds": part, "fetched": 0,
            "note": note + (" Nothing matched every word: closest cached sounds." if part
                            else " Nothing found: try other words (in English).")}


# --- renders and credits -------------------------------------------------------------------
def refs(value: Any) -> List[str]:
    """Openverse ids of every `ov:<id>` string in `value` (props), in order, once each."""
    found: List[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, str):
            m = REF.match(v)
            if m and m.group(1) not in found:
                found.append(m.group(1))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(value)
    return found


def _cached(sound_id: str) -> Dict[str, Any]:
    e = load().get(sound_id)
    if not e or not (SFX_DIR / e["file"]).is_file():
        raise ValueError(f"sound ov:{sound_id} is not in the library: find_sfx first")
    return e


def credits(props: Any) -> List[str]:
    """The credit lines the caption needs for the library sounds `props` use (CC BY ones);
    ValueError for a sound not in the library."""
    return [e["credit"] for e in map(_cached, refs(props)) if e.get("credit")]


def stage(public: Path, props: Any) -> None:
    """Copy the library sounds `props` use into `public/BUNDLE_DIR/` of a Remotion bundle."""
    for sound_id in refs(props):
        src = SFX_DIR / _cached(sound_id)["file"]
        dest = public / BUNDLE_DIR / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)


def missing_credits(recipe: Any, caption: Optional[str]) -> List[str]:
    """Credit lines (kept in the recipe by queue_motion_render) the caption lacks."""
    lines = (recipe or {}).get("sfx_credits") if isinstance(recipe, dict) else None
    return [c for c in lines or [] if c not in (caption or "")]


def with_credits(caption: str, recipe: Any) -> str:
    """`caption` with the missing credit lines added at the end."""
    missing = missing_credits(recipe, caption)
    return caption.rstrip() + "\n\n" + "\n".join(missing) if missing else caption
