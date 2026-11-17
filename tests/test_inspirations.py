"""Step 051b: inspirations, Reel links the owner pastes from the phone with a note."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import src.instagram_mcp_server as srv
from src.api.app import create_app
from src.learning import brief as B

from .conftest import LOCAL
from .test_api_assets import _settings

REEL = "https://www.instagram.com/reel/C1a-B_2/"


@pytest.mark.parametrize("url, canonical", [
    (REEL, REEL),
    ("  https://instagram.com/reel/C1a-B_2?igsh=abc123  ", REEL),
    ("https://www.instagram.com/reel/C1a-B_2/?utm_source=ig_web_copy_link#x", REEL),
    ("https://www.instagram.com/p/XyZ9/", "https://www.instagram.com/p/XyZ9/"),
])
def test_urls_are_normalised(store, url, canonical):
    assert store.add_inspiration(url)["url"] == canonical


@pytest.mark.parametrize("url", [
    "", "http://www.instagram.com/reel/C1/", "https://www.instagram.com/rival/",
    "https://www.instagram.com/stories/rival/123/", "https://evil.com/reel/C1/",
    "https://www.instagram.com.evil.com/reel/C1/", "https://www.instagram.com/reel/",
    "https://www.instagram.com/reel/C1/extra", "javascript:alert(1)//instagram.com/reel/C1/",
])
def test_other_links_are_refused(store, url):
    with pytest.raises(ValueError, match="Instagram Reel or post link"):
        store.add_inspiration(url)


def test_duplicates_note_and_status(store):
    a = store.add_inspiration(REEL, "  this format is funny ")
    assert (a["note"], a["status"], a["used_at"]) == ("this format is funny", "new", None)
    again = store.add_inspiration(REEL + "?igsh=1", "another note")
    assert again == a  # the existing row, unchanged
    assert store.add_inspiration("https://www.instagram.com/p/P1/", "   ")["note"] is None
    with pytest.raises(ValueError, match="at most 200"):
        store.add_inspiration("https://www.instagram.com/p/P2/", "x" * 201)
    used = store.set_inspiration_status(a["id"], "used")
    assert used["status"] == "used" and used["used_at"]
    assert store.set_inspiration_status(a["id"], "new")["used_at"] is None
    with pytest.raises(ValueError, match="status must be one of"):
        store.set_inspiration_status(a["id"], "liked")
    with pytest.raises(KeyError):
        store.set_inspiration_status(999, "used")
    store.set_inspiration_status(a["id"], "dismissed")
    assert [r["url"] for r in store.list_inspirations()] == [
        "https://www.instagram.com/p/P1/", REEL]  # newest first
    assert [r["id"] for r in store.list_inspirations("dismissed")] == [a["id"]]
    assert store.delete_inspiration(a["id"])["id"] == a["id"]
    with pytest.raises(KeyError):
        store.delete_inspiration(a["id"])


async def test_mcp_doors(store, monkeypatch):
    monkeypatch.setattr(srv, "store", lambda: store)
    a = store.add_inspiration(REEL, "react to this")
    assert (await srv.list_inspirations())["inspirations"] == [a]
    assert (await srv.mark_inspiration_used(a["id"]))["status"] == "used"
    assert (await srv.list_inspirations())["inspirations"] == []
    assert len((await srv.list_inspirations(None))["inspirations"]) == 1
    with pytest.raises(srv.ToolError):
        await srv.mark_inspiration_used(999)


def test_brief_lists_new_ones_capped(store, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(B, "BIBLE_PATH", tmp_path / "BIBLE.md")
    for k in range(B.INSPIRATIONS + 2):
        store.add_inspiration(f"https://www.instagram.com/reel/R{k}/", f"note {k}")
    store.set_inspiration_status(store.list_inspirations()[0]["id"], "dismissed")
    got = B.creative_brief(store, settings, datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
                           )["inspirations"]
    assert len(got) == B.INSPIRATIONS
    assert got[0] == {"id": 21, "url": "https://www.instagram.com/reel/R20/",
                      "note": "note 20", "created_at": got[0]["created_at"]}


def test_api(store):
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as tc:
        r = tc.post("/api/inspirations", json={"url": REEL + "?igsh=1", "note": "funny"})
        assert r.status_code == 200 and r.json()["url"] == REEL
        i = r.json()["id"]
        assert tc.post("/api/inspirations", json={"url": "https://x.com/a"}).status_code == 422
        assert tc.patch(f"/api/inspirations/{i}", json={"status": "dismissed"}
                        ).json()["status"] == "dismissed"
        assert tc.patch(f"/api/inspirations/{i}", json={"status": "gone"}).status_code == 422
        assert tc.patch("/api/inspirations/999", json={"status": "used"}).status_code == 404
        assert [x["id"] for x in tc.get("/api/inspirations").json()] == [i]
        assert tc.get("/api/inspirations?status=new").json() == []
        assert tc.delete(f"/api/inspirations/{i}").status_code == 204
        assert tc.delete(f"/api/inspirations/{i}").status_code == 404
