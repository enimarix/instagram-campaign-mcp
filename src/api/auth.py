"""
Website password (step 008): sessions, login lockout, origin check, bind guard.

Pure logic here; `app.py` wires it as a middleware plus thin login routes.
With no UI_PASSWORD everything is open to loopback Host names only; the origin check always runs.
Sessions survive a restart (168): their keyed digests live in the store's `ui_sessions` state.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import secrets
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from ..config import InstagramMCPSettings

COOKIE = "studio_session"
SESSIONS_KEY = "ui_sessions"  # worker_state key: {sha256-HMAC digest: expiry}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class Locked(Exception):
    def __init__(self, retry_after: int):
        super().__init__(f"locked for {retry_after}s")
        self.retry_after = retry_after


class Auth:
    # ponytail: the failure counter lives in memory (a restart clears the lock); one global
    # counter is fine for a single-owner studio. Sessions go to `store` when one is attached
    # (app.py's lifespan does), else to memory (tests, no store).
    def __init__(self, settings: InstagramMCPSettings, clock: Callable[[], float] = time.time,
                 store: Any = None):
        secret = settings.ui_password.get_secret_value() if settings.ui_password else ""
        self.required = bool(secret)
        self._password_hash = hashlib.sha256(secret.encode("utf-8")).digest()
        self.ttl = settings.session_ttl_hours * 3600
        self.max_failures = settings.login_max_failures
        self.lockout = settings.login_lockout_minutes * 60
        self.clock = clock
        self.store = store
        self._sessions: Dict[str, float] = {}  # _digest(token) -> expiry
        self._failures: List[float] = []
        self._locked_until = 0.0

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

    def _digest(self, token: str) -> str:
        # Keyed by the password hash: a changed UI_PASSWORD makes every old session unknown, and
        # the database never holds the token nor anything to guess the password from.
        return hmac.new(self._password_hash, token.encode(), hashlib.sha256).hexdigest()

    def _load(self) -> Dict[str, float]:
        if self.store is None:
            return dict(self._sessions)
        saved = self.store.get_state(SESSIONS_KEY)
        return dict(saved) if isinstance(saved, dict) else {}

    def _save(self, sessions: Dict[str, float]) -> None:
        now = self.clock()
        sessions = {h: exp for h, exp in sessions.items() if exp > now}  # prune expired
        if self.store is None:
            self._sessions = sessions
        else:
            self.store.set_state(SESSIONS_KEY, sessions)

    def new_session(self) -> str:
        token = secrets.token_urlsafe(32)
        sessions = self._load()
        sessions[self._digest(token)] = self.clock() + self.ttl
        self._save(sessions)
        return token

    def valid(self, token: Optional[str]) -> bool:
        return bool(token) and self._load().get(self._digest(token), 0) > self.clock()

    def logout(self, token: Optional[str]) -> None:
        if token:
            sessions = self._load()
            sessions.pop(self._digest(token), None)
            self._save(sessions)


def reauth_error(auth: Auth, password: Any) -> Optional[Tuple[int, Dict[str, Any]]]:
    """Ask the website password again before a money action (GOAL.md §5.4: ads unkill in
    091, budget approval in 094). None = confirmed, else (HTTP status, JSON body).

    Without UI_PASSWORD nothing can confirm, so the action is refused.
    """
    if not auth.required:
        return 403, {"error": "password_not_set"}
    if not isinstance(password, str) or not password:
        return 400, {"error": "password_required"}
    try:
        ok = auth.check_password(password)
    except Locked as e:
        return 429, {"error": "locked", "retry_after": e.retry_after}
    return None if ok else (403, {"error": "bad_password"})


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


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def host_ok(hostname: Optional[str], password_set: bool) -> bool:
    """DNS-rebinding guard: without a password, only loopback Host names reach the studio.

    A rebinding page talks to 127.0.0.1 under its own domain name, so its Host header gives it
    away. With a password the studio may be reached by any name (phone over LAN / Tailscale).
    """
    return password_set or (hostname or "").lower() in LOOPBACK_HOSTS


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
