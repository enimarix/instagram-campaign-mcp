"""Step 081: the evidence engine (src/learning/evidence.py), its worker job and CLI."""

from datetime import datetime, timedelta, timezone

import pytest

from src import scheduler, worker
from src.learning import learnings as L
from src.learning.evidence import evaluate_learning, refresh_learnings

from .test_api_assets import _settings
from .test_breakdowns import _post
from .test_worker_data_jobs import FakeClient

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
Q = {"tag": "hook_type", "value": "question"}
B = {"tag": "hook_type", "value": "bold_claim"}


@pytest.fixture
def settings():
    return _settings(timezone="UTC")


@pytest.fixture
def seeded(store):
    """6 strong `question` Reels and 6 weak `bold_claim` ones, plus 2 QuizChest."""
    day = NOW - timedelta(days=5)
    for i in range(6):
        _post(store, f"q{i}", day - timedelta(hours=i), saved=40,
              studio=("motion", "question", "FactQuest", 20))
        _post(store, f"b{i}", day - timedelta(hours=i, minutes=30), saved=4,
              studio=("motion", "bold_claim", "BossBattle", 20))
    for i in range(2):
        _post(store, f"z{i}", day - timedelta(days=1, hours=i), saved=20,
              studio=("motion", "pov", "QuizChest", 20))
    return store


def _add(store, kind, scope, origin="audience", confidence="medium", **kw):
    return L.add_learning(store, f"{kind} {scope}", kind, origin, scope=scope,
                          confidence=confidence, actor="owner", **kw)["learning"]


def _eval(store, settings, row):
    return evaluate_learning(store, settings, store.get_learning(row["id"]), now=NOW)


def _items(row, kind):
    return [e for e in row["evidence"] if e.get("kind") == kind]


def test_do_confirmed_medium_then_high(seeded, settings):
    row = _eval(seeded, settings, _add(seeded, "do", Q, confidence="low"))
    (item,) = _items(row, "audience_index")
    assert item["n"] == 6 and item["index"] > 1.15 and item["verdict"] == "supports"
    assert row["confidence"] == "medium" and row["status"] == "active"
    high = _settings(timezone="UTC", evidence_min_n_high=6)
    assert _eval(seeded, high, row)["confidence"] == "high"


def test_dont_confirmed(seeded, settings):
    row = _eval(seeded, settings, _add(seeded, "dont", B, confidence="low"))
    assert row["confidence"] == "medium" and _items(row, "audience_index")[0]["index"] < 0.85


def test_not_enough_n_is_low_with_a_note(seeded, settings):
    row = _eval(seeded, settings, _add(seeded, "do", {"tag": "template", "value": "QuizChest"}))
    (item,) = _items(row, "audience_index")
    assert item["n"] == 2 and item["verdict"] == "needs_n" and item["note"] == "needs n ≥ 5"
    assert row["confidence"] == "low" and row["status"] == "active"


def test_contradicted_is_flagged_kept_and_restored(seeded, settings):
    row = _add(seeded, "do", B)
    out = refresh_learnings(seeded, settings, NOW)
    assert out["contradicted"] == [row["id"]]
    kept = seeded.get_learning(row["id"])
    assert kept["status"] == "contradicted" and kept["confidence"] == "medium"
    seeded.update_learning(row["id"], scope=Q)  # the numbers now agree
    assert _eval(seeded, settings, row)["status"] == "active"


def test_owner_confidence_and_status_untouched(seeded, settings):
    row = _eval(seeded, settings, _add(seeded, "do", B, confidence="owner"))
    assert row["confidence"] == "owner" and row["status"] == "active"
    assert _items(row, "audience_index")[0]["verdict"] == "contradicts"


def test_evidence_item_replaced_not_duplicated(seeded, settings):
    row = _add(seeded, "do", Q, evidence=[{"source": "manual"}])
    _eval(seeded, settings, row)
    row = _eval(seeded, settings, row)
    assert len(_items(row, "audience_index")) == 1 and {"source": "manual"} in row["evidence"]


