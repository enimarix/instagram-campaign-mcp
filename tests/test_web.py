"""Step 010: website served by the API, Host guard, `ig-campaign up` wiring."""

import asyncio

import pytest
import uvicorn
from fastapi.testclient import TestClient

from src import scheduler, worker
from src.agent import schedule
from src.api.app import create_app
from src.config import InstagramMCPSettings

from .conftest import LOCAL


@pytest.fixture(autouse=True)
def _no_agent_catch_up(monkeypatch):
    """The real worker's catch-up starts the due playbooks detached: on the real clock, past
    03:00 with an empty test DB, that rebuilt the live agent workspace (step 160)."""
    async def idle(store, settings):
        await asyncio.sleep(3600)

    monkeypatch.setattr(schedule, "catch_up_loop", idle)


def _settings(tmp_path, password=None, **kw):
    return InstagramMCPSettings(_env_file=None, database_path=":memory:",
                                instagram_access_token=None, ui_password=password,
                                web_dist=str(tmp_path / "dist"), **kw)


@pytest.fixture
def site(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root>INDEX</div>")
    (dist / "assets" / "app.js").write_text("console.log('app')")
    (tmp_path / "secret.txt").write_text("TOP SECRET")  # next to dist, must never leak
    with TestClient(create_app(_settings(tmp_path)), base_url=LOCAL) as tc:
        yield tc


def test_static_files_and_spa_fallback(site):
    r = site.get("/assets/app.js")
    assert r.status_code == 200 and r.text == "console.log('app')"
    for path in ("/", "/inbox", "/calendar/2026-11", "/assets/missing.js"):
        r = site.get(path)
        assert r.status_code == 200 and "INDEX" in r.text, path
    assert site.get("/api/health").json()["status"] == "ok"  # routes still win


def test_unknown_api_path_is_json_404(site):
    for path in ("/api/nope", "/api", "/api/inbox/1"):
        r = site.get(path)
        assert r.status_code == 404 and r.json() == {"error": "not_found"}, path


@pytest.mark.parametrize("path", ["/..%2fsecret.txt", "/assets/..%2f..%2fsecret.txt",
                                  "/%2e%2e/secret.txt", "/..%5csecret.txt"])
def test_path_traversal_refused(site, path):
    r = site.get(path)
    assert "TOP SECRET" not in r.text


def test_missing_dist_hint_and_api_still_works(tmp_path):
    with TestClient(create_app(_settings(tmp_path)), base_url=LOCAL) as tc:
        r = tc.get("/")
        assert r.status_code == 200 and "npm --prefix web run build" in r.text
        assert tc.get("/api/health").status_code == 200


def test_host_guard_open_mode(site):
    for host in ("evil.example", "evil.example:8765", "192.168.1.20", "testserver"):
        for path in ("/", "/assets/app.js", "/api/health"):
            r = site.get(path, headers={"Host": host})
            assert r.status_code == 403 and r.json() == {"error": "bad_host"}, (host, path)
    for host in ("127.0.0.1:8765", "localhost:8765", "LOCALHOST", "[::1]:8765"):
        assert site.get("/api/health", headers={"Host": host}).status_code == 200, host


def test_host_unrestricted_with_password(tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("INDEX")
    app = create_app(_settings(tmp_path, password="pw"))
    with TestClient(app, base_url="http://studio.tailnet.ts.net") as tc:
        assert "INDEX" in tc.get("/inbox").text  # static stays public: the login page loads
        assert tc.get("/api/health").status_code == 200
        assert tc.get("/api/account").json() == {"error": "login_required"}


async def test_up_runs_worker_and_stops_it_with_the_server(settings, monkeypatch):
    calls = []
    ran = asyncio.Event()

    async def fake_run_due(client, store, **kw):
        calls.append("run_due")
        ran.set()
        return {"published": [], "retrying": [], "failed": [], "recovered_stuck": []}

    async def fake_collect(client, store, limit):
        calls.append(("collect", limit))

    async def fake_data_jobs(client, store, settings):
        calls.append("data_jobs")
        return {}

    class FakeServer:
        def __init__(self, config):
            self.config = config

        async def serve(self):  # stands in for uvicorn: returns as on Ctrl+C
            await asyncio.wait_for(ran.wait(), 5)

    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduler, "configure_logging", lambda *a: None)
    monkeypatch.setattr(worker, "run_due", fake_run_due)
    monkeypatch.setattr(worker, "collect_insights", fake_collect)
    monkeypatch.setattr(worker, "data_jobs", fake_data_jobs)
    tasks_before = asyncio.all_tasks()
    await asyncio.wait_for(scheduler._up("127.0.0.1", 0), 5)
    assert calls[:3] == ["run_due", "data_jobs", ("collect", 0)]
    assert asyncio.all_tasks() == tasks_before  # the worker task was cancelled and awaited


async def test_up_worker_idles_in_setup_mode(tmp_path, monkeypatch, capsys):
    rendered = []

    async def render_loop(store, settings):  # renders run without Instagram (034)
        rendered.append(settings)

    monkeypatch.setattr(scheduler.worker, "render_loop", render_loop)
    await asyncio.wait_for(scheduler._worker(_settings(tmp_path)), 1)
    assert "publishing is idle" in capsys.readouterr().err and len(rendered) == 1


async def test_up_worker_failure_is_reported(settings, monkeypatch, capsys):
    def broken_store(path):
        raise RuntimeError("database is newer than this code")

    monkeypatch.setattr(scheduler, "CampaignStore", broken_store)
    await asyncio.wait_for(scheduler._worker(settings), 1)
    assert "worker stopped" in capsys.readouterr().err


def test_csp_allows_instagram_frames_and_cdn_media_only(site):
    for path, host in (("/trending", None), ("/api/health", None), ("/", "evil.example")):
        r = site.get(path, headers={"Host": host} if host else {})
        csp = dict(d.split(" ", 1) for d in r.headers["Content-Security-Policy"].split("; "))
        assert csp["frame-src"] == "https://www.instagram.com", path
        assert "https://*.cdninstagram.com https://*.fbcdn.net" in csp["media-src"]
        assert "https://*.elevenlabs.io" in csp["media-src"]  # voice previews (204)
        assert "https://*.cdninstagram.com https://*.fbcdn.net" in csp["img-src"]
        assert csp["frame-ancestors"] == "'none'"
