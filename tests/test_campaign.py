from datetime import timedelta

import httpx
import pytest
import respx

from src import campaign as camp
from src.scoring import ScoringConfig, compare_variants, score_posts
from src.store import to_iso, utcnow

from .conftest import API


# ---------------------------------------------------------------- store
def test_schedule_claim_publish_labels(store):
    past = utcnow() - timedelta(minutes=1)
    future = utcnow() + timedelta(hours=2)
    a = store.schedule("image", {"image_url": "https://x/1.jpg"}, past, "launch", "A", "hook=question")
    store.schedule("image", {"image_url": "https://x/2.jpg"}, future, "launch", "B")

    due = store.claim_due()
    assert [p["id"] for p in due] == [a["id"]]
    assert due[0]["status"] == "publishing" and due[0]["attempts"] == 1
    assert store.claim_due() == []  # not claimed twice

    store.mark_published(a["id"], "M1", "https://ig/p/1")
    assert store.get_scheduled(a["id"])["status"] == "published"
    assert store.get_label("M1")["variant"] == "A"
    assert store.get_label("M1")["hypothesis"] == "hook=question"


def test_cancel_and_reschedule(store):
    p = store.schedule("story", {"image_url": "https://x/s.jpg"}, utcnow() + timedelta(hours=1))
    assert store.cancel(p["id"])["status"] == "cancelled"
    with pytest.raises(ValueError):
        store.cancel(p["id"])
    again = store.reschedule(p["id"], utcnow() + timedelta(hours=3))
    assert again["status"] == "pending"


def test_stuck_publishing_is_failed_not_retried(store):
    p = store.schedule("image", {"image_url": "https://x/1.jpg"}, utcnow() - timedelta(hours=2))
    store.claim_due()
    store._conn.execute("UPDATE scheduled_posts SET updated_at=? WHERE id=?",
                        (to_iso(utcnow() - timedelta(hours=1)), p["id"]))
    assert store.recover_stuck() == 1
    assert store.get_scheduled(p["id"])["status"] == "failed"


def test_validate_payload():
    with pytest.raises(ValueError, match="video_url"):
        camp.validate_payload("reel", {"caption": "x"})
    with pytest.raises(ValueError, match="2 to 10"):
        camp.validate_payload("carousel", {"items": [{"image_url": "a"}]})
    camp.validate_payload("story", {"image_url": "https://x/s.jpg"})


# ---------------------------------------------------------------- run_due
def _publish_ok(media_id="M1"):
    respx.post(f"{API}/1789/media").respond(json={"id": "C1"})
    respx.get(f"{API}/C1").respond(json={"status_code": "FINISHED"})
    respx.post(f"{API}/1789/media_publish").respond(json={"id": media_id})
    respx.get(f"{API}/{media_id}").respond(json={"id": media_id, "permalink": "https://ig/p"})


@respx.mock
async def test_run_due_publishes_and_labels(client, store):
    _publish_ok()
    p = store.schedule("image", {"image_url": "https://x/1.jpg", "caption": "hi"},
                       utcnow() - timedelta(seconds=5), "launch", "A")
    res = await camp.run_due(client, store)
    assert res["published"][0]["media_id"] == "M1"
    assert store.get_scheduled(p["id"])["status"] == "published"
    assert store.get_label("M1")["campaign"] == "launch"


@respx.mock
async def test_run_due_retries_transient_and_stops_permanent(client, store):
    respx.post(f"{API}/1789/media").respond(
        400, json={"error": {"message": "temporary", "code": 2}})
    p = store.schedule("image", {"image_url": "https://x/1.jpg"}, utcnow() - timedelta(seconds=5))
    res = await camp.run_due(client, store)
    assert res["retrying"] and store.get_scheduled(p["id"])["status"] == "pending"

    respx.routes.clear()
    respx.post(f"{API}/1789/media").respond(
        400, json={"error": {"message": "bad ratio", "code": 36003, "error_subcode": 2207009}})
    store._conn.execute("UPDATE scheduled_posts SET publish_at=? WHERE id=?",
                        (to_iso(utcnow() - timedelta(seconds=1)), p["id"]))
    res = await camp.run_due(client, store)
    assert res["failed"] and store.get_scheduled(p["id"])["status"] == "failed"


