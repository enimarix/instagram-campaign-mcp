"""Learning-loop tables: feedback, learnings, daily_reports, agent_runs."""

import sqlite3
from datetime import date

import pytest

from src.store import MIGRATIONS, SCHEMA, STUDIO_SCHEMA, CampaignStore
from src.taxonomy import TaxonomyError


@pytest.fixture
def asset(store):
    return store.add_asset(store.add_idea("motion")["id"])


def test_migration_2_database_upgrades_to_3_keeping_data(tmp_path):
    db = str(tmp_path / "v2.db")
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA + STUDIO_SCHEMA)
    now = "2026-01-01T00:00:00+00:00"
    conn.execute("INSERT INTO ideas (track, batch_date, created_at) VALUES ('motion', ?, ?)",
                 ("2026-01-01", now))
    conn.execute("INSERT INTO assets (idea_id, batch_date, created_at, updated_at)"
                 " VALUES (1, '2026-01-01', ?, ?)", (now, now))
    conn.execute("PRAGMA user_version=2")
    conn.commit()
    conn.close()
    s = CampaignStore(db)
    try:
        assert s.get_asset(1)["batch_date"] == "2026-01-01"
        assert s.add_feedback(1, text="nice")["asset_id"] == 1
    finally:
        s.close()
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    conn.close()


def test_feedback_crud(store, asset):
    fb = store.add_feedback(asset["id"], text="hook too slow", reason_codes=["too_slow"],
                            video_time_s=2.5, wants_changes=True)
    assert (fb["reason_codes"], fb["video_time_s"], fb["wants_changes"]) == (["too_slow"], 2.5, 1)
    assert fb["digested_at"] is None and fb["created_at"] == fb["updated_at"]
    assert store.get_feedback(fb["id"]) == fb
    other = store.add_feedback(asset["id"], reason_codes=["weak_hook"])
    assert [f["id"] for f in store.list_feedback(asset_id=asset["id"])] == [fb["id"], other["id"]]

    out = store.update_feedback(fb["id"], text="ok now", reason_codes=[], wants_changes=False)
    assert (out["text"], out["reason_codes"], out["wants_changes"]) == ("ok now", [], 0)
    with pytest.raises(TypeError):
        store.update_feedback(fb["id"], asset_id=2)
    store.delete_feedback(fb["id"])
    with pytest.raises(KeyError, match="No feedback"):
        store.get_feedback(fb["id"])
    with pytest.raises(KeyError):
        store.delete_feedback(fb["id"])


def test_feedback_needs_text_or_reason(store, asset):
    with pytest.raises(ValueError, match="text or at least one reason"):
        store.add_feedback(asset["id"], text="  ")
    fb = store.add_feedback(asset["id"], text="meh")
    with pytest.raises(ValueError, match="text or at least one reason"):
        store.update_feedback(fb["id"], text=None)


def test_unknown_reason_code_is_rejected_with_valid_list(store, asset):
    with pytest.raises(TaxonomyError, match="'boring'.*valid: weak_hook"):
        store.add_feedback(asset["id"], reason_codes=["too_slow", "boring"])
    fb = store.add_feedback(asset["id"], text="x")
    with pytest.raises(TaxonomyError, match="valid:"):
        store.update_feedback(fb["id"], reason_codes=["boring"])


def test_feedback_for_missing_asset_violates_foreign_key(store):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.add_feedback(12345, text="hi")


def test_feedback_negative_video_time_is_rejected(store, asset):
    with pytest.raises(sqlite3.IntegrityError):
        store.add_feedback(asset["id"], text="x", video_time_s=-1)


def test_undigested_filter_and_mark_digested(store, asset):
    a, b, c = (store.add_feedback(asset["id"], text=t)["id"] for t in "abc")
    assert [f["id"] for f in store.list_feedback(undigested=True)] == [a, b, c]
    assert store.mark_feedback_digested([a, b]) == 2
    assert store.mark_feedback_digested([a]) == 0  # already digested: stamp kept
    assert store.mark_feedback_digested([]) == 0
    assert [f["id"] for f in store.list_feedback(undigested=True)] == [c]
    assert [f["id"] for f in store.list_feedback(undigested=False)] == [a, b]
    assert store.get_feedback(a)["digested_at"]
    store.update_feedback(a, text="edited")  # an edit needs a fresh read
    assert [f["id"] for f in store.list_feedback(undigested=True)] == [a, c]


