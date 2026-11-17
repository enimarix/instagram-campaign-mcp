"""
Website password (step 008): sessions, login lockout, origin check, bind guard.

Pure logic here; `app.py` wires it as a middleware plus thin login routes.
With no UI_PASSWORD everything is open (loopback use) but the origin check still runs.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import secrets
import time
from typing import Callable, Dict, List, Optional
from urllib.parse import urlsplit

from ..config import InstagramMCPSettings

COOKIE = "studio_session"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class Locked(Exception):
    def __init__(self, retry_after: int):
        super().__init__(f"locked for {retry_after}s")
        self.retry_after = retry_after


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Auth:
    # ponytail: sessions and the failure counter live in memory: a restart logs everyone out
    # and clears the lock. One global counter is fine for a single-owner studio.
    def __init__(self, settings: InstagramMCPSettings, clock: Callable[[], float] = time.time):
        secret = settings.ui_password.get_secret_value() if settings.ui_password else ""
        self._required = bool(secret)
        self._password_hash = hashlib.sha256(secret.encode("utf-8")).digest()
        self.ttl = settings.session_ttl_hours * 3600
        self.max_failures = settings.login_max_failures
        self.lockout = settings.login_lockout_minutes * 60
        self.clock = clock
        self._sessions: Dict[str, float] = {}  # sha256(token) -> expiry
        self._failures: List[float] = []
        self._locked_until = 0.0

    @property
    def required(self) -> bool:
        return self._required

    def check_password(self, password: str) -> bool:
        """Constant-time check that counts failures and honours the lock.

        Reusable for re-asking the password (ad budgets, GOAL.md §5.4). Raises `Locked`.
        """
        now = self.clock()
        if now < self._locked_until:
            raise Locked(math.ceil(self._locked_until - now))
        # Hashing first makes the comparison length-independent too.
        given = hashlib.sha256(password.encode("utf-8", "surrogatepass")).digest()
        if hmac.compare_digest(given, self._password_hash):
            self._failures.clear()
            return True
        self._failures = [t for t in self._failures if now - t < self.lockout] + [now]
        if len(self._failures) >= self.max_failures:
            self._failures.clear()
            self._locked_until = now + self.lockout
        return False

    def new_session(self) -> str:
        now = self.clock()
        self._sessions = {h: exp for h, exp in self._sessions.items() if exp > now}
        token = secrets.token_urlsafe(32)
        self._sessions[_digest(token)] = now + self.ttl
        return token

    def valid(self, token: Optional[str]) -> bool:
        return bool(token) and self._sessions.get(_digest(token), 0) > self.clock()

    def logout(self, token: Optional[str]) -> None:
        if token:
            self._sessions.pop(_digest(token), None)


def _origin(url: str) -> tuple:
    p = urlsplit(url)
    try:
        port = p.port
    except ValueError:  # malformed port: never equal to a real origin
        return ("invalid",)
    scheme = p.scheme.lower()
    return (scheme, (p.hostname or "").lower(), port or {"http": 80, "https": 443}.get(scheme))


def origin_ok(method: str, url: str, headers, has_session_cookie: bool) -> bool:
    """CSRF guard for state-changing requests.

    Origin (else Referer) present and not this site's own → refuse. Both missing → allow only
    when the request carries no session cookie (curl / scripts; browsers always send Origin on
    cross-site POST, so a cookie-carrying request without it is refused to be safe).
    """
    if method.upper() not in UNSAFE_METHODS:
        return True
    claimed = headers.get("origin") or headers.get("referer")
    if not claimed:
        return not has_session_cookie
    return _origin(claimed) == _origin(url)


def bind_error(host: str, settings: InstagramMCPSettings) -> Optional[str]:
    """Message refusing a non-loopback bind without UI_PASSWORD, else None."""
    if settings.ui_password and settings.ui_password.get_secret_value():
        return None
    if host.lower() == "localhost":
        return None
    try:
        if ipaddress.ip_address(host.strip("[]")).is_loopback:
            return None
    except ValueError:
        pass
    return (f"Refusing to serve on {host!r} without a password: anyone on the network could "
            "use the studio. Set UI_PASSWORD in .env, or use --host 127.0.0.1.")
