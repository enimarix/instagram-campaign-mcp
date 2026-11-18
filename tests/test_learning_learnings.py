"""Feedback and learning tools (step 054): src/learning/learnings.py and its MCP doors."""

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import src.instagram_mcp_server as srv
from src.learning import learnings as L
from src.studio.assets import transition
from src.studio.feedback import add_comment


def _asset(store, status="ready"):
    idea = store.add_idea("motion", pillar="fun_facts", hook="Did you know?",
                          hook_type="question", batch_date="2026-11-17")
    a = store.add_asset(idea["id"], batch_date="2026-11-17",
                        recipe={"kind": "motion", "template": "FactQuest", "props": {}})
    if status != "rendering":
        transition(store, a["id"], "ready", actor="worker")
    return a["id"]


def _fb(store, asset_id, text="too slow at the start", **kw):
    return store.add_feedback(asset_id, text=text, **kw)["id"]


@pytest.fixture
def mcp_store(store, monkeypatch):
    monkeypatch.setattr(srv, "store", lambda: store)
    return store


def test_get_feedback_has_labels_context_and_digest_round_trip(store):
    a = _asset(store)
    f1 = _fb(store, a, reason_codes=["weak_hook", "too_slow"], video_time_s=1.5)
    f2 = _fb(store, a, text="nice")
    rows = L.get_feedback(store)
    assert [r["id"] for r in rows] == [f1, f2]
    assert rows[0]["reasons"] == [{"code": "weak_hook", "label": "Weak hook"},
                                  {"code": "too_slow", "label": "Too slow"}]
    assert rows[0]["video_time_s"] == 1.5 and rows[0]["wants_changes"] is False
    ctx = rows[0]["asset"]
    assert ctx["template"] == "FactQuest" and ctx["hook"] == "Did you know?"
    assert (ctx["pillar"], ctx["hook_type"], ctx["track"]) == ("fun_facts", "question", "motion")
    assert "recipe" not in ctx
    assert L.mark_feedback_digested(store, [f1, 999]) == {"digested": 1}
    assert [r["id"] for r in L.get_feedback(store)] == [f2]
    assert [r["id"] for r in L.get_feedback(store, undigested=False)] == [f1, f2]
    assert L.mark_feedback_digested(store, [f1, f2]) == {"digested": 1}
    assert L.get_feedback(store) == []


def test_revision_requests_listed_with_comments_newest_first(store):
    a, other = _asset(store), _asset(store)
    add_comment(store, a, text="louder please", wants_changes=True)
    _fb(store, a, text="just a note")
    add_comment(store, a, reason_codes=["bad_audio"], wants_changes=True)
    _fb(store, other, text="fine")
    [req] = L.list_revision_requests(store)
    assert req["asset"]["id"] == a and req["asset"]["status"] == "revision_requested"
    assert [c["text"] for c in req["comments"]] == [None, "louder please"]
    assert req["comments"][0]["reasons"][0]["label"] == "Bad audio"


def test_revision_request_hidden_while_its_new_version_renders(store, monkeypatch):
    a, b = _asset(store), _asset(store)
    for x in (a, b):
        add_comment(store, x, text="louder", wants_changes=True)
    store.add_asset(store.get_asset(a)["idea_id"], parent_asset_id=a)  # rendering
    assert [r["asset"]["id"] for r in L.list_revision_requests(store)] == [b]


def test_one_comment_forces_low_hypothesis(store):
    f = _fb(store, _asset(store))
    out = L.add_learning(store, "Slow starts lose the owner", "dont", "taste", [f, f],
                         confidence="medium")
    row = out["learning"]
    assert (row["kind"], row["confidence"]) == ("hypothesis", "low")
    assert row["evidence"] == [{"feedback_id": f}] and "hypothesis" in out["note"]
    assert L.add_learning(store, "x", "hypothesis", "taste", [f])["note"] is None
    with pytest.raises(ValueError, match="not for the agent"):  # refused, not forced
        L.add_learning(store, "x", "hypothesis", "taste", [f], confidence="owner")


def test_two_comments_allow_do_dont_up_to_medium(store):
    a = _asset(store)
    f1, f2 = _fb(store, a), _fb(store, a)
    row = L.add_learning(store, "Open on the punchline", "do", "taste", [f1, f2],
                         confidence="medium", scope={"template": "FactQuest"})["learning"]
    assert (row["kind"], row["confidence"], row["scope"]) == \
        ("do", "medium", {"template": "FactQuest"})
    for bad in ("high", "owner"):
        with pytest.raises(ValueError, match="not for the agent"):
            L.add_learning(store, "x", "do", "taste", [f1, f2], confidence=bad)


def test_evidence_is_required_and_must_exist(store):
    f = _fb(store, _asset(store))
    with pytest.raises(ValueError, match="cite evidence"):
        L.add_learning(store, "x", "do", "taste", [])
    with pytest.raises(KeyError, match="999"):
        L.add_learning(store, "x", "do", "taste", [f, 999])
    with pytest.raises(ValueError, match="evidence dicts"):
        L.add_learning(store, "x", "do", "taste", [f], evidence=[{"post": 1}])
    row = L.add_learning(store, "Evenings win", "hypothesis", "audience",
                         evidence=[{"media_id": "1"}])["learning"]
    assert row["evidence"] == [{"media_id": "1"}]
    assert store.list_learnings() == [row]


