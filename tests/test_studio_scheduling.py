"""Step 023: propose a slot, schedule, unschedule, unapprove (service + routes)."""

from datetime import datetime, time, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.store import parse_dt, to_iso, utcnow
from src.studio import scheduling
from src.studio.assets import set_verdict
from src.studio.publish import QueueRefused

from .conftest import LOCAL
from .test_studio_publish import _asset

H = {"Origin": LOCAL}
COMMENTARY = {"rights_basis": "commentary", "author": "@creator"}


@pytest.fixture
def cfg(tmp_path):
    return InstagramMCPSettings(_env_file=None, database_path=":memory:",
                                media_root=str(tmp_path), timezone="UTC",
                                posting_windows="10:00-12:00", max_posts_per_day=2,
                                min_slot_gap_minutes=60, slot_jitter_minutes=0)


@pytest.fixture
def tc(store, cfg):
    with TestClient(create_app(cfg, store=store), base_url=LOCAL) as c:
        yield c


def _day(n=2):
    """09:00 UTC n days from now (before the 10-12 window opens)."""
    return datetime.combine(utcnow().date() + timedelta(days=n), time(9), tzinfo=timezone.utc)


def test_propose_respects_taken_slots_and_gap(store, cfg):
    a = _asset(store, cfg)
    now = _day()
    first = scheduling.propose_slot(store, cfg, a["id"], now)
    assert parse_dt(first["publish_at"]) == now.replace(hour=11)  # window centre
    assert first["local"].startswith(f"{now.date()}T11:00:00") and not first["needs_confirmation"]
    store.schedule("reel", {"video_path": "x.mp4"}, now.replace(hour=11))
    second = parse_dt(scheduling.propose_slot(store, cfg, a["id"], now)["publish_at"])
    assert second.date() == now.date() and abs(second - now.replace(hour=11)) >= timedelta(hours=1)
    store.schedule("reel", {"video_path": "x.mp4"}, second)  # the day is full (max 2)
    third = parse_dt(scheduling.propose_slot(store, cfg, a["id"], now)["publish_at"])
    assert third.date() == now.date() + timedelta(days=1)


def test_proposed_slot_route(tc, store, cfg):
    comm = _asset(store, cfg, track="remix", source=COMMENTARY)
    r = tc.get(f"/api/assets/{comm['id']}/proposed-slot")
    assert r.status_code == 200 and r.json()["needs_confirmation"] is True
    assert r.json()["ai_label"] is True
    assert parse_dt(r.json()["publish_at"]) > utcnow()
    assert tc.get("/api/assets/999/proposed-slot").status_code == 404


