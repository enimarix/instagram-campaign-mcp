"""Creative brief and batch size that follows the bench (step 055)."""

import json
from datetime import datetime, timezone

import pytest

import src.instagram_mcp_server as srv
from src.learning import brief as B
from src.learning.quotas import effective_batch_size, todays_quotas
from src.studio import production
from src.studio.assets import set_verdict, transition

DAY = "2026-11-17"
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def utc(settings, tmp_path, monkeypatch):
    settings.timezone = "UTC"
    monkeypatch.setattr(B, "BIBLE_PATH", tmp_path / "BIBLE.md")


def _asset(store, verdict="none", batch_date="2026-11-10", status="ready", **idea):
    i = store.add_idea("motion", batch_date=batch_date, **idea)
    a = store.add_asset(i["id"], batch_date=batch_date,
                        recipe={"kind": "motion", "template": "FactQuest",
                                "props": {"hook": "SECRET_PROP"}})
    if status != "rendering":
        transition(store, a["id"], status, actor="worker")
    if verdict != "none":
        set_verdict(store, a["id"], verdict)
    return a["id"]


def _bench(store, n):
    for k in range(n):
        _asset(store, "liked", hook=f"bench hook {k}")


# Batch-size rule: 3 days x 3 posts = 9 liked videos are fine, each one beyond takes one off.
@pytest.mark.parametrize("bench, size, surplus", [(0, 10, 0), (9, 10, 0), (12, 7, 3),
                                                  (100, 5, 91)])
def test_effective_batch_size(settings, bench, size, surplus):
    assert effective_batch_size(settings, bench) == {"effective_batch_size": size,
                                                     "bench_surplus": surplus}


def test_floor_never_raises_the_configured_size(settings):
    settings.batch_size = 3
    assert effective_batch_size(settings, 0)["effective_batch_size"] == 3


def test_quotas_follow_the_bench_and_explore_keeps_its_count(store, settings):
    settings.bench_target_days = 0  # every liked video is surplus
    _bench(store, 3)
    q = todays_quotas(store, settings, DAY, NOW)
    assert (q["batch_size"], q["effective_batch_size"], q["bench_surplus"]) == (10, 7, 3)
    # explore keeps ceil(10 x 0.3) = 3 from the configured size; humour target round(3.5) = 4
    assert q["limits"] | {"reactions": 0} == {"ideas": 7, "explore": 3, "humour": 5,
                                              "informative": 4, "reactions": 0}
    settings.explore_share = 0.9  # ceil(9) capped at the effective 7
    assert todays_quotas(store, settings, DAY, NOW)["limits"]["explore"] == 7


def test_create_idea_refuses_at_the_effective_size(store, settings):
    settings.bench_target_days = 0
    _bench(store, 8)  # 10 - 8 = 2, floor 5
    for k, pillar in enumerate(["stories", "everyday_humor"] * 2 + ["stories"]):
        production.create_idea(store, settings, "motion", hook=f"idea {'abcde'[k] * 5}",
                               pillar=pillar, batch_date=DAY)
    with pytest.raises(ValueError, match="batch full: 5/5 ideas today"):
        production.create_idea(store, settings, "motion", hook="one too many",
                               pillar="stories", batch_date=DAY)


# The brief

def test_every_key_on_an_empty_db(store, settings):
    b = B.creative_brief(store, settings, NOW)
    mix = b.pop("mix")
    assert set(mix) == {"template", "hook_type", "pillar", "humour", "moved"}
    # 10 ideas, 3 explore: 7 exploit ideas split in every dimension
    assert all(sum(r["count"] for r in mix[d]) == 7 for d in mix if d != "moved")
    # 134: the owner's work orders first; 133: then what the owner turned down
    assert list(b)[:2] == ["work_orders", "owner_decisions"]
    assert b == {
        "work_orders": [],
        "owner_decisions": {"decline_motives": [], "approved_changes": []},
        "bible": None, "bible_note": B.NO_BIBLE, "learnings": [], "feedback": [],
        "change_requests": [], "last_daily_report": None, "experiments": [],
        "explore_plan": [], "quotas": todays_quotas(store, settings, DAY, NOW), "today": [], "recent_hooks": [],
        "inspirations": [], "trend_taste": {"liked": [], "disliked": []},
        "bench": {"count": 0, "supply_days": 0, "hooks": []},
    }
    assert b["quotas"]["effective_batch_size"] == 10


