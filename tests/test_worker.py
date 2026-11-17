"""Step 025: worker core (late-slot policy, gap rule, pause, heartbeat, status, wake task)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src import worker
from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.store import parse_dt, to_iso, utcnow

from .conftest import LOCAL

T = datetime(2026, 11, 17, 17, 30, tzinfo=timezone.utc)  # 18:30 Paris, inside 17:00-21:00
ORIGIN = {"Origin": LOCAL}


def clock():
    return T


@pytest.fixture
def cfg():
    return InstagramMCPSettings(_env_file=None, database_path=":memory:",
                                instagram_access_token=None)


class FakeClient:
    def __init__(self):
        self.calls = 0

    async def publish_image(self, **payload):
        self.calls += 1
        return {"media_id": f"M{self.calls}"}


def _due(store, minutes_late):
    return store.schedule("image", {"image_url": "https://x/1.jpg"},
                          T - timedelta(minutes=minutes_late))["id"]


async def test_late_post_is_replanned_not_published(store, cfg):
    post_id = _due(store, 45)
    fake = FakeClient()
    res = await worker.cycle(fake, store, cfg, now=clock)
    assert fake.calls == 0 and res["replanned"][0]["id"] == post_id
    row = store.get_scheduled(post_id)
    assert row["status"] == "pending" and parse_dt(row["publish_at"]) >= T
    assert "45 min late" in row["error"] and row["attempts"] == 0


async def test_slightly_late_post_still_goes_out(store, cfg):
    post_id = _due(store, 20)
    fake = FakeClient()
    await worker.cycle(fake, store, cfg, now=clock)
    assert fake.calls == 1 and store.get_scheduled(post_id)["status"] == "published"


async def test_burst_publishes_one_and_moves_the_other_a_gap_later(store, cfg):
    first, second = _due(store, 2), _due(store, 1)
    fake = FakeClient()
    res = await worker.cycle(fake, store, cfg, now=clock)
    assert fake.calls == 1 and len(res["published"]) == 1
    assert store.get_scheduled(first)["status"] == "published"
    moved = store.get_scheduled(second)
    assert moved["status"] == "pending"
    assert parse_dt(moved["publish_at"]) >= T + timedelta(minutes=cfg.min_slot_gap_minutes)


@pytest.mark.parametrize("setting, flag, publishes", [
    (True, None, False),   # the setting is the default
    (False, True, False),  # the website's switch wins...
    (True, False, True),   # ...both ways
])
async def test_pause_holds_queue_but_heartbeat_runs(store, setting, flag, publishes):
    cfg = InstagramMCPSettings(_env_file=None, database_path=":memory:",
                               publishing_paused=setting)
    if flag is not None:
        store.set_state("paused", flag)
    post_id = _due(store, 1)
    fake = FakeClient()
    res = await worker.cycle(fake, store, cfg, now=clock)
    assert res["paused"] is not publishes and fake.calls == int(publishes)
    assert store.get_scheduled(post_id)["status"] == ("published" if publishes else "pending")
    assert store.get_state("heartbeat_at") == to_iso(T)
    assert store.get_state("last_result")["paused"] is not publishes


async def test_cycle_survives_errors(store, cfg, monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("db gone")

    monkeypatch.setattr(worker, "run_due", boom)
    res = await worker.cycle(FakeClient(), store, cfg, now=clock)
    assert "db gone" in res["error"] and store.get_state("heartbeat_at") == to_iso(T)


def test_status_route(store, cfg):
    later = utcnow() + timedelta(hours=3)
    store.schedule("image", {"image_url": "https://x/2.jpg"}, utcnow() + timedelta(hours=5))
    store.schedule("image", {"image_url": "https://x/1.jpg"}, later)
    with TestClient(create_app(cfg, store=store), base_url=LOCAL) as tc:
        r = tc.get("/api/worker/status").json()
        assert r["heartbeat_at"] is None and r["alive"] is False and r["paused"] is False
        assert r["next_slot"] == to_iso(later)
        store.set_state("heartbeat_at", to_iso(utcnow() - timedelta(minutes=1)))
        assert tc.get("/api/worker/status").json()["alive"] is True
        store.set_state("heartbeat_at", to_iso(utcnow() - timedelta(minutes=4)))
        assert tc.get("/api/worker/status").json()["alive"] is False


def test_pause_resume_need_a_session(store):
    cfg = InstagramMCPSettings(_env_file=None, database_path=":memory:",
                               instagram_access_token=None, ui_password="pw")
    with TestClient(create_app(cfg, store=store), base_url=LOCAL) as tc:
        r = tc.post("/api/worker/pause", headers=ORIGIN)
        assert r.status_code == 401 and store.get_state("paused") is None
        assert tc.post("/api/login", json={"password": "pw"}, headers=ORIGIN).status_code == 200
        assert tc.post("/api/worker/pause", headers=ORIGIN).json()["paused"] is True
        assert store.get_state("paused") is True
        assert tc.get("/api/worker/status").json()["paused"] is True
        assert tc.post("/api/worker/resume", headers=ORIGIN).json()["paused"] is False


def test_wake_command_time_and_flag():
    cmd = worker.wake_task_command(T, exe=r"C:\it's\python.exe")
    script = cmd[-1]
    local = (T - timedelta(minutes=5)).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
    assert cmd[0] == "powershell.exe" and f"-At '{local}'" in script
    assert "-WakeToRun" in script and "-TaskName 'IGCampaignWake'" in script
    assert r"-Execute 'C:\it''s\python.exe'" in script and "run-due" in script


def test_wake_runs_only_on_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(worker.sys, "platform", "linux")
    assert worker.register_wake(T, run=lambda *a, **kw: calls.append(a)) is False
    assert calls == []
    monkeypatch.setattr(worker.sys, "platform", "win32")
    assert worker.register_wake(T, run=lambda *a, **kw: calls.append(a)) is True
    assert calls[0][0][0] == "powershell.exe"

    def fail(*a, **kw):
        raise OSError("no powershell")

    assert worker.register_wake(T, run=fail) is False  # logged, never raised