def test_owner_instruction_stored_at_owner_confidence(store):
    a = _asset(store)
    f = _fb(store, a, text="Never use the red palette")
    chips = _fb(store, a, text=None, reason_codes=["ugly_visual"])
    row = L.add_learning(store, "Never use red", "dont", "taste", [f],
                         owner_instruction=True)["learning"]
    assert (row["kind"], row["confidence"]) == ("dont", "owner")
    assert L.add_learning(store, "Always loop", "do", "taste", [f],
                          owner_instruction=True)["learning"]["confidence"] == "owner"
    with pytest.raises(ValueError, match="needs a comment with text"):
        L.add_learning(store, "x", "dont", "taste", [chips], owner_instruction=True)
    with pytest.raises(ValueError, match="exactly one"):
        L.add_learning(store, "x", "dont", "taste", [f, chips], owner_instruction=True)
    with pytest.raises(ValueError, match="exactly one"):
        L.add_learning(store, "x", "hypothesis", "taste", [f], owner_instruction=True)


def test_agent_cannot_change_or_retire_owner_learning(store):
    f = _fb(store, _asset(store), text="Never use red")
    lid = L.add_learning(store, "Never red", "dont", "taste", [f],
                         owner_instruction=True)["learning"]["id"]
    for change in ({"status": "retired"}, {"statement": "Red is fine"},
                   {"evidence_feedback_ids_to_add": [f]},
                   {"evidence_to_add": [{"media_id": "1"}]}):
        with pytest.raises(ValueError, match="only the owner can change this"):
            L.update_learning(store, lid, **change)
    assert store.get_learning(lid)["status"] == "active"
    assert L.update_learning(store, lid, status="retired", actor="owner")["status"] == "retired"


def test_update_caps_and_evidence(store):
    a = _asset(store)
    f1, f2 = _fb(store, a), _fb(store, a)
    lid = L.add_learning(store, "Slow starts", "hypothesis", "taste", [f1])["learning"]["id"]
    with pytest.raises(ValueError, match="at least 2"):
        L.update_learning(store, lid, kind="dont")
    with pytest.raises(ValueError, match="not for the agent"):
        L.update_learning(store, lid, confidence="high", evidence_feedback_ids_to_add=[f2])
    with pytest.raises(KeyError):
        L.update_learning(store, lid, evidence_feedback_ids_to_add=[999])
    row = L.update_learning(store, lid, kind="dont", confidence="medium",
                            evidence_feedback_ids_to_add=[f1, f2])
    assert row["evidence"] == [{"feedback_id": f1}, {"feedback_id": f2}]
    assert (row["kind"], row["confidence"]) == ("dont", "medium")
    assert L.update_learning(store, lid, status="contradicted")["status"] == "contradicted"
    assert L.list_learnings(store) == []
    assert [r["id"] for r in L.list_learnings(store, status=None)] == [lid]


def test_update_adds_audience_evidence(store):
    lid = L.add_learning(store, "Evenings win", "hypothesis", "audience",
                         evidence=[{"media_id": "1"}])["learning"]["id"]
    row = L.update_learning(store, lid, evidence_to_add=[{"media_id": "2", "at_s": 2}],
                            confidence="medium")
    assert row["evidence"] == [{"media_id": "1"}, {"media_id": "2", "at_s": 2}]
    assert row["confidence"] == "medium"
    for bad in ([{}], ["media 3"]):
        with pytest.raises(ValueError, match="evidence dicts"):
            L.update_learning(store, lid, evidence_to_add=bad)
    taste = L.add_learning(store, "x", "hypothesis", "taste",
                           [_fb(store, _asset(store))])["learning"]["id"]
    with pytest.raises(ValueError, match="evidence dicts"):
        L.update_learning(store, taste, evidence_to_add=[{"media_id": "1"}])
    assert len(store.get_learning(lid)["evidence"]) == 2


async def test_mcp_doors(mcp_store):
    a = _asset(mcp_store)
    f = _fb(mcp_store, a, text="Never use red")
    assert (await srv.get_feedback())["feedback"][0]["id"] == f
    assert await srv.mark_feedback_digested([f]) == {"digested": 1}
    assert (await srv.list_revision_requests()) == {"assets": []}
    out = await srv.add_learning("Never red", "dont", "taste", [f], owner_instruction=True)
    with pytest.raises(ToolError, match="only the owner"):
        await srv.update_learning(out["learning"]["id"], status="retired")
    with pytest.raises(ToolError, match="kind must be one of"):
        await srv.add_learning("x", "maybe", "taste", [f])
    assert [r["confidence"] for r in (await srv.list_learnings())["learnings"]] == ["owner"]


async def test_mcp_update_learning_passes_scope_and_evaluate(mcp_store, monkeypatch):
    seen = {}
    monkeypatch.setattr(srv.learnings, "update_learning",
                        lambda store, lid, **kw: seen.update(kw, id=lid) or {"id": lid})
    scope = {"tag": "hook_type", "value": "question"}
    ev = [{"media_id": "1"}]
    assert await srv.update_learning(7, scope=scope, evaluate=True,
                                     evidence_to_add=ev) == {"id": 7}
    assert (seen["id"], seen["scope"], seen["evaluate"]) == (7, scope, True)
    assert seen["evidence_to_add"] == ev
