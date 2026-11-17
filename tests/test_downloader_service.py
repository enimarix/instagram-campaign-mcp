"""Step 063a: the Reel downloader service (loopback start, restart, health, setup, update).
No npm, git, node or network: run_cmd / Popen are faked, the health check uses respx."""

import asyncio
import json
import subprocess

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from src import worker
from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.studio import downloader_service as svc

from .conftest import LOCAL

REEL = "https://www.instagram.com/reel/ABC123/"
API = "http://127.0.0.1:3711/api/video"


def cfg(**kw):
    return InstagramMCPSettings(_env_file=None, database_path=":memory:", **kw)


@pytest.fixture
def vendor(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "VENDOR_DIR", tmp_path)
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / ".git").write_text("gitdir: elsewhere")
    return tmp_path


def build_it(vendor):
    (vendor / ".next").mkdir()
    (vendor / ".next" / "BUILD_ID").write_text("x")


class FakeProc:
    def __init__(self, exit_code=None):
        self.returncode = exit_code
        self.stopped = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.stopped = True
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode


def test_start_binds_loopback_without_upstash_or_our_secrets(vendor, tmp_path, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "secret")
    monkeypatch.setenv("UI_PASSWORD", "secret")
    seen = {}

    def popen(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return FakeProc()

    svc.spawn(cfg(downloader_port=4000), tmp_path / "logs" / "d.log", popen=popen)
    cmd, env = seen["cmd"], seen["env"]
    assert cmd[2:] == ["start", "-H", "127.0.0.1", "-p", "4000"]
    assert cmd[1].endswith("next") and seen["cwd"] == vendor
    assert env["USE_UPSTASH"] == "false" and env["NODE_ENV"] == "production"
    assert "secret" not in env.values() and not any(k.startswith("INSTAGRAM") for k in env)


async def poll_until(cond, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not cond():
        assert asyncio.get_running_loop().time() < deadline, "timed out"
        await asyncio.sleep(0.005)


async def test_restarts_after_death_and_stops_on_exit(vendor, store):
    build_it(vendor)
    procs = []

    def spawn():
        procs.append(FakeProc(exit_code=1 if not procs else None))  # the first one dies
        return procs[-1]

    task = asyncio.create_task(worker.downloader_loop(store, cfg(), spawn=spawn, tick=0.001,
                                                      backoff=(0.01, 0.02)))
    await poll_until(lambda: len(procs) == 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert procs[1].stopped and not procs[0].stopped


async def test_disabled_until_set_up(vendor, store):
    spawned = []
    task = asyncio.create_task(worker.downloader_loop(store, cfg(), spawn=spawned.append,
                                                      tick=0.001))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert spawned == [] and svc.status(store, cfg())["set_up"] is False


async def test_health_not_configured():
    assert (await svc.health_check(cfg()))["status"] == "not_configured"


@respx.mock
@pytest.mark.parametrize("response, expected", [
    (httpx.Response(200, json={"success": True, "data": {"medias": [
        {"type": "video", "url": "https://scontent.cdninstagram.com/v.mp4"}]}}), "up"),
    (httpx.Response(200, json={"success": True, "data": {"medias": []}}), "broken"),
    (httpx.Response(500, json={"status": "error", "message": "Server Error"}), "broken"),
    (httpx.Response(200, text="<html>"), "broken"),
    (httpx.ConnectError("refused"), "down"),
])
async def test_health_up_down_broken(store, response, expected):
    respx.get(API, params={"postUrl": REEL, "enhanced": "true"}).mock(side_effect=[response])
    result = await svc.check_and_store(store, cfg(downloader_health_url=REEL))
    assert result["status"] == expected and result["checked_at"]
    assert store.get_state(svc.STATE_KEY) == result


def fake_run(calls, outputs):
    def run(cmd, *, check=True, timeout_s=None):
        calls.append(" ".join(cmd))
        return subprocess.CompletedProcess(cmd, 1 if "audit" in cmd else 0,
                                           stdout=outputs.get(" ".join(cmd), ""), stderr="")
    return run


def test_setup_runs_ci_build_audit_in_order(vendor, monkeypatch):
    calls = []
    audit = json.dumps({"metadata": {"vulnerabilities": {"high": 2, "total": 2}}})
    monkeypatch.setattr(svc, "run_cmd", fake_run(calls, {
        "npm audit --omit=dev --json": audit, "git rev-parse HEAD": "c36c205\n"}))
    result = svc.setup()
    assert calls == ["npm ci", "npm run build", "npm audit --omit=dev --json",
                     "git rev-parse HEAD"]
    assert result["audit"] == {"high": 2, "total": 2} and result["commit"] == "c36c205"


def test_setup_without_submodule_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "VENDOR_DIR", tmp_path)
    with pytest.raises(svc.DownloaderError, match="submodule"):
        svc.setup()


@pytest.mark.parametrize("health, kept", [("broken", False), ("up", True)])
async def test_update_keeps_or_rolls_back(vendor, monkeypatch, tmp_path, health, kept):
    calls, procs = [], []
    monkeypatch.setattr(svc, "run_cmd", fake_run(calls, {
        "git rev-parse HEAD": "old\n", "git rev-parse FETCH_HEAD": "new\n"}))
    monkeypatch.setattr(svc, "port_open", lambda port: False)
    monkeypatch.setattr(svc, "spawn", lambda s, log: procs.append(FakeProc()) or procs[-1])

    async def check(settings):
        return {"status": health, "checked_at": "now"}

    monkeypatch.setattr(svc, "health_check", check)
    result = await svc.update(cfg(downloader_health_url=REEL), tmp_path / "d.log")
    assert result["updated"] is kept and procs[0].stopped
    assert calls.index("git checkout --quiet new") < calls.index("npm run build")
    if kept:
        assert result["commit"] == "new" and "git checkout --quiet old" not in calls
    else:
        assert result == {"updated": False, "commit": "old", "rolled_back_from": "new",
                          "health": {"status": "broken", "checked_at": "now"}}
        assert calls[-4:] == ["git checkout --quiet old", "npm ci", "npm run build",
                              "npm audit --omit=dev --json"]


async def test_update_refuses_without_health_url_or_with_the_port_taken(vendor, monkeypatch):
    with pytest.raises(svc.DownloaderError, match="DOWNLOADER_HEALTH_URL"):
        await svc.update(cfg())
    monkeypatch.setattr(svc, "port_open", lambda port: True)
    with pytest.raises(svc.DownloaderError, match="in use"):
        await svc.update(cfg(downloader_health_url=REEL))


def test_status_route(store):
    store.set_state(svc.STATE_KEY, {"status": "up", "checked_at": "2026-11-17T00:00:00Z"})
    with TestClient(create_app(cfg(), store=store), base_url=LOCAL) as c:
        body = c.get("/api/downloader/status").json()
    assert body == {"set_up": False, "host": "127.0.0.1", "port": 3711,
                    "health_configured": False,
                    "health": {"status": "up", "checked_at": "2026-11-17T00:00:00Z"}}
