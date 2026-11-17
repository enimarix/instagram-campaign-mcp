"""Step 007: REST API skeleton and setup mode (no Instagram token yet)."""

import argparse

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

import src.instagram_mcp_server as srv
from src import scheduler
from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.store import CampaignStore

from .conftest import API, LOCAL


@pytest.fixture
def setup_settings(monkeypatch):
    monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", raising=False)
    return InstagramMCPSettings(_env_file=None, database_path=":memory:")


def test_settings_load_without_token(setup_settings, settings):
    assert setup_settings.instagram_access_token is None
    assert not setup_settings.instagram_configured
    assert settings.instagram_configured


def test_health_both_modes(setup_settings, settings):
    for s, configured in ((setup_settings, False), (settings, True)):
        with TestClient(create_app(s), base_url=LOCAL) as tc:
            r = tc.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["instagram_configured"] is configured


def test_account_setup_mode_is_503(setup_settings):
    with TestClient(create_app(setup_settings), base_url=LOCAL) as tc:
        r = tc.get("/api/account")
    assert r.status_code == 503
    assert r.json() == {"error": "instagram_not_configured"}


@respx.mock
def test_account_configured(settings):
    respx.get(f"{API}/me").mock(return_value=httpx.Response(200, json={"id": "1"}))
    respx.get(f"{API}/1789").mock(
        return_value=httpx.Response(200, json={"id": "1789", "username": "macrobody"}))
    respx.get(f"{API}/1789/content_publishing_limit").mock(
        return_value=httpx.Response(200, json={"data": [{"quota_usage": 2}]}))
    with TestClient(create_app(settings), base_url=LOCAL) as tc:
        r = tc.get("/api/account")
    assert r.status_code == 200
    assert r.json() == {"token_valid": True,
                        "profile": {"id": "1789", "username": "macrobody"},
                        "publishing_limit": {"quota_usage": 2}}


@respx.mock
def test_account_graph_error_is_clean_json(settings):
    respx.get(f"{API}/me").mock(return_value=httpx.Response(200, json={"id": "1"}))
    respx.get(f"{API}/1789").mock(return_value=httpx.Response(
        400, json={"error": {"message": "Unsupported get request", "code": 100}}))
    with TestClient(create_app(settings), base_url=LOCAL) as tc:
        r = tc.get("/api/account")
    assert r.status_code == 502
    assert r.json()["error"] == "instagram_api_error"
    assert r.json()["code"] == 100
    assert "test_token" not in r.text


async def test_mcp_setup_mode(setup_settings, monkeypatch):
    monkeypatch.setattr(srv, "get_settings", lambda: setup_settings)
    monkeypatch.setattr(srv, "_client", None)
    monkeypatch.setattr(srv, "_store", CampaignStore(":memory:"))
    with pytest.raises(ToolError, match="instagram_not_configured"):
        await srv.get_profile_info()
    assert (await srv.rank_posts())["posts"] == []
    srv._store.close()


@respx.mock  # any request would fail: no route is mocked
@pytest.mark.parametrize("command", ["run-due", "collect"])  # daemon: test_studio_render
async def test_cli_setup_mode_skips(setup_settings, monkeypatch, capsys, command):
    monkeypatch.setattr(scheduler, "get_settings", lambda: setup_settings)
    # configure_logging would bind loggers to capsys's stream, closed after this test.
    monkeypatch.setattr(scheduler, "configure_logging", lambda *a: None)
    args = argparse.Namespace(command=command, limit=25, stories_only=False,
                              interval=60, stories_every=60)
    assert await scheduler._run(args) == 0
    assert "Instagram not configured" in capsys.readouterr().err
    assert not respx.calls