def test_taste_vs_audience_conflict_marks_both(seeded, settings):
    taste = _add(seeded, "do", B, origin="taste")
    audience = _add(seeded, "dont", B)
    plain = _add(seeded, "do", {"pillar": "myths"})  # no predicate: left alone
    out = refresh_learnings(seeded, settings, NOW)
    t, a = seeded.get_learning(taste["id"]), seeded.get_learning(audience["id"])
    assert {c["with"] for c in _items(t, "conflict")} == {None, audience["id"]}
    assert [c["with"] for c in _items(a, "conflict")] == [taste["id"]]
    assert t["status"] == a["status"] == "active" and t["confidence"] == "medium"
    assert out["conflicts"] == sorted([taste["id"], audience["id"]]) and out["evaluated"] == 2
    assert seeded.get_learning(plain["id"])["evidence"] == []
    refresh_learnings(seeded, settings, NOW)  # recomputed, not grown
    assert len(_items(seeded.get_learning(taste["id"]), "conflict")) == 2


@pytest.mark.parametrize("scope, match", [
    ({"tag": "colour", "value": "red"}, "tag must be one of"),
    ({"tag": "hook_type", "value": "shouting"}, "unknown hook_types"),
    ({"tag": "hook_type"}, "needs a value"),
    ({"tag": "hour", "value": 25}, "hour"),
    ({"tag": "duration", "value": "2 min"}, "duration"),
])
def test_invalid_predicate_refused_at_add_time(store, scope, match):
    with pytest.raises(ValueError, match=match):
        _add(store, "do", scope)
    assert store.list_learnings() == []


def test_update_learning_re_evaluates_after_a_kind_change(seeded, settings):
    # the agent's edits: an owner edit would make it the owner's rule (084), left alone
    row = _add(seeded, "do", Q, confidence="low", evidence=[{"note": "a"}, {"note": "b"}])
    row = L.update_learning(seeded, row["id"], kind="dont", settings=settings, now=NOW)
    assert row["status"] == "contradicted" and len(_items(row, "audience_index")) == 1
    row = L.update_learning(seeded, row["id"], scope=B, settings=settings, now=NOW)
    assert row["status"] == "active" and row["confidence"] == "medium"
    with pytest.raises(ValueError):
        L.update_learning(seeded, row["id"], scope={"tag": "nope", "value": "x"})
    legacy = seeded.add_learning("old", "do", "audience", scope={"tag": "nope", "value": "x"})
    with pytest.raises(ValueError):  # a stale stored predicate: refused before writing
        L.update_learning(seeded, legacy["id"], statement="new", settings=settings, now=NOW)
    assert seeded.get_learning(legacy["id"])["statement"] == "old"
    assert refresh_learnings(seeded, settings, NOW)["skipped"][0]["id"] == legacy["id"]


async def test_worker_refreshes_once_a_day(seeded):
    cfg = _settings(timezone="UTC")
    row = _add(seeded, "do", Q, confidence="low")
    runs = [await worker.data_jobs(FakeClient(), seeded, cfg, now=lambda t=t: t)
            for t in (NOW, NOW + timedelta(hours=1), NOW + timedelta(days=1))]
    assert runs[0]["learnings_day"]["evaluated"] == 1 and "learnings_day" not in runs[1]
    assert "learnings_day" in runs[2]
    assert seeded.get_learning(row["id"])["confidence"] == "medium"


def test_cli_refresh(tmp_path, monkeypatch, capsys):
    cfg = _settings(database_path=str(tmp_path / "l.db"))
    monkeypatch.setattr(scheduler, "get_settings", lambda: cfg)
    monkeypatch.setattr(scheduler, "configure_logging", lambda *a: None)
    with pytest.raises(SystemExit) as e:
        scheduler.main(["learnings", "refresh"])
    assert e.value.code == 0 and '"evaluated": 0' in capsys.readouterr().out
