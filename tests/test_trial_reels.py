"""Step 088: trial Reels are tagged when published and scored in their own group."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.learning import experiments as X
from src.learning.analytics import posts_table
from src.scoring import ScoringConfig, group_of, score_posts
from src.store import to_iso, utcnow
from src.studio import scheduling
from src.studio.publish import QueueRefused

from .conftest import LOCAL
from .test_api_assets import _settings
from .test_experiments import NOW, _baseline, _open, _post
from .test_studio_publish import _asset
from .test_studio_scheduling import _day


@pytest.fixture
def settings():
    return _settings(timezone="UTC")


def _snap(mid, saved, trial=False):
    return {"media_id": mid, "media_product_type": "REELS", "age_hours": 72,
            "posted_at": "2026-11-10T12:00:00+00:00", "trial": int(trial),
            "metrics": {"reach": 1000, "saved": saved}}


def test_group_of_separates_trial_reels():
    assert [group_of(s) for s in (_snap("a", 1), _snap("b", 1, trial=True))] == [
        "REELS", "TRIAL"]
    assert group_of({"media_product_type": "FEED", "trial": 1}) == "FEED"  # Reels only


def test_trial_and_normal_baselines_never_mix():
    # Followers save normal Reels far more than strangers save trial Reels: the trial
    # post is typical among trials, but against a mixed baseline it would look weak.
    normal = [_snap(f"n{i}", 20) for i in range(6)]
    trials = [_snap(f"t{i}", 6, trial=True) for i in range(3)]
    cfg = ScoringConfig(weights={"saved": 1.0}, min_reach=100)
    scored = {s["media_id"]: s for s in score_posts(normal + trials, cfg)}
    assert scored["t0"]["group"] == "TRIAL" and scored["t0"]["baseline_posts"] == 2
    assert (scored["t0"]["engagement_index"], scored["t0"]["verdict"]) == (1.0, "average")
    assert scored["n0"]["baseline_posts"] == 5 and scored["n0"]["verdict"] == "average"
    mixed = {s["media_id"]: s for s in score_posts(
        [{**s, "trial": 0} for s in normal + trials], cfg)}
    assert mixed["t0"]["verdict"] == "weak"  # what mixing would have said


def test_a_published_trial_gets_the_tag(store, settings):
    trial = store.schedule("reel", {"video_url": "https://x/v.mp4", "caption": "c",
                                    "trial_graduation": "SS_PERFORMANCE"},
                           utcnow() + timedelta(minutes=1))
    normal = store.schedule("reel", {"video_url": "https://x/w.mp4", "caption": "c"},
                            utcnow() + timedelta(minutes=1))
    store.mark_published(trial["id"], "m_trial", None)
    store.mark_published(normal["id"], "m_normal", None)
    assert (store.get_label("m_trial")["trial"], store.get_label("m_normal")["trial"]) == (1, 0)
    store.label_post("m_trial", campaign="later")  # relabelling keeps the tag
    assert store.get_label("m_trial")["trial"] == 1
    for mid in ("m_trial", "m_normal"):
        store.add_snapshot(mid, {"reach": 10}, "REELS", "VIDEO", to_iso(NOW - timedelta(days=3)))
    rows = {r["media_id"]: r["group"] for r in posts_table(store, settings)["posts"]}
    assert rows == {"m_trial": "TRIAL", "m_normal": "REELS"}
    assert [r["media_id"] for r in posts_table(store, settings, post_type="TRIAL")["posts"]] == [
        "m_trial"]


def _trial(store, mid):
    with store._tx() as c:
        c.execute("UPDATE post_labels SET trial = 1 WHERE media_id = ?", (mid,))


def test_experiments_compare_variants_within_one_group(store, settings):
    exp = _open(store, settings)
    _baseline(store)
    for i in range(3):  # question: 3 trial Reels; bold_claim: 3 normal Reels
        _post(store, f"question{i}", 60, X.label(exp["id"], "question"))
        _trial(store, f"question{i}")
        _post(store, f"bold_claim{i}", 4, X.label(exp["id"], "bold_claim"))
    ev = X.evaluate(store, settings, exp, now=NOW)
    assert ev["group"] == "REELS"  # trials are not compared with normal posts
    assert {v: p["n"] for v, p in ev["per_variant"].items()} == {"question": 0, "bold_claim": 3}
    for i in range(3, 5):  # now both variants have trial Reels: compared among trials
        _post(store, f"bold_claim{i}", 4, X.label(exp["id"], "bold_claim"))
        _trial(store, f"bold_claim{i}")
    ev = X.evaluate(store, settings, exp, now=NOW)
    assert ev["group"] == "TRIAL"
    assert {v: p["n"] for v, p in ev["per_variant"].items()} == {"question": 3, "bold_claim": 2}
    assert ev["per_variant"]["question"]["index"] > ev["per_variant"]["bold_claim"]["index"]


# --- queueing as a trial (studio side) -------------------------------------------------

H = {"Origin": LOCAL}


@pytest.fixture
def cfg(tmp_path):
    return InstagramMCPSettings(_env_file=None, database_path=":memory:",
                                media_root=str(tmp_path), timezone="UTC",
                                posting_windows="10:00-12:00", slot_jitter_minutes=0)


def _idea_is(store, asset, **fields):
    sets = ", ".join(f"{k} = ?" for k in fields)
    with store._tx() as c:
        c.execute(f"UPDATE ideas SET {sets} WHERE id = ?", (*fields.values(), asset["idea_id"]))
    return asset


def test_explore_and_experiment_videos_queue_as_trials(store, cfg):
    explore = _idea_is(store, _asset(store, cfg, status="ready"), strategy="explore")
    out = scheduling.approve_and_queue(store, cfg, explore["id"], _day(), trial="SS_PERFORMANCE")
    assert out["post"]["payload"]["trial_graduation"] == "SS_PERFORMANCE"
    exp = _idea_is(store, _asset(store, cfg), strategy="exploit", experiment="exp:1:question")
    out = scheduling.schedule_asset(store, cfg, exp["id"], _day(), trial="MANUAL")
    assert out["post"]["payload"]["trial_graduation"] == "MANUAL"
    normal = _idea_is(store, _asset(store, cfg), strategy="explore")
    out = scheduling.schedule_asset(store, cfg, normal["id"], _day(3))  # no trial asked
    assert "trial_graduation" not in out["post"]["payload"]


def test_normal_videos_are_refused_as_trials(store, cfg):
    for asset in (_idea_is(store, _asset(store, cfg, status="ready"), strategy="exploit"),
                  _idea_is(store, _asset(store, cfg, status="ready"), experiment="short hooks")):
        with pytest.raises(QueueRefused) as e:
            scheduling.approve_and_queue(store, cfg, asset["id"], _day(), trial="MANUAL")
        assert e.value.code == "trial" and "explore or experiment" in str(e.value)
        assert store.get_asset(asset["id"])["status"] == "ready"  # nothing happened
        assert scheduling.trial_problem(store, asset["id"])
    assert store.list_scheduled() == []


def test_trial_routes(store, cfg):
    with TestClient(create_app(cfg, store=store), base_url=LOCAL) as tc:
        a = _idea_is(store, _asset(store, cfg, status="ready"), strategy="explore")
        r = tc.post(f"/api/assets/{a['id']}/approve-and-queue", json={"trial": "SS_PERFORMANCE"},
                    headers=H)
        assert r.status_code == 200, r.text
        assert store.list_scheduled()[0]["payload"]["trial_graduation"] == "SS_PERFORMANCE"
        b = _asset(store, cfg)  # not explore
        r = tc.post(f"/api/assets/{b['id']}/schedule",
                    json={"publish_at": to_iso(_day()), "trial": "MANUAL"}, headers=H)
        assert r.status_code == 409 and r.json()["error"] == "trial"
        r = tc.post(f"/api/assets/{b['id']}/schedule",
                    json={"publish_at": to_iso(_day()), "trial": "SOMETIMES"}, headers=H)
        assert r.status_code == 422


def test_proposed_slot_says_whether_a_trial_is_possible(store, cfg):
    explore = _idea_is(store, _asset(store, cfg), strategy="explore")
    normal = _idea_is(store, _asset(store, cfg), strategy="exploit")
    assert scheduling.propose_slot(store, cfg, explore["id"], _day())["trial_eligible"] is True
    assert scheduling.propose_slot(store, cfg, normal["id"], _day())["trial_eligible"] is False


async def test_a_trial_published_from_the_mcp_tool_is_tagged(store, monkeypatch):
    import src.instagram_mcp_server as srv

    class Client:
        async def publish_reel(self, *args, **kw):
            return {"media_id": "m_mcp"}

    monkeypatch.setattr(srv, "store", lambda: store)
    monkeypatch.setattr(srv, "client", lambda: Client())
    res = await srv.publish_reel("https://cdn/x.mp4", "hi", trial_graduation="MANUAL")
    assert res["trial"] == "MANUAL" and store.get_label("m_mcp")["trial"] == 1
