"""Step 074: analytics services and API (account series, posts table, post detail)."""

import random
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.learning.analytics import account_series
from src.scoring import ScoringConfig, score_posts
from src.store import to_iso
from src.studio.seed import local_today

from .conftest import LOCAL
from .test_api_assets import _settings

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
AGES = (1, 3, 6, 12, 24, 48, 168, 720)


def _post(store, mid, posted_hours_ago, kind="FEED", reach=1000, seed=0, caption=None):
    """Snapshots at every schedule age the post has reached; metrics grow with age."""
    rng = random.Random(seed)
    posted = NOW - timedelta(hours=posted_hours_ago)
    for age in (a for a in AGES if a <= posted_hours_ago):
        r = int(reach * min(1, age / 48) * rng.uniform(0.8, 1.2)) + 1
        store.add_snapshot(mid, {"reach": r, "views": r * 3, "likes": r // 20,
                                 "saved": r // rng.randint(30, 90), "shares": r // 70},
                           kind, "VIDEO", to_iso(posted), caption=caption or f"post {mid}",
                           permalink=f"https://instagram.com/p/{mid}",
                           captured_at=posted + timedelta(hours=age))


def test_indexed_baselines_score_like_the_full_history(store):
    for i in range(12):
        _post(store, f"f{i}", (60, 200, 800)[i % 3] + i, reach=500 + 150 * i, seed=i)
        _post(store, f"r{i}", (30, 100, 750)[i % 3] + i, "REELS", reach=900 + 90 * i, seed=50 + i)
    latest = store.latest_snapshots()
    cfg = ScoringConfig(min_reach=100, baseline_window=8)
    old = score_posts(latest, cfg, history=store.snapshot_history(), now=NOW)
    new = score_posts(latest, cfg, near_age=store.snapshots_near_age, now=NOW)
    assert new == old
    assert old != score_posts(latest, cfg, now=NOW)  # the age matching really mattered


def test_account_series_deltas(store):
    d0 = local_today("UTC", NOW)
    for i, followers in enumerate((100, 110, 105)):
        store.save_account_snapshot(d0 + timedelta(days=i), {}, followers=followers,
                                    reach=50 * (i + 1), views=None if i == 2 else 300)
    out = account_series(store, d0 + timedelta(days=1), d0 + timedelta(days=2))
    assert [d["date"] for d in out["days"]] == [str(d0 + timedelta(days=1)),
                                                str(d0 + timedelta(days=2))]
    first, second = out["days"]
    assert first["deltas"]["followers"] == 10  # against the day before `since`
    assert second["deltas"] == {"followers": -5, "reach": 50, "views": None,
                                "reach_followers": None, "reach_non_followers": None}


@pytest.fixture
def tc(store):
    with TestClient(create_app(_settings(timezone="UTC"), store=store), base_url=LOCAL) as c:
        yield c


def _studio_post(store, mid):
    idea = store.add_idea("motion", pillar="myths", hook_type="question",
                          hypothesis="questions hook better")
    asset = store.add_asset(idea["id"], recipe={"kind": "motion", "template": "FactQuest"},
                            preview_path="2026-11-01/1/preview.mp4")
    store.label_post(mid, asset_id=asset["id"])
    store.add_feedback(asset["id"], text="love the ending")
    return asset


def test_account_route(tc, store):
    today = local_today("UTC")
    for i in range(3):
        store.save_account_snapshot(today - timedelta(days=i), {}, followers=100 - i)
    days = tc.get("/api/analytics/account?days=2").json()["days"]
    assert [d["followers"] for d in days] == [99, 100]
    assert days[-1]["deltas"]["followers"] == 1


def test_posts_table_sort_paging_and_tags(tc, store):
    _post(store, "ext", 100, reach=3000, seed=1)
    _post(store, "ours", 200, "REELS", reach=2000, seed=2)
    _post(store, "young", 2, reach=10, seed=3)
    asset = _studio_post(store, "ours")

    body = tc.get("/api/analytics/posts?sort=-views&limit=2").json()
    assert body["total"] == 3 and [p["media_id"] for p in body["posts"]] == ["ext", "ours"]
    ext, ours = body["posts"]
    assert ext["tags"] is None and ext["asset_id"] is None and ext["owner_verdict"] is None
    assert ours["asset_id"] == asset["id"] and ours["owner_verdict"] == "none"
    assert ours["tags"] == {"track": "motion", "pillar": "myths", "hook_type": "question",
                            "strategy": None, "style": None, "template": "FactQuest"}
    assert ours["metrics"]["reach"] > 0 and ours["caption"] == "post ours"

    page2 = tc.get("/api/analytics/posts?sort=-views&limit=2&offset=2").json()["posts"]
    assert [p["media_id"] for p in page2] == ["young"]
    assert page2[0]["verdict"] == "too_early"
    asc = tc.get("/api/analytics/posts?sort=posted_at").json()["posts"]
    assert [p["media_id"] for p in asc] == ["ours", "ext", "young"]
    reels = tc.get("/api/analytics/posts?type=reels").json()["posts"]
    assert [p["media_id"] for p in reels] == ["ours"]
    assert tc.get("/api/analytics/posts?sort=nope").status_code == 422
    assert tc.get("/api/analytics/posts?type=nope").status_code == 422


def test_post_detail(tc, store):
    _post(store, "ours", 50, "REELS", seed=4)
    _post(store, "other", 50, seed=5)
    asset = _studio_post(store, "ours")
    body = tc.get("/api/analytics/posts/ours").json()
    assert [s["age_hours"] for s in body["series"]] == [1, 3, 6, 12, 24, 48]
    assert body["series"][-1]["metrics"]["reach"] > body["series"][0]["metrics"]["reach"]
    assert body["asset_id"] == asset["id"] and body["tags"]["template"] == "FactQuest"
    assert body["hypothesis"] == "questions hook better"
    assert body["preview_url"] == "/api/media/2026-11-01/1/preview.mp4"
    assert [f["text"] for f in body["feedback"]] == ["love the ending"]
    assert "asset" not in body

    ext = tc.get("/api/analytics/posts/other").json()
    assert len(ext["series"]) == 6 and ext["tags"] is None and ext["feedback"] == []
    r = tc.get("/api/analytics/posts/unknown")
    assert r.status_code == 404 and r.json() == {"error": "not_found"}


def test_posts_table_rows_carry_watch_ratio_and_view_rate(tc, store):
    posted = to_iso(NOW - timedelta(days=5))
    for mid in ("ours", "ext"):
        store.add_snapshot(mid, {"reach": 1000, "views": 1500, "ig_reels_avg_watch_time": 6000},
                           "REELS", "VIDEO", posted, captured_at=NOW)
    asset = _studio_post(store, "ours")
    store.update_asset(asset["id"], duration=20.0)
    rows = {p["media_id"]: p for p in tc.get("/api/analytics/posts").json()["posts"]}
    assert rows["ours"]["watch_ratio"] == 0.3 and rows["ours"]["view_rate"] == 1.5
    assert rows["ext"]["watch_ratio"] is None and rows["ext"]["view_rate"] == 1.5


def test_posts_table_urls_and_verdict_tagged_filters(tc, store):
    _post(store, "ext", 100, reach=3000, seed=1)
    _post(store, "ours", 200, "REELS", reach=2000, seed=2)
    _post(store, "young", 2, reach=10, seed=3)
    asset = _studio_post(store, "ours")
    store.update_asset(asset["id"], thumbnail_path="2026-11-01/1/thumb.jpg")

    rows = {p["media_id"]: p for p in tc.get("/api/analytics/posts").json()["posts"]}
    assert rows["ours"]["thumbnail_url"] == "/api/media/2026-11-01/1/thumb.jpg"
    assert rows["ours"]["preview_url"] == "/api/media/2026-11-01/1/preview.mp4"
    assert rows["ext"]["thumbnail_url"] is None and rows["ext"]["preview_url"] is None
    assert "asset" not in rows["ours"]

    def ids(query):
        body = tc.get(f"/api/analytics/posts?{query}").json()
        return sorted(p["media_id"] for p in body["posts"]), body["total"]

    assert ids("tagged=true") == (["ours"], 1)
    assert ids("tagged=false") == (["ext", "young"], 2)
    assert ids("verdict=too_early") == (["young"], 1)
    assert ids("verdict=too_early&tagged=true") == ([], 0)
    assert tc.get("/api/analytics/posts?verdict=nope").status_code == 422
    assert tc.get("/api/analytics/posts?sort=-watch_ratio").status_code == 200
