"""`ig-campaign doctor`: is everything the studio needs in place? (step 100)

The installers end with it and the owner can re-run it any time. It changes nothing
and calls no network service (the token's expiry is `ig-campaign token status`).
Each check is {name, ok, detail, fix}; fix says what to do and is empty when ok.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ..agent.runner import AgentError, preflight
from ..config import ENV_FILE, InstagramMCPSettings
from . import cinematic, downloader_service, ffmpeg, motion

Check = Dict[str, Any]

FFMPEG_FIX = f"install ffmpeg ({ffmpeg.install_hint()}), then open a new terminal"
DOWNLOADER_FIX = ("git submodule update --init vendor/instagram-reels-downloader, "
                  "then ig-campaign downloader setup")


def checks(settings: InstagramMCPSettings, env_file: str = ENV_FILE) -> List[Check]:
    out: List[Check] = []

    def add(name: str, ok: bool, detail: str, fix: str) -> None:
        out.append({"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix})

    env = Path(env_file)
    add(".env", env.is_file(), str(env), "copy env.example to .env (the installer does it)")
    ig_set = settings.instagram_configured  # env.example's placeholders count as not set
    add("Instagram account", ig_set, "token and account id set" if ig_set
        else "token or account id missing, or still env.example's placeholder",
        "set INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_BUSINESS_ACCOUNT_ID in .env, "
        "then ig-campaign token status")
    for name, find in (("ffmpeg", ffmpeg.find_ffmpeg), ("ffprobe", ffmpeg.find_ffprobe)):
        try:
            add(name, True, find(), "")
        except ffmpeg.FFmpegNotFound as e:
            add(name, False, str(e), FFMPEG_FIX)
    try:
        add("Node.js + motion packages", True, motion.find_node(), "")
    except motion.MotionError as e:
        add("Node.js + motion packages", False, str(e),
            "install Node.js 22.12+, then npm --prefix motion ci")
    try:
        add("Blender (cinematic style)", True, cinematic.find_blender(), "")
    except cinematic.CinematicError as e:
        add("Blender (cinematic style)", False, str(e), "python cinematic/setup.py")
    index = Path(settings.web_dist) / "index.html"
    add("website build", index.is_file(), str(index.parent),
        "npm --prefix web ci, then npm --prefix web run build")
    checked_out = (downloader_service.VENDOR_DIR / "package.json").is_file()
    add("Reel downloader", checked_out and downloader_service.built(),
        "built" if downloader_service.built() else
        "not built yet" if checked_out else "submodule not checked out", DOWNLOADER_FIX)
    try:
        add("Claude Code CLI", True, f"{preflight(settings)} (signed in)", "")
    except AgentError as e:
        add("Claude Code CLI", False, str(e),
            "install Claude Code, run claude auth login, then ig-campaign agent check")
    return out
