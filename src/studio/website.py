"""
The website the studio serves is never stale (step 175): `ig-campaign up` rebuilds web/dist
before serving when a source is newer than the build (merges never rebuilt it: 168, 169 and
172's pages stayed invisible for two days). `ig-campaign web build` builds it by hand.

The build goes to a sibling folder first and replaces web/dist only once it succeeded, so a
failed build keeps the old site; the failure becomes a website alert (STATE_KEY) until a
build succeeds. npm runs at low priority on half the CPUs (guard.run).
"""

from __future__ import annotations

import shutil
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import InstagramMCPSettings
from ..store import CampaignStore, to_iso, utcnow
from . import guard

STATE_KEY = "website_build"
BUILD_TIMEOUT_S = 600.0
ERROR_TAIL = 160  # characters of npm's output kept for the alert (alerts cut at 300)


def sources(web: Path) -> list[Path]:
    """The files a build depends on: web/src, web/index.html, web/package.json."""
    src = web / "src"
    found = [p for p in src.rglob("*") if p.is_file()] if src.is_dir() else []
    return [*found, *(p for p in (web / "index.html", web / "package.json") if p.is_file())]


def stale(settings: InstagramMCPSettings) -> bool:
    """True when web/dist is missing or older than one of its sources (False without
    sources: a web_dist that is not built from a web/ folder here)."""
    dist = Path(settings.web_dist)
    web = dist.parent
    if not (web / "package.json").is_file():
        return False
    try:
        built = (dist / "index.html").stat().st_mtime
    except OSError:
        return True
    return any(p.stat().st_mtime > built for p in sources(web))


def build(settings: InstagramMCPSettings) -> Dict[str, Any]:
    """`npm run build` in web/ into a fresh folder, swapped in for web/dist when it worked.
    {ok, error, at}; never raises (a failure keeps the old dist)."""
    dist = Path(settings.web_dist)
    web, new = dist.parent, dist.with_name(dist.name + ".new")
    npm = shutil.which("npm")  # npm.cmd on Windows
    error: Optional[str] = None
    if not npm:
        error = "Node.js is not installed (npm not found)"
    elif not (web / "node_modules").is_dir():
        error = "web/node_modules is missing: run npm --prefix web ci"
    else:
        shutil.rmtree(new, ignore_errors=True)
        try:  # npm passes the args after -- to the script's last command, vite build
            r = guard.run([npm, "run", "build", "--", "--outDir", str(new), "--emptyOutDir"],
                          cwd=web, capture_output=True, timeout=BUILD_TIMEOUT_S,
                          encoding="utf-8", errors="replace")
            if r.returncode:
                error = f"npm run build exited {r.returncode}: " + (
                    (r.stdout or "") + (r.stderr or "")).strip()[-ERROR_TAIL:]
            elif not (new / "index.html").is_file():
                error = "npm run build wrote no index.html"
        except (OSError, subprocess.SubprocessError, guard.Stopped) as e:
            error = f"npm run build failed: {e}"
        if error is None:
            old = dist.with_name(dist.name + ".old")
            shutil.rmtree(old, ignore_errors=True)
            try:
                if dist.exists():
                    dist.replace(old)
                new.replace(dist)
            except OSError as e:
                error = f"the new build could not replace {dist.name}: {e}"
                if not dist.exists() and old.exists():
                    with suppress(OSError):
                        old.replace(dist)
            shutil.rmtree(old, ignore_errors=True)
        shutil.rmtree(new, ignore_errors=True)
    return {"ok": error is None, "error": error, "at": to_iso(utcnow())}


def record(store: CampaignStore, result: Dict[str, Any]) -> None:
    """Keep the last build's result: a failed one shows as a website alert."""
    store.set_state(STATE_KEY, result)


def rebuild_if_stale(settings: InstagramMCPSettings, store: Optional[CampaignStore] = None
                     ) -> Optional[Dict[str, Any]]:
    """`up`'s step before serving: build when stale, record the result; None when fresh
    (a failure recorded earlier is cleared then: someone built it by hand)."""
    if not stale(settings):
        if store is not None and (store.get_state(STATE_KEY) or {}).get("ok") is False:
            record(store, {"ok": True, "error": None, "at": to_iso(utcnow())})
        return None
    result = build(settings)
    if store is not None:
        record(store, result)
    return result