@respx.mock
async def test_network_error_is_not_auto_retried(client, store):
    respx.post(f"{API}/1789/media").respond(json={"id": "C1"})
    respx.get(f"{API}/C1").respond(json={"status_code": "FINISHED"})
    respx.post(f"{API}/1789/media_publish").mock(side_effect=httpx.ReadTimeout("slow"))
    p = store.schedule("image", {"image_url": "https://x/1.jpg"}, utcnow() - timedelta(seconds=5))
    res = await camp.run_due(client, store)
    post = store.get_scheduled(p["id"])
    assert res["failed"] and post["status"] == "failed"
    assert "check Instagram" in post["error"]


@respx.mock
async def test_rate_limit_leaves_other_posts_pending(client, store):
    respx.post(f"{API}/1789/media").respond(
        400, json={"error": {"message": "limit", "code": 4}})
    ids = [store.schedule("image", {"image_url": f"https://x/{i}.jpg"},
                          utcnow() - timedelta(seconds=5))["id"] for i in range(3)]
    res = await camp.run_due(client, store)
    assert len(res["retrying"]) == 1
    statuses = [store.get_scheduled(i)["status"] for i in ids]
    assert statuses == ["pending", "pending", "pending"]


# ---------------------------------------------------------------- insights
@respx.mock
async def test_collect_insights_snapshots_matured_posts(client, store):
    old = to_iso(utcnow() - timedelta(days=3))
    fresh = to_iso(utcnow() - timedelta(minutes=10))
    respx.get(f"{API}/1789/media").respond(json={"data": [
        {"id": "A", "timestamp": fresh, "media_product_type": "FEED"},
        {"id": "B", "timestamp": old, "media_product_type": "REELS", "media_type": "VIDEO"},
    ]})
    respx.get(f"{API}/1789/stories").respond(json={"data": []})
    respx.get(f"{API}/B/insights").respond(json={"data": [
        {"name": "reach", "values": [{"value": 1000}]},
        {"name": "saved", "values": [{"value": 30}]}]})
    res = await camp.collect_insights(client, store)
    assert res == {"captured": 1, "skipped": 1, "errors": []}
    snap = store.latest_snapshots()[0]
    assert snap["media_id"] == "B" and snap["metrics"]["saved"] == 30
    assert 71 < snap["age_hours"] < 73


