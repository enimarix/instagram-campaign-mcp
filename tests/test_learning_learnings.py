"""Feedback and learning tools (step 054): src/learning/learnings.py and its MCP doors."""

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import src.instagram_mcp_server as srv
from src.learning import learnings as L
from src.studio import production
from src.studio.assets import transition
from src.studio.feedback import add_comment, decline


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


def _posts(store, *media_ids):
    """Posts with insights: what an agent's audience evidence may cite."""
    for m in media_ids:
        store.add_snapshot(m, {"reach": 100}, "REELS", "VIDEO", "2026-11-17T10:00:00+00:00")


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
    assert rows[0]["reasons"] == [{"code": "weak_hook", "label": "Accroche faible"},
                                  {"code": "too_slow", "label": "Trop lent"}]
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
    assert req["comments"][0]["reasons"][0]["label"] == "Son raté"


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
    with pytest.raises(KeyError, match="no media_id '1'"):  # never measured
        L.add_learning(store, "x", "hypothesis", "audience", evidence=[{"media_id": "1"}])
    with pytest.raises(ValueError, match="names its media_id"):
        L.add_learning(store, "x", "hypothesis", "audience", evidence=[{"views": 9}])
    _posts(store, "1")
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


def test_owner_instruction_scope_must_be_the_commented_video(store):
    f = _fb(store, _asset(store), text="Very bad style never do it again")  # a FactQuest
    row = L.add_learning(store, "Never FactQuest", "dont", "taste", [f], owner_instruction=True,
                         scope={"tag": "template", "value": "FactQuest"})["learning"]
    assert row["confidence"] == "owner"  # like learning 35 (DialogStory, on video 86)
    for scope in ({"tag": "template", "value": "QuizChest"}, {"tag": "pillar", "value": "myths"},
                  {"tag": "hour", "value": 9}):
        with pytest.raises(ValueError, match="must match the commented video"):
            L.add_learning(store, "Never", "dont", "taste", [f], owner_instruction=True,
                           scope=scope)


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
    _posts(store, "1", "2")
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


def test_duplicated_or_reworded_claims_do_not_gain_confidence(store):
    _posts(store, "1", "2")
    one = {"media_id": "1"}
    added = L.add_learning(store, "x", "do", "audience", evidence=[one, dict(one)],
                           confidence="medium")
    assert added["learning"]["evidence"] == [one] and added["learning"]["kind"] == "hypothesis"
    lid = added["learning"]["id"]
    with pytest.raises(ValueError, match="at least 2"):  # 2 metrics of one Reel: one Reel
        L.update_learning(store, lid, evidence_to_add=[one, {"media_id": "1", "at_s": 3}],
                          confidence="medium")
    row = L.update_learning(store, lid, evidence_to_add=[{"media_id": "2"}], kind="do",
                            confidence="medium")
    store.update_learning(lid, confidence="high")  # as the evidence engine would
    row = L.update_learning(store, lid, statement="Everything works", scope={})
    assert row["confidence"] == "low"  # a new claim starts over


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


# Step 133: every decline has a motive, every change teaches


def _revision(store, reason="Changed: hook cut to 2 s"):
    """A video sent back with a change request, and its new version, ready."""
    before = _asset(store)
    ask = add_comment(store, before, text="Shorter hook", reason_codes=["weak_hook"],
                      wants_changes=True)["feedback"]["id"]
    after = store.add_asset(store.get_asset(before)["idea_id"], batch_date="2026-11-17",
                            parent_asset_id=before, self_score_reason=reason)["id"]
    transition(store, after, "ready", actor="worker")
    return before, ask, after


def test_approved_change_comes_back_with_its_outcome(store):
    before, ask, after = _revision(store)
    [row] = L.get_feedback(store)
    assert row["change"]["outcome"] == "pending"  # the new version is not judged yet
    L.mark_feedback_digested(store, [ask])
    assert L.get_feedback(store) == []
    transition(store, after, "approved", actor="owner")
    [row] = L.get_feedback(store)  # undigested again, now with the outcome
    assert row["id"] == ask and row["change"] == {
        "before_asset_id": before, "after_asset_id": after,
        "asked": [{"feedback_id": ask, "text": "Shorter hook", "reasons": ["Accroche faible"]}],
        "changed": "Changed: hook cut to 2 s", "outcome": "approved", "decline_motives": [],
        "asked_again": []}
    assert L.owner_decisions(store)["approved_changes"] == [row["change"]]


@pytest.mark.parametrize("note, changed", [
    (" Changed: hook cut to 2 s ", "Changed: hook cut to 2 s"), (None, None)])
def test_submit_note_is_the_change_daily_learn_reads(store, settings, note, changed):
    """189: no self-score; the submit note is still the « changed » line of approved_changes."""
    _, _, after = _revision(store, reason=None)
    production.submit_asset(store, settings, after, caption="c", note=note)
    transition(store, after, "approved", actor="owner")
    [change] = L.owner_decisions(store)["approved_changes"]
    assert change["after_asset_id"] == after and change["changed"] == changed


def test_declined_revision_carries_its_motive(store):
    before, ask, after = _revision(store)
    L.mark_feedback_digested(store, [ask])
    decline(store, after, text="Still too slow")
    rows = L.get_feedback(store)
    assert [r["id"] for r in rows][0] == ask
    motive = rows[1]
    assert motive["text"] == "Still too slow" and motive["asset"]["id"] == after
    for r in rows:  # both name the change, both assets and the motive
        assert r["change"]["outcome"] == "declined"
        assert (r["change"]["before_asset_id"], r["change"]["after_asset_id"]) == (before, after)
        assert r["change"]["decline_motives"] == [
            {"feedback_id": motive["id"], "text": "Still too slow", "reasons": []}]
    decisions = L.owner_decisions(store)
    assert [m["id"] for m in decisions["decline_motives"]] == [motive["id"]]
    assert decisions["approved_changes"] == []


def test_revision_sent_back_again(store):
    _, _, after = _revision(store)
    again = add_comment(store, after, text="Even shorter", wants_changes=True)["feedback"]
    change = L.get_feedback(store)[0]["change"]
    assert change["outcome"] == "sent_back"
    assert change["asked_again"] == [{"feedback_id": again["id"], "text": "Even shorter",
                                      "reasons": []}]


def test_feed_rows_carry_the_change_request(store):
    before, _, after = _revision(store)
    rows = {a["id"]: a for a in store.list_assets()}
    assert rows[after]["change_request"] == {"text": "Shorter hook",
                                             "reason_codes": ["weak_hook"]}
    assert rows[before]["change_request"] is None
