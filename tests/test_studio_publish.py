"""Step 019a: the publish guard (queue_asset) and the worker's asset outcomes."""

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import SecretStr

import src.instagram_mcp_server as srv
from src import campaign as camp
from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.instagram_client import InstagramAPIError, InvalidMedia
from src.store import utcnow
from src.studio.assets import InvalidTransition, edit_asset, transition
from src.studio.publish import (
    QueueRefused,
    cancel_post,
    queue_asset,
    reconcile_publish_checks,
    release_publish_check,
)

from .conftest import LOCAL

LATER = timedelta(hours=2)


@pytest.fixture
def cfg(tmp_path):
    return InstagramMCPSettings(_env_file=None, database_path=":memory:",
                                media_root=str(tmp_path))


def _asset(store, cfg, status="approved", track="motion", source=None, **fields):
    """An asset walked to `status`, with a real file and QC passed unless overridden."""
    source_id = store.add_source("test", **source)["id"] if source else None
    idea = store.add_idea(track, source_id=source_id)
    rel = "2026-11-17/master.mp4"
    (Path(cfg.media_root) / rel).parent.mkdir(parents=True, exist_ok=True)
    (Path(cfg.media_root) / rel).write_bytes(b"mp4")
    fields = {"file_path": rel, "qc": {"passed": True}, "caption": "hi #demo", **fields}
    a = store.add_asset(idea["id"], **fields)
    path = {
        "rendering": [], "failed": [("failed", "worker")], "ready": [("ready", "worker")],
        "revision_requested": [("ready", "worker"), ("revision_requested", "owner")],
        "archived": [("ready", "worker"), ("archived", "owner")],
        "approved": [("ready", "worker"), ("approved", "owner")],
        "scheduled": [("ready", "worker"), ("approved", "owner"), ("scheduled", "system")],
        "publish_check": [("ready", "worker"), ("approved", "owner"), ("scheduled", "system"),
                          ("publish_check", "worker")],
        "published": [("ready", "worker"), ("approved", "owner"), ("scheduled", "system"),
                      ("published", "worker")],
    }[status]
    for to, actor in path:
        a = transition(store, a["id"], to, actor=actor)
    return a


def _refused(code, store, cfg, asset_id, **kw):
    with pytest.raises(QueueRefused) as e:
        queue_asset(store, cfg, asset_id, utcnow() + LATER, **kw)
    assert e.value.code == code, str(e.value)
    assert store.list_scheduled() == []


def test_queue_approved_asset(store, cfg):
    a = _asset(store, cfg, audio_name="Original", recipe={"thumb_offset_ms": 1500})
    post = queue_asset(store, cfg, a["id"], utcnow() + LATER)
    assert post["kind"] == "reel" and post["asset_id"] == a["id"]
    assert post["payload"] == {"video_path": a["file_path"], "caption": "hi #demo",
                               "audio_name": "Original", "thumb_offset_ms": 1500}
    assert store.get_asset(a["id"])["status"] == "scheduled"
    with pytest.raises(QueueRefused, match="scheduled"):  # queued twice
        queue_asset(store, cfg, a["id"], utcnow() + LATER)
    assert len(store.list_scheduled()) == 1


def test_every_status_but_approved_is_refused(store, cfg):  # DoD (1) and (3)
    for status in ("rendering", "failed", "ready", "revision_requested", "archived",
                   "scheduled", "publish_check", "published"):
        a = _asset(store, cfg, status=status)
        before = store.list_scheduled()
        with pytest.raises(QueueRefused) as e:
            queue_asset(store, cfg, a["id"], utcnow() + LATER)
        assert e.value.code == "not_approved", status
        assert store.list_scheduled() == before
        assert store.get_asset(a["id"])["status"] == status


