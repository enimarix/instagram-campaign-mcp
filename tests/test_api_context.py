"""Step 016: GET /api/assets/{id}/context (idea, source, version chain)."""

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app

from .conftest import LOCAL
from .test_api_assets import _settings


@pytest.fixture
def tc(store):
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as c:
        yield c


def test_remix_with_source_and_versions(tc, store):
    src = store.add_source("demo", url="https://example.org/clip", author="someone",
                           rights_basis="licensed")
    idea = store.add_idea("remix", hook="Wait for it", hook_type="question",
                          hypothesis="questions hook better", source_id=src["id"],
                          citations=[{"title": "Paper", "url": "https://example.org/p"}])
    v1 = store.add_asset(idea["id"])
    v2 = store.add_asset(idea["id"], parent_asset_id=v1["id"])
    v3 = store.add_asset(idea["id"], parent_asset_id=v1["id"])

    body = tc.get(f"/api/assets/{v1['id']}/context").json()
    assert body["idea"]["hook"] == "Wait for it"
    assert body["idea"]["citations"] == [{"title": "Paper", "url": "https://example.org/p"}]
    assert body["source"]["rights_basis"] == "licensed" and body["source"]["author"] == "someone"
    assert body["parent"] is None
    assert [c["id"] for c in body["children"]] == [v2["id"], v3["id"]]

    body = tc.get(f"/api/assets/{v2['id']}/context").json()
    assert body["parent"]["id"] == v1["id"] and body["children"] == []


def test_motion_without_source(tc, store):
    a = store.add_asset(store.add_idea("motion", pillar="myths")["id"])
    body = tc.get(f"/api/assets/{a['id']}/context").json()
    assert body["source"] is None and body["idea"]["pillar"] == "myths"


def test_missing_asset(tc):
    r = tc.get("/api/assets/999/context")
    assert r.status_code == 404 and r.json() == {"error": "not_found"}
