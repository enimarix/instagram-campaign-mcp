"""
ffmpeg / ffprobe from Python (GOAL.md §4.1): find the binaries, probe a file, run ffmpeg.

Binaries: `FFMPEG_PATH` / `FFPROBE_PATH` (a full path or a command name) override the
lookup on PATH. Every call uses list arguments, never a shell, so file names are never
interpreted. Works the same on Windows and Linux.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union

from . import guard

PathLike = Union[str, Path]

# Always passed to ffmpeg by run(): no banner noise in the log, never wait for keyboard
# input (a stray "q" or a prompt would hang a worker), and overwrite the output file.
FIXED_ARGS = ("-hide_banner", "-nostdin", "-y")
TAIL_LINES = 20


class FFmpegNotFound(RuntimeError):
    """ffmpeg or ffprobe is not installed (or the env override points nowhere)."""


class FFmpegError(RuntimeError):
    """ffmpeg/ffprobe failed. `stderr_tail` holds its last lines of output."""

    def __init__(self, message: str, *, returncode: Optional[int] = None,
                 stderr_tail: str = "") -> None:
        super().__init__(f"{message}\n{stderr_tail}" if stderr_tail else message)
        self.returncode = returncode
        self.stderr_tail = stderr_tail


class FFmpegTimeout(FFmpegError):
    """ffmpeg/ffprobe ran past its timeout and was killed."""


@dataclass(frozen=True)
class MediaInfo:
    duration: float  # seconds; 0.0 when the container has none (a still image)
    width: Optional[int]
    height: Optional[int]
    fps: Optional[float]
    video_codec: Optional[str]
    has_audio: bool
    audio_codec: Optional[str]
    sample_rate: Optional[int]
    size_bytes: int


@dataclass(frozen=True)
class RunResult:
    returncode: int
    elapsed: float  # seconds
    stderr_tail: str


def install_hint() -> str:
    if sys.platform == "win32":
        return "winget install --id Gyan.FFmpeg -e"
    if sys.platform == "darwin":
        return "brew install ffmpeg"
    return "sudo apt install ffmpeg (or your distribution's package manager)"


def _find(name: str, env: str) -> str:
    # ponytail: read from os.environ; a setting in src/config.py can replace it later
    override = os.environ.get(env)
    if override:
        found = shutil.which(override)
        if not found:
            raise FFmpegNotFound(f"{env}={override!r} is not an executable {name}.")
        return found
    found = shutil.which(name)
    if not found:
        raise FFmpegNotFound(
            f"{name} not found on PATH. Install ffmpeg: {install_hint()}; "
            f"or set {env} to the {name} executable."
        )
    return found


def find_ffmpeg() -> str:
    return _find("ffmpeg", "FFMPEG_PATH")


def find_ffprobe() -> str:
    return _find("ffprobe", "FFPROBE_PATH")


def _tail(stderr: str, n: int = TAIL_LINES) -> str:
    return "\n".join(stderr.strip().splitlines()[-n:])


def _decode(data: Optional[bytes]) -> str:
    return (data or b"").decode("utf-8", errors="replace")


def _fps(rate: Optional[str]) -> Optional[float]:
    """'30000/1001' -> 29.97; '0/0' or missing -> None."""
    try:
        num, _, den = (rate or "").partition("/")
        value = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None
    return value or None


def _int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def probe(path: PathLike, *, timeout_s: float = 30.0) -> MediaInfo:
    """Read a media file's streams with ffprobe. Raises FFmpegError for non-media files."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no such media file: {path}")
    cmd = [find_ffprobe(), "-v", "error", "-print_format", "json",
           "-show_streams", "-show_format", str(path)]
    try:
        proc = guard.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                         timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        raise FFmpegTimeout(f"ffprobe timed out after {timeout_s}s on {path}",
                            stderr_tail=_tail(_decode(e.stderr))) from None
    stderr = _decode(proc.stderr)
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe cannot read {path} (not a media file?)",
                          returncode=proc.returncode, stderr_tail=_tail(stderr))
    data = json.loads(proc.stdout or b"{}")
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    # Cover art in audio files is a "video" stream flagged attached_pic: not real video.
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    # ffprobe "decodes" any .txt/.nfo as ANSI art (tty demuxer): that is not media.
    if (video is None and audio is None) or fmt.get("format_name") == "tty":
        raise FFmpegError(f"{path} has no audio or video stream")
    # Streams often lack a duration (e.g. Matroska/WebM); the container has one.
    duration = fmt.get("duration") or (video or audio).get("duration")
    return MediaInfo(
        duration=float(duration or 0.0),
        width=_int(video.get("width")) if video else None,
        height=_int(video.get("height")) if video else None,
        fps=_fps(video.get("r_frame_rate")) if video else None,
        video_codec=video.get("codec_name") if video else None,
        has_audio=audio is not None,
        audio_codec=audio.get("codec_name") if audio else None,
        sample_rate=_int(audio.get("sample_rate")) if audio else None,
        size_bytes=path.stat().st_size,
    )


def run(args: Sequence[PathLike], *, timeout_s: float,
        log_path: Optional[PathLike] = None) -> RunResult:
    """Run `ffmpeg FIXED_ARGS *args`. Kills it and raises FFmpegTimeout past `timeout_s`;
    raises FFmpegError on a non-zero exit. The full stderr goes to `log_path` if given.
    stdout is discarded: write outputs to files, not to `pipe:`."""
    cmd = [find_ffmpeg(), *FIXED_ARGS, *map(str, args)]
    start = time.monotonic()
    timed_out = False
    try:
        # On timeout subprocess.run kills the child and waits for it (no orphan:
        # ffmpeg spawns no children of its own).
        # Low priority (166): guard.Stopped when the resource guard killed it.
        proc = guard.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.PIPE, timeout=timeout_s)
        returncode, stderr = proc.returncode, _decode(proc.stderr)
    except subprocess.TimeoutExpired as e:
        timed_out, returncode, stderr = True, -1, _decode(e.stderr)
    elapsed = time.monotonic() - start
    if log_path is not None:
        Path(log_path).write_text(stderr, encoding="utf-8")
    tail = _tail(stderr)
    if timed_out:
        raise FFmpegTimeout(f"ffmpeg timed out after {timeout_s}s and was killed",
                            stderr_tail=tail)
    if returncode != 0:
        raise FFmpegError(f"ffmpeg exited with code {returncode}", returncode=returncode,
                          stderr_tail=tail)
    return RunResult(returncode=returncode, elapsed=elapsed, stderr_tail=tail)
