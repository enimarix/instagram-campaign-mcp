"""Step 063b: Reel downloads (studio/downloader.py, route). The service and the CDN are
respx mocks; yt-dlp is a fake module in sys.modules. No network, no real account."""

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.store import to_iso
from src.studio import downloader as D

from .conftest import LOCAL

REEL = "https://www.instagram.com/reel/ABC123/"
API = "http://127.0.0.1:3711/api/video"
CDN = "https://scontent-cdg4-1.cdninstagram.com/v/t50/clip.mp4?sig=1"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
TOKEN = "secret-brand-token"
VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"v" * 5000


@pytest.fixture
def cfg(tmp_path):
    return InstagramMCPSettings(_env_file=None, database_path=":memory:",
                                media_root=str(tmp_path / "media"),
                                instagram_access_token=TOKEN, download_delay_s=0,
                                max_download_mb=1)


def answer(**over):
    data = {"title": "the caption", "view_count": 120000, "like_count": 9000, "duration": 14.5,
            "owner": {"username": "creator.one", "is_private": False},
            "medias": [{"type": "video", "url": CDN}]}
    data.update(over)
    return httpx.Response(200, json={"success": True, "message": "success", "data": data})


class FakeYDL:
    """yt_dlp.YoutubeDL: returns `info` (or raises `error`), records its options."""
    info: dict = {}
    error = None
    opts: list = []

    def __init__(self, opts):
        FakeYDL.opts.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download):
        assert download is False  # only the info: our code fetches the file
        if FakeYDL.error:
            raise FakeYDL.error
        return FakeYDL.info


@pytest.fixture
def ytdlp(monkeypatch):
    mod = types.ModuleType("yt_dlp")
    mod.YoutubeDL = FakeYDL
    ver = types.ModuleType("yt_dlp.version")
    ver.__version__ = "2026.10.26"
    monkeypatch.setitem(sys.modules, "yt_dlp", mod)
    monkeypatch.setitem(sys.modules, "yt_dlp.version", ver)
    FakeYDL.info = {"channel": "creator.one", "description": "yt caption", "duration": 14.5,
                    "view_count": 5, "like_count": 2,
                    "formats": [{"url": "https://x.fbcdn.net/dash.mp4", "vcodec": "avc1",
                                 "acodec": "none", "height": 1920},
                                {"url": "https://x.fbcdn.net/full.mp4", "vcodec": "avc1",
                                 "acodec": "mp4a", "height": 1280}]}
    FakeYDL.error, FakeYDL.opts = None, []
    return FakeYDL


@pytest.fixture
def no_ytdlp(monkeypatch):
    monkeypatch.setitem(sys.modules, "yt_dlp", None)  # import raises ImportError


def run(store, cfg, target=REEL, **kw):
    return D.download_reel(store, cfg, target, now=kw.pop("now", NOW), **kw)


def no_token_sent():
    for call in respx.calls:
        assert TOKEN not in str(call.request.url)
        assert all(TOKEN not in v for v in call.request.headers.values())


@respx.mock
def test_success_stores_every_field(store, cfg, no_ytdlp):
    svc = respx.get(API).mock(return_value=answer())
    respx.get(CDN).mock(return_value=httpx.Response(200, content=VIDEO))
    r = run(store, cfg, "https://instagram.com/reels/ABC123?igsh=x")
    assert (r["status"], r["provider"]) == ("downloaded", "reels_downloader")
    assert dict(svc.calls.last.request.url.params) == {"postUrl": REEL, "enhanced": "true"}
    s = r["source"]
    assert (s["provider"], s["role"], s["url"], s["author"]) == (
        "instagram_reel", "clip", REEL, "creator.one")
    assert (s["rights_basis"], s["audio_rights"]) == ("commentary", "not_covered")
    assert "@creator.one" in s["rights_note"] and "commentary" in s["rights_note"]
    assert s["local_path"] == f"sources/{s['id']}/clip.mp4"
    assert (Path(cfg.media_root) / s["local_path"]).read_bytes() == VIDEO
    assert s["downloaded_at"] == to_iso(NOW)
    assert s["downloader_version"].startswith("reels_downloader ")
    assert s["stats"] == {"permalink": REEL, "caption": "the caption", "views": 120000,
                          "likes": 9000, "duration_s": 14.5, "size_bytes": len(VIDEO)}
    no_token_sent()


@respx.mock
@pytest.mark.parametrize("resp, reason", [
    (httpx.Response(400, json={"status": "error", "message": "This post is not a video"}),
     "not a video"),
    (answer(owner={"username": "x", "is_private": True}), "private account"),
    (answer(medias=[]), "not a video"),
])
def test_private_or_non_video_refused_without_fallback(store, cfg, ytdlp, resp, reason):
    respx.get(API).mock(return_value=resp)
    r = run(store, cfg)
    assert (r["status"], r["reason"]) == ("refused", reason)
    assert r["source"]["local_path"] is None and r["source"]["rights_basis"] == "unknown"
    assert reason in r["source"]["stats"]["download_error"]
    assert FakeYDL.opts == []  # a refusal is final


