"""Step 012: review inbox REST routes (assets)."""

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.studio.assets import transition

from .conftest import LOCAL

ORIGIN = {"Origin": LOCAL}


def _settings(**kw):
    kw.setdefault("database_path", ":memory:")
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None, **kw)


@pytest.fixture
def tc(store):
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as c:
        yield c


def _asset(store, status="ready", track="motion", **fields):
    idea = store.add_idea(track)
    a = store.add_asset(idea["id"], **fields)
    if status != "rendering":
        a = transition(store, a["id"], "ready", actor="worker")
    if status == "approved":
        a = transition(store, a["id"], "approved", actor="owner")
    return a


def test_list_filters_and_default_order(tc, store):
    # 189: newest batch first, then best_before soonest (none last), then id; a legacy
    # self_score no longer orders anything
    late = _asset(store, self_score=9, batch_date="2026-11-17", best_before="2026-11-30")
    undated = _asset(store, batch_date="2026-11-17")
    soon = _asset(store, self_score=3, batch_date="2026-11-17", best_before="2026-11-20")
    other_day = _asset(store, self_score=10, batch_date="2026-11-16", track="remix")
    rendering = _asset(store, status="rendering", batch_date="2026-11-17")

    ids = [a["id"] for a in tc.get("/api/assets", params={"batch_date": "2026-11-17"}).json()]
    assert ids == [soon["id"], late["id"], undated["id"], rendering["id"]]
    assert [a["id"] for a in tc.get("/api/assets").json()][-1] == other_day["id"]
    r = tc.get("/api/assets", params={"status": "rendering"}).json()
    assert [a["id"] for a in r] == [rendering["id"]]
    r = tc.get("/api/assets", params={"track": "remix"}).json()
    assert [a["id"] for a in r] == [other_day["id"]]
    assert len(tc.get("/api/assets", params={"limit": 2}).json()) == 2
    r = tc.get("/api/assets", params={"limit": 0})
    assert r.status_code == 422 and r.json()["error"] == "invalid"


def test_list_rows_carry_rights_and_dm_pick_sender(tc, store):
    src = store.add_source("downloader", url="https://example.org/r", author="creator",
                           rights_basis="commentary")
    with store._tx() as c:
        c.execute("INSERT INTO dm_picks (message_id, sender_username, reel_url, received_at,"
                  " source_id, created_at, updated_at) VALUES ('m1', 'pal', 'https://x', 't',"
                  " ?, 't', 't')", (src["id"],))
    idea = store.add_idea("remix", source_id=src["id"])
    picked = transition(store, store.add_asset(idea["id"])["id"], "ready", actor="worker")
    plain = _asset(store)
    rows = {a["id"]: a for a in tc.get("/api/assets").json()}
    assert (rows[picked["id"]]["rights_basis"], rows[picked["id"]]["dm_pick_sender"]) == (
        "commentary", "pal")
    assert (rows[plain["id"]]["rights_basis"], rows[plain["id"]]["dm_pick_sender"]) == (None, None)


def test_get_and_404(tc, store):
    a = _asset(store, recipe={"template": "FactQuest"})
    r = tc.get(f"/api/assets/{a['id']}")
    assert r.status_code == 200 and r.json()["recipe"] == {"template": "FactQuest"}
    for r in (tc.get("/api/assets/999"),
              tc.post("/api/assets/999/approve", headers=ORIGIN),
              tc.post("/api/assets/999/verdict", json={"verdict": "liked"}, headers=ORIGIN),
              tc.patch("/api/assets/999", json={"caption": "hi"}, headers=ORIGIN)):
        assert r.status_code == 404 and r.json() == {"error": "not_found"}


def test_verdict_leaves_status_alone(tc, store):
    a = _asset(store)
    for verdict in ("liked", "disliked", "none"):
        r = tc.post(f"/api/assets/{a['id']}/verdict", json={"verdict": verdict})
        assert r.status_code == 200
        assert r.json()["verdict"] == verdict and r.json()["status"] == "ready"
    r = tc.post(f"/api/assets/{a['id']}/verdict", json={"verdict": "love"})
    assert r.status_code == 422 and r.json()["error"] == "invalid"
    r = tc.post(f"/api/assets/{a['id']}/verdict", json={})
    assert r.status_code == 422 and r.json()["error"] == "invalid"