def test_learning_crud_and_defaults(store):
    ln = store.add_learning("Open on the punchline", "do", "taste",
                            evidence=[{"asset_id": 1}], scope={"template": "FactQuest"})
    assert (ln["confidence"], ln["status"]) == ("low", "active")
    assert (ln["evidence"], ln["scope"]) == ([{"asset_id": 1}], {"template": "FactQuest"})
    assert store.add_learning("x", "hypothesis", "audience")["scope"] == {}
    out = store.update_learning(ln["id"], status="retired", confidence="high")
    assert (out["status"], out["confidence"]) == ("retired", "high")
    assert store.get_learning(ln["id"]) == out
    with pytest.raises(KeyError, match="No learning"):
        store.update_learning(999, status="retired")


@pytest.mark.parametrize("field,value", [
    ("kind", "maybe"), ("confidence", "certain"), ("status", "paused"), ("origin", "gut"),
])
def test_learning_check_constraints(store, field, value):
    args = {"statement": "s", "kind": "do", "origin": "taste", field: value}
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.add_learning(**args)
    ln = store.add_learning("s", "do", "taste")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.update_learning(ln["id"], **{field: value})


def test_learnings_ordered_by_confidence_then_newest(store):
    ids = {}
    for name, conf in [("low1", "low"), ("high1", "high"), ("owner1", "owner"),
                       ("med1", "medium"), ("high2", "high"), ("low2", "low")]:
        ids[name] = store.add_learning(name, "do", "taste", confidence=conf)["id"]
    store.add_learning("old", "dont", "audience", status="retired")
    got = [r["statement"] for r in store.list_learnings(status="active")]
    assert got == ["owner1", "high2", "high1", "med1", "low2", "low1"]
    assert [r["statement"] for r in store.list_learnings(kind="dont")] == ["old"]
    assert [r["statement"] for r in store.list_learnings(origin="audience")] == ["old"]


def test_daily_report_upsert_and_latest(store):
    assert store.latest_daily_report() is None
    assert store.get_daily_report(date(2026, 11, 16)) is None
    first = store.save_daily_report(date(2026, 11, 16), "v1", {"posts": 3})
    store.save_daily_report(date(2026, 11, 17), "next day", {})
    again = store.save_daily_report(date(2026, 11, 16), "v2", {"posts": 4})
    assert again["id"] == first["id"]
    assert (again["summary"], again["facts"]) == ("v2", {"posts": 4})
    assert store.get_daily_report("2026-11-16") == again
    assert store.latest_daily_report()["summary"] == "next day"
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.save_daily_report("17/11/2026", "bad", {})


def test_agent_runs_lifecycle(store):
    run = store.start_agent_run("produce")
    assert (run["status"], run["finished_at"]) == ("running", None) and run["started_at"]
    assert store.running_agent_run("produce")["id"] == run["id"]
    assert store.running_agent_run("learn") is None
    done = store.finish_agent_run(run["id"], "succeeded", summary="8 videos",
                                  usage={"tokens": 1200, "cost_usd": 0.4}, log_path="logs/1.log")
    assert (done["status"], done["usage"], done["log_path"]) == (
        "succeeded", {"tokens": 1200, "cost_usd": 0.4}, "logs/1.log")
    assert done["finished_at"]
    assert store.running_agent_run("produce") is None
    with pytest.raises(ValueError, match="already finished"):
        store.finish_agent_run(run["id"], "failed")
    with pytest.raises(ValueError, match="finishes as"):
        store.finish_agent_run(store.start_agent_run("learn")["id"], "running")
    with pytest.raises(KeyError):
        store.finish_agent_run(999, "failed")
    second = store.start_agent_run("produce")
    assert [r["id"] for r in store.list_agent_runs("produce")] == [second["id"], run["id"]]
    assert len(store.list_agent_runs(limit=1)) == 1


def test_agent_run_status_check(store):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store._insert("agent_runs", ("playbook", "status"), {"playbook": "p", "status": "odd"})