def test_not_a_reel_link_is_refused(store, cfg):
    for bad in ("https://www.instagram.com/stories/x/1/", "https://evil.com/reel/A/", "", "x"):
        with pytest.raises(ValueError, match="not a Reel link"):
            run(store, cfg, bad)
    with pytest.raises(KeyError):
        run(store, cfg, 999)
    assert store.list_sources() == []


@respx.mock
def test_service_down_falls_back_to_ytdlp_with_the_cookies(store, cfg, ytdlp, tmp_path):
    cfg = cfg.model_copy(update={"downloader_cookies_file": str(tmp_path / "personal.txt")})
    respx.get(API).mock(side_effect=httpx.ConnectError("refused"))
    full = respx.get("https://x.fbcdn.net/full.mp4").mock(
        return_value=httpx.Response(200, content=VIDEO))
    r = run(store, cfg)
    assert (r["status"], r["provider"]) == ("downloaded", "ytdlp")
    assert full.called  # the best format with picture AND sound
    assert r["source"]["downloader_version"] == "ytdlp 2026.10.26"
    assert r["source"]["stats"]["caption"] == "yt caption"
    assert FakeYDL.opts[0]["cookiefile"] == cfg.downloader_cookies_file
    assert TOKEN not in repr(FakeYDL.opts)
    no_token_sent()


@respx.mock
def test_only_ytdlp_gets_cookies_and_none_by_default(store, cfg, ytdlp):
    respx.get(API).mock(return_value=httpx.Response(500, json={"status": "error"}))
    respx.get("https://x.fbcdn.net/full.mp4").mock(return_value=httpx.Response(200, content=VIDEO))
    assert run(store, cfg)["status"] == "downloaded"
    assert "cookiefile" not in FakeYDL.opts[0]


@respx.mock
def test_ytdlp_dash_only_is_a_failure_not_a_refusal(store, cfg, ytdlp):
    respx.get(API).mock(side_effect=httpx.ConnectError("refused"))
    FakeYDL.info["formats"] = FakeYDL.info["formats"][:1]
    r = run(store, cfg)
    assert r["status"] == "failed" and "no single file" in r["reason"]


@respx.mock
def test_both_down_records_why_on_the_source(store, cfg, no_ytdlp):
    respx.get(API).mock(side_effect=httpx.ConnectError("refused"))
    r = run(store, cfg)
    assert r["status"] == "failed" and "inbox" in r["reason"]
    err = store.get_source(r["source"]["id"])["stats"]["download_error"]
    assert "not running" in err and "yt-dlp is not installed" in err
    # a later success clears the error
    respx.get(API).mock(return_value=answer())
    respx.get(CDN).mock(return_value=httpx.Response(200, content=VIDEO))
    again = run(store, cfg)
    assert again["source"]["id"] == r["source"]["id"]
    assert "download_error" not in again["source"]["stats"]


@respx.mock
@pytest.mark.parametrize("video_url", [
    "https://evil.com/clip.mp4", "http://scontent.cdninstagram.com/clip.mp4",
    "https://cdninstagram.com.evil.com/clip.mp4", "https://evilfbcdn.net/clip.mp4"])
def test_non_cdn_video_host_refused(store, cfg, no_ytdlp, video_url):
    respx.get(API).mock(return_value=answer(medias=[{"type": "video", "url": video_url}]))
    r = run(store, cfg)
    assert r["status"] == "failed" and "not Instagram's CDN" in r["reason"]
    assert [c.request.url.host for c in respx.calls] == ["127.0.0.1"]  # never fetched


def test_cdn_hosts():
    assert D.cdn_ok("https://scontent.cdninstagram.com/a.mp4")
    assert D.cdn_ok("https://video.xx.fbcdn.net/a.mp4")
    assert not D.cdn_ok("https://fbcdn.net.evil.com/a.mp4")


@respx.mock
def test_size_cap_mid_stream_removes_the_partial_file(store, cfg, no_ytdlp):
    respx.get(API).mock(return_value=answer())
    big = (b"x" * 400_000 for _ in range(4))  # 1.6 MB, no content-length
    respx.get(CDN).mock(return_value=httpx.Response(200, content=big))
    r = run(store, cfg)
    assert r["status"] == "failed" and "larger than 1 MB" in r["reason"]
    folder = Path(cfg.media_root) / "sources" / str(r["source"]["id"])
    assert list(folder.iterdir()) == []


