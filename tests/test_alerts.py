"""Step 098: alerts computed from existing state, dismissal, routes."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from src.agent.packet import SKIPPED
from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.store import to_iso, utcnow
from src.studio import alerts, downloader_service

from .conftest import LOCAL

ORIGIN = {"Origin": LOCAL}


@pytest.fixture
def cfg():
    return InstagramMCPSettings(_env_file=None, database_path=":memory:",
                                instagram_access_token=None)


def _sql(store, q, *args):
    with store._tx() as c:
        return c.execute(q, args).lastrowid


def _asset(store, status, batch="2026-11-17", qc=None, updated=None):
    idea = store.add_idea("motion")
    a = store.add_asset(idea["id"], batch_date=batch, qc=qc)
    _sql(store, "UPDATE assets SET status=?, updated_at=? WHERE id=?", status,
         to_iso(updated or utcnow()), a["id"])
    return a["id"]


def _post(store, status, error=None, updated=None, asset_id=None):
    pid = store.schedule("image", {"image_url": "https://x/1.jpg"},
                         utcnow() + timedelta(hours=2))["id"]
    _sql(store, "UPDATE scheduled_posts SET status=?, error=?, updated_at=?, asset_id=?"
         " WHERE id=?", status, error, to_iso(updated or utcnow()), asset_id, pid)
    return pid


async def _ids(store, cfg, now=None, kind=None):
    found = await alerts.alerts(store, cfg, now or utcnow())
    return [a["id"] for a in found if kind is None or a["kind"] == kind]


async def test_nothing_wrong_means_no_alerts(store, cfg):
    assert await _ids(store, cfg) == []


async def test_failed_publish(store, cfg):
    aid = _asset(store, "approved")
    pid = _post(store, "failed", "Rate limited", asset_id=aid)
    found = await alerts.alerts(store, cfg, utcnow())
    assert found[0]["id"] == f"publish_failed:{pid}" and found[0]["severity"] == "error"
    assert found[0]["link"] == f"/assets/{aid}" and found[0]["detail"] == "Rate limited"
    _post(store, "failed", "old", updated=utcnow() - timedelta(days=8))  # too old
    _post(store, "published")
    assert await _ids(store, cfg, kind="publish_failed") == [f"publish_failed:{pid}"]


async def test_publish_check_stuck(store, cfg):
    stuck = _asset(store, "publish_check", updated=utcnow() - timedelta(hours=1))
    _asset(store, "publish_check")  # reconcile has not had its turn yet
    assert await _ids(store, cfg) == [f"publish_check:{stuck}"]


async def test_replanned(store, cfg):
    _post(store, "pending", "Re-planned: 45 min late")
    _post(store, "pending", "Re-planned: 50 min late", updated=utcnow() - timedelta(days=2))
    _post(store, "pending")
    found = await alerts.alerts(store, cfg, utcnow())
    assert [a["id"] for a in found] == ["replanned"]
    assert found[0]["title"] == "1 post moved to a later slot"
    assert found[0]["detail"] == "Latest: 45 min late."


@pytest.mark.parametrize("status, ids", [
    ({"configured": True, "valid": True, "days_left": 30, "expires_at": "2027-01-01T00:00:00+00:00"}, []),
    ({"configured": True, "valid": True, "days_left": None, "expires_at": None}, []),
    ({"configured": True, "valid": None}, []),  # setup mode: unknown
    ({"configured": True, "valid": True, "days_left": 9, "expires_at": "2026-12-01T00:00:00+00:00"},
     ["token:expiring"]),
    ({"configured": True, "valid": False, "days_left": None, "expires_at": None}, ["token:invalid"]),
])
async def test_token(store, cfg, monkeypatch, status, ids):
    async def fake(client, settings):
        return {"can_refresh": False, **status}
    monkeypatch.setattr(alerts.token, "token_status", fake)
    assert await _ids(store, cfg) == ids


async def test_agent_runs(store, cfg):
    def run(playbook, status, summary, usage=None):
        r = store.start_agent_run(playbook)
        store.finish_agent_run(r["id"], status, summary=summary, usage=usage)
    run("daily-produce", "failed", "boom")
    run("daily-produce", "succeeded", "done")  # the latest run is fine
    run("daily-revise", "failed", "error_max_turns", usage={"subtype": "error_max_turns"})
    run("daily-learn", "succeeded", "ok\nwork packet: 1 of 2 revisions not handled: #4")
    run("daily-skip", "succeeded", SKIPPED)
    store.start_agent_run("daily-skip")  # running: not judged
    found = {a["id"]: a for a in await alerts.alerts(store, cfg, utcnow())}
    assert set(found) == {"agent_run:daily-revise", "agent_run:daily-learn"}
    assert found["agent_run:daily-revise"]["title"].endswith("stopped at its limit")
    assert found["agent_run:daily-learn"]["severity"] == "warn"
    assert found["agent_run:daily-learn"]["detail"] == "1 of 2 revisions not handled: #4"


async def test_qc_spike_in_the_last_batch(store, cfg):
    bad = {"passed": False, "checks": []}
    for _ in range(3):
        _asset(store, "failed", batch="2026-11-16", qc=bad)  # older batch: ignored
    for _ in range(7):
        _asset(store, "ready", qc={"passed": True})
    _asset(store, "failed", qc=bad)
    _asset(store, "failed", qc=bad)
    assert await _ids(store, cfg) == []  # 2 of 9
    _asset(store, "failed", qc=bad)
    assert await _ids(store, cfg) == ["qc_spike:2026-11-17"]  # 3 of 10


async def test_stale_worker_heartbeat(store, cfg):
    assert await _ids(store, cfg) == []  # never started
    store.set_state("heartbeat_at", to_iso(utcnow() - timedelta(minutes=1)))
    assert await _ids(store, cfg) == []
    store.set_state("heartbeat_at", to_iso(utcnow() - timedelta(minutes=10)))
    assert await _ids(store, cfg) == ["worker"]


@pytest.mark.parametrize("status, ids", [
    ("up", []), ("not_configured", []), ("down", ["downloader"]), ("broken", ["downloader"]),
])
async def test_downloader(store, cfg, status, ids):
    store.set_state(downloader_service.STATE_KEY,
                    {"status": status, "checked_at": to_iso(utcnow())})
    assert await _ids(store, cfg) == ids


async def test_dm_picks_skipped_today(store, cfg):
    def pick(n, status, reason, updated):
        _sql(store, "INSERT INTO dm_picks (message_id, sender_username, reel_url, received_at,"
             " status, skip_reason, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
             f"m{n}", "friend", f"https://www.instagram.com/reel/{n}/", to_iso(updated),
             status, reason, to_iso(updated), to_iso(updated))
    pick(1, "skipped", "not a video", utcnow() - timedelta(days=2))
    pick(2, "new", None, utcnow())
    assert await _ids(store, cfg) == []
    pick(3, "skipped", "too long", utcnow())
    found = await alerts.alerts(store, cfg, utcnow())
    assert [a["id"] for a in found] == ["dm_skipped"]
    assert found[0]["detail"] == "Latest, from @friend: too long"


async def test_ids_are_stable_and_newest_first(store, cfg):
    old = _post(store, "failed", "a", updated=utcnow() - timedelta(hours=3))
    new = _post(store, "failed", "b", updated=utcnow() - timedelta(hours=1))
    first = await _ids(store, cfg)
    assert first == [f"publish_failed:{new}", f"publish_failed:{old}"]
    assert await _ids(store, cfg, now=utcnow() + timedelta(minutes=5)) == first


async def test_dismissed_until_it_changes(store, cfg):
    store.set_state("heartbeat_at", to_iso(utcnow() - timedelta(minutes=10)))
    now = utcnow()
    alerts.dismiss(store, "worker", now)
    assert await _ids(store, cfg, now) == []
    # The worker came back, then went quiet again: a new stale heartbeat.
    store.set_state("heartbeat_at", to_iso(now + timedelta(minutes=1)))
    assert await _ids(store, cfg, now + timedelta(minutes=10)) == ["worker"]


async def test_dismissing_old_entries_are_forgotten(store):
    now = utcnow()
    alerts.dismiss(store, "old", now - timedelta(days=31))
    alerts.dismiss(store, "worker", now)
    assert set(store.get_state(alerts.STATE_KEY)) == {"worker"}


def test_routes(store, cfg):
    pid = _post(store, "failed", "nope")
    with TestClient(create_app(cfg, store=store), base_url=LOCAL) as tc:
        found = tc.get("/api/alerts").json()
        assert [a["id"] for a in found] == [f"publish_failed:{pid}"]
        assert set(found[0]) == {"id", "kind", "severity", "title", "detail", "link", "since"}
        r = tc.post(f"/api/alerts/publish_failed:{pid}/dismiss", headers=ORIGIN)
        assert r.status_code == 200 and r.json()["id"] == f"publish_failed:{pid}"
        assert tc.get("/api/alerts").json() == []
