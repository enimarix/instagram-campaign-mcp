"""Step 057: the agent sees its renders and previews as images (lavfi clips, no Remotion)."""

import base64
import json
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import src.instagram_mcp_server as srv
from src.config import InstagramMCPSettings
from src.studio import ffmpeg, frames, motion
from src.studio.assets import transition
from tests.test_studio_ffmpeg import needs_ffmpeg
from tests.test_studio_qc import make

QC_OK = {"passed": True, "checks": [], "reasons": []}


@pytest.fixture
def media(tmp_path, monkeypatch, store):
    settings = InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                                    media_root=str(tmp_path))
    monkeypatch.setattr(srv, "get_settings", lambda: settings)
    monkeypatch.setattr(srv, "store", lambda: store)
    return settings


def _asset(store, media_root, *, file=True, status="ready"):
    a = store.add_asset(store.add_idea("motion")["id"],
                        recipe={"kind": "motion", "template": "X", "props": {},
                                "thumb_offset_ms": 500})
    if file:
        (media_root / "a").mkdir(exist_ok=True)
        make(media_root / "a" / "video.mp4", size="1080x1920", duration=3, audio=None)
        store.update_asset(a["id"], file_path="a/video.mp4", duration=3.0, qc=QC_OK,
                           description="A hook card.", timeline=TIMELINE)
    if status != "rendering":
        transition(store, a["id"], status, actor="worker")
    return a["id"]


TIMELINE = [{"t": 0.0, "d": 3.0, "e": "hook card: 'Hi'"}]


def _no_ffmpeg(*a, **kw):
    raise AssertionError("ffmpeg ran on a cached call")


@needs_ffmpeg
def test_asset_frames_are_small_jpegs_and_cached(store, media, monkeypatch):
    aid = _asset(store, Path(media.media_root))
    jpegs, info = frames.asset_frames(store, media, aid)
    assert info == {"asset_id": aid, "status": "ready", "qc": "passed", "duration_s": 3.0,
                    "frame_times_s": [0.5, 0.967, 1.933, 2.9],
                    "description": "A hook card.", "timeline": TIMELINE}
    assert len(jpegs) == 4 and all(j[:2] == b"\xff\xd8" for j in jpegs)
    assert sum(map(len, jpegs)) < 400_000
    monkeypatch.setattr(ffmpeg, "run", _no_ffmpeg)
    assert frames.asset_frames(store, media, aid) == (jpegs, info)


def test_asset_frames_needs_a_file(store, media):
    with pytest.raises(ValueError, match="still rendering"):
        frames.asset_frames(store, media, _asset(store, Path(media.media_root), file=False,
                                                 status="rendering"))
    with pytest.raises(ValueError, match="failed before a file was written"):
        frames.asset_frames(store, media, _asset(store, Path(media.media_root), file=False,
                                                 status="failed"))
    with pytest.raises(ValueError, match="n must be"):
        frames.asset_frames(store, media, 1, n=20)


def _split(result):
    text, *images = result.content
    assert not result.is_error and text.type == "text"
    assert all(i.type == "image" and i.mime_type == "image/jpeg" for i in images)
    assert all(base64.b64decode(i.data)[:2] == b"\xff\xd8" for i in images)
    return json.loads(text.text), images


@needs_ffmpeg
async def test_get_asset_frames_tool_returns_images(store, media):
    aid = _asset(store, Path(media.media_root))
    agent = srv.build_server("agent")
    info, images = _split(await agent.call_tool("get_asset_frames", {"asset_id": aid, "n": 2}))
    assert len(images) == 2 and info["qc"] == "passed" and info["frame_times_s"] == [0.5, 2.9]
    bad = _asset(store, Path(media.media_root), file=False, status="rendering")
    with pytest.raises(ToolError, match="still rendering"):
        await agent.call_tool("get_asset_frames", {"asset_id": bad})


@needs_ffmpeg
async def test_preview_motion_returns_images(media, monkeypatch):
    def stills(template, props, media_root, frames_):
        folder = Path(media_root) / "previews" / "h"
        folder.mkdir(parents=True, exist_ok=True)
        for f in frames_:
            ffmpeg.run(["-f", "lavfi", "-i", "testsrc2=size=1080x1920", "-frames:v", "1",
                        folder / f"frame-{f}.png"], timeout_s=30)
        return [f"previews/h/frame-{f}.png" for f in frames_]

    monkeypatch.setattr(motion, "preview_stills", stills)
    args = {"template": "Hello", "props": {"title": "Hi"}, "frames": [0, 9]}
    info, images = _split(await srv.build_server("agent").call_tool("preview_motion", args))
    assert info == {"stills": ["previews/h/frame-0.png", "previews/h/frame-9.png"]}
    assert len(images) == 2
    assert (Path(media.media_root) / "previews/h/frame-0.png").is_file()  # kept for the website
    # A second preview of the same stills converts nothing again.
    monkeypatch.setattr(ffmpeg, "run", _no_ffmpeg)
    monkeypatch.setattr(motion, "preview_stills", lambda *a: info["stills"])
    jpegs, _ = frames.preview_images("Hello", {}, media.media_root, [0, 9])
    assert [base64.b64encode(j).decode() for j in jpegs] == [i.data for i in images]