def test_rights_refusals(store, cfg):  # DoD (2)
    _refused("rights", store, cfg, _asset(store, cfg, track="remix",
                                          source={"rights_basis": "unknown"})["id"])
    _refused("rights", store, cfg, _asset(store, cfg, track="remix")["id"])  # no source
    comm = _asset(store, cfg, track="remix",
                  source={"rights_basis": "commentary", "author": "@creator"})
    _refused("rights", store, cfg, comm["id"])  # not confirmed
    post = queue_asset(store, cfg, comm["id"], utcnow() + LATER, confirmed=True)
    assert post["asset_id"] == comm["id"]
    assert queue_asset(store, cfg, _asset(store, cfg)["id"], utcnow() + LATER)  # motion = own


def test_file_qc_caption_refusals(store, cfg):
    _refused("no_file", store, cfg, _asset(store, cfg, file_path=None)["id"])
    _refused("no_file", store, cfg, _asset(store, cfg, file_path="nope/x.mp4")["id"])
    _refused("no_file", store, cfg, _asset(store, cfg, file_path="../escape.mp4")["id"])
    _refused("qc", store, cfg, _asset(store, cfg, qc=None)["id"])
    _refused("qc", store, cfg, _asset(store, cfg, qc={"passed": False})["id"])
    _refused("caption", store, cfg, _asset(store, cfg, caption="#x " * 31)["id"])
    with pytest.raises(ValueError, match="future"):
        queue_asset(store, cfg, _asset(store, cfg)["id"], utcnow())


def test_lost_race_leaves_no_row(store, cfg, monkeypatch):
    a = _asset(store, cfg)
    monkeypatch.setattr(store, "_set_asset_status", lambda *a, **k: False)  # moved meanwhile
    _refused("not_approved", store, cfg, a["id"])


def test_no_api_route_can_queue(store, cfg):  # DoD (4)
    app = create_app(cfg, store=store)
    paths = list(app.openapi()["paths"])  # included routers too; the source scan below
    # also covers routes hidden from the schema
    assert "/api/assets/{asset_id}/approve" in paths
    # The owner's schedule route (023) goes through studio.scheduling -> queue_asset; the
    # calendar's (024) moves rows already queued (store.reschedule refuses a non-pending
    # asset row) and its replan re-queues an asset through scheduling too. The agent
    # schedule (061) is read-only: agent run times, no post. The feed's one-tap approve
    # (115) queues through studio.scheduling too.
    assert [p for p in paths if "schedule" in p.lower() or "queue" in p.lower()] == [
        "/api/assets/{asset_id}/approve-and-queue",
        "/api/assets/{asset_id}/schedule", "/api/assets/{asset_id}/unschedule",
        "/api/agent/schedule", "/api/posts/{post_id}/reschedule"]
    for f in (Path(__file__).parents[1] / "src" / "api").glob("*.py"):  # approving schedules nothing: test_api_assets
        text = f.read_text(encoding="utf-8")
        assert "queue_asset" not in text and ".schedule(" not in text, f


def test_caption_edit_refused_once_queued(store, cfg):  # DoD (6)
    for status in ("scheduled", "publish_check", "published"):
        a = _asset(store, cfg, status=status)
        with pytest.raises(ValueError, match=status):
            edit_asset(store, a["id"], caption="new")
        assert edit_asset(store, a["id"], best_before="2026-12-01")["best_before"]
    assert edit_asset(store, _asset(store, cfg)["id"], caption="new")["caption"] == "new"


def test_owner_cancel_returns_asset_to_approved(store, cfg):  # DoD (7)
    a = _asset(store, cfg)
    post = queue_asset(store, cfg, a["id"], utcnow() + LATER)
    assert cancel_post(store, post["id"])["status"] == "cancelled"
    assert store.get_asset(a["id"])["status"] == "approved"
    with pytest.raises(ValueError, match="queue the asset again"):
        store.reschedule(post["id"], utcnow() + LATER)
    assert queue_asset(store, cfg, a["id"], utcnow() + LATER)  # can be queued again


# ------------------------------------------------------------- run_due outcomes (DoD 5)
class FakeClient:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, 0

    async def publish_reel(self, **payload):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return {"media_id": "M1", "permalink": "https://instagram.com/p/x"}


