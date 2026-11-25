"""Step 077: studio funnel, like-rate, waste and reasons (src/learning/funnel.py)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.learning.funnel import funnel, taste
from src.store import to_iso
from src.studio.seed import local_today

from .conftest import LOCAL
from .test_api_assets import _settings

TZ = "America/New_York"
NOW = datetime(2026, 11, 17, 3, tzinfo=timezone.utc)  # still 2026-11-16 in New York


@pytest.fixture
def settings():
    return _settings(timezone=TZ)


def _asset(store, day, *, track="motion", hook="question", template="FactQuest", qc=True,
           status="ready", verdict="none", approved=False, best_before=None,
           updated_at=None, reasons=(), render_ms=(), file_path="d/video.mp4"):
    idea = store.add_idea(track, hook_type=hook, batch_date=day)
    recipe = {"kind": "motion", "template": template} if track == "motion" else {"kind": "ffmpeg"}
    a = store.add_asset(idea["id"], batch_date=day, recipe=recipe,
                        qc={"passed": True} if qc else None, best_before=best_before,
                        file_path=file_path)
    with store._tx() as c:  # tests set the end state directly
        c.execute("UPDATE assets SET status=?, verdict=?, approved_at=?, updated_at=? WHERE id=?",
                  (status, verdict, to_iso(NOW) if approved else None,
                   updated_at or to_iso(NOW), a["id"]))
    if reasons:
        store.add_feedback(a["id"], reason_codes=reasons)
    for i, ms in enumerate(render_ms):
        job = store.add_render_job(a["id"], f"{a['id']}-{i}")
        store.update_render_job(job["id"], state="done", render_ms=ms)
    return a["id"]


def _make_winner(store, asset_id):
    posted = NOW - timedelta(hours=72)
    for mid, (reach, saved, shares, follows) in [(f"b{i}", (1000, 10, 5, 1)) for i in range(8)] \
            + [("star", (1200, 60, 30, 12))]:
        store.add_snapshot(mid, {"reach": reach, "saved": saved, "shares": shares,
                                 "follows": follows, "likes": reach // 20, "comments": 2},
                           "REELS", "VIDEO", to_iso(posted), captured_at=NOW)
    store.label_post("star", asset_id=asset_id)


def test_funnel_counts_per_group(store, settings):
    win = _asset(store, "2026-11-16", verdict="liked", approved=True, status="published")
    _make_winner(store, win)
    _asset(store, "2026-11-16", template="BossBattle", verdict="disliked")
    _asset(store, "2026-11-16", status="revision_requested")  # owner move, no verdict
    _asset(store, "2026-11-15", track="remix", hook="pov")  # produced, unreviewed
    _asset(store, "2026-11-15", track="remix", status="rendering", qc=False)  # not produced
    _asset(store, "2026-11-17", verdict="liked")  # tomorrow in New York: outside
    _asset(store, "2026-11-13", verdict="liked")  # before the window

    by_track = funnel(store, settings, days=3, group_by="track", now=NOW)
    assert (by_track["since"], by_track["until"]) == ("2026-11-14", "2026-11-16")
    motion, remix = by_track["groups"]
    assert motion == {"key": "motion", "produced": 3, "reviewed": 3, "liked": 1, "approved": 1,
                      "published": 1, "winner": 1, "like_rate": 0.333, "approval_rate": 0.333}
    assert remix["key"] == "remix" and remix["produced"] == 1 and remix["reviewed"] == 0
    assert remix["like_rate"] is None
    assert by_track["totals"]["produced"] == 4 and by_track["approval_rate_note"]

    by_template = funnel(store, settings, days=3, group_by="template", now=NOW)["groups"]
    assert [(g["key"], g["produced"]) for g in by_template] == [
        ("BossBattle", 1), ("FactQuest", 2), (None, 1)]
    by_day = funnel(store, settings, days=3, group_by="day", now=NOW)["groups"]
    assert [(g["key"], g["reviewed"]) for g in by_day] == [("2026-11-15", 0), ("2026-11-16", 3)]
    hooks = funnel(store, settings, days=3, group_by="hook_type", now=NOW)["groups"]
    assert [g["key"] for g in hooks] == ["pov", "question"]
    with pytest.raises(ValueError):
        funnel(store, settings, group_by="pillar", now=NOW)


def test_like_rate_and_rolling(store, settings):
    for v in ("liked", "liked"):
        _asset(store, "2026-11-09", verdict=v)  # only in the rolling part
    for v in ("liked", "disliked"):
        _asset(store, "2026-11-14", verdict=v)
    _asset(store, "2026-11-16", verdict="disliked")
    _asset(store, "2026-11-16")  # unreviewed: not in the rate
    _asset(store, "2026-11-17", verdict="liked")  # outside (New York date)

    series = taste(store, settings, days=3, now=NOW)["like_rate"]
    assert series == [
        {"date": "2026-11-14", "reviewed": 2, "liked": 1, "like_rate": 0.5, "rolling_7d": 0.75},
        {"date": "2026-11-15", "reviewed": 0, "liked": 0, "like_rate": None, "rolling_7d": 0.75},
        {"date": "2026-11-16", "reviewed": 1, "liked": 0, "like_rate": 0.0, "rolling_7d": 0.333},
    ]


def test_no_self_score_calibration(store, settings):
    """Step 189: the agent no longer scores itself, so taste has no calibration block."""
    _asset(store, "2026-11-16", verdict="liked")
    assert set(taste(store, settings, days=3, now=NOW)) == {
        "since", "until", "like_rate", "waste", "reasons"}


def test_waste_and_reasons(store, settings):
    wasted = _asset(store, "2026-11-14", verdict="liked", status="archived",
                    best_before="2026-11-14", updated_at="2026-11-15T12:00:00Z",
                    render_ms=(60000, 30000), reasons=["weak_hook", "too_long"])
    # archived 2026-11-16 03:00 UTC = 2026-11-15 in New York: on its best_before, not after
    _asset(store, "2026-11-14", verdict="liked", status="archived", best_before="2026-11-15",
           updated_at="2026-11-16T03:00:00Z", render_ms=(60000,))
    _asset(store, "2026-11-14", verdict="liked", status="archived", best_before="2026-11-30")
    # archived early by the owner, files purged 14 days later (the default): updated_at is the purge
    _asset(store, "2026-11-14", verdict="liked", status="archived",
                   best_before="2026-11-20", updated_at="2026-12-02T12:00:00Z", file_path=None)
    _asset(store, "2026-11-14", verdict="disliked", status="archived", best_before="2026-11-01",
           reasons=["weak_hook"])
    _asset(store, "2026-11-10", reasons=["off_brand"])  # outside the window

    out = taste(store, settings, days=3, now=NOW)
    assert out["waste"] == {"count": 1, "asset_ids": [wasted], "render_minutes": 1.5}
    assert out["reasons"] == [{"code": "weak_hook", "label": "Accroche faible", "count": 2},
                              {"code": "too_long", "label": "Trop long", "count": 1}]


def test_routes(store):
    today = local_today(TZ).isoformat()
    _asset(store, today, verdict="liked", reasons=["caption"])
    with TestClient(create_app(_settings(timezone=TZ), store=store), base_url=LOCAL) as tc:
        groups = tc.get("/api/analytics/funnel?days=7&group_by=hook_type").json()["groups"]
        assert groups[0]["key"] == "question" and groups[0]["liked"] == 1
        r = tc.get("/api/analytics/funnel?group_by=nope")
        assert r.status_code == 422 and r.json()["error"] == "invalid"
        assert tc.get("/api/analytics/funnel?days=0").status_code == 422
        body = tc.get("/api/analytics/taste?days=7").json()
        assert body["like_rate"][-1] == {"date": today, "reviewed": 1, "liked": 1,
                                         "like_rate": 1.0, "rolling_7d": 1.0}
        assert body["reasons"] == [{"code": "caption", "label": "Légende", "count": 1}]
