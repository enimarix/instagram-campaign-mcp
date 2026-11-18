"""Step 084: the owner's Learnings page routes (src/api/learnings.py)."""

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.learning import learnings as L

from .conftest import LOCAL
from .test_api_assets import _settings
from .test_learning_learnings import _asset, _fb

Q = {"tag": "hook_type", "value": "question"}


@pytest.fixture
def tc(store):
    with TestClient(create_app(_settings(timezone="UTC"), store=store), base_url=LOCAL) as c:
        yield c


def _agent_row(store, **kw):
    a = _asset(store)
    ids = [_fb(store, a, text="slow"), _fb(store, a, text="too slow")]
    return L.add_learning(store, "Slow starts lose me", kw.pop("kind", "dont"), "taste", ids,
                          confidence="medium", **kw)["learning"]


def test_list_filters_and_linked_evidence(tc, store):
    row = _agent_row(store)
    store.add_learning("Questions win", "do", "audience", scope=Q, confidence="high")
    store.add_learning("Old idea", "hypothesis", "taste", status="retired")
    body = tc.get("/api/learnings").json()
    assert [r["statement"] for r in body] == ["Questions win", "Slow starts lose me", "Old idea"]
    mine = body[1]
    assert mine["id"] == row["id"]
    assert [e["text"] for e in mine["evidence"]] == ["slow", "too slow"]
    assert mine["evidence"][0]["asset_id"] and "thumbnail_url" in mine["evidence"][0]
    for query, expected in (("status=retired", ["Old idea"]), ("origin=audience", ["Questions win"]),
                            ("kind=dont", ["Slow starts lose me"]),
                            ("confidence=high", ["Questions win"]),
                            ("status=active&origin=taste", ["Slow starts lose me"])):
        assert [r["statement"] for r in tc.get(f"/api/learnings?{query}").json()] == expected
    r = tc.get("/api/learnings?confidence=sure")
    assert r.status_code == 422 and "confidence" in r.json()["message"]


def test_owner_adds_rule_with_and_without_predicate(tc, store):
    r = tc.post("/api/learnings", json={"statement": " Never use red ", "kind": "dont"})
    assert r.status_code == 200
    row = r.json()
    assert (row["statement"], row["kind"], row["origin"], row["confidence"], row["scope"]) == (
        "Never use red", "dont", "taste", "owner", {})
    r = tc.post("/api/learnings", json={"statement": "Ask a question", "kind": "do",
                                        "predicate": Q})
    assert r.status_code == 200 and r.json()["scope"] == Q
    for bad, word in (({"tag": "hook_type", "value": "nope"}, "nope"),
                      ({"tag": "colour", "value": "red"}, "predicate tag")):
        r = tc.post("/api/learnings", json={"statement": "x", "kind": "do", "predicate": bad})
        assert r.status_code == 422 and word in r.json()["message"], bad
    for body in ({"statement": "  ", "kind": "do"}, {"statement": "x", "kind": "maybe"},
                 {"statement": "x", "kind": "do", "origin": "ads"}):
        assert tc.post("/api/learnings", json=body).status_code == 422, body
    assert len(store.list_learnings()) == 2


def test_owner_edit_wins_and_agent_cannot_override(tc, store):
    lid = _agent_row(store)["id"]
    r = tc.patch(f"/api/learnings/{lid}", json={"statement": "Slow intros lose me",
                                                "predicate": Q})
    assert r.status_code == 200
    row = r.json()
    assert (row["statement"], row["confidence"], row["scope"]) == ("Slow intros lose me",
                                                                   "owner", Q)
    assert any(e.get("kind") == "audience_index" for e in row["evidence"])  # re-checked
    for change in ({"statement": "Slow is fine"}, {"kind": "do"}, {"confidence": "low"},
                   {"status": "retired"}):
        with pytest.raises(ValueError, match="only the owner"):
            L.update_learning(store, lid, **change)  # actor agent
    assert store.get_learning(lid)["statement"] == "Slow intros lose me"
    r = tc.patch(f"/api/learnings/{lid}", json={"predicate": None})
    assert r.status_code == 200 and r.json()["scope"] == {}
    r = tc.patch(f"/api/learnings/{lid}", json={"predicate": {"tag": "hour", "value": "25"}})
    assert r.status_code == 422 and "hour" in r.json()["message"]
    assert tc.patch("/api/learnings/999", json={"statement": "x"}).status_code == 404


def test_confirm_retire_reactivate(tc, store):
    lid = _agent_row(store, kind="hypothesis")["id"]
    assert tc.post(f"/api/learnings/{lid}/confirm").json()["confidence"] == "owner"
    with pytest.raises(ValueError, match="only the owner"):
        L.update_learning(store, lid, status="retired")
    assert tc.post(f"/api/learnings/{lid}/retire").json()["status"] == "retired"
    assert tc.post(f"/api/learnings/{lid}/reactivate").json()["status"] == "active"
    assert tc.post("/api/learnings/999/confirm").status_code == 404


def test_retiring_does_not_make_it_owners(tc, store):
    lid = _agent_row(store)["id"]
    row = tc.post(f"/api/learnings/{lid}/retire").json()
    assert (row["status"], row["confidence"]) == ("retired", "medium")


def test_refresh(tc, store):
    lid = store.add_learning("Questions win", "do", "audience", scope=Q,
                             confidence="medium")["id"]
    r = tc.post("/api/learnings/refresh")
    assert r.status_code == 200
    assert r.json()["evaluated"] == 1
    item = store.get_learning(lid)["evidence"][-1]
    assert (item["kind"], item["n"], item["verdict"]) == ("audience_index", 0, "needs_n")
