"""Step 076: tag breakdowns (src/learning/breakdowns.py) and GET /api/analytics/breakdown."""

from datetime import datetime, timedelta, timezone
from statistics import median

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.campaign import rank
from src.learning.breakdowns import duration_bucket, tag_breakdown
from src.store import to_iso

from .conftest import LOCAL
from .test_api_assets import _settings

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


@pytest.fixture
def settings():
    return _settings(timezone="America/New_York")


def _post(store, mid, posted, kind="REELS", reach=1000, saved=10, age=72, studio=None):
    """One snapshot `age` hours after `posted`; studio = (track, hook, template, duration)."""
    store.add_snapshot(mid, {"reach": reach, "views": reach * 2, "saved": saved,
                             "likes": reach // 20, "shares": saved // 2},
                       kind, "VIDEO", to_iso(posted), captured_at=posted + timedelta(hours=age))
    if studio:
        track, hook, template, duration = studio
        idea = store.add_idea(track, hook_type=hook, pillar="myths")
        asset = store.add_asset(idea["id"], duration=duration,
                                recipe={"kind": "motion", "template": template})
        store.label_post(mid, asset_id=asset["id"])


@pytest.fixture
def seeded(store):
    day = datetime(2026, 11, 10, 23, 30, tzinfo=timezone.utc)  # 18:30 in New York
    _post(store, "q1", day, saved=40, studio=("motion", "question", "FactQuest", 10))
    _post(store, "q2", day - timedelta(days=1), saved=30,
          studio=("motion", "question", "FactQuest", 20))
    _post(store, "q3", day - timedelta(days=2), saved=20,
          studio=("motion", "question", "QuizChest", 45))
    _post(store, "b1", day - timedelta(days=3), saved=5,
          studio=("remix", "bold_claim", "BossBattle", 90))
    _post(store, "ext1", day - timedelta(days=4, hours=10), saved=10)  # 08:30 NY
    _post(store, "ext2", day - timedelta(days=5), saved=12)
    # Excluded: too young, a feed post, older than the window.
    _post(store, "young", NOW - timedelta(hours=5), age=4, saved=99,
          studio=("motion", "question", "FactQuest", 12))
    _post(store, "feed", day, kind="FEED", saved=99, studio=("motion", "question", "FactQuest", 12))
    _post(store, "old", NOW - timedelta(days=200), saved=99,
          studio=("motion", "question", "FactQuest", 12))
    return store


def _groups(store, settings, tag, **kw):
    out = tag_breakdown(store, settings, tag=tag, post_type=kw.pop("post_type", "REELS"),
                        now=NOW, **kw)
    return {g["tag_value"]: g for g in out["groups"]}


def test_hook_type_grouping_excludes_young_feed_and_old(seeded, settings):
    g = _groups(seeded, settings, "hook_type")
    assert {k: v["n"] for k, v in g.items()} == {"question": 3, "bold_claim": 1, "untagged": 2}
    assert not g["question"]["small_sample"] and g["bold_claim"]["small_sample"]
    assert g["untagged"]["reach"] == {"median": 1000} and g["untagged"]["views"] == {"median": 2000}
    assert "total_watch_time" not in g["question"]  # no post carries it
    assert set(_groups(seeded, settings, "hook_type", days=365)) == set(g)
    assert _groups(seeded, settings, "hook_type", days=365)["question"]["n"] == 4  # + old


def test_engagement_index_matches_the_scorer_and_quantiles(seeded, settings):
    ranked = {p["media_id"]: p["engagement_index"] for p in rank(seeded, settings, limit=99)["posts"]}
    eng = [ranked[m] for m in ("q1", "q2", "q3")]
    assert None not in eng and len(set(eng)) == 3
    q = _groups(seeded, settings, "hook_type")["question"]["engagement_index"]
    lo, mid, hi = sorted(eng)
    assert q == {"median": mid, "p25": round((lo + mid) / 2, 2), "p75": round((mid + hi) / 2, 2)}
    one = _groups(seeded, settings, "hook_type")["bold_claim"]["engagement_index"]
    assert one == {"median": ranked["b1"], "p25": ranked["b1"], "p75": ranked["b1"]}
    groups = tag_breakdown(seeded, settings, tag="track", post_type="REELS", now=NOW)["groups"]
    medians = [g["engagement_index"]["median"] for g in groups]
    assert medians == sorted(medians, reverse=True)
    assert median(eng) == mid


def test_other_tags(seeded, settings):
    assert {k: v["n"] for k, v in _groups(seeded, settings, "template").items()} == {
        "FactQuest": 2, "QuizChest": 1, "BossBattle": 1, "untagged": 2}
    assert {k: v["n"] for k, v in _groups(seeded, settings, "track").items()} == {
        "motion": 3, "remix": 1, "untagged": 2}
    assert {k: v["n"] for k, v in _groups(seeded, settings, "duration").items()} == {
        "<15 s": 1, "15–30 s": 1, "30–60 s": 1, "60 s+": 1, "unknown": 2}
    # Owner-local hour (New York), external posts included.
    assert {k: v["n"] for k, v in _groups(seeded, settings, "hour").items()} == {18: 5, 8: 1}
    feed = _groups(seeded, settings, "pillar", post_type="feed")
    assert list(feed) == ["myths"] and feed["myths"]["engagement_index"] is None  # no baseline


def test_duration_bucket_edges():
    assert [duration_bucket(s) for s in (None, 0, 14.9, 15, 29.9, 30, 59.9, 60, 300)] == [
        "unknown", "<15 s", "<15 s", "15–30 s", "15–30 s", "30–60 s", "30–60 s", "60 s+", "60 s+"]


def test_unknown_tag_or_type(store, settings):
    with pytest.raises(ValueError):
        tag_breakdown(store, settings, tag="colour", post_type="REELS")
    with pytest.raises(ValueError):
        tag_breakdown(store, settings, tag="track", post_type="CAROUSEL")


def test_route(seeded, settings):
    with TestClient(create_app(settings, store=seeded), base_url=LOCAL) as tc:
        body = tc.get("/api/analytics/breakdown?tag=hook_type&days=3660").json()
        assert body["post_type"] == "REELS" and body["tag"] == "hook_type"
        assert {g["tag_value"] for g in body["groups"]} == {"question", "bold_claim", "untagged"}
        feed = tc.get("/api/analytics/breakdown?tag=hour&type=feed&days=3660").json()
        assert [g["n"] for g in feed["groups"]] == [1]
        assert tc.get("/api/analytics/breakdown?tag=nope").status_code == 422
        assert tc.get("/api/analytics/breakdown?tag=track&type=nope").status_code == 422
        assert tc.get("/api/analytics/breakdown").status_code == 422
