"""
The Reel downloader service (step 063a, GOAL.md §5.1): the owner's chosen downloader,
Okramjimmy/Instagram-reels-downloader (Next.js, MIT), vendored as a git submodule in
vendor/instagram-reels-downloader and run on 127.0.0.1 only.

- `ig-campaign downloader setup|update|status` (src/scheduler.py) call setup(), update(),
  status(). One-shot commands (npm, git) all go through run_cmd().
- The worker (src/worker.py downloader_loop) starts start_command() once the build exists
  (built()), restarts it when it dies, stops it on exit, and stores health_check() daily
  in worker state `downloader_health`.
- Only its `/api/video` API is ever called, never its pages (they carry AdSense). It is
  logged out by design: it never gets an Instagram credential, and its environment is an
  allow-list (child_env), so no secret of ours reaches the third-party code. Its Upstash
  rate limiter stays off (USE_UPSTASH=false).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx
import structlog

from ..config import APP_HOME, InstagramMCPSettings
from ..store import CampaignStore, to_iso, utcnow

logger = structlog.get_logger(__name__)

VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendor" / "instagram-reels-downloader"
LOG_PATH = APP_HOME / "data" / "logs" / "downloader.log"  # the service's own output
HOST = "127.0.0.1"  # loopback only, never exposed
STATE_KEY = "downloader_health"
CMD_TIMEOUT_S = 1800.0  # npm ci / next build on a slow disk
HEALTH_TIMEOUT_S = 60.0
READY_WAIT_S = 60.0  # update: how long a fresh server may take to answer
TAIL_CHARS = 2000
# Variables the third-party code gets (proxies for npm behind one); nothing else of ours.
ENV_KEEP = ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME",
            "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")


class DownloaderError(RuntimeError):
    """A setup/update command failed, or the submodule is missing."""


def built() -> bool:
    """`downloader setup` ran: the worker starts the service only then."""
    return (VENDOR_DIR / ".next" / "BUILD_ID").is_file()


def child_env() -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() in ENV_KEEP}
    env.update(USE_UPSTASH="false", NEXT_TELEMETRY_DISABLED="1")
    return env


def start_command(settings: InstagramMCPSettings) -> List[str]:
    """`next start` on loopback, run with node directly (a .cmd shim would outlive a stop)."""
    node = os.environ.get("NODE_BIN") or "node"
    return [node, str(VENDOR_DIR / "node_modules" / "next" / "dist" / "bin" / "next"), "start",
            "-H", HOST, "-p", str(settings.downloader_port)]


def spawn(settings: InstagramMCPSettings, log_path: Path = LOG_PATH,
          popen: Callable[..., subprocess.Popen] = subprocess.Popen) -> subprocess.Popen:
    """Start the service; its output is appended to log_path."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as log:  # the child keeps its own handle
        return popen(start_command(settings), cwd=VENDOR_DIR,
                     env={**child_env(), "NODE_ENV": "production"},
                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def run_cmd(cmd: List[str], *, check: bool = True,
            timeout_s: float = CMD_TIMEOUT_S) -> subprocess.CompletedProcess:
    """Every one-shot command (npm, git), in the submodule (mocked in tests)."""
    exe = shutil.which(cmd[0]) or cmd[0]  # npm is npm.cmd on Windows
    try:
        done = subprocess.run([exe, *cmd[1:]], cwd=VENDOR_DIR, env=child_env(),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DownloaderError(f"{' '.join(cmd)}: {e}") from None
    if check and done.returncode != 0:
        tail = (done.stderr or done.stdout).strip()[-TAIL_CHARS:]
        raise DownloaderError(f"{' '.join(cmd)} failed ({done.returncode}): {tail}")
    return done


def _submodule() -> None:
    if not (VENDOR_DIR / "package.json").is_file():
        raise DownloaderError("submodule missing: run `git submodule update --init "
                              "vendor/instagram-reels-downloader`")


def build() -> Dict[str, Any]:
    """npm ci (lockfile only), next build, then npm audit: advisories are logged, not fatal."""
    run_cmd(["npm", "ci"])
    run_cmd(["npm", "run", "build"])
    out = run_cmd(["npm", "audit", "--omit=dev", "--json"], check=False).stdout
    try:
        audit = json.loads(out)["metadata"]["vulnerabilities"]
    except (ValueError, KeyError, TypeError):
        audit = {"error": "npm audit output unreadable"}
    logger.info("downloader_audit", **audit)
    return audit


def setup() -> Dict[str, Any]:
    _submodule()
    audit = build()
    return {"built": True, "commit": commit(), "audit": audit}


def commit() -> Optional[str]:
    if not (VENDOR_DIR / ".git").exists():  # not checked out: git would answer for our repo
        return None
    return run_cmd(["git", "rev-parse", "HEAD"]).stdout.strip()


def port_open(port: int) -> bool:
    try:
        with socket.create_connection((HOST, port), timeout=1):
            return True
    except OSError:
        return False


async def health_check(settings: InstagramMCPSettings) -> Dict[str, Any]:
    """{status: up | down (no connection) | broken (bad answer, no video URL) |
    not_configured, checked_at, detail?}"""
    result: Dict[str, Any] = {"status": "not_configured", "checked_at": to_iso(utcnow())}
    if not settings.downloader_health_url:
        return result
    url = f"http://{HOST}:{settings.downloader_port}/api/video"
    try:
        async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_S, trust_env=False) as http:
            r = await http.get(url, params={"postUrl": settings.downloader_health_url,
                                            "enhanced": "true"})
    except httpx.ConnectError:
        return {**result, "status": "down"}
    except httpx.HTTPError as e:
        return {**result, "status": "broken", "detail": type(e).__name__}
    try:
        body = r.json()
        medias = body["data"]["medias"]
        ok = r.status_code == 200 and any(m.get("type") == "video" and m.get("url")
                                          for m in medias)
    except (ValueError, KeyError, TypeError, AttributeError):
        ok, body = False, None
    if ok:
        return {**result, "status": "up"}
    message = body.get("message") if isinstance(body, dict) else None
    return {**result, "status": "broken",
            "detail": f"HTTP {r.status_code}" + (f": {str(message)[:200]}" if message else "")}


async def check_and_store(store: CampaignStore, settings: InstagramMCPSettings
                          ) -> Dict[str, Any]:
    result = await health_check(settings)
    store.set_state(STATE_KEY, result)
    return result


async def _health_when_ready(settings: InstagramMCPSettings) -> Dict[str, Any]:
    deadline = time.monotonic() + READY_WAIT_S
    while True:
        result = await health_check(settings)
        if result["status"] != "down" or time.monotonic() >= deadline:
            return result
        await asyncio.sleep(1.0)


async def update(settings: InstagramMCPSettings, log_path: Path = LOG_PATH
                 ) -> Dict[str, Any]:
    """Move the submodule to upstream's latest commit, rebuild, health-check it on a
    temporary server; anything failing rolls back to the previous commit and rebuilds."""
    _submodule()
    if not settings.downloader_health_url:
        raise DownloaderError("set DOWNLOADER_HEALTH_URL first: an update is kept only "
                              "when the health check passes")
    if port_open(settings.downloader_port):
        raise DownloaderError(f"port {settings.downloader_port} is in use: stop "
                              "`ig-campaign up` / the worker first")
    old = commit()
    run_cmd(["git", "fetch", "origin", "HEAD"])
    new = run_cmd(["git", "rev-parse", "FETCH_HEAD"]).stdout.strip()
    if new == old:
        return {"updated": False, "commit": old, "detail": "already the latest commit"}
    run_cmd(["git", "checkout", "--quiet", new])
    health: Dict[str, Any] = {"status": "broken"}
    try:
        build()
        proc = spawn(settings, log_path)
        try:
            health = await _health_when_ready(settings)
        finally:
            stop(proc)
    except (DownloaderError, OSError) as e:  # OSError: e.g. node missing
        health["detail"] = str(e)[-TAIL_CHARS:]
    if health["status"] == "up":
        return {"updated": True, "commit": new, "previous": old, "health": health}
    logger.warning("downloader_update_rolled_back", commit=new, status=health["status"])
    run_cmd(["git", "checkout", "--quiet", old])
    build()
    return {"updated": False, "commit": old, "rolled_back_from": new, "health": health}


def status(store: CampaignStore, settings: InstagramMCPSettings) -> Dict[str, Any]:
    return {"set_up": built(), "host": HOST, "port": settings.downloader_port,
            "health_configured": bool(settings.downloader_health_url),
            "health": store.get_state(STATE_KEY)}
