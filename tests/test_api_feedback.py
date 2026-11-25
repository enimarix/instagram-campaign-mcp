"""Step 013: owner comments (feedback) REST routes and GET /api/taxonomy."""

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app

from .conftest import LOCAL
from .test_api_assets import _asset, _settings


@pytest.fixture
def tc(store):
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as c:
        yield c


def _post(tc, asset_id, **body):
    return tc.post(f"/api/assets/{asset_id}/feedback", json=body)


def test_add_and_list(tc, store):
    a = _asset(store, duration=20.0)
    r = _post(tc, a["id"], text="Love the palette")
    assert r.status_code == 200
    body = r.json()
    assert body["feedback"]["text"] == "Love the palette"
    assert body["moved"] is False and body["asset"]["status"] == "ready"
    assert "file_url" in body["asset"]
    r = _post(tc, a["id"], reason_codes=["weak_hook", "too_long"], video_time_s=20.0)
    assert r.status_code == 200
    assert r.json()["feedback"]["reason_codes"] == ["weak_hook", "too_long"]
    listed = tc.get(f"/api/assets/{a['id']}/feedback").json()
    assert [f["video_time_s"] for f in listed] == [None, 20.0]


def test_add_invalid(tc, store):
    a = _asset(store, duration=20.0)
    for body in ({}, {"text": "  "}, {"video_time_s": -1, "text": "x"},
                 {"video_time_s": 20.5, "text": "x"}, {"text": "x", "status": "approved"}):
        r = _post(tc, a["id"], **body)
        assert r.status_code == 422 and r.json()["error"] == "invalid", body
    r = _post(tc, a["id"], reason_codes=["meh"])
    assert r.status_code == 422 and "weak_hook" in r.json()["message"]  # lists valid ones
    assert store.list_feedback(asset_id=a["id"]) == []
    # no known duration: any non-negative time is accepted
    assert _post(tc, _asset(store)["id"], text="x", video_time_s=99).status_code == 200


def test_wants_changes_moves_only_ready(tc, store):
    ready = _asset(store)
    r = _post(tc, ready["id"], text="Shorter intro", wants_changes=True)
    assert r.status_code == 200
    assert r.json()["moved"] is True and r.json()["asset"]["status"] == "revision_requested"

    approved = _asset(store, status="approved")
    r = _post(tc, approved["id"], reason_codes=["weak_hook"], wants_changes=True)
    assert r.status_code == 200 and r.json()["feedback"]["wants_changes"] == 1
    assert r.json()["moved"] is False and "approved" in r.json()["reason"]
    assert store.get_asset(approved["id"])["status"] == "approved"
    assert store.list_scheduled() == []  # comments never publish anything


def test_edit_and_delete(tc, store):
    a = _asset(store, duration=10.0)
    fid = _post(tc, a["id"], text="hm").json()["feedback"]["id"]
    store.mark_feedback_digested([fid])
    r = tc.patch(f"/api/feedback/{fid}", json={"text": "Too slow", "reason_codes": ["too_slow"]})
    assert r.status_code == 200 and r.json()["feedback"]["digested_at"] is None
    assert r.json()["moved"] is False
    assert tc.patch(f"/api/feedback/{fid}", json={"video_time_s": 11}).status_code == 422
    assert tc.patch(f"/api/feedback/{fid}", json={"reason_codes": None}).status_code == 422

    r = tc.patch(f"/api/feedback/{fid}", json={"wants_changes": True})
    assert r.json()["moved"] is True and r.json()["asset"]["status"] == "revision_requested"
    r = tc.patch(f"/api/feedback/{fid}", json={"wants_changes": False})
    assert r.json()["asset"]["status"] == "revision_requested"  # never moved back

    r = tc.delete(f"/api/feedback/{fid}")
    assert r.status_code == 204
    assert store.list_feedback(asset_id=a["id"]) == []
    assert store.get_asset(a["id"])["status"] == "revision_requested"
    assert store.list_scheduled() == []


def test_404s(tc, store):
    for r in (tc.get("/api/assets/999/feedback"),
              _post(tc, 999, text="x"),
              tc.patch("/api/feedback/999", json={"text": "x"}),
              tc.delete("/api/feedback/999")):
        assert r.status_code == 404 and r.json() == {"error": "not_found"}


def test_taxonomy(tc):
    r = tc.get("/api/taxonomy")
    assert r.status_code == 200
    reasons = r.json()["feedback_reasons"]["values"]
    assert {"id": "weak_hook", "label": "Accroche faible"} in reasons


def test_decline_is_one_call(tc, store):
    a = _asset(store)
    r = tc.post(f"/api/assets/{a['id']}/decline", json={"reason_codes": ["too_long"]})
    assert r.status_code == 200
    body = r.json()
    assert (body["status"], body["verdict"]) == ("archived", "disliked") and "file_url" in body
    [fb] = store.list_feedback(asset_id=a["id"])
    assert fb["reason_codes"] == ["too_long"] and not fb["wants_changes"]
    b = _asset(store)
    r = tc.post(f"/api/assets/{b['id']}/decline", json={"text": " Trop lent "})
    assert r.status_code == 200 and r.json()["verdict"] == "disliked"
    [fb] = store.list_feedback(asset_id=b["id"])
    assert (fb["text"], fb["reason_codes"]) == ("Trop lent", [])


def test_decline_needs_a_motive(tc, store):
    a = _asset(store)
    for body in ({}, {"reason_codes": []}, {"text": "   "}, {"text": None, "reason_codes": []}):
        r = tc.post(f"/api/assets/{a['id']}/decline", json=body)
        assert r.status_code == 422, body
        assert r.json() == {"error": "invalid",
                            "message": "a decline needs a motive: pick a reason or say why"}
    row = store.get_asset(a["id"])
    assert (row["status"], row["verdict"]) == ("ready", "none")
    assert store.list_feedback(asset_id=a["id"]) == []


def test_decline_refused_leaves_the_asset_unchanged(tc, store):
    a = _asset(store)
    r = tc.post(f"/api/assets/{a['id']}/decline", json={"reason_codes": ["meh"]})
    assert r.status_code == 422
    approved = _asset(store, status="approved")
    r = tc.post(f"/api/assets/{approved['id']}/decline", json={"reason_codes": ["too_long"]})
    assert r.status_code == 409 and r.json()["error"] == "invalid_transition"
    for x in (a, approved):
        row = store.get_asset(x["id"])
        assert (row["status"], row["verdict"]) == (x["status"], "none")
        assert store.list_feedback(asset_id=x["id"]) == []
    assert tc.post("/api/assets/999/decline", json={"text": "x"}).status_code == 404
