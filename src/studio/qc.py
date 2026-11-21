"""
Quality check after every render (GOAL.md §3, §5.6): decides `ready` vs `failed`.

run_qc() returns what is saved as `assets.qc`:
  {"passed": bool, "checks": [{"name", "ok", "detail"}], "reasons": [<detail of each failed
   check>], "warnings": [...], "loudness_lufs": float | None}
Checks: output spec (size, fps, codec), duration bounds, audio present, loudness, black and
frozen stretches (one ffmpeg analysis pass), the caption (length, hashtags) and the texts
drawn on screen (never a price, owner rule; screen_texts()). Motion
renders (`recipe.kind == "motion"`) get a longer freeze limit: their hook and end cards are
still on purpose (`qc_max_freeze_s_motion`). Health, medical or income promises are only
warnings: the owner can overrule them in review.
The QC also listens (src/studio/listen.py, step 149): true peak, sudden jumps, the voice
above the bed, point sounds on their cut. Those checks carry `"blocking": false`: a failing
one is a warning ("audio: ...") for the owner to judge by ear, never a failed render.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import InstagramMCPSettings
from ..instagram_client import caption_problem
from . import ffmpeg, listen, media
from .brand import has_price
from .ffmpeg import PathLike
from .recipe import FPS, HEIGHT, LOUDNESS_I, WIDTH, Recipe

ANALYSIS_TIMEOUT_S = 600.0

# ponytail: placeholder list, English + French basics, until the channel basics (H9) and
# multi-language captions; extend it here. (regex, what the wording promises)
CLAIM_PATTERNS = [
    (r"\b(lose|perdre|perdez|perds)\s+\d+([.,]\d+)?\s*(kg|kilos?|lbs?|pounds?)\b",
     "weight-loss promise"),
    (r"\b(cure[sd]?|heals?|gu[ée]ri[rst]?|gu[ée]rissent)\b", "medical promise"),
    (r"\b(guarantee[sd]?|garanti[es]{0,2})\b", "guarantee"),
    (r"\b(miracle|miraculeux|miraculeuse)\b", "miracle claim"),
    (r"\b(earn|make|gagner|gagnez|gagne)\s+([$€£]\s?\d[\d,.]*k?|\d[\d,.]*\s*k?\s*([$€£]"
     r"|euros?|dollars?))", "income promise"),
]
_CLAIMS = [(re.compile(p, re.IGNORECASE), kind) for p, kind in CLAIM_PATTERNS]


def claim_warnings(*texts: Optional[str]) -> List[str]:
    """Health, medical or income promises found in the texts (GOAL.md §5.6), one warning per
    distinct wording, e.g. "weight-loss promise: 'lose 5 kg'"."""
    found: List[str] = []
    for text in filter(None, texts):
        for pattern, kind in _CLAIMS:
            for m in pattern.finditer(text):
                warning = f"{kind}: {m.group(0)!r}"
                if warning not in found:
                    found.append(warning)
    return found


# Motion props that are never drawn: sources, the voice (its lines repeat the drawn texts) and
# asset ids.
_NOT_DRAWN = {"citations", "voice", "music", "palette"}


def screen_texts(recipe: Optional[Dict[str, Any]]) -> List[str]:
    """Every text a render of the stored recipe envelope draws: the ffmpeg ops' texts (hook,
    credit, captions, end card) or the motion props' strings (ids such as sprite names come
    along: they never look like a price)."""
    env = recipe or {}
    if env.get("kind") == "ffmpeg":
        ops = Recipe.model_validate(env["recipe"]).ops if env.get("recipe") else []
        return [t for op in ops for t in op.texts()]
    found: List[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, dict):
            for k, v in value.items():
                if k not in _NOT_DRAWN:
                    walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(env.get("props") or {})
    return found


def analyze(path: PathLike, *, max_black_s: float, max_freeze_s: float, has_audio: bool,
            timeout_s: float = ANALYSIS_TIMEOUT_S) -> Dict[str, Any]:
    """One ffmpeg pass over the video: black stretches at least `max_black_s` long
    [(start, end)], starts of frozen stretches at least `max_freeze_s` long, the integrated
    loudness in LUFS and the true peak in dBTP (None without audio), and the momentary
    loudness [(t, LUFS)] every 100 ms ([] without audio)."""
    args = ["-i", path, "-vf", f"blackdetect=d={max_black_s},freezedetect=d={max_freeze_s}"]
    if has_audio:  # framelog=verbose: ebur128's own per-frame lines stay out of the log
        args += ["-af", "ebur128=framelog=verbose:peak=true:metadata=1,"
                        "ametadata=mode=print:key=lavfi.r128.M"]
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "qc.log"
        ffmpeg.run([*args, "-f", "null", "-"], timeout_s=timeout_s, log_path=log)
        text = log.read_text(encoding="utf-8")
    loudness = re.search(r"Integrated loudness:\s+I:\s+(\S+) LUFS", text)
    peak = re.search(r"True peak:\s+Peak:\s+(\S+) dBFS", text)
    return {
        "black": [(float(a), float(b))
                  for a, b in re.findall(r"black_start:(\S+) black_end:(\S+)", text)],
        "freeze": [float(s) for s in re.findall(r"freeze_start: (\S+)", text)],
        "loudness": float(loudness.group(1)) if loudness else None,
        "true_peak": float(peak.group(1)) if peak else None,
        "momentary": [(float(t), float(m)) for t, m in re.findall(
            r"pts_time:(\S+)\s+\[[^\]]*\]\s*lavfi\.r128\.M=(\S+)", text)],
    }


def run_qc(asset: Dict[str, Any], idea: Optional[Dict[str, Any]], master_path: str,
           media_root: PathLike, settings: InstagramMCPSettings) -> Dict[str, Any]:
    """Check the rendered master (`master_path` relative to the media root) and the asset's
    caption; the idea's hook and script are scanned for claim wording too."""
    s = settings
    path = media.resolve(media_root, master_path)
    info = ffmpeg.probe(path)
    # a Lemo-Opuscar film (173) is code-animated like a motion render: same freeze limit
    motion = ((asset.get("recipe") or {}).get("kind") == "motion"
              or str((idea or {}).get("style") or "").startswith("lemo:"))
    max_freeze = s.qc_max_freeze_s_motion if motion else s.qc_max_freeze_s
    found = analyze(path, max_black_s=s.qc_max_black_s, max_freeze_s=max_freeze,
                    has_audio=info.has_audio)
    checks: List[Dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    fps_ok = info.fps is not None and abs(info.fps - FPS) < 0.01
    check("spec", (info.width, info.height, info.video_codec) == (WIDTH, HEIGHT, "h264")
          and fps_ok, f"{info.width}x{info.height} {info.fps or 0:g} fps {info.video_codec}"
          f" (want {WIDTH}x{HEIGHT} {FPS} fps h264)")
    check("duration", s.qc_min_duration_s <= info.duration <= s.qc_max_duration_s,
          f"{info.duration:.1f} s (want {s.qc_min_duration_s:g}-{s.qc_max_duration_s:g} s)")
    check("audio", info.has_audio, "audio track" if info.has_audio else "no audio track")
    lufs = found["loudness"]
    check("loudness", lufs is not None and abs(lufs - LOUDNESS_I) <= s.qc_loudness_tolerance_lu,
          f"{'no audio' if lufs is None else f'{lufs:g} LUFS'}"
          f" (want {LOUDNESS_I:g} +/- {s.qc_loudness_tolerance_lu:g} LU)")
    check("black", not found["black"],
          "; ".join(f"black {a:.1f}-{b:.1f} s" for a, b in found["black"])
          or f"no black stretch of {s.qc_max_black_s:g} s")
    check("freeze", not found["freeze"],
          "; ".join(f"frozen from {t:.1f} s for {max_freeze:g} s or more"
                    for t in found["freeze"]) or f"no frozen stretch of {max_freeze:g} s")
    problem = caption_problem(asset.get("caption"), s.max_hashtags)
    check("caption", problem is None, problem or "caption ok")
    priced = [t for t in screen_texts(asset.get("recipe")) if has_price(t)]
    check("price", not priced, "; ".join(f"a price on screen: {t!r}" for t in priced)
          or "no price on screen")
    blocking = list(checks)
    idea = idea or {}
    warnings = claim_warnings(asset.get("caption"), idea.get("hook"), idea.get("script"))
    if info.has_audio:  # the listening checks flag for the owner, they never fail a render
        try:
            heard = listen.checks(path, listen.voice_track(asset.get("recipe"), media_root),
                                  asset.get("timeline"), found, timeout_s=ANALYSIS_TIMEOUT_S,
                                  voice_parts=asset.get("voice_parts"))
        except Exception as e:  # noqa: BLE001 - a listening failure must not fail the render
            heard = [("listen", False, f"could not listen: {type(e).__name__}: {e}"[:200])]
        for name, ok, detail in heard:
            checks.append({"name": name, "ok": ok, "detail": detail, "blocking": False})
            if not ok:
                warnings.append(f"audio: {detail}")
    return {
        "passed": all(c["ok"] for c in blocking),
        "checks": checks,
        "reasons": [c["detail"] for c in blocking if not c["ok"]],  # what the asset page shows
        "warnings": warnings,
        "loudness_lufs": lufs,
    }
