"""Step 029: token care (debug_token status, fb_exchange_token refresh, .env rewrite)."""

import logging
import os
import stat
import time
from datetime import datetime, timezone

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from src import config, scheduler
from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.instagram_client import InstagramClient
from src.logging_setup import configure_logging
from src.studio import token as token_mod
from src.studio.token import RefreshRefused, refresh_token, token_status

from .conftest import API, LOCAL

TOKEN = "EAAsecretTOKENvalue123"
NEW = "EAAbrandNEWtoken456"
NOW = 1_800_000_000.0
DAY = 86400


@pytest.fixture(autouse=True)
def fresh_cache():
    token_mod._status.clear()
    yield
    token_mod._status.clear()


def _settings(**kw):
    base = dict(_env_file=None, instagram_access_token=TOKEN,
                instagram_business_account_id="1789", database_path=":memory:",
                cache_enabled=False, facebook_app_id="42", facebook_app_secret="shh")
    return InstagramMCPSettings(**{**base, **kw})


def _debug(**data):
    return respx.get(f"{API}/debug_token").mock(
        return_value=httpx.Response(200, json={"data": data}))


async def _status(settings, clock=lambda: NOW):
    async with InstagramClient(settings, http_client=httpx.AsyncClient()) as client:
        return await token_status(client, settings, clock=clock)


@pytest.mark.parametrize("data, valid, days", [
    ({"is_valid": True, "expires_at": int(NOW + 40 * DAY), "scopes": ["instagram_basic"]},
     True, 40),
    ({"is_valid": True, "expires_at": int(NOW + 5 * DAY + 60)}, True, 5),
    ({"is_valid": False, "expires_at": int(NOW - 2 * DAY)}, False, -2),
    ({"is_valid": True, "expires_at": 0}, True, None),  # system-user token: never expires
])
@respx.mock
async def test_status(data, valid, days):
    route = _debug(**data)
    out = await _status(_settings())
    assert out["configured"] and out["can_refresh"]
    assert out["valid"] is valid and out["days_left"] == days
    assert (out["expires_at"] is None) == (not data["expires_at"])
    req = route.calls.last.request
    assert req.url.params["input_token"] == TOKEN
    assert req.headers["Authorization"] == "Bearer 42|shh"  # app access token
    assert TOKEN not in str(out)


@respx.mock
async def test_status_invalid_token_and_self_inspection():
    route = respx.get(f"{API}/debug_token").mock(return_value=httpx.Response(
        400, json={"error": {"code": 190, "message": "Error validating access token"}}))
    out = await _status(_settings(facebook_app_id=None))
    assert out["valid"] is False and out["days_left"] is None and not out["can_refresh"]
    # no app credentials: the token inspects itself
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


@respx.mock
async def test_status_cached_for_an_hour():
    route = _debug(is_valid=True, expires_at=int(NOW + 30 * DAY))
    s = _settings()
    await _status(s)
    await _status(s, clock=lambda: NOW + 3599)
    assert route.call_count == 1
    await _status(s, clock=lambda: NOW + 3601)
    assert route.call_count == 2


async def test_status_setup_mode():
    out = await token_status(None, _settings(instagram_access_token=None))
    assert out == {"configured": False, "valid": None, "expires_at": None, "days_left": None,
                   "can_refresh": True, "scopes": []}


ENV = ("# Instagram\r\nINSTAGRAM_ACCESS_TOKEN=" + TOKEN + "\r\n"
       "INSTAGRAM_BUSINESS_ACCOUNT_ID=1789\r\n\r\n# app\r\nFACEBOOK_APP_ID=42\r\n")


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN", raising=False)
    path = tmp_path / ".env"
    path.write_bytes(ENV.encode())
    os.chmod(path, 0o600)
    return path


def _exchange():
    return respx.get(f"{API}/oauth/access_token").mock(return_value=httpx.Response(
        200, json={"access_token": NEW, "token_type": "bearer", "expires_in": 60 * DAY}))