def test_bible_report_today_and_bench(store, settings):
    B.BIBLE_PATH.write_text("# Bible\n" + "x" * 9000, encoding="utf-8")
    store.save_daily_report("2026-11-16", "y" * 3000, {"liked": 4})
    idea = store.add_idea("motion", pillar="stories", hook_type="question", hook="Why?",
                          strategy="explore", script="long script", batch_date=DAY)
    _bench(store, 2)
    b = B.creative_brief(store, settings, NOW)
    assert b["bible"].startswith("# Bible") and len(b["bible"]) == B.BIBLE_CHARS + 1
    assert b["bible_note"] is None
    assert b["last_daily_report"]["report_date"] == "2026-11-16"
    assert len(b["last_daily_report"]["summary"]) == B.REPORT_CHARS + 1
    assert b["today"] == [{"id": idea["id"], "track": "motion", "pillar": "stories",
                           "hook_type": "question", "strategy": "explore", "hook": "Why?"}]
    assert b["bench"] == {"count": 2, "supply_days": 1,
                          "hooks": ["bench hook 0", "bench hook 1"]}


def test_caps_and_newest_hooks_first(store, settings):
    for k in range(70):
        store.add_idea("motion", hook=f"hook {k}", batch_date=DAY)
    store.add_idea("motion", hook="too old", batch_date="2026-10-01")
    for k in range(45):
        store.add_learning(f"rule {k}", "do", "taste", confidence="low")
    a = _asset(store)
    for k in range(35):
        store.add_feedback(a, text=f"comment {k}")
    b = B.creative_brief(store, settings, NOW)
    assert b["recent_hooks"][:2] == ["hook 69", "hook 68"] and len(b["recent_hooks"]) == 60
    assert len(b["learnings"]) == 40 and len(b["feedback"]) == 30
    assert set(b["learnings"][0]) == {"id", "statement", "kind", "confidence", "origin",
                                      "scope", "evidence_count"}


async def test_no_recipe_props_and_mcp_door(store, settings, monkeypatch):
    a = _asset(store, "liked")
    store.add_feedback(a, text="redo the end", wants_changes=True)
    transition(store, _asset(store), "revision_requested", actor="owner")
    monkeypatch.setattr(srv, "store", lambda: store)
    monkeypatch.setattr(srv, "get_settings", lambda: settings)
    b = await srv.get_creative_brief()
    assert b["feedback"] and b["change_requests"] and b["bench"]["count"] == 1
    assert "SECRET_PROP" not in json.dumps(b) and '"props"' not in json.dumps(b)


def test_decline_motives_and_approved_changes_come_first(store, settings):
    from src.studio.feedback import add_comment, decline

    declined = _asset(store, hook="boring one")
    decline(store, declined, reason_codes=["weak_hook"], text="On s'ennuie")
    store.mark_feedback_digested([f["id"] for f in store.list_feedback()])  # read: still listed
    before = _asset(store, hook="good one")
    ask = add_comment(store, before, text="Plus court", wants_changes=True)["feedback"]
    after = store.add_asset(store.get_asset(before)["idea_id"], batch_date="2026-11-10",
                            parent_asset_id=before, self_score_reason="Changed: cut to 12 s")
    transition(store, after["id"], "ready", actor="worker")
    transition(store, after["id"], "approved", actor="owner")
    b = B.creative_brief(store, settings, NOW)
    assert list(b)[:2] == ["work_orders", "owner_decisions"]
    [motive] = b["owner_decisions"]["decline_motives"]
    assert (motive["text"], motive["reasons"]) == (
        "On s'ennuie", [{"code": "weak_hook", "label": "Weak hook"}])
    assert motive["asset"]["id"] == declined and motive["asset"]["hook"] == "boring one"
    assert b["owner_decisions"]["approved_changes"] == [{
        "before_asset_id": before, "after_asset_id": after["id"],
        "asked": [{"feedback_id": ask["id"], "text": "Plus court", "reasons": []}],
        "changed": "Changed: cut to 12 s", "outcome": "approved", "decline_motives": [],
        "asked_again": []}]
