"""Step 111: retention diagnosis (src/learning/retention.py), facts and post detail wiring."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.learning.facts import daily_facts
from src.learning.retention import diagnose, retention_all, retention_for
from src.store import to_iso

from .conftest import LOCAL
from .test_api_assets import _settings

TIMELINE = [
    {"t": 0, "d": 2.5, "e": "hook card: 'POV: you skip breakfast'"},
    {"t": 0.5, "d": 2, "e": "sfx: coin"},
    {"t": 2.5, "d": 6, "e": "fact 1: protein"},
    {"t": 8.5, "d": 6, "e": "fact 2: fibre"},
    {"t": 14.5, "d": 6, "e": "fact 3: water"},
    {"t": 20.5, "d": 4, "e": "outro: follow for more"},
]
DURATION = 24.5


def _base(skip=30.0, ratio=0.5, ss=0.02, n=8):
    return {"reels_skip_rate": {"median": skip, "n": n}, "watch_ratio": {"median": ratio, "n": n},
            "share_save_rate": {"median": ss, "n": n}}


def _metrics(skip=30.0, watch_s=12.25, shares=10, saved=10, reach=1000):
    return {"reels_skip_rate": skip, "ig_reels_avg_watch_time": watch_s * 1000,
            "shares": shares, "saved": saved, "reach": reach}


def _kinds(findings):
    return [f["kind"] for f in findings]


def test_hook_problem_quotes_the_first_3_seconds():
    (hook, exit_) = diagnose(TIMELINE, DURATION, _metrics(skip=55), _base())
    assert hook["kind"] == "hook" and hook["at_s"] == 0 and hook["confidence"] == "medium"
    assert hook["evidence"] == {"reels_skip_rate": 55, "baseline_median": 30, "n": 8}
    assert "POV: you skip breakfast" in hook["text"] and "sfx: coin" in hook["text"]
    assert "fact 1" in hook["event"] and "fact 2" not in hook["event"]  # starts at 2.5 s
    assert exit_["kind"] == "exit"


def test_exit_at_15_s_names_the_event_playing_then():
    exit_ = next(f for f in diagnose(TIMELINE, DURATION, _metrics(watch_s=15.2), _base(ratio=.62))
                 if f["kind"] == "exit")
    assert exit_["at_s"] == 15.2 and exit_["event"] == "fact 3: water"
    assert "0:15" in exit_["text"] and "fact 3: water" in exit_["text"]
    assert exit_["confidence"] == "low" and "average" in exit_["text"]
    assert exit_["evidence"]["avg_watch_s"] == 15.2 and exit_["evidence"]["n"] == 8
    # watched to the end (loops): no exit
    assert "exit" not in _kinds(diagnose(TIMELINE, DURATION, _metrics(watch_s=30), _base()))


def test_payoff_problem():
    findings = diagnose(TIMELINE, DURATION, _metrics(watch_s=13, shares=2, saved=3), _base())
    payoff = next(f for f in findings if f["kind"] == "payoff")
    assert payoff["evidence"]["share_save_rate"] == 0.005
    assert payoff["evidence"]["baseline_median"] == 0.02
    assert payoff["event"] == "outro: follow for more" and "payoff problem" in payoff["text"]
    # same watch ratio, normal shares/saves: no payoff problem
    assert "payoff" not in _kinds(diagnose(TIMELINE, DURATION, _metrics(watch_s=13), _base()))


def test_strong_hook_and_watch_ratio():
    findings = diagnose(TIMELINE, DURATION, _metrics(skip=15, watch_s=20), _base())
    strong = [f for f in findings if f["kind"] == "strong"]
    assert {next(iter(f["evidence"])) for f in strong} == {"reels_skip_rate", "watch_ratio"}
    assert all("POV: you skip breakfast" in f["text"] for f in strong)
    assert "hook" not in _kinds(findings)


def test_no_timeline_gives_metrics_only_findings():
    findings = diagnose(None, None, _metrics(skip=55, watch_s=4), _base())
    assert _kinds(findings) == ["hook", "exit"]
    assert all("event" not in f for f in findings)
    assert "0:04" in findings[1]["text"] and findings[1]["evidence"]["n"] == 0


def test_missing_metrics_or_baseline_give_no_finding():
    assert diagnose(TIMELINE, DURATION, {}, _base()) == []
    assert diagnose(TIMELINE, DURATION, {"reach": 1000}, _base()) == []
    empty = {k: {"median": None, "n": 0} for k in _base()}
    assert _kinds(diagnose(TIMELINE, DURATION, _metrics(skip=90, shares=0, saved=0),
                           empty)) == ["exit"]  # the exit second needs no baseline


def test_small_baseline_is_low_confidence():
    (hook, _) = diagnose(TIMELINE, DURATION, _metrics(skip=55), _base(n=2))
    assert hook["confidence"] == "low"


# --- service, facts and post detail ---------------------------------------------------

NOW = datetime(2026, 11, 17, 3, tzinfo=timezone.utc)


def _reel(store, mid, posted, *, skip=30.0, watch_s=12.0, age=50.0, kind="REELS",
          timeline=None):
    store.add_snapshot(mid, _metrics(skip=skip, watch_s=watch_s), kind, "VIDEO", to_iso(posted),
                       permalink=f"https://ig/{mid}", captured_at=posted + timedelta(hours=age))
    if timeline:
        idea = store.add_idea("motion")
        asset = store.add_asset(idea["id"], recipe={"kind": "motion", "template": "FactQuest"},
                                duration=DURATION, timeline=timeline)
        store.label_post(mid, asset_id=asset["id"])


def _seed(store):
    for i in range(6):
        _reel(store, f"b{i}", datetime(2026, 11, 1, 12, tzinfo=timezone.utc))
    _reel(store, "ours", datetime(2026, 11, 13, 14, tzinfo=timezone.utc), skip=60,
          watch_s=15.2, timeline=TIMELINE)
    _reel(store, "feed", datetime(2026, 11, 13, 15, tzinfo=timezone.utc), kind="FEED")
    _reel(store, "young", datetime(2026, 11, 16, 20, tzinfo=timezone.utc), age=3, skip=90)


def test_retention_for_and_all(store):
    _seed(store)
    s = _settings(timezone="America/New_York")
    findings = retention_for(store, s, "ours")
    hook = findings[0]
    assert hook["kind"] == "hook" and hook["evidence"]["n"] == 6
    assert hook["evidence"]["baseline_median"] == 30
    assert any(f.get("event") == "fact 3: water" for f in findings)
    assert retention_for(store, s, "feed") == [] and retention_for(store, s, "young") == []
    assert retention_for(store, s, "nope") == []
    since = datetime(2026, 11, 15, tzinfo=timezone.utc)
    assert set(retention_all(store, s, since=since, until=NOW)) == {"ours"}


async def test_facts_and_post_detail_carry_retention(store):
    _seed(store)
    s = _settings(timezone="America/New_York")
    f = await daily_facts(store, s, now=NOW)
    rows = {p["media_id"]: p for p in f["last_7_days"]["matured"]["posts"]}
    assert _kinds(rows["ours"]["retention"])[0] == "hook" and rows["feed"]["retention"] == []
    with TestClient(create_app(s, store=store), base_url=LOCAL) as tc:
        body = tc.get("/api/analytics/posts/ours").json()
    assert body["retention"] == retention_for(store, s, "ours")
