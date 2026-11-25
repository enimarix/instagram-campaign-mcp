"""Step 025: worker core (late-slot policy, gap rule, pause, heartbeat, status, wake task);
025a: stay awake for due slots."""

import asyncio
import ctypes
import sys
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src import scheduler, worker
from src.api.app import create_app
from src.campaign import run_due
from src.config import InstagramMCPSettings
from src.store import CampaignStore, parse_dt, to_iso, utcnow
from src.studio import power

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


async def test_gap_counts_from_the_last_posts_slot_not_its_publish_finish(store, cfg):
    gap = timedelta(minutes=cfg.min_slot_gap_minutes)
    first = _due(store, gap.total_seconds() / 60 + 0.5)  # the planner's slot before
    with store._tx() as c:  # it went out, its publish done 43 s after its slot
        c.execute("UPDATE scheduled_posts SET status='published', updated_at=? WHERE id=?",
                  (to_iso(T - gap - timedelta(seconds=30) + timedelta(seconds=43)), first))
    second = _due(store, 0.5)  # exactly one gap after it, run 30 s later
    fake = FakeClient()
    res = await worker.cycle(fake, store, cfg, now=clock)
    assert res["replanned"] == [] and store.get_scheduled(second)["status"] == "published"


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
    assert r"-Execute 'C:\it''s\python.exe'" in script
    assert "'-m src.scheduler run-due --wait-until-next'" in script


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


# --- 025a: stay awake for due slots ---------------------------------------------------

ON = power.ES_CONTINUOUS | power.ES_SYSTEM_REQUIRED
OFF = power.ES_CONTINUOUS


@pytest.fixture
def ste(monkeypatch):
    """A fake SetThreadExecutionState on a fake Windows: the list of flags it was called with."""
    calls = []

    class Kernel32:
        def SetThreadExecutionState(self, flags):
            calls.append(flags)

    monkeypatch.setattr(ctypes, "windll", type("W", (), {"kernel32": Kernel32()})(),
                        raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    yield calls
    assert power._holds == 0  # every hold was released


async def test_slot_hold_taken_before_slot_and_released_after_run(store, cfg, ste):
    post_id = _due(store, 0)  # due at T
    held = worker.hold_for_slot(store, cfg, T - timedelta(minutes=11), False)
    assert held is False and ste == []
    held = worker.hold_for_slot(store, cfg, T - timedelta(minutes=9), held)
    assert held is True and ste == [ON]
    held = worker.hold_for_slot(store, cfg, T - timedelta(minutes=1), held)
    assert held is True and ste == [ON]  # taken once
    fake = FakeClient()
    await worker.cycle(fake, store, cfg, now=clock)
    assert store.get_scheduled(post_id)["status"] == "published"
    held = worker.hold_for_slot(store, cfg, T, held)
    assert held is False and ste == [ON, OFF]


def test_slot_hold_overdue_paused_and_late(store, cfg, ste):
    _due(store, 0)
    assert worker.slot_near(store, cfg, T + timedelta(minutes=cfg.max_late_minutes))
    assert not worker.slot_near(store, cfg, T + timedelta(minutes=cfg.max_late_minutes + 1))
    store.set_state("paused", True)
    assert not worker.slot_near(store, cfg, T)  # paused: overdue posts may wait for days


def test_render_and_slot_holds_coexist(ste):
    power.hold()  # slot
    with power.keep_awake():  # render
        assert ste == [ON]
    assert ste == [ON]  # the render ending doesn't drop the slot's hold
    with power.keep_awake():
        power.release()  # the slot handled while a render runs
        assert ste == [ON]
    assert ste == [ON, OFF]
    power.release()  # unbalanced: ignored
    assert ste == [ON, OFF] and power._holds == 0


class Clock:
    def __init__(self):
        self.t, self.slept = T, []

    def __call__(self):
        return self.t

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += timedelta(seconds=seconds)


async def test_wait_until_next_waits_awake_then_runs_once(store, cfg, ste):
    post_id = store.schedule("image", {"image_url": "https://x/1.jpg"},
                             T + timedelta(minutes=4))["id"]
    c, fake = Clock(), FakeClient()

    async def sleep(seconds):
        assert ste == [ON]  # awake while waiting
        await c.sleep(seconds)

    res = await worker.run_due_after_wait(fake, store, cfg, now=c, sleep=sleep)
    assert c.slept == [241] and res["waited_s"] == 240 and fake.calls == 1
    assert store.get_scheduled(post_id)["status"] == "published"
    assert ste == [ON, OFF]


async def test_wait_until_next_gives_up_past_the_bound(store, cfg, ste):
    post_id = store.schedule("image", {"image_url": "https://x/1.jpg"},
                             T + timedelta(minutes=16))["id"]
    c, fake = Clock(), FakeClient()
    res = await worker.run_due_after_wait(fake, store, cfg, now=c, sleep=c.sleep)
    assert c.slept == [] and res["waited_s"] == 0 and fake.calls == 0
    assert store.get_scheduled(post_id)["status"] == "pending" and ste == [ON, OFF]


def test_two_runners_on_one_db_publish_once(tmp_path, cfg):
    db = str(tmp_path / "q.db")
    stores = [CampaignStore(db), CampaignStore(db)]
    post_id = stores[0].schedule("image", {"image_url": "https://x/1.jpg"},
                                 utcnow() - timedelta(minutes=1))["id"]
    calls, lock, start = [], threading.Lock(), threading.Barrier(2)

    class SlowClient:
        async def publish_image(self, **payload):
            with lock:
                calls.append(payload)
            await asyncio.sleep(0.2)  # the other runner tries while this one publishes
            return {"media_id": "M1"}

    results = []

    def runner(s):  # `up`'s worker and the wake task: two processes, one DB
        start.wait()
        results.append(asyncio.run(run_due(SlowClient(), s, settings=cfg)))

    threads = [threading.Thread(target=runner, args=(s,)) for s in stores]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        assert len(calls) == 1 and sum(len(r["published"]) for r in results) == 1
        assert stores[1].get_scheduled(post_id)["status"] == "published"
    finally:
        for s in stores:
            s.close()


def test_cli_run_due_wait_until_next(settings, tmp_path, monkeypatch, capsys):
    settings.database_path = str(tmp_path / "q.db")
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduler, "configure_logging", lambda *a: None)

    async def fake(client, store, settings):
        return {"waited_s": 7}

    monkeypatch.setattr(worker, "run_due_after_wait", fake)
    with pytest.raises(SystemExit) as e:
        scheduler.main(["run-due", "--wait-until-next"])
    assert e.value.code == 0 and '"waited_s": 7' in capsys.readouterr().out
