"""Step 024: the Calendar (range by owner-local day, reschedule, cancel, re-plan, release)."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.store import parse_dt, to_iso, utcnow
from src.studio.assets import transition

from .conftest import LOCAL
from .test_studio_publish import _asset

H = {"Origin": LOCAL}
UTC = timezone.utc


@pytest.fixture
def cfg(tmp_path):
    return InstagramMCPSettings(_env_file=None, database_path=":memory:",
                                media_root=str(tmp_path), timezone="Europe/Paris",
                                posting_windows="10:00-12:00", max_posts_per_day=2,
                                min_slot_gap_minutes=60, slot_jitter_minutes=0)


@pytest.fixture
def tc(store, cfg):
    with TestClient(create_app(cfg, store=store), base_url=LOCAL) as c:
        yield c


def _failed(store, asset_id=None):
    """A row whose publish failed for good (the worker's path)."""
    post = store.schedule("reel", {"video_path": "x.mp4", "caption": "x"},
                          utcnow() - timedelta(minutes=5), asset_id=asset_id)
    assert [p["id"] for p in store.claim_due()] == [post["id"]]
    store.mark_failed(post["id"], "boom", None)
    return store.get_scheduled(post["id"])


def test_range_uses_owner_local_days(tc, store, cfg):
    # Paris is UTC+1 in November: 22:59Z is the 19th, 23:00Z already the 20th.
    late = store.schedule("reel", {"caption": "  a\nlong  " + "x" * 100},
                          datetime(2026, 11, 19, 22, 59, tzinfo=UTC))
    midnight = store.schedule("reel", {}, datetime(2026, 11, 19, 23, 0, tzinfo=UTC))
    store.schedule("reel", {}, datetime(2026, 11, 18, 22, 59, tzinfo=UTC))  # the 18th
    store.move_pending(midnight["id"], datetime(2026, 11, 19, 23, 0, tzinfo=UTC),
                       "Re-planned: 40 min late")
    a = _asset(store, cfg, status="publish_check")

    r = tc.get("/api/calendar", params={"from": "2026-11-19", "to": "2026-11-20"})
    assert r.status_code == 200, r.text
    days = r.json()["days"]
    assert [d["date"] for d in days] == ["2026-11-19", "2026-11-20"]
    (row,), (moved,) = days[0]["posts"], days[1]["posts"]
    assert row["id"] == late["id"] and row["local"] == "2026-11-19T23:59:00+01:00"
    assert row["caption"].startswith("a long x") and row["caption"].endswith("…")
    assert len(row["caption"]) == 81 and not row["replanned"]
    assert moved["id"] == midnight["id"] and moved["replanned"]
    assert moved["error"] == "Re-planned: 40 min late"
    assert [x["id"] for x in r.json()["publish_check"]] == [a["id"]]
    assert "preview_url" in r.json()["publish_check"][0]

    one = tc.get("/api/calendar", params={"from": "2026-11-20", "to": "2026-11-20"}).json()
    assert [p["id"] for p in one["days"][0]["posts"]] == [midnight["id"]]


@pytest.mark.parametrize("params", [
    {"from": "2026-11-20", "to": "2026-11-19"},  # reversed
    {"from": "2026-01-01", "to": "2026-03-04"},  # 63 days
    {"from": "2026-11-19"},
    {"from": "nope", "to": "2026-11-19"},
])
def test_range_refusals(tc, params):
    r = tc.get("/api/calendar", params=params)
    assert r.status_code == 422 and r.json()["error"] == "invalid"


def test_asset_row_carries_preview(tc, store, cfg):
    a = _asset(store, cfg, preview_path="2026-11-17/preview.mp4")
    at = utcnow() + timedelta(days=1)
    r = tc.post(f"/api/assets/{a['id']}/schedule", json={"publish_at": to_iso(at)}, headers=H)
    assert r.status_code == 200, r.text
    day = at.astimezone(ZoneInfo(cfg.timezone)).date()
    r = tc.get("/api/calendar", params={"from": str(day - timedelta(days=1)),
                                        "to": str(day + timedelta(days=1))})
    (row,) = [p for d in r.json()["days"] for p in d["posts"]]
    assert row["asset_id"] == a["id"] and row["preview_url"] == "/api/media/2026-11-17/preview.mp4"


def test_reschedule(tc, store):
    post = store.schedule("reel", {}, utcnow() + timedelta(days=1))
    at = to_iso(utcnow() + timedelta(days=2))
    r = tc.post(f"/api/posts/{post['id']}/reschedule", json={"publish_at": at}, headers=H)
    assert r.status_code == 200 and r.json()["publish_at"] == at
    past = to_iso(utcnow() - timedelta(hours=1))
    for body in ({"publish_at": past}, {"publish_at": "2026-12-01T10:00:00"}):  # naive
        r = tc.post(f"/api/posts/{post['id']}/reschedule", json=body, headers=H)
        assert r.status_code == 422, body
    store.mark_published(post["id"], "m1", None)
    r = tc.post(f"/api/posts/{post['id']}/reschedule", json={"publish_at": at}, headers=H)
    assert r.status_code == 422 and "published" in r.json()["message"]
    assert tc.post("/api/posts/999/reschedule", json={"publish_at": at},
                   headers=H).status_code == 404


def test_cancel_gives_the_asset_back(tc, store, cfg):
    a = _asset(store, cfg)
    tc.post(f"/api/assets/{a['id']}/schedule",
            json={"publish_at": to_iso(utcnow() + timedelta(days=1))}, headers=H)
    (post,) = store.list_scheduled()
    r = tc.post(f"/api/posts/{post['id']}/cancel", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert store.get_asset(a["id"])["status"] == "approved"
    assert tc.post(f"/api/posts/{post['id']}/cancel", headers=H).status_code == 422


def test_replan_plain_row_in_place(tc, store):
    post = _failed(store)
    r = tc.post(f"/api/posts/{post['id']}/replan", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == post["id"] and r.json()["status"] == "pending"
    assert parse_dt(r.json()["publish_at"]) > utcnow() and r.json()["error"] is None
    r = tc.post(f"/api/posts/{post['id']}/replan", headers=H)  # pending now
    assert r.status_code == 409 and r.json()["error"] == "invalid_transition"


def test_replan_asset_row_queues_the_asset_again(tc, store, cfg):
    a = _asset(store, cfg, status="scheduled")
    post = _failed(store, a["id"])
    transition(store, a["id"], "approved", actor="worker")  # the publish surely failed
    r = tc.post(f"/api/posts/{post['id']}/replan", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["id"] != post["id"] and r.json()["asset_id"] == a["id"]
    assert r.json()["status"] == "pending" and parse_dt(r.json()["publish_at"]) > utcnow()
    assert store.get_scheduled(post["id"])["status"] == "cancelled"
    assert store.get_asset(a["id"])["status"] == "scheduled"


def test_replan_refuses_unsettled_asset_until_released(tc, store, cfg):
    a = _asset(store, cfg, status="scheduled")
    post = _failed(store, a["id"])
    transition(store, a["id"], "publish_check", actor="worker")  # may be on Instagram
    r = tc.post(f"/api/posts/{post['id']}/replan", headers=H)
    assert r.status_code == 409 and r.json()["error"] == "not_approved"
    assert store.get_scheduled(post["id"])["status"] == "failed"

    r = tc.post(f"/api/assets/{a['id']}/release", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert tc.get("/api/calendar", params={"from": "2026-11-19", "to": "2026-11-19"}
                  ).json()["publish_check"] == []
    assert tc.post(f"/api/posts/{post['id']}/replan", headers=H).status_code == 200


def test_replan_commentary_needs_the_rights_confirmation(tc, store, cfg):
    # 072: every queue path asks for it (schedule and approve-and-queue: scheduling tests).
    a = _asset(store, cfg, status="scheduled", track="remix", caption="ha @creator",
               source={"rights_basis": "commentary", "author": "@creator"})
    post = _failed(store, a["id"])
    transition(store, a["id"], "approved", actor="worker")
    r = tc.post(f"/api/posts/{post['id']}/replan", headers=H)
    assert r.status_code == 409 and r.json()["error"] == "rights"
    assert store.get_scheduled(post["id"])["status"] == "failed"
    r = tc.post(f"/api/posts/{post['id']}/replan", json={"confirmed": True}, headers=H)
    assert r.status_code == 200 and store.get_asset(a["id"])["status"] == "scheduled"
