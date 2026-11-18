"""Step 008: website password, sessions, origin check, lockout, bind guard."""

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.auth import Auth, bind_error
from src.config import InstagramMCPSettings

PASSWORD = "correct horse"


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def _settings(password=PASSWORD, **kw):
    return InstagramMCPSettings(_env_file=None, database_path=":memory:",
                                instagram_access_token=None, ui_password=password, **kw)


@pytest.fixture
def make():
    """make(password, clock, base_url, **settings) -> (started TestClient, Auth)."""
    started = []

    def _make(password=PASSWORD, clock=None, base_url="http://127.0.0.1", **kw):
        s = _settings(password, **kw)
        auth = Auth(s, clock or Clock())
        tc = TestClient(create_app(s, auth=auth), base_url=base_url)
        started.append(tc.__enter__())  # runs the lifespan (app.state.client)
        return tc, auth

    yield _make
    for tc in started:
        tc.__exit__(None, None, None)


def _login(tc, password=PASSWORD):
    return tc.post("/api/login", json={"password": password},
                   headers={"Origin": str(tc.base_url).rstrip("/")})


def test_no_password_everything_open(make):
    tc, _ = make(password=None)
    assert tc.get("/api/account").status_code == 200  # setup mode, not 401
    assert tc.get("/api/session").json() == {"authenticated": False,
                                             "password_required": False}


def test_password_required_then_login(make):
    tc, _ = make()
    assert tc.get("/api/health").status_code == 200
    assert tc.get("/api/session").json()["password_required"] is True
    r = tc.get("/api/account")
    assert r.status_code == 401 and r.json() == {"error": "login_required"}
    assert _login(tc).status_code == 200
    assert tc.get("/api/account").status_code == 200
    assert tc.get("/api/session").json()["authenticated"] is True


def test_bad_password_and_bad_body_never_echo(make):
    tc, _ = make()
    r = _login(tc, "wrong-guess-123")
    assert r.status_code == 401 and r.json() == {"error": "bad_password"}
    assert "wrong-guess-123" not in r.text and PASSWORD not in r.text
    origin = {"Origin": "http://127.0.0.1"}
    for body in ({"password": 12345}, {}, None):
        r = tc.post("/api/login", json=body, headers=origin)
        assert r.status_code == 400 and "12345" not in r.text
    assert PASSWORD not in repr(_settings())


@pytest.mark.parametrize("base_url,secure", [("http://127.0.0.1", False),
                                             ("https://127.0.0.1", True)])
def test_cookie_flags(base_url, secure, make):
    tc, _ = make(base_url=base_url)
    attrs = {a.strip().lower() for a in _login(tc).headers["set-cookie"].split(";")[1:]}
    assert {"httponly", "samesite=strict", "path=/"} <= attrs
    assert ("secure" in attrs) is secure


def test_session_expires(make):
    clock = Clock()
    tc, _ = make(clock=clock, session_ttl_hours=1)
    _login(tc)
    clock.now += 3599
    assert tc.get("/api/account").status_code == 200
    clock.now += 2
    assert tc.get("/api/account").status_code == 401


def test_logout(make):
    tc, _ = make()
    _login(tc)
    token = tc.cookies.get("studio_session")
    assert tc.post("/api/logout", headers={"Origin": "http://127.0.0.1"}).status_code == 200
    assert tc.get("/api/account").status_code == 401
    tc.cookies.set("studio_session", token)  # replaying the old cookie is no good either
    assert tc.get("/api/account").status_code == 401


@pytest.mark.parametrize("password", [None, PASSWORD])
def test_cross_site_post_refused(password, make):
    tc, _ = make(password=password)
    for headers in ({"Origin": "https://evil.example"},
                    {"Referer": "https://evil.example/page"},
                    {"Origin": "https://127.0.0.1"},  # other scheme = other origin
                    {"Origin": "null"}):
        r = tc.post("/api/login", json={"password": PASSWORD}, headers=headers)
        assert r.status_code == 403 and r.json() == {"error": "bad_origin"}


def test_same_origin_post_ok_and_missing_origin_rules(make):
    tc, _ = make(base_url="https://studio.local:8443")
    assert _login(tc).status_code == 200  # Origin https://studio.local:8443
    assert tc.post("/api/logout", headers={"Referer": "https://studio.local:8443/x"}
                   ).status_code == 200
    tc2, _ = make()
    assert tc2.post("/api/login", json={"password": PASSWORD}).status_code == 200  # curl
    # With the session cookie and neither Origin nor Referer: refused.
    assert tc2.post("/api/logout").status_code == 403


def test_lockout_and_unlock(make):
    clock = Clock()
    tc, _ = make(clock=clock)
    for _ in range(5):
        assert _login(tc, "nope").status_code == 401
    r = _login(tc)  # even the right password is refused while locked
    assert r.status_code == 429
    assert r.json() == {"error": "locked", "retry_after": 900}
    clock.now += 899
    assert _login(tc).status_code == 429
    clock.now += 1
    assert _login(tc).status_code == 200


def test_failures_outside_window_do_not_lock():
    clock = Clock()
    auth = Auth(_settings(), clock)
    for _ in range(4):
        assert auth.check_password("nope") is False
    clock.now += 15 * 60
    assert auth.check_password("nope") is False  # older 4 fell out of the window
    assert auth.check_password(PASSWORD) is True


def test_bind_guard():
    open_, locked = _settings(password=None), _settings()
    for host in ("127.0.0.1", "::1", "[::1]", "localhost", "127.0.0.2"):
        assert bind_error(host, open_) is None
    for host in ("0.0.0.0", "192.168.1.20", "::", "studio.lan"):
        assert "UI_PASSWORD" in bind_error(host, open_)
        assert bind_error(host, locked) is None
    assert bind_error("0.0.0.0", _settings(password="")) is not None