def test_schedule_ok_slot_and_unschedule(tc, store, cfg):
    a = _asset(store, cfg)
    at = to_iso(_day())
    r = tc.post(f"/api/assets/{a['id']}/schedule", json={"publish_at": at}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["post"]["publish_at"] == at and r.json()["asset"]["status"] == "scheduled"
    assert "file_url" in r.json()["asset"]
    r = tc.get(f"/api/assets/{a['id']}/slot")
    assert r.json()["publish_at"] == at and r.json()["post_id"] == store.list_scheduled()[0]["id"]
    r = tc.post(f"/api/assets/{a['id']}/unschedule", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert store.list_scheduled()[0]["status"] == "cancelled"
    assert tc.get(f"/api/assets/{a['id']}/slot").status_code == 404
    assert tc.post(f"/api/assets/{a['id']}/unschedule", headers=H).status_code == 409


@pytest.mark.parametrize("code, kw", [
    ("not_approved", {"status": "ready"}),
    ("rights", {"track": "remix", "source": COMMENTARY}),  # not confirmed
    ("no_file", {"file_path": None}),
    ("qc", {"qc": {"passed": False}}),
    ("caption", {"caption": "#x " * 31}),
])
def test_schedule_refusals_are_409(tc, store, cfg, code, kw):
    a = _asset(store, cfg, **kw)
    r = tc.post(f"/api/assets/{a['id']}/schedule", json={"publish_at": to_iso(_day())},
                headers=H)
    assert r.status_code == 409 and r.json()["error"] == code and r.json()["message"]
    assert store.list_scheduled() == []


def test_schedule_commentary_with_confirmation(tc, store, cfg):
    a = _asset(store, cfg, track="remix", source=COMMENTARY, caption="ha @creator")
    r = tc.post(f"/api/assets/{a['id']}/schedule",
                json={"publish_at": to_iso(_day()), "confirmed": True}, headers=H)
    assert r.status_code == 200 and r.json()["asset"]["status"] == "scheduled"


def test_schedule_bad_times_are_422(tc, store, cfg):
    a = _asset(store, cfg)
    url = f"/api/assets/{a['id']}/schedule"
    past = to_iso(utcnow() - timedelta(minutes=5))
    assert tc.post(url, json={"publish_at": past}, headers=H).status_code == 422
    naive = _day().replace(tzinfo=None).isoformat()  # no offset: ambiguous
    assert tc.post(url, json={"publish_at": naive}, headers=H).status_code == 422
    assert store.list_scheduled() == []


def test_unapprove_scheduled_cancels_the_row(tc, store, cfg):
    a = _asset(store, cfg)
    tc.post(f"/api/assets/{a['id']}/schedule", json={"publish_at": to_iso(_day())}, headers=H)
    r = tc.post(f"/api/assets/{a['id']}/unapprove", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert [p["status"] for p in store.list_scheduled()] == ["cancelled"]


def test_unapprove_publish_check_is_409(tc, store, cfg):
    a = _asset(store, cfg, status="publish_check")
    r = tc.post(f"/api/assets/{a['id']}/unapprove", headers=H)
    assert r.status_code == 409 and r.json()["error"] == "invalid_transition"
    assert "publish_check" in r.json()["message"]
    assert store.get_asset(a["id"])["status"] == "publish_check"


# Step 023a: the bench (ready + liked from every batch).

def _liked(store, cfg, best_before=None, self_score=None, status="ready"):
    a = _asset(store, cfg, status=status, best_before=best_before, self_score=self_score)
    return set_verdict(store, a["id"], "liked")


def test_bench_order_and_expiry(store, cfg):
    now = _day()
    d = lambda n: (now.date() + timedelta(days=n)).isoformat()  # noqa: E731
    late = _liked(store, cfg, d(5), 9)
    none_hi = _liked(store, cfg, None, 8)
    soon_lo = _liked(store, cfg, d(1), 3)
    soon_hi = _liked(store, cfg, d(1), 7)
    today = _liked(store, cfg, d(0))
    _liked(store, cfg, d(-1), 10)  # expired: left out before housekeeping archives it
    _liked(store, cfg, d(1), 10, status="approved")  # not on the bench any more
    _asset(store, cfg, status="ready", best_before=d(1))  # not liked
    ids = [a["id"] for a in scheduling.bench(store, cfg, now)["assets"]]
    # 189: same best_before -> oldest first; the legacy self_score (soon_hi 7) orders nothing
    assert ids == [today["id"], soon_lo["id"], soon_hi["id"], late["id"], none_hi["id"]]


@pytest.mark.parametrize("n, days", [(0, 0), (1, 1), (3, 1), (4, 2)])
def test_bench_supply_days(store, cfg, n, days):
    cfg = cfg.model_copy(update={"max_posts_per_day": 3})
    for _ in range(n):
        _liked(store, cfg)
    out = scheduling.bench(store, cfg, _day())
    assert len(out["assets"]) == n and out["supply_days"] == days
    assert out["max_posts_per_day"] == 3


def test_bench_suggestion_only_with_a_free_slot_within_24h(store, cfg):
    now = _day()
    assert scheduling.bench(store, cfg, now)["suggestion"] is None  # empty bench
    _liked(store, cfg, None, 2)
    fresh = _liked(store, cfg, (now.date() + timedelta(days=3)).isoformat(), 1)
    s = scheduling.bench(store, cfg, now)["suggestion"]
    assert s["asset_id"] == fresh["id"] and parse_dt(s["publish_at"]) == now.replace(hour=11)
    assert s["local"].startswith(f"{now.date()}T11:00:00")
    for day in (0, 1):  # today and tomorrow full (2 a day): the next slot is > 24 h away
        for hour in (10, 11):
            store.schedule("reel", {"video_path": "x.mp4"}, now.replace(hour=hour) + timedelta(
                days=day, minutes=30))
    assert scheduling.bench(store, cfg, now)["suggestion"] is None


def test_bench_route(tc, store, cfg):
    a = _liked(store, cfg)
    r = tc.get("/api/bench")
    assert r.status_code == 200
    body = r.json()
    assert [x["id"] for x in body["assets"]] == [a["id"]] and "file_url" in body["assets"][0]
    assert body["supply_days"] == 1


# Step 115: the feed's one-tap Approve.

def _fill_week(store, now):
    """Two posts a day (the max) for the planner's whole week: no free slot left."""
    for day in range(7):
        for hour in (10, 11):
            store.schedule("reel", {"video_path": "x.mp4"},
                           now.replace(hour=hour, minute=30) + timedelta(days=day))


def test_approve_and_queue_takes_the_next_free_slot(store, cfg):
    a = _asset(store, cfg, status="ready")
    now = _day()
    out = scheduling.approve_and_queue(store, cfg, a["id"], now)
    assert out["asset"]["status"] == "scheduled" and out["asset"]["approved_at"]
    assert parse_dt(out["post"]["publish_at"]) == now.replace(hour=11)
    assert out["slot"]["publish_at"] == out["post"]["publish_at"]


def test_approve_and_queue_without_a_free_slot_approves_only(store, cfg):
    a = _asset(store, cfg, status="ready")
    now = _day()
    _fill_week(store, now)
    out = scheduling.approve_and_queue(store, cfg, a["id"], now)
    assert out["asset"]["status"] == "approved" and out["post"] is None and out["slot"] is None
    assert len(store.list_scheduled()) == 14


@pytest.mark.parametrize("code, kw", [
    ("rights", {"track": "remix", "source": COMMENTARY}),  # not confirmed
    ("qc", {"qc": {"passed": False}}),
])
def test_approve_and_queue_refusal_leaves_the_asset_ready(store, cfg, code, kw):
    a = _asset(store, cfg, status="ready", **kw)
    with pytest.raises(QueueRefused) as e:
        scheduling.approve_and_queue(store, cfg, a["id"], _day())
    assert e.value.code == code
    after = store.get_asset(a["id"])
    assert after["status"] == "ready" and after["approved_at"] is None
    assert store.list_scheduled() == []


def test_approve_and_queue_route(tc, store, cfg):
    url = "/api/assets/{}/approve-and-queue".format
    a = _asset(store, cfg, status="ready")
    r = tc.post(url(a["id"]), json={}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["asset"]["status"] == "scheduled" and "file_url" in r.json()["asset"]
    assert parse_dt(r.json()["slot"]["publish_at"]) > utcnow()
    comm = _asset(store, cfg, status="ready", track="remix", source=COMMENTARY,
                  caption="ha @creator")
    r = tc.post(url(comm["id"]), json={}, headers=H)
    assert r.status_code == 409 and r.json()["error"] == "rights"
    assert store.get_asset(comm["id"])["status"] == "ready"
    r = tc.post(url(comm["id"]), json={"confirmed": True}, headers=H)
    assert r.status_code == 200 and r.json()["asset"]["status"] == "scheduled"
    r = tc.post(url(comm["id"]), json={"confirmed": True}, headers=H)  # not ready any more
    assert r.status_code == 409 and r.json()["error"] == "invalid_transition"
    assert store.get_asset(comm["id"])["status"] == "scheduled"
    assert [p["status"] for p in store.list_scheduled()] == ["pending", "pending"]
    assert tc.post(url(999), json={}, headers=H).status_code == 404


# --- Step 087: the planner learns from our results ---------------------------------------

def test_slot_inputs_reads_matured_reels_in_owner_local_time(store, cfg):
    from src.campaign import slot_inputs

    from .test_breakdowns import _post

    now = _day()
    _post(store, "a", now - timedelta(days=3, hours=-5))  # 14:00 UTC, matured
    _post(store, "b", now - timedelta(days=4))
    _post(store, "young", now - timedelta(hours=3), age=2)
    _post(store, "feed", now - timedelta(days=3), kind="FEED")
    _post(store, "old", now - timedelta(days=200))
    paris = cfg.model_copy(update={"timezone": "Europe/Paris"})
    profile, results = slot_inputs(store, paris, now)
    assert profile == {}
    local = sorted(t for t, _ in results)
    assert len(results) == 2 and all(isinstance(i, float) for _, i in results)
    assert local[0].hour in (10, 11) and local[1].hour in (15, 16)  # UTC+1 / +2


@pytest.fixture
def learning(monkeypatch, cfg):
    """Two windows; our evening posts do 2x typical (never explore: the day is today's)."""
    import src.campaign as campaign

    lc = cfg.model_copy(update={"posting_windows": "10:00-11:00,13:00-15:00",
                                "slot_explore_share": 0})
    inputs = ({}, [(time(14), 2.0)] * 5)
    monkeypatch.setattr(campaign, "slot_inputs", lambda *a: inputs)
    monkeypatch.setattr(scheduling, "slot_inputs", lambda *a: inputs)
    return lc


def test_propose_slot_uses_results_and_says_why(store, learning):
    a = _asset(store, learning)
    now = _day()
    out = scheduling.propose_slot(store, learning, a["id"], now)
    assert parse_dt(out["publish_at"]) == now.replace(hour=14)
    assert out["why"] == "13:00–15:00: your posts there do 2.0× typical (n = 5)"


def test_approve_and_queue_uses_results(store, learning):
    a = _asset(store, learning, status="ready")
    now = _day()
    out = scheduling.approve_and_queue(store, learning, a["id"], now)
    assert parse_dt(out["post"]["publish_at"]) == now.replace(hour=14)
