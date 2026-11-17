"""
The reaction reel (step 071, docs/DECISIONS.md 2026-11-17): the owner records one long
reaction video; every reaction video gets the next consecutive piece of it.

A stored cursor marks where the next piece starts. A piece that would pass the end starts
over at 0 (the reel loops; the end and the start are never stitched together), so
consecutive videos never reuse footage until the whole reel has been used. The start snaps
forward to a silence within SNAP_S when there is one (best effort: not mid-word); silences
are found once, at upload. Several reels may be kept; one is active.

Files: `<media root>/reactions/<reel id>/reel.<ext>` and `.../pieces/<piece id>.mp4`.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from ..store import CampaignStore
from . import ffmpeg, media
from .recipe import AUDIO_ARGS, CONTAINER_ARGS, VIDEO_ARGS

SNAP_S = 1.5
SILENCE_NOISE_DB = -35
SILENCE_MIN_S = 0.3
VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".mkv", ".webm")
PIECE_PRESET = "veryfast"  # the piece is re-encoded again by the reaction_collage op
_SILENCE = re.compile(r"silence_(start|end): (-?\d+(?:\.\d+)?)")


class ReactionError(ValueError):
    """No usable reel: none active, too short, not a video with sound."""


class UploadTooLarge(ReactionError):
    pass


def detect_silences(path: Path, duration_s: float, *, timeout_s: float = 900) -> List[List[float]]:
    """[[start_s, end_s], ...] of the quiet stretches, in order (one ffmpeg pass)."""
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "silences.log"
        ffmpeg.run(["-i", path, "-vn", "-af",
                    f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_S}",
                    "-f", "null", "-"], timeout_s=timeout_s, log_path=log)
        text = log.read_text(encoding="utf-8")
    out: List[List[float]] = []
    for kind, value in _SILENCE.findall(text):
        t = max(0.0, float(value))
        if kind == "start":
            out.append([t, duration_s])  # a silence running to the end never gets its end
        elif out:
            out[-1][1] = t
    return out


def snap(start_s: float, silences: List[List[float]]) -> float:
    """The earliest point at or after `start_s` inside a silence, if it is at most SNAP_S
    away; else `start_s`. Never earlier: footage before the cursor is already used."""
    for a, b in silences:
        if b >= start_s:
            p = max(a, start_s)
            return p if p - start_s <= SNAP_S else start_s
    return start_s


def reel_status(reel: Dict[str, Any]) -> Dict[str, Any]:
    total = reel["duration_s"]
    return {"id": reel["id"], "path": reel["path"], "duration_s": total,
            "cursor_s": reel["cursor_s"], "pieces_used": reel["pieces_used"],
            "used_pct": round(100 * reel["cursor_s"] / total, 1) if total else 0.0,
            "active": bool(reel["active"]), "created_at": reel["created_at"]}


def list_reels(store: CampaignStore) -> List[Dict[str, Any]]:
    """Every reel with its status, newest first."""
    return [reel_status(r) for r in store.list_reaction_reels()]


def activate(store: CampaignStore, reel_id: int) -> Dict[str, Any]:
    return reel_status(store.activate_reaction_reel(reel_id))


def reset_cursor(store: CampaignStore, reel_id: int) -> Dict[str, Any]:
    """Start the reel over from 0."""
    return reel_status(store.reset_reaction_cursor(reel_id))


def add_reel(store: CampaignStore, settings, path: Path) -> Dict[str, Any]:
    """Probe the recording (video and sound required), find its silences, move it under
    the media root and make it the active reel."""
    path = Path(path)
    try:
        info = ffmpeg.probe(path)
    except ffmpeg.FFmpegError as e:
        raise ReactionError("the file is not a video ffmpeg can read") from e
    if not info.video_codec or not info.has_audio or info.duration <= 0:
        raise ReactionError("the reaction reel needs both video and sound")
    silences = detect_silences(path, info.duration)
    reel = store.add_reaction_reel(path.suffix.lower(), info.duration, True, silences)
    try:
        dest = media.resolve(settings.media_root, reel["path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(path, dest)
    except BaseException:
        store.delete_reaction_reel(reel["id"])
        raise
    return activate(store, reel["id"])


async def upload_reel(store: CampaignStore, settings, chunks: AsyncIterator[bytes],
                      filename: str, content_length: Optional[int]) -> Dict[str, Any]:
    """Stream an upload to disk (never whole in memory), refusing it past
    reaction_upload_max_mb, then add_reel() it. The partial file never stays behind."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise ReactionError(f"upload a video file ({', '.join(VIDEO_SUFFIXES)})")
    cap = settings.reaction_upload_max_mb * 1_000_000
    if content_length is not None and content_length > cap:
        raise UploadTooLarge(f"the file is larger than {settings.reaction_upload_max_mb} MB")
    inbox = Path(settings.media_root) / "reactions" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    tmp = inbox / f"upload-{uuid.uuid4().hex}{suffix}"
    try:
        size = 0
        with tmp.open("wb") as f:
            async for chunk in chunks:
                size += len(chunk)
                if size > cap:
                    raise UploadTooLarge(
                        f"the file is larger than {settings.reaction_upload_max_mb} MB")
                f.write(chunk)
        return await asyncio.to_thread(add_reel, store, settings, tmp)
    finally:
        tmp.unlink(missing_ok=True)


def next_reaction_piece(store: CampaignStore, settings, duration_s: float, *,
                        asset_id: Optional[int] = None, timeout_s: float = 600,
                        preset: str = PIECE_PRESET) -> Dict[str, Any]:
    """Cut the next `duration_s` seconds of the active reel to a file:
    {piece_id, path (relative to the media root), start_s, end_s}. The cursor moves in one
    write transaction, so two concurrent renders never get the same piece."""
    if duration_s <= 0:
        raise ReactionError("a reaction piece needs a positive length")
    while True:
        reel = store.active_reaction_reel()
        if reel is None:
            raise ReactionError("no active reaction reel: upload one in Settings")
        total, cursor = reel["duration_s"], reel["cursor_s"]
        if total < duration_s:
            raise ReactionError(f"the reaction reel is {total:.1f} s long, shorter than the"
                                f" {duration_s:.1f} s piece needed")
        start = snap(cursor, reel["silences"])
        if start + duration_s > total:  # the snap pushed it past the end: don't snap
            start = cursor
        wrapped = start + duration_s > total
        if wrapped:
            start = 0.0
        piece = store.claim_reaction_piece(
            reel["id"], cursor, start, start + duration_s,
            1 if wrapped else reel["pieces_used"] + 1, asset_id)
        if piece:
            break
    src = media.resolve(settings.media_root, reel["path"])
    out = src.parent / "pieces" / f"{piece['id']}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    # -ss before -i while re-encoding: a fast seek that is still frame-accurate.
    ffmpeg.run(["-ss", f"{start:.3f}", "-i", src, "-t", f"{duration_s:.3f}",
                "-map", "0:v:0", "-map", "0:a:0", *VIDEO_ARGS, "-preset", preset,
                *AUDIO_ARGS, *CONTAINER_ARGS, out], timeout_s=timeout_s)
    return {"piece_id": piece["id"], "path": media.relative(settings.media_root, out),
            "start_s": start, "end_s": piece["end_s"]}
