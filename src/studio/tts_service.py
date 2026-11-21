"""
The local VoxCPM2 voice service (step 038, vendor/voxcpm_tts) as a child of `ig-campaign up`
when TTS_SERVER_PYTHON is set: spawn() on TTS_HTTP_URL's port (loopback), wait_ready() before
the worker starts, downloader_service.stop() on exit. The child watches this process's pid and
exits when it is gone, so a killed studio leaves no process holding the GPU. It runs at low
priority and loads no model before the startup grace ends (step 166).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urlsplit

import httpx

from ..config import APP_HOME, InstagramMCPSettings
from . import guard

SERVER = Path(__file__).resolve().parents[2] / "vendor" / "voxcpm_tts" / "server.py"
LOG_PATH = APP_HOME / "data" / "logs" / "tts.log"
READY_WAIT_S = 120.0  # the service is up in seconds: its model loads on the first request


def command(settings: InstagramMCPSettings) -> List[str]:
    port = urlsplit(settings.tts_http_url or "").port
    if not port:
        raise ValueError("TTS_SERVER_PYTHON needs TTS_HTTP_URL with a port, e.g. "
                         "http://127.0.0.1:8766/tts")
    return [settings.tts_server_python, str(SERVER), "--host", "127.0.0.1", "--port", str(port),
            "--exit-with-pid", str(os.getpid())]


def health_url(settings: InstagramMCPSettings) -> str:
    return urlsplit(settings.tts_http_url)._replace(path="/health", query="").geturl()


def spawn(settings: InstagramMCPSettings, log_path: Path = LOG_PATH,
          popen: Callable[..., subprocess.Popen] = subprocess.Popen) -> subprocess.Popen:
    """Start the service; its output is appended to log_path. ValueError: bad TTS_HTTP_URL."""
    env = dict(os.environ)
    if settings.tts_server_hf_home:
        env["HF_HOME"] = settings.tts_server_hf_home
    if settings.gpu_lock_path:  # the same GPU lock as this studio's renders (.env is ours)
        env["GPU_LOCK_PATH"] = settings.gpu_lock_path
    # the studio's resource guard (166): its RAM floor, and no model load in the startup grace
    env["GUARD_MIN_FREE_RAM_GB"] = str(settings.guard_min_free_ram_gb)
    env["GUARD_CPU_SHARE"] = str(settings.guard_cpu_share)  # its CPUs and torch threads (171)
    env["GUARD_NOT_BEFORE"] = str(time.time() + settings.guard_startup_grace_min * 60)
    cmd = command(settings)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as log:  # the child keeps its own handle
        return popen(cmd, **guard.low_priority(dict(  # its model worker inherits it
            cwd=SERVER.parent, env=env, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT)))


async def wait_ready(settings: InstagramMCPSettings, proc: subprocess.Popen, *,
                     timeout_s: float = READY_WAIT_S, poll_s: float = 2.0) -> bool:
    """True once /health answers (the service is up; its model loads on the first request,
    step 145); False when the child died or timeout_s passed."""
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(timeout=5, trust_env=False) as http:
        while proc.poll() is None and time.monotonic() < deadline:
            try:
                if (await http.get(health_url(settings))).status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(poll_s)
    return False


def worker_pid(settings: InstagramMCPSettings) -> Optional[int]:
    """The voice model worker's pid while its models are loaded, else None (the resource
    guard's watchdog may pause or stop it, never the service itself: step 166)."""
    try:
        pid = httpx.get(health_url(settings), timeout=2, trust_env=False).json()["worker_pid"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    return pid if isinstance(pid, int) else None
