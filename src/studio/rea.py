"""
rea-video (JuneYaooo/rea-video, Apache-2.0): a Reel broken down shot by shot (how each shot
was made, its timing, on-screen text, sound) into a VIDEO.md package, for a DM order the
owner confirmed with the « rea-video » route (work_orders.METHODS). It renders nothing: the
agent reads the breakdown (breakdown_reel) and remakes the video with our own templates.

`ig-campaign rea setup` clones it into vendor/rea-video (git-ignored) with its own venv, so
its heavy dependencies (opencv, onnxruntime) stay out of ours. It runs offline (no vision
model, no key) with the downloader's environment allow-list: no secret of ours reaches the
third-party code. A breakdown is kept in data/rea/<source_id> and reused.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from ..config import APP_HOME, InstagramMCPSettings
from ..store import CampaignStore
from . import media
from .downloader_service import child_env

REPO_URL = "https://github.com/JuneYaooo/rea-video"
VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendor" / "rea-video"
OUT_DIR = APP_HOME / "data" / "rea"
SETUP_TIMEOUT_S = 30 * 60
DECOMPOSE_TIMEOUT_S = 20 * 60  # ~1 min per 30 s of video on CPU; the first run also downloads ~220 MB of models
# what a remake with our templates needs (the agent cannot open files outside its workspace);
# remake.md (AI-generation prompts, ~20k) is left out: we never generate the Reel's shots
READ_FILES = ("VIDEO.md", "video/timeline.md", "video/content.md", "video/rhythm.md",
              "video/packaging.md", "video/sound.md", "video/cast.md")
READ_CHARS = 40_000
TAIL_CHARS = 1500


class ReaError(RuntimeError):
    """rea-video is missing, or one of its commands failed."""


def exe() -> Path:
    """The venv's python (run as `python -m rea_video`: a timeout then kills the process
    doing the work, not a launcher whose child would keep running)."""
    bin_dir, name = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    return VENDOR_DIR / ".venv" / bin_dir / name


def _run(cmd: List[str], timeout_s: float) -> None:
    try:
        # UTF-8: its messages are partly Chinese, which Windows' cp1252 cannot print
        done = subprocess.run(cmd, env={**child_env(), "PYTHONUTF8": "1",
                                        "PYTHONIOENCODING": "utf-8"},
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ReaError(f"{' '.join(cmd[:4])}: {e}") from None
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip()[-TAIL_CHARS:]
        raise ReaError(f"{' '.join(cmd[:4])} failed ({done.returncode}): {tail}")


def setup() -> Dict[str, Any]:
    """Clone (once), make its venv, install it with OCR (on-screen text), then the opencv fix
    its install script does (the OCR extra pulls the GUI opencv over the headless one)."""
    if not (VENDOR_DIR / "pyproject.toml").is_file():
        _run(["git", "clone", "--depth", "1", REPO_URL, str(VENDOR_DIR)], SETUP_TIMEOUT_S)
    venv = VENDOR_DIR / ".venv"
    if not venv.is_dir():
        _run([sys.executable, "-m", "venv", str(venv)], SETUP_TIMEOUT_S)
    py = str(exe())
    _run([py, "-m", "pip", "install", "-q", "-e", f"{VENDOR_DIR}[ocr]"], SETUP_TIMEOUT_S)
    _run([py, "-m", "pip", "uninstall", "-q", "-y", "opencv-python"], SETUP_TIMEOUT_S)
    _run([py, "-m", "pip", "install", "-q", "--force-reinstall", "--no-deps",
          "opencv-python-headless>=4.8,<5"], SETUP_TIMEOUT_S)
    return status()


def installed() -> bool:
    """pip's last step, the console script, exists: the install finished."""
    return (exe().parent / ("rea-video.exe" if os.name == "nt" else "rea-video")).is_file()


def status() -> Dict[str, Any]:
    return {"installed": installed(), "folder": str(VENDOR_DIR)}


def breakdown(store: CampaignStore, settings: InstagramMCPSettings, source_id: int
              ) -> Dict[str, Any]:
    """The downloaded Reel `source_id` broken down (made once, then reused): {source_id,
    folder, breakdown (READ_FILES joined, at most READ_CHARS), truncated}. ValueError: not downloaded, or rea-video not
    installed; ReaError: the breakdown failed."""
    source = store.get_source(source_id)
    if not source["local_path"]:
        raise ValueError(f"source {source_id} has no video file: download_reel first")
    if not installed():
        raise ValueError("rea-video is not installed here: the owner runs `ig-campaign rea"
                         " setup`; make the order without the breakdown and say so")
    out = OUT_DIR / str(source_id)
    if not (out / "VIDEO.md").is_file():
        video = media.resolve(settings.media_root, source["local_path"])
        _run([str(exe()), "-m", "rea_video", "decompose", str(video), "-o", str(out),
              "--lang", "en", "--no-vlm"],
             DECOMPOSE_TIMEOUT_S)
    text = "\n\n".join(f"=== {name} ===\n{(out / name).read_text(encoding='utf-8')}"
                       for name in READ_FILES if (out / name).is_file())
    return {"source_id": source_id, "folder": str(out), "breakdown": text[:READ_CHARS],
            "truncated": len(text) > READ_CHARS}
