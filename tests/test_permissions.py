"""Permission tracker (step 065): one open request per source, the draft, answers, attach
(only once granted) turning the source into a `permission` clip, the routes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.studio import permissions, rights
from tests.test_studio_audio import make_clip
from tests.test_studio_ffmpeg import needs_ffmpeg

from .conftest import LOCAL
from .test_api_assets import _settings

KIT = {"name": "Macrobody", "handle": "@macrobody"}
REEL = "https://www.instagram.com/reel/AbC123/"


@pytest.fixture
def cfg(tmp_path):
    return _settings(media_root=str(tmp_path / "media"))


@pytest.fixture
def ref(store):
    return store.add_source("research", role="reference", url=REEL, author="ann")


def test_request_draft_and_one_open_per_source(store, ref):
    out = permissions.request_permission(store, ref["id"], "dm", " DM on 2026-11-18 ",
                                         brand_kit=KIT)
    req = out["request"]
    assert (req["status"], req["creator"], req["channel"]) == ("requested", "ann", "dm")
    assert req["proof_note"] == "DM on 2026-11-18" and req["ads_allowed"] is False
    assert req["requested_at"] and req["answered_at"] is None and req["has_file"] is False
    msg = out["draft"]["message"]
    for words in ("Hi @ann", REEL, "Macrobody (@macrobody)", "credit", "paid ad", "a no is"):
        assert words in msg
    with pytest.raises(ValueError, match="already has an open"):
        permissions.request_permission(store, ref["id"], "email", brand_kit=KIT)
    permissions.answer(store, req["id"], "denied")  # answered: a new request may start
    assert permissions.request_permission(store, ref["id"], "email", brand_kit=KIT)
    assert [r["status"] for r in permissions.list_requests(store)] == ["requested", "denied"]


def test_request_refusals_and_links(store):
    with pytest.raises(KeyError):
        permissions.request_permission(store, 999, "dm", brand_kit=KIT)
    with pytest.raises(ValueError, match="channel"):
        permissions.request_permission(store, REEL, "sms", brand_kit=KIT)
    with pytest.raises(ValueError, match="not a Reel link"):
        permissions.request_permission(store, "https://x.org/v", "dm", brand_kit=KIT)
    with pytest.raises(ValueError, match="who the creator is"):
        permissions.request_permission(store, REEL, "dm", brand_kit=KIT)
    assert store.list_sources() == []  # nothing stored for a refused request
    # an inspiration link becomes a reference source, the owner names the creator
    out = permissions.request_permission(store, REEL + "?igsh=x", "other", creator="@bob",
                                         brand_kit=KIT)
    src = store.get_source(out["request"]["source_id"])
    assert (src["role"], src["rights_basis"], src["url"]) == ("reference", "unknown", REEL)
    assert out["request"]["creator"] == "bob" and "Hi @bob" in out["draft"]["message"]
    # no creator known yet: the draft still reads
    assert "Hi there" in permissions.draft(store, "https://instagram.com/p/Zz9/",
                                           brand_kit=KIT)["message"]


def test_answers(store, ref):
    rid = permissions.request_permission(store, ref["id"], "dm", brand_kit=KIT)["request"]["id"]
    with pytest.raises(ValueError, match="status"):
        permissions.answer(store, rid, "maybe")
    with pytest.raises(ValueError, match="proof"):
        permissions.answer(store, rid, "granted", " ")
    req = permissions.answer(store, rid, "granted", "DM screenshot 2026-11-18", ads_allowed=True)
    assert req["status"] == "granted" and req["ads_allowed"] is True and req["answered_at"]
    assert store.get_source(ref["id"]) == ref  # the source changes only at attach
    with pytest.raises(ValueError, match="already answered"):
        permissions.answer(store, rid, "denied")


def test_denied_keeps_the_source_and_refuses_attach(store, cfg, ref, tmp_path):
    rid = permissions.request_permission(store, ref["id"], "dm", brand_kit=KIT)["request"]["id"]
    f = tmp_path / "c.mp4"
    f.write_bytes(b"x")
    with pytest.raises(ValueError, match="said yes"):
        permissions.attach_granted_file(store, cfg, rid, f)  # still requested
    req = permissions.answer(store, rid, "denied", "no thanks", ads_allowed=True)
    assert req["ads_allowed"] is False  # a no never allows ads
    with pytest.raises(ValueError, match="said yes"):
        permissions.attach_granted_file(store, cfg, rid, f)
    assert store.get_source(ref["id"]) == ref and f.exists()


@needs_ffmpeg
def test_attach_makes_a_permission_clip(store, cfg, ref, tmp_path):
    rid = permissions.request_permission(store, ref["id"], "email", brand_kit=KIT)["request"]["id"]
    permissions.answer(store, rid, "granted", "email from ann", ads_allowed=True)
    f = make_clip(tmp_path / "From Ann.MP4")
    with pytest.raises(ValueError, match="has sound"):
        permissions.attach_granted_file(store, cfg, rid, f)
    assert f.exists()
    src = permissions.attach_granted_file(store, cfg, rid, f, audio_rights="covered")
    assert not f.exists() and (Path(cfg.media_root) / src["local_path"]).is_file()
    assert src["local_path"] == f"sources/{ref['id']}/clip.mp4" and src["id"] == ref["id"]
    assert (src["role"], src["rights_basis"], src["author"]) == ("clip", "permission", "ann")
    assert src["rights_note"].startswith("Permission from @ann by email on 20")
    assert src["rights_note"].endswith(": email from ann")
    assert src["audio_rights"] == "covered" and src["stats"]["has_audio"] is True
    assert src["attribution"] == "Credit: ann"
    assert rights.can_publish(src) and rights.can_advertise(src)
    assert permissions.get_request(store, rid)["has_file"] is True


@needs_ffmpeg
def test_attach_removes_the_old_clip_file(store, cfg, ref, tmp_path):
    old = Path(cfg.media_root) / "sources" / str(ref["id"]) / "clip.webm"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"downloaded")
    with store._tx() as c:
        c.execute("UPDATE sources SET local_path=? WHERE id=?",
                  (f"sources/{ref['id']}/clip.webm", ref["id"]))
    rid = permissions.request_permission(store, ref["id"], "dm", brand_kit=KIT)["request"]["id"]
    permissions.answer(store, rid, "granted", "DM yes")
    src = permissions.attach_granted_file(store, cfg, rid, make_clip(tmp_path / "a.mp4"),
                                          audio_rights="covered")
    assert src["local_path"] == f"sources/{ref['id']}/clip.mp4"
    assert not old.exists() and (Path(cfg.media_root) / src["local_path"]).is_file()


@needs_ffmpeg
def test_routes(store, ref, tmp_path):
    cfg = _settings(media_root=str(tmp_path / "media"), max_clip_mb=1)
    with TestClient(create_app(cfg, store=store), base_url=LOCAL) as tc:
        r = tc.get(f"/api/permissions/draft?source_id={ref['id']}")
        assert r.status_code == 200 and "Hi @ann" in r.json()["message"]
        assert tc.get("/api/permissions/draft?url=nope").status_code == 422
        assert tc.post("/api/permissions", json={"source_id": ref["id"],
                                                 "channel": "sms"}).status_code == 422
        r = tc.post("/api/permissions", json={"source_id": ref["id"], "channel": "dm"})
        assert r.status_code == 200 and r.json()["draft"]["creator"] == "ann"
        rid = r.json()["request"]["id"]
        assert tc.post("/api/permissions", json={"source_id": ref["id"],
                                                 "channel": "dm"}).status_code == 422
        assert tc.post(f"/api/permissions/{rid}/attach?name=c.mp4",
                       content=b"x").status_code == 422  # not granted yet
        r = tc.post(f"/api/permissions/{rid}/answer",
                    json={"status": "granted", "proof_note": "DM", "ads_allowed": False})
        assert r.status_code == 200 and r.json()["status"] == "granted"
        assert tc.post("/api/permissions/999/answer", json={"status": "denied"}).status_code == 404
        assert tc.post(f"/api/permissions/{rid}/attach?name=a.txt",
                       content=b"x").status_code == 422
        assert tc.post(f"/api/permissions/{rid}/attach?name=a.mp4",
                       content=b"x" * 1_000_001).status_code == 413
        data = make_clip(tmp_path / "c.mp4").read_bytes()
        r = tc.post(f"/api/permissions/{rid}/attach?name=c.mp4&audio_rights=not_covered",
                    content=data)
        assert r.status_code == 200 and r.json()["rights_basis"] == "permission"
        assert r.json()["stats"]["original_name"] == "c.mp4"
        assert r.json()["ads_allowed"] == 0
        assert [p["has_file"] for p in tc.get("/api/permissions").json()] == [True]
        assert tc.get("/api/permissions?status=denied").json() == []
        assert list((Path(cfg.media_root) / "sources" / "uploads").iterdir()) == []