def _due(store, cfg, **kw):
    a = _asset(store, cfg, **kw)
    post = queue_asset(store, cfg, a["id"], utcnow() + LATER)
    store.reschedule(post["id"], utcnow() - timedelta(seconds=5))  # pending: allowed
    return a, post


def _maybe():
    e = InstagramAPIError("timeout")
    e.maybe_published = True
    return e


@pytest.mark.parametrize("outcome, row, asset", [
    (None, "published", "published"),
    (InvalidMedia("bad ratio"), "failed", "approved"),
    (_maybe(), "failed", "publish_check"),
    (InstagramAPIError("server busy"), "pending", "scheduled"),  # retrying
    (RuntimeError("bug"), "failed", "publish_check"),
])
async def test_run_due_outcomes(store, cfg, outcome, row, asset):
    a, post = _due(store, cfg)
    await camp.run_due(FakeClient(outcome), store)
    assert store.get_scheduled(post["id"])["status"] == row
    assert store.get_asset(a["id"])["status"] == asset
    if row == "published":
        assert store.get_label("M1")["asset_id"] == a["id"]


async def test_run_due_skips_asset_no_longer_scheduled(store, cfg):
    a, post = _due(store, cfg)
    transition(store, a["id"], "publish_check", actor="worker")
    fake = FakeClient(None)
    res = await camp.run_due(fake, store)
    assert fake.calls == 0 and res["failed"][0]["id"] == post["id"]
    row = store.get_scheduled(post["id"])
    assert row["status"] == "cancelled" and "publish_check" in row["error"]


async def test_interrupted_publish_needs_a_check(store, cfg):
    a, post = _due(store, cfg)
    store.claim_due()
    store.mark_failed(post["id"], "Interrupted", retry_in_minutes=None)  # as recover_stuck
    await camp.run_due(FakeClient(None), store)
    assert store.get_asset(a["id"])["status"] == "publish_check"
    assert cancel_post(store, post["id"])["status"] == "cancelled"
    assert store.get_asset(a["id"])["status"] == "publish_check"  # never back to approved


# ------------------------------------------------------------- 019b: reconcile, release
class MediaClient:
    def __init__(self, *pages):
        self.pages, self.calls = list(pages), 0

    async def get_media_posts(self, limit=25, after=None):
        self.calls += 1
        posts = self.pages.pop(0) if self.pages else []
        return {"posts": posts, "next_cursor": "c" if self.pages else None}


def _reel(media_id, caption="hi #demo", at=None, kind="REELS"):
    return {"id": media_id, "caption": caption, "media_product_type": kind,
            "permalink": f"https://instagram.com/reel/{media_id}",
            "timestamp": (at or utcnow()).strftime("%Y-%m-%dT%H:%M:%S+0000")}


async def _checked(store, cfg):
    """An asset whose publish may have reached Instagram, and its failed queue row."""
    a, post = _due(store, cfg)
    await camp.run_due(FakeClient(_maybe()), store)
    assert store.get_asset(a["id"])["status"] == "publish_check"
    return a, post


async def test_reconcile_one_match_publishes(store, cfg):
    a, post = await _checked(store, cfg)
    fake = MediaClient([_reel("OTHER", "something else"), _reel("IMG", kind="FEED")],
                       [_reel("M9", "  hi\n #demo ")])  # whitespace differs, page 2
    res = await reconcile_publish_checks(fake, store)
    assert res == {"checked": 1, "published": 1, "ambiguous": 0, "not_found": 0}
    assert fake.calls == 2
    row = store.get_scheduled(post["id"])
    assert row["status"] == "published" and row["media_id"] == "M9"
    assert row["permalink"].endswith("/M9")
    assert store.get_label("M9")["asset_id"] == a["id"]
    assert store.get_asset(a["id"])["status"] == "published"


