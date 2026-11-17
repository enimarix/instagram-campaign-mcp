"""
Self-review (step 057): the agent sees its own work as small JPEG frames.

The locked-down agent (step 058) cannot read `data/media`, so the MCP tools hand it images:
`asset_frames` for a rendered asset (plus its QC result), `preview_images` for the stills of
`preview_motion`. Frames are cached under `<media root>/frames/`, so asking twice is free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..config import InstagramMCPSettings
from ..store import CampaignStore
from . import ffmpeg, media, motion
from .production import qc_summary

WIDTH = 540
JPEG_Q = "5"  # mjpeg qscale (2 best .. 31): ~40-80 KB per 540 px frame
TIMEOUT_S = 60.0


def _jpegs(inputs: Sequence[Sequence[Any]], outs: Sequence[Path], width: int) -> None:
    """One ffmpeg call: input i (its `-ss`/`-i` args) becomes outs[i], `width` px wide."""
    args: List[Any] = [a for inp in inputs for a in inp]
    for i, out in enumerate(outs):
        args += ["-map", f"{i}:v:0", "-frames:v", "1", "-vf", f"scale={width}:-2",
                 "-q:v", JPEG_Q, out]
    ffmpeg.run(args, timeout_s=TIMEOUT_S)


def asset_frames(store: CampaignStore, settings: InstagramMCPSettings, asset_id: int,
                 n: int = 4, width: int = WIDTH) -> Tuple[List[bytes], Dict[str, Any]]:
    """`n` JPEG frames of the asset's master (the cover, then the rest spread up to the end)
    and {asset_id, status, qc, duration_s, frame_times_s}. ValueError without a master."""
    if not 1 <= n <= 8 or not 120 <= width <= 1080:
        raise ValueError("n must be 1..8 and width 120..1080")
    asset = store.get_asset(asset_id)
    if not asset["file_path"]:
        why = ("failed before a file was written" if asset["status"] == "failed"
               else "still rendering" if asset["status"] == "rendering" else "has no video file")
        raise ValueError(f"asset {asset_id} {why}: {qc_summary(asset['qc']) or 'no QC yet'}")
    video = media.resolve(settings.media_root, asset["file_path"])
    if not video.is_file():
        raise ValueError(f"asset {asset_id}: its video file is gone ({asset['status']})")
    duration = asset["duration"] or ffmpeg.probe(video).duration
    last = max(duration - 0.1, 0.0)  # a frame that exists
    cover = ((asset["recipe"] or {}).get("thumb_offset_ms") or 0) / 1000
    times = [round(min(t, last), 3)
             for t in [cover] + [last * k / (n - 1) for k in range(1, n)]]
    stat = video.stat()
    folder = (Path(settings.media_root) / "frames"
              / f"{asset_id}-{stat.st_mtime_ns:x}-{stat.st_size:x}-{width}")
    outs = [folder / f"frame-{i}-{t:.3f}.jpg" for i, t in enumerate(times)]
    if not all(p.is_file() for p in outs):
        folder.mkdir(parents=True, exist_ok=True)
        _jpegs([["-ss", f"{t:.3f}", "-i", video] for t in times], outs, width)
    info = {"asset_id": asset_id, "status": asset["status"], "qc": qc_summary(asset["qc"]),
            "duration_s": round(duration, 3), "frame_times_s": times}
    return [p.read_bytes() for p in outs], info


def preview_images(template: str, props: Dict[str, Any], media_root: Any,
                   frames: Optional[Sequence[int]] = None,
                   width: int = WIDTH) -> Tuple[List[bytes], Dict[str, Any]]:
    """motion.preview_stills (PNGs kept on disk for the website) plus a `width` px JPEG of
    each, next to it, for the agent. Returns (jpegs, {stills: media paths})."""
    stills = motion.preview_stills(template, props, media_root, frames)
    pngs = [media.resolve(media_root, s) for s in stills]
    outs = [p.with_name(f"{p.stem}-{width}.jpg") for p in pngs]
    # preview_stills re-renders the PNGs each time: convert again when one is newer.
    todo = [i for i, out in enumerate(outs)
            if not out.is_file() or out.stat().st_mtime_ns < pngs[i].stat().st_mtime_ns]
    if todo:
        _jpegs([["-i", pngs[i]] for i in todo], [outs[i] for i in todo], width)
    return [p.read_bytes() for p in outs], {"stills": stills}
