"""Step 088: trial Reels are tagged when published and scored in their own group."""

from datetime import timedelta

import pytest

from src.learning import experiments as X
from src.learning.analytics import posts_table
from src.scoring import ScoringConfig, group_of, score_posts
from src.store import to_iso, utcnow

from .test_api_assets import _settings
from .test_experiments import NOW, _baseline, _open, _post


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