@respx.mock
async def test_refresh_rewrites_only_the_token_line(env_file):
    mode = stat.S_IMODE(os.stat(env_file).st_mode)
    route = _exchange()
    s = _settings()
    async with InstagramClient(s, http_client=httpx.AsyncClient()) as client:
        out = await refresh_token(client, s, env_file, clock=lambda: NOW)
    assert out == {"expires_at": datetime.fromtimestamp(NOW + 60 * DAY, timezone.utc).isoformat()}
    assert env_file.read_bytes() == ENV.replace(TOKEN, NEW).encode()
    assert stat.S_IMODE(os.stat(env_file).st_mode) == mode
    assert list(env_file.parent.iterdir()) == [env_file]  # no temp file left
    params = route.calls.last.request.url.params
    assert params["grant_type"] == "fb_exchange_token" and params["client_id"] == "42"
    assert params["client_secret"] == "shh" and params["fb_exchange_token"] == TOKEN


@pytest.mark.parametrize("kw, env, why", [
    ({"facebook_app_secret": None}, None, "FACEBOOK_APP_SECRET"),
    ({"facebook_app_id": ""}, None, "FACEBOOK_APP_ID"),
    ({}, TOKEN, "process environment"),
])
@respx.mock
async def test_refresh_refuses(env_file, monkeypatch, kw, env, why):
    if env:
        monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", env)
    route = _exchange()
    s = _settings(**kw)
    async with InstagramClient(s, http_client=httpx.AsyncClient()) as client:
        with pytest.raises(RefreshRefused, match=why):
            await refresh_token(client, s, env_file)
    assert not route.called and env_file.read_bytes() == ENV.encode()


@pytest.fixture
def real_logging():
    """The CLI's configure_logging binds loggers to capsys's stream, closed after the test:
    rebind to the session's stderr. Request it before capsys so it tears down after it."""
    yield
    configure_logging()


def _cli(argv, settings, env_file, monkeypatch):
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(config, "ENV_FILE", str(env_file))
    with pytest.raises(SystemExit) as e:
        scheduler.main(argv)
    return e.value.code


@respx.mock
def test_cli_never_prints_or_logs_the_token(real_logging, env_file, monkeypatch, capsys):
    _debug(is_valid=True, expires_at=int(time.time() + 5 * DAY + 60), scopes=["instagram_basic"])
    _exchange()
    s = _settings(log_level="DEBUG")
    assert _cli(["token", "status"], s, env_file, monkeypatch) == 0
    assert _cli(["token", "refresh"], s, env_file, monkeypatch) == 0
    out = capsys.readouterr()
    assert '"days_left": 5' in out.out and "refreshed, expires on " in out.out
    for text in (out.out, out.err):  # logs go to stderr (LOG_LEVEL=DEBUG)
        assert TOKEN not in text and NEW not in text and "shh" not in text
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert NEW in env_file.read_text()


def test_cli_setup_mode_and_refusal(real_logging, env_file, monkeypatch, capsys):
    assert _cli(["token", "status"], _settings(instagram_access_token=None),
                env_file, monkeypatch) == 0
    assert "setup mode" in capsys.readouterr().err
    with respx.mock:
        assert _cli(["token", "refresh"], _settings(facebook_app_secret=None),
                    env_file, monkeypatch) == 1
    assert "refused" in capsys.readouterr().err


@respx.mock
def test_api_route(monkeypatch):
    _debug(is_valid=True, expires_at=int(time.time() + 8 * DAY + 60))
    with TestClient(create_app(_settings()), base_url=LOCAL) as tc:
        r = tc.get("/api/token")
    assert r.status_code == 200 and TOKEN not in r.text
    body = r.json()
    assert body["valid"] is True and body["days_left"] == 8 and body["can_refresh"] is True
    with TestClient(create_app(_settings(instagram_access_token=None)), base_url=LOCAL) as tc:
        assert tc.get("/api/token").json()["configured"] is False
