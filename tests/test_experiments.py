"""Step 086: experiments (src/learning/experiments.py), their store table, create_idea rule,
brief, facts section, worker job, MCP tools and API."""

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import src.instagram_mcp_server as srv
from src import worker
from src.api.app import create_app
from src.learning import brief, report
from src.learning import experiments as X
from src.learning.facts import daily_facts
from src.store import MIGRATIONS, CampaignStore, to_iso
from src.studio import production
from src.studio.assets import set_verdict, transition

from .conftest import LOCAL
from .test_api_assets import _settings
from .test_worker_data_jobs import FakeClient

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
HOOKS = ["question", "bold_claim"]


@pytest.fixture
def settings():
    return _settings(timezone="UTC")


def _open(store, settings, variable="hook_type", variants=HOOKS, **kw):
    return X.open_experiment(store, settings, f"{variable} test", variable, variants,
                             now=NOW, **kw)


def _post(store, mid, saved, experiment=None, age=72):
    """A Reel (one snapshot `age` h after posting, 72: matured) made from an idea of
    `experiment`."""
    idea = store.add_idea("motion", hook_type="question", experiment=experiment)
    asset = store.add_asset(idea["id"], recipe={"kind": "motion", "template": "FactQuest"})
    store.label_post(mid, asset_id=asset["id"])
    posted = NOW - timedelta(days=5, hours=len(mid))
    store.add_snapshot(mid, {"reach": 1000, "views": 2000, "saved": saved, "likes": 50,
                             "shares": saved // 2}, "REELS", "VIDEO", to_iso(posted),
                       captured_at=posted + timedelta(hours=age))


def _variant_posts(store, exp, saved, n=5):
    for v, s in zip(exp["variants"], saved):
        for i in range(n):
            _post(store, f"{v}{i}", s, X.label(exp["id"], v))


def _baseline(store, n=10):
    for i in range(n):
        _post(store, f"base{i}", 20)


def test_migration_adds_the_table(tmp_path):
    path = tmp_path / "db.sqlite"
    CampaignStore(path).close()
    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(experiments)")}
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    with pytest.raises(sqlite3.IntegrityError):  # the status CHECK
        conn.execute("INSERT INTO experiments (hypothesis, variable, variants, status,"
                     " created_at, updated_at) VALUES ('h', 'v', '[]', 'nope', 'x', 'x')")
    conn.close()
    assert {"hypothesis", "variable", "variants", "target_per_variant", "ends_on", "status",
            "result", "learning_id", "report_date", "opened_at"} <= cols


def test_open_sets_the_end_and_the_cap_refuses_a_third(store, settings):
    row = _open(store, settings, target_per_variant=3)
    assert (row["status"], row["variants"], row["target_per_variant"]) == ("open", HOOKS, 3)
    assert row["ends_on"] == "2026-12-01" and row["opened_at"]
    _open(store, settings, "pillar", ["stories", "myths"])
    with pytest.raises(ValueError, match="2 experiments are open already"):
        _open(store, settings, "hour", ["9", "18"])
    assert [r["status"] for r in store.list_experiments()] == ["open", "open"]
    settings.max_open_experiments = 3
    assert _open(store, settings, "hour", ["09", "18"])["variants"] == ["9", "18"]


@pytest.mark.parametrize("variable, variants, match", [
    ("posting hour", ["9", "18"], "tag dimension"),
    ("length", ["short", "long"], "tag dimension"),
    ("hook_type", ["question"], "2-4 variants"),
    ("hook_type", ["question", "question"], "differ"),
    ("hook_type", ["question", "nope"], "nope"),
    ("hour", ["9", "25"], "0-23"),
])
def test_a_non_tag_variable_or_value_is_refused(store, settings, variable, variants, match):
    with pytest.raises(ValueError, match=match):
        _open(store, settings, variable, variants)
    assert store.list_experiments() == []


def test_proposals_from_a_report_replace_the_days_earlier_ones(store, settings):
    store.save_daily_report(date(2026, 11, 16), None, {"yesterday": {}})
    good = {"hypothesis": "Questions keep viewers", "variable": "hook_type", "variants": HOOKS}
    bad = {"hypothesis": "Shorter is better", "variable": "length", "variants": ["15", "30"]}
    row = report.save_daily_report(store, settings, "2026-11-16", "ok",
                                   experiments=[good, bad], now=NOW)
    (proposed,), (skipped,) = (row["experiment_proposals"][k] for k in ("proposed", "skipped"))
    assert (proposed["status"], proposed["report_date"]) == ("proposed", "2026-11-16")
    assert skipped["variable"] == "length" and "tag dimension" in skipped["error"]
    report.save_daily_report(store, settings, "2026-11-16", "v2", experiments=[good], now=NOW)
    (again,) = store.list_experiments()
    opened = X.open_experiment(store, settings, proposed_id=again["id"], now=NOW)
    assert (opened["id"], opened["status"], opened["variants"]) == (again["id"], "open", HOOKS)
    with pytest.raises(ValueError, match="open, not proposed"):
        X.open_experiment(store, settings, proposed_id=again["id"], now=NOW)
    report.save_daily_report(store, settings, "2026-11-16", "v3", now=NOW)
    assert [r["status"] for r in store.list_experiments()] == ["open"]  # an opened one stays


def test_explore_plan_fills_the_furthest_variant_round_robin(store, settings):
    exp = _open(store, settings, target_per_variant=2)
    store.add_idea("motion", experiment=X.label(exp["id"], "question"))  # on its way: counts
    dead = store.add_idea("motion", experiment=X.label(exp["id"], "bold_claim"))
    a = store.add_asset(dead["id"])
    transition(store, a["id"], "ready", actor="worker")
    set_verdict(store, a["id"], "disliked")  # never posted: does not count
    store.add_idea("motion", experiment="short hooks")  # free text: no experiment
    plan = X.explore_plan(store, 10)
    assert [p["variant"] for p in plan] == ["bold_claim", "question", "bold_claim"]
    assert plan[0] == {"experiment_id": exp["id"], "variant": "bold_claim",
                       "experiment": f"exp:{exp['id']}:bold_claim"}
    assert X.explore_plan(store, 1) == plan[:1] and X.explore_plan(store, 0) == []
    b = brief.creative_brief(store, settings, NOW)
    assert b["explore_plan"] == X.explore_plan(store, 3)  # 3 explore ideas left today
    assert [e["id"] for e in b["experiments"]] == [exp["id"]]


def test_create_idea_validates_the_experiment(store, settings):
    exp = _open(store, settings)
    tracks = _open(store, settings, "track", ["motion", "remix"])
    proposed = store.add_experiment("h", "pillar", ["stories", "myths"])

    def make(experiment, track="motion", **kw):
        return production.create_idea(store, settings, track, hook=f"hook {experiment} {kw}",
                                      experiment=experiment, **kw)

    for value, match in [("short hooks", "exp:<id>:<variant>"), ("exp:99:question", "no exp"),
                         (f"exp:{proposed['id']}:stories", "proposed, not open"),
                         (f"exp:{exp['id']}:pov", "one of question, bold_claim"),
                         (f"exp:{tracks['id']}:remix", "needs track=remix")]:
        with pytest.raises(ValueError, match=match):
            make(value)
    with pytest.raises(ValueError, match="needs hook_type=question"):
        make(f"exp:{exp['id']}:question", hook_type="pov")
    assert store.list_ideas(limit=100) == []
    idea = make(f"exp:{exp['id']}:question")  # the variant's tag is filled in
    assert (idea["hook_type"], idea["strategy"]) == ("question", "explore")
    assert make(f"exp:{exp['id']}:bold_claim", hook_type="bold_claim")["experiment"] == (
        f"exp:{exp['id']}:bold_claim")


def test_evaluate_counts_matured_reels_per_variant(store, settings):
    exp = _open(store, settings, target_per_variant=5)
    _baseline(store)
    _variant_posts(store, exp, (60, 4), n=4)
    ev = X.evaluate(store, settings, exp, now=NOW)
    q, b = ev["per_variant"]["question"], ev["per_variant"]["bold_claim"]
    assert (q["n"], b["n"]) == (4, 4) and q["index"] > 1.15 > 0.85 > b["index"]
    assert (ev["done"], ev["why"]) == (False, None)
    _post(store, "young", 60, X.label(exp["id"], "question"), age=3)  # not matured
    _post(store, "question4", 60, X.label(exp["id"], "question"))
    _post(store, "bold_claim4", 4, X.label(exp["id"], "bold_claim"))
    ev = X.evaluate(store, settings, exp, now=NOW)
    assert ev["per_variant"]["question"]["n"] == 5 and ev["why"] == "target reached"
    late = X.evaluate(store, settings, {**exp, "target_per_variant": 50},
                      now=NOW + timedelta(days=15))
    assert late["why"] == "ended 2026-12-01" and late["done"]


@pytest.mark.parametrize("saved, n, kind, value, confidence", [
    ((60, 18), 5, "do", "question", "medium"),        # the best is far above typical
    ((22, 2), 5, "dont", "bold_claim", "medium"),     # the worst is far below
    ((20, 21), 5, "hypothesis", None, "low"),         # no clear difference
])
def test_finish_writes_the_result_and_its_learning(store, settings, saved, n, kind, value,
                                                   confidence):
    exp = _open(store, settings)
    _baseline(store)
    _variant_posts(store, exp, saved, n=n)
    ev = X.evaluate(store, settings, exp, now=NOW)
    done = X.finish(store, settings, exp, ev)
    learning = store.get_learning(done["learning_id"])
    assert done["status"] == "finished" and done["result"]["kind"] == kind
    assert (learning["kind"], learning["origin"], learning["confidence"]) == (
        kind, "audience", confidence)
    assert learning["scope"]["tag"] == "hook_type"
    if value:
        assert learning["scope"]["value"] == value
    assert learning["evidence"] == [{"kind": "experiment", "id": exp["id"],
                                     "per_variant": ev["per_variant"]}]
    assert f"experiment {exp['id']}" in learning["statement"]


@pytest.mark.parametrize("n", [0, 2])  # nothing posted / a big gap but n under medium
def test_finish_without_enough_data_writes_no_learning(store, settings, n):
    exp = _open(store, settings)
    _baseline(store)
    _variant_posts(store, exp, (60, 2), n=n)
    done = X.finish(store, settings, exp, X.evaluate(store, settings, exp, now=NOW))
    assert done["status"] == "finished" and done["learning_id"] is None
    assert done["result"]["kind"] == "not_enough_data" and store.list_learnings() == []


def test_a_gap_from_noise_is_no_rule():
    loud = [0.5, 3.0, 0.6, 2.8, 0.7]  # medians 0.7 vs 1.4, but the posts overlap
    assert X.p_value([[0.6, 3.0, 0.7, 2.8, 1.4], loud]) > X.P_MAX
    assert X.p_value([[2.0] * 5, [0.5] * 5]) < X.P_MAX  # cleanly apart: 2 of 252 labellings


def test_template_experiment_counts_the_template_really_used(store, settings):
    exp = _open(store, settings, "template", ["FactQuest", "PixelCinema"])
    _baseline(store)
    _post(store, "a", 60, X.label(exp["id"], "PixelCinema"))  # labelled Pixel, made FactQuest
    per = X.evaluate(store, settings, exp, now=NOW)["per_variant"]
    assert (per["FactQuest"]["n"], per["PixelCinema"]["n"]) == (1, 0)


async def test_worker_checks_experiments_once_a_day(store, settings):
    exp = _open(store, settings)
    _baseline(store)
    _variant_posts(store, exp, (60, 18))
    runs = [await worker.data_jobs(FakeClient(), store, settings, now=lambda t=t: t)
            for t in (NOW, NOW + timedelta(hours=1), NOW + timedelta(days=1))]
    assert runs[0]["experiments_day"] == {"evaluated": 1, "finished": [exp["id"]]}
    assert "experiments_day" not in runs[1]
    assert runs[2]["experiments_day"] == {"evaluated": 0, "finished": []}
    assert store.get_experiment(exp["id"])["status"] == "finished"


def _batch(store, day, experiment=None, approved=False):
    idea = store.add_idea("motion", batch_date=day, experiment=experiment)
    a = store.add_asset(idea["id"], batch_date=day)
    if approved:
        with store._tx() as c:
            c.execute("UPDATE assets SET approved_at = ? WHERE id = ?", (day, a["id"]))


async def test_facts_list_progress_and_warn_without_approved_videos(store, settings):
    opened = _open(store, settings)
    quiet = _open(store, settings, "pillar", ["stories", "myths"])
    with store._tx() as c:  # both were open before the last 3 batch days
        c.execute("UPDATE experiments SET opened_at = '2026-11-10T09:00:00+00:00'")
    for day in ("2026-11-14", "2026-11-15", "2026-11-16"):
        _batch(store, day, X.label(opened["id"], "question"), approved=day == "2026-11-15")
        _batch(store, day, X.label(quiet["id"], "stories"))
    _batch(store, "2026-11-17")  # today: not a day of the report
    f = await daily_facts(store, settings, now=NOW)
    section = f["experiments"]
    assert [e["id"] for e in section["open"]] == [opened["id"], quiet["id"]]
    assert section["open"][0]["progress"] == {"question": {"n": 0, "index": None},
                                              "bold_claim": {"n": 0, "index": None}}
    assert section["warnings"] == [{
        "experiment_id": quiet["id"],
        "warning": "no approved video in the last 3 batch days (2026-11-14 to 2026-11-16)"}]
    with store._tx() as c:  # opened inside the window: too early to warn
        c.execute("UPDATE experiments SET opened_at = '2026-11-15T09:00:00+00:00'")
    assert (await daily_facts(store, settings, now=NOW))["experiments"]["warnings"] == []


async def test_mcp_tools_and_api(store, settings, monkeypatch):
    monkeypatch.setattr(srv, "store", lambda: store)
    monkeypatch.setattr(srv, "get_settings", lambda: settings)
    row = await srv.open_experiment("Questions keep viewers", "hook_type", HOOKS,
                                    target_per_variant=4)
    assert row["status"] == "open" and row["target_per_variant"] == 4
    with pytest.raises(srv.ToolError, match="tag dimension"):
        await srv.open_experiment("h", "length", ["a", "b"])
    listed = await srv.list_experiments(status="open")
    assert [e["id"] for e in listed["experiments"]] == [row["id"]]
    with pytest.raises(srv.ToolError, match="status must be one of"):
        await srv.list_experiments(status="running")
    with TestClient(create_app(settings, store=store), base_url=LOCAL) as tc:
        assert tc.get("/api/experiments").json()["experiments"][0]["id"] == row["id"]
        assert tc.get("/api/experiments?status=finished").json() == {"experiments": []}
        assert tc.get("/api/experiments?status=nope").status_code == 422