@pytest.mark.parametrize("posts, key", [
    ([], "not_found"),
    ([_reel("M1", at=utcnow() - timedelta(hours=60))], "not_found"),  # outside the window
    ([_reel("M1"), _reel("M2")], "ambiguous"),
])
async def test_reconcile_leaves_unsure_assets(store, cfg, posts, key):
    a, post = await _checked(store, cfg)
    res = await reconcile_publish_checks(MediaClient(posts), store)
    assert res["checked"] == 1 and res[key] == 1 and res["published"] == 0
    assert store.get_asset(a["id"])["status"] == "publish_check"
    assert store.get_scheduled(post["id"])["status"] == "failed"


async def test_reconcile_without_checks_makes_no_call(store, cfg):
    fake = MediaClient([_reel("M1")])
    assert (await reconcile_publish_checks(fake, store))["checked"] == 0
    assert fake.calls == 0


async def test_release_publish_check(store, cfg):
    a, _ = await _checked(store, cfg)
    assert release_publish_check(store, a["id"])["status"] == "approved"
    with pytest.raises(InvalidTransition):  # approved now
        release_publish_check(store, a["id"])
    assert queue_asset(store, cfg, a["id"], utcnow() + LATER)  # can be queued again


def test_release_route(store, cfg):
    a = _asset(store, cfg, status="publish_check")
    ready = _asset(store, cfg, status="ready")
    with TestClient(create_app(cfg, store=store), base_url=LOCAL) as c:
        r = c.post(f"/api/assets/{a['id']}/release", headers={"Origin": LOCAL})
        assert r.status_code == 200 and r.json()["status"] == "approved"
        r = c.post(f"/api/assets/{ready['id']}/release", headers={"Origin": LOCAL})
        assert r.status_code == 409 and r.json()["error"] == "invalid_transition"
        assert c.post("/api/assets/999/release", headers={"Origin": LOCAL}).status_code == 404


def test_release_route_needs_session_with_password(store, cfg):
    a = _asset(store, cfg, status="publish_check")
    s = cfg.model_copy(update={"ui_password": SecretStr("pw")})
    with TestClient(create_app(s, store=store), base_url=LOCAL) as c:
        url, h = f"/api/assets/{a['id']}/release", {"Origin": LOCAL}
        assert c.post(url, headers=h).status_code == 401
        assert c.post("/api/login", json={"password": "pw"}, headers=h).status_code == 200
        assert c.post(url, headers=h).json()["status"] == "approved"


# ------------------------------------------------------------- 019b: MCP bypass closed
class ReelClient:
    def __init__(self):
        self.paths = []

    async def publish_reel(self, *args, video_path=None, **kw):
        self.paths.append(video_path)
        return {"media_id": "M1", "permalink": None}


@pytest.fixture
def mcp_env(store, cfg, monkeypatch):
    fake = ReelClient()
    monkeypatch.setattr(srv, "_store", store)
    monkeypatch.setattr(srv, "_client", fake)
    monkeypatch.setattr(srv, "get_settings", lambda: cfg)
    return fake


async def test_mcp_tools_refuse_asset_files(store, cfg, mcp_env):
    a = _asset(store, cfg, preview_path="2026-11-17/preview.mp4")
    for path in (a["file_path"], "2026-11-17/./master.mp4", a["preview_path"]):
        with pytest.raises(ToolError, match="queue the asset from the website"):
            await srv.publish_reel(video_path=path)
        with pytest.raises(ToolError, match="queue the asset from the website"):
            await srv.schedule_post("reel", (utcnow() + LATER).isoformat(), "hi",
                                    video_path=path)
    assert mcp_env.paths == [] and store.list_scheduled() == []


async def test_mcp_tools_allow_other_media_files(store, cfg, mcp_env):
    _asset(store, cfg)
    (Path(cfg.media_root) / "own.mp4").write_bytes(b"mp4")
    assert (await srv.publish_reel(video_path="own.mp4"))["media_id"] == "M1"
    assert mcp_env.paths == ["own.mp4"]
    post = await srv.schedule_post("reel", (utcnow() + LATER).isoformat(), "hi",
                                   video_path="own.mp4")
    assert post["payload"]["video_path"] == "own.mp4"