@respx.mock
def test_daily_cap_and_delay(store, cfg, no_ytdlp):
    cfg = cfg.model_copy(update={"max_downloads_per_day": 2, "download_delay_s": 5})
    respx.get(API).mock(return_value=answer())
    respx.get(CDN).mock(return_value=httpx.Response(200, content=VIDEO))
    slept = []
    yesterday = to_iso(NOW - timedelta(days=1))
    store.add_source("x", downloaded_at=yesterday)  # not today (owner-local): not counted
    assert run(store, cfg, sleep=slept.append)["status"] == "downloaded"
    assert slept == []
    r = run(store, cfg, "https://www.instagram.com/reel/B2/", sleep=slept.append,
            now=NOW + timedelta(seconds=2))
    assert r["status"] == "downloaded" and slept == [3.0]
    assert r["source"]["downloaded_at"] == to_iso(NOW + timedelta(seconds=5))
    capped = run(store, cfg, "https://www.instagram.com/reel/C3/", sleep=slept.append)
    assert (capped["status"], capped["source"]) == ("refused", None)
    assert "daily cap reached (2" in capped["reason"]
    assert len(store.list_sources()) == 3  # no row for the capped Reel


@respx.mock
def test_same_url_reuses_the_source(store, cfg, no_ytdlp):
    ref, _ = store.upsert_reference_source("instagram", "1789", url=REEL, author=None,
                                           stats={"views": 10})
    respx.get(API).mock(return_value=answer(view_count=None))
    respx.get(CDN).mock(return_value=httpx.Response(200, content=VIDEO))
    r = run(store, cfg, ref["id"])  # a trend result, by source id
    s = r["source"]
    assert s["id"] == ref["id"] and (s["role"], s["provider"]) == ("clip", "instagram")
    assert (s["stats"]["views"], s["stats"]["likes"]) == (10, 9000)  # research's views kept
    again = run(store, cfg, "https://www.instagram.com/p/ABC123/")
    assert (again["status"], again["source"]["id"]) == ("exists", ref["id"])
    assert len(respx.calls) == 2 and len(store.list_sources()) == 1


def _pick(store, msg, url):
    with store._tx() as c:
        return c.execute(
            "INSERT INTO dm_picks (message_id, sender_username, reel_url, received_at,"
            " created_at, updated_at) VALUES (?, 'friend', ?, 't', 't', 't')",
            (msg, url)).lastrowid


@respx.mock
def test_dm_pick_marked_downloaded_or_skipped(store, cfg, no_ytdlp):
    ok = _pick(store, "m1", "https://www.instagram.com/reel/ABC123/?igsh=1")
    bad = _pick(store, "m2", "https://www.instagram.com/reel/PRIV/")
    other = _pick(store, "m3", "https://scontent.cdninstagram.com/x.mp4")
    respx.get(API, params={"postUrl": REEL}).mock(return_value=answer())
    respx.get(API, params={"postUrl": "https://www.instagram.com/reel/PRIV/"}).mock(
        return_value=answer(owner={"username": "p", "is_private": True}))
    respx.get(CDN).mock(return_value=httpx.Response(200, content=VIDEO))
    r = run(store, cfg, "https://www.instagram.com/reel/ABC123/?igsh=1")
    pick = store._get("dm_picks", ok)
    assert (pick["status"], pick["source_id"]) == ("downloaded", r["source"]["id"])
    run(store, cfg, "https://www.instagram.com/reel/PRIV/")
    pick = store._get("dm_picks", bad)
    assert (pick["status"], pick["skip_reason"]) == ("skipped", "private account")
    assert store._get("dm_picks", other)["status"] == "new"


@respx.mock
def test_route(store, cfg, no_ytdlp):
    respx.get(API).mock(return_value=answer())
    respx.get(CDN).mock(return_value=httpx.Response(200, content=VIDEO))
    with TestClient(create_app(cfg, store=store), base_url=LOCAL) as tc:
        r = tc.post("/api/sources/download", json={"url": REEL})
        assert r.status_code == 200 and r.json()["status"] == "downloaded"
        sid = r.json()["source"]["id"]
        assert tc.post("/api/sources/download", json={"source_id": sid}).json()["status"] == "exists"
        assert tc.post("/api/sources/download", json={"source_id": 999}).status_code == 404
        bad = tc.post("/api/sources/download", json={"url": "https://x.com/a"})
        assert bad.status_code == 422 and "not a Reel link" in bad.json()["message"]
        assert tc.post("/api/sources/download", json={}).status_code == 422
        assert tc.post("/api/sources/download", json={"x": 1}).status_code == 422


@respx.mock
async def test_mcp_tool(store, cfg, no_ytdlp, monkeypatch):
    import src.instagram_mcp_server as srv
    monkeypatch.setattr(srv, "store", lambda: store)
    monkeypatch.setattr(srv, "get_settings", lambda: cfg)
    respx.get(API).mock(return_value=answer())
    respx.get(CDN).mock(return_value=httpx.Response(200, content=VIDEO))
    r = await srv.download_reel(REEL)
    assert r["status"] == "downloaded" and r["source"]["author"] == "creator.one"
    assert (await srv.download_reel(r["source"]["id"]))["status"] == "exists"
    with pytest.raises(srv.ToolError, match="not a Reel link"):
        await srv.download_reel("https://x.com/a")
