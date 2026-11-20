"""
Token care: how long the Instagram access token has left, and swapping it for a new one.

The token lives in `.env` only (GOAL.md §5.4): these helpers never return, print or log it.
Meta docs (verified for step 029):
- `GET /debug_token?input_token=<token>` with an app access token (`app_id|app_secret`) or a
  token of a developer of the app; returns `data.{is_valid, expires_at, scopes, ...}`.
- `GET /oauth/access_token?grant_type=fb_exchange_token&client_id&client_secret
  &fb_exchange_token` returns a new long-lived (~60 days) token; an expired one can't be swapped.
Both carry secrets in the query string: `logging_setup` keeps httpx's URL logging off.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from ..config import InstagramMCPSettings
from ..instagram_client import AccessBlocked, InstagramAPIError, InstagramClient

CACHE_SECONDS = 3600.0
ERROR_CACHE_SECONDS = 600.0  # a failed check (Meta blocked, bad app credentials)
INVALID_TOKEN = 190  # Graph error code for an expired / revoked token
ENV_KEY = "INSTAGRAM_ACCESS_TOKEN"
_ENV_LINE = re.compile(rf"^\s*(export\s+)?{ENV_KEY}\s*=", re.IGNORECASE)
_status: Dict[str, Tuple[float, Dict[str, Any]]] = {}  # sha256(token) -> (taken at, status)


class RefreshRefused(Exception):
    """Refresh can't run safely; the message says why (never contains the token)."""


def _app_token(settings: InstagramMCPSettings) -> Optional[str]:
    secret = settings.facebook_app_secret
    secret = secret.get_secret_value() if secret else ""
    return f"{settings.facebook_app_id}|{secret}" if settings.facebook_app_id and secret else None


def _iso(ts: Optional[int]) -> Optional[str]:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None


async def token_status(client: Optional[InstagramClient], settings: InstagramMCPSettings,
                       clock: Callable[[], float] = time.time) -> Dict[str, Any]:
    """{configured, valid, expires_at, days_left, can_refresh, scopes[, error]}; cached an
    hour, a failed check 10 min (never raised: `valid` None and Meta's `error` text).

    `valid`/`expires_at` are None when unknown (no client). A valid token with `expires_at`
    None never expires (system-user token: debug_token reports expires_at 0).
    """
    token = settings.instagram_access_token
    out: Dict[str, Any] = {"configured": bool(token), "valid": None, "expires_at": None,
                           "days_left": None, "can_refresh": _app_token(settings) is not None,
                           "scopes": []}
    if not token or client is None:
        return out
    key = hashlib.sha256(token.encode()).hexdigest()
    now = clock()
    hit = _status.get(key)
    if hit and now - hit[0] < (ERROR_CACHE_SECONDS if "error" in hit[1] else CACHE_SECONDS):
        return {**hit[1], "can_refresh": out["can_refresh"]}
    app_token = _app_token(settings)
    try:
        # Without app credentials, the token inspects itself (works for the app's developers).
        data = (await client._make_request("GET", "debug_token", params={"input_token": token},
                                           token=app_token)).get("data") or {}
    except InstagramAPIError as e:
        # With an app token, a bad input token answers 200 is_valid=false; 190 = bad app creds.
        if isinstance(e, AccessBlocked) or e.error_code != INVALID_TOKEN or app_token:
            out["error"] = e.message
            _status[key] = (now, out)
            return out
        data = {"is_valid": False}
    expires = data.get("expires_at") or None
    out.update(valid=bool(data.get("is_valid")), expires_at=_iso(expires),
               days_left=int((expires - now) // 86400) if expires else None,
               scopes=list(data.get("scopes") or []))
    _status[key] = (now, out)
    return out


def _env_has_token(env_path: Path) -> bool:
    try:
        return any(_ENV_LINE.match(line) for line in env_path.read_text("utf-8").splitlines())
    except OSError:
        return False


def write_env_token(env_path: Path, token: str) -> None:
    """Replace the INSTAGRAM_ACCESS_TOKEN line(s); every other line, comment, line ending and
    the file mode stay. Atomic: a temp file in the same folder, then os.replace."""
    lines = env_path.read_bytes().decode("utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if _ENV_LINE.match(line):
            ending = line[len(line.rstrip("\r\n")):]
            lines[i] = f"{ENV_KEY}={token}{ending}"
    fd, tmp = tempfile.mkstemp(dir=env_path.parent, prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.writelines(lines)
        shutil.copymode(env_path, tmp)
        os.replace(tmp, env_path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


async def refresh_token(client: InstagramClient, settings: InstagramMCPSettings,
                        env_path: Path, clock: Callable[[], float] = time.time) -> Dict[str, Any]:
    """Swap the token for a new long-lived one and store it in `env_path`.

    Returns {"expires_at": ISO or None}. Raises RefreshRefused before any call when it can't
    store the result safely (no app id/secret, token set in the process env, no line in .env).
    """
    if _app_token(settings) is None:
        raise RefreshRefused("set FACEBOOK_APP_ID and FACEBOOK_APP_SECRET in .env to refresh")
    if any(k.upper() == ENV_KEY for k in os.environ):
        raise RefreshRefused(f"{ENV_KEY} comes from the process environment, not {env_path}; "
                             "can't rewrite it safely. Refresh it where it is set.")
    if not _env_has_token(env_path):
        raise RefreshRefused(f"no {ENV_KEY}= line in {env_path}")
    data = await client._make_request("GET", "oauth/access_token", params={
        "grant_type": "fb_exchange_token", "client_id": settings.facebook_app_id,
        "client_secret": settings.facebook_app_secret.get_secret_value(),
        "fb_exchange_token": settings.instagram_access_token})
    new = data.get("access_token")
    if not isinstance(new, str) or not new or "\n" in new or "\r" in new:
        raise InstagramAPIError("token exchange returned no usable access_token")
    write_env_token(env_path, new)
    expires_in = data.get("expires_in")
    return {"expires_at": _iso(int(clock() + expires_in)) if expires_in else None}