def test_approve_unapprove_archive(tc, store):
    a = _asset(store)
    r = tc.post(f"/api/assets/{a['id']}/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "approved" and r.json()["approved_at"]
    assert store.list_scheduled() == []  # approve schedules nothing
    r = tc.post(f"/api/assets/{a['id']}/unapprove")
    assert r.json()["status"] == "ready" and r.json()["approved_at"] is None
    r = tc.post(f"/api/assets/{a['id']}/archive")
    assert r.status_code == 200 and r.json()["status"] == "archived"


def test_invalid_transitions_are_409(tc, store):
    rendering = _asset(store, status="rendering")
    r = tc.post(f"/api/assets/{rendering['id']}/approve")
    assert r.status_code == 409 and r.json()["error"] == "invalid_transition"
    assert "rendering -> approved" in r.json()["message"]
    ready = _asset(store)
    assert tc.post(f"/api/assets/{ready['id']}/unapprove").status_code == 409
    assert store.get_asset(ready["id"])["status"] == "ready"


def test_edit_caption_and_best_before(tc, store):
    a = _asset(store)
    r = tc.patch(f"/api/assets/{a['id']}", json={"caption": "New hook #8bit"})
    assert r.status_code == 200 and r.json()["caption"] == "New hook #8bit"
    r = tc.patch(f"/api/assets/{a['id']}", json={"best_before": "2026-12-01"})
    assert r.json()["best_before"] == "2026-12-01"
    assert r.json()["caption"] == "New hook #8bit"  # untouched
    r = tc.patch(f"/api/assets/{a['id']}", json={"best_before": None})
    assert r.status_code == 200 and r.json()["best_before"] is None

    bad = [{"caption": " ".join(f"#t{i}" for i in range(31))},
           {"caption": "x" * 2201},
           {"best_before": "01/12/2026"},
           {"best_before": "20261201"},
           {"best_before": "2026-02-30"},
           {"status": "approved"},
           {"verdict": "liked"}]
    for body in bad:
        r = tc.patch(f"/api/assets/{a['id']}", json=body)
        assert r.status_code == 422 and r.json()["error"] == "invalid", body
        assert r.json()["message"]
    after = store.get_asset(a["id"])
    assert after["status"] == "ready" and after["verdict"] == "none"
    assert after["caption"] == "New hook #8bit"


def test_routes_need_session_with_password(store):
    s = _settings(ui_password="pw")
    with TestClient(create_app(s, store=store), base_url=LOCAL) as c:
        a = _asset(store)
        assert c.get("/api/assets").status_code == 401
        assert c.post(f"/api/assets/{a['id']}/approve", headers=ORIGIN).status_code == 401
        assert c.post("/api/login", json={"password": "pw"}, headers=ORIGIN).status_code == 200
        assert c.get("/api/assets").status_code == 200
        r = c.post(f"/api/assets/{a['id']}/approve", headers=ORIGIN)
        assert r.status_code == 200 and r.json()["status"] == "approved"


def test_cross_site_post_refused(tc, store):
    a = _asset(store)
    r = tc.post(f"/api/assets/{a['id']}/approve", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json() == {"error": "bad_origin"}
    r = tc.patch(f"/api/assets/{a['id']}", json={"caption": "x"},
                 headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert store.get_asset(a["id"])["status"] == "ready"


def test_app_opens_and_closes_its_own_store(tmp_path):
    app = create_app(_settings(database_path=str(tmp_path / "studio.db")))
    with TestClient(app, base_url=LOCAL) as c:
        a = _asset(app.state.store)
        assert c.post(f"/api/assets/{a['id']}/approve").json()["status"] == "approved"
        opened = app.state.store
        assert opened._conns
    assert not opened._conns  # closed on shutdown