# ---------------------------------------------------------------- scoring
def _snap(mid, reach, saved, shares, follows=1, age=72, pt="FEED", posted="2026-11-01"):
    return {"media_id": mid, "media_product_type": pt, "age_hours": age, "posted_at": posted,
            "metrics": {"reach": reach, "saved": saved, "shares": shares, "follows": follows,
                        "likes": reach // 20, "comments": 2, "profile_visits": 5}}


def test_scoring_finds_winner_and_respects_maturity():
    baseline = [_snap(f"b{i}", 1000, 10, 5) for i in range(8)]
    star = _snap("star", 1200, 60, 30, follows=12)
    young = _snap("young", 5000, 500, 200, age=10)
    weak = _snap("weak", 900, 1, 0, follows=0)
    scored = {r["media_id"]: r for r in score_posts([star, young, weak] + baseline,
                                                     ScoringConfig(min_reach=300))}
    assert scored["star"]["verdict"] == "winner"
    assert scored["star"]["engagement_index"] > 3
    assert scored["young"]["verdict"] == "too_early"
    assert scored["weak"]["verdict"] == "weak"
    assert scored["b0"]["verdict"] == "average"
    assert scored["star"]["confidence"] == "medium"


def test_reels_judged_only_against_reels():
    feed = [_snap(f"f{i}", 1000, 100, 50) for i in range(5)]   # very engaging feed posts
    reels = [_snap(f"r{i}", 3000, 10, 5, pt="REELS") for i in range(5)]
    reel = _snap("reel", 3000, 40, 20, pt="REELS")
    scored = {r["media_id"]: r for r in score_posts([reel] + feed + reels)}
    assert scored["reel"]["verdict"] == "winner"


def test_small_reach_is_not_a_winner():
    baseline = [_snap(f"b{i}", 1000, 10, 5) for i in range(5)]
    tiny = _snap("tiny", 120, 20, 10)
    scored = {r["media_id"]: r for r in score_posts([tiny] + baseline)}
    assert scored["tiny"]["verdict"] == "promising"


def test_compare_variants_flags_thin_samples():
    baseline = [_snap(f"b{i}", 1000, 10, 5) for i in range(6)]
    a = [_snap(f"a{i}", 1000, 40, 20) for i in range(3)]
    b = [_snap(f"v{i}", 1000, 10, 5) for i in range(3)]
    labels = {**{p["media_id"]: {"campaign": "launch", "variant": "A"} for p in a},
              **{p["media_id"]: {"campaign": "launch", "variant": "B"} for p in b}}
    out = compare_variants(score_posts(a + b + baseline, labels=labels), "launch")
    assert out["leader"] == "A" and out["note"] is None
    assert out["variants"][0]["avg_engagement_index"] > out["variants"][1]["avg_engagement_index"]

    out2 = compare_variants(score_posts(a[:1] + b + baseline, labels=labels), "launch")
    assert out2["leader"] is None and "Fewer than 3" in out2["note"]


# ---------------------------------------------------------------- regressions
def test_claim_due_skips_posts_claimed_by_another_process(tmp_path):
    from src.store import CampaignStore

    db = str(tmp_path / "q.db")
    a, b = CampaignStore(db), CampaignStore(db)
    try:
        a.schedule("image", {"image_url": "https://x/1.jpg"}, utcnow() - timedelta(minutes=1))
        assert len(a.claim_due()) == 1
        assert b.claim_due() == []
        # Simulate b's SELECT seeing the row as pending before a's UPDATE committed.
        p = b.schedule("image", {"image_url": "https://x/2.jpg"}, utcnow() - timedelta(minutes=1))
        b._conn.execute("UPDATE scheduled_posts SET status='publishing' WHERE id=?", (p["id"],))
        b._conn.commit()
        orig = b._conn

        class Stale:  # returns the row id as if it were still pending
            def __init__(self, conn):
                self.conn = conn

            def execute(self, sql, args=()):
                if sql.startswith("SELECT id FROM scheduled_posts"):
                    return self.conn.execute("SELECT id FROM scheduled_posts WHERE id=?",
                                             (p["id"],))
                return self.conn.execute(sql, args)

            def __getattr__(self, name):
                return getattr(self.conn, name)

        b._conn = Stale(orig)
        assert b.claim_due() == []
        b._conn = orig
    finally:
        a.close()
        b.close()


def test_reschedule_resets_attempts(store):
    p = store.schedule("image", {"image_url": "https://x/1.jpg"}, utcnow() - timedelta(minutes=1))
    store.claim_due()
    store.mark_failed(p["id"], "boom", retry_in_minutes=None)
    again = store.reschedule(p["id"], utcnow() + timedelta(hours=1))
    assert again["attempts"] == 0 and again["status"] == "pending"


def test_cannot_cancel_or_reschedule_while_publishing(store):
    p = store.schedule("image", {"image_url": "https://x/1.jpg"}, utcnow() - timedelta(minutes=1))
    store.claim_due()
    with pytest.raises(ValueError):
        store.cancel(p["id"])
    with pytest.raises(ValueError):
        store.reschedule(p["id"], utcnow() + timedelta(hours=1))


def test_parse_dt_handles_meta_offsets_and_dates():
    from src.store import parse_dt

    assert parse_dt("2026-11-01T10:00:00+0000").hour == 10
    assert parse_dt("2026-11-01T10:00:00+0130").hour == 8
    assert parse_dt("2026-11-01T10:00:00Z").hour == 10
    assert parse_dt("2026-11-20").day == 20


@respx.mock
async def test_network_error_before_publish_is_retried(client, store):
    respx.post(f"{API}/1789/media").respond(json={"id": "C1"})
    respx.get(f"{API}/C1").mock(side_effect=httpx.ConnectError("down"))
    p = store.schedule("image", {"image_url": "https://x/1.jpg"}, utcnow() - timedelta(seconds=5))
    res = await camp.run_due(client, store)
    assert res["retrying"] and store.get_scheduled(p["id"])["status"] == "pending"
