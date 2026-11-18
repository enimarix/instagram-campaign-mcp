"""Step 064: Pexels stock clips (studio/stock.py, routes, MCP tools). Pexels and its file
hosts are respx mocks; the downloaded clip is a small ffmpeg (lavfi) video."""

import logging
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

import src.instagram_mcp_server as srv
from src.api.app import create_app
from src.studio import rights, stock
from tests.test_studio_audio import make_clip
from tests.test_studio_ffmpeg import needs_ffmpeg

from .conftest import LOCAL
from .test_api_assets import _settings

KEY = "pexels-secret-key-123"
SEARCH = "https://api.pexels.com/v1/videos/search"
VIDEO_API = "https://api.pexels.com/v1/videos/videos/42"
HD = "https://videos.pexels.com/video-files/42/42-hd_1080_1920_30fps.mp4"
UHD = "https://videos.pexels.com/video-files/42/42-uhd_2160_3840_30fps.mp4"
SD = "https://videos.pexels.com/video-files/42/42-sd_540_960_30fps.mp4"


def video(id=42, duration=12, files=None):
    return {"id": id, "width": 1080, "height": 1920, "duration": duration,
            "url": f"https://www.pexels.com/video/gym-{id}/",
            "image": f"https://images.pexels.com/videos/{id}/pictures/preview-0.jpg",
            "user": {"id": 7, "name": "Ann Lee", "url": "https://www.pexels.com/@ann"},
            "video_files": files if files is not None else [
                {"id": 1, "quality": "uhd", "file_type": "video/mp4", "width": 2160,
                 "height": 3840, "link": UHD},
                {"id": 2, "quality": "hd", "file_type": "video/mp4", "width": 1080,
                 "height": 1920, "link": HD},
                {"id": 3, "quality": "sd", "file_type": "video/mp4", "width": 540,
                 "height": 960, "link": SD},
                {"id": 4, "quality": "hd", "file_type": "video/mp4", "width": 1920,
                 "height": 1080, "link": HD + "?landscape"}]}


@pytest.fixture
def cfg(tmp_path):
    return _settings(media_root=str(tmp_path / "media"), pexels_api_key=KEY)


@pytest.fixture(scope="module")
def clip_bytes(tmp_path_factory):
    path = tmp_path_factory.mktemp("stock") / "c.mp4"
    return make_clip(path, audio=False).read_bytes()


def test_pick_files_prefers_portrait_up_to_1920():
    files = stock.normalise(video())["files"]
    assert [f["link"] for f in stock.pick_files(files)] == [HD, SD, UHD]
    assert stock.pick_files([{"file_type": "video/mp4", "width": 1920, "height": 1080,
                              "link": HD}]) == []


def test_file_hosts():
    assert stock.file_host_ok(HD) and stock.file_host_ok("https://player.vimeo.com/x.mp4")
    for bad in ("http://videos.pexels.com/a.mp4", "https://evil.com/videos.pexels.com.mp4",
                "https://pexels.com.evil.com/a.mp4", "https://vimeo.com/a.mp4"):
        assert not stock.file_host_ok(bad)


@respx.mock
def test_search_normalises_and_filters_by_duration(store, cfg, caplog):
    caplog.set_level(logging.DEBUG)
    route = respx.get(SEARCH).mock(return_value=httpx.Response(
        200, json={"videos": [video(1, 5), video(2, 12), video(3, 40)]}))
    out = stock.search(store, cfg, " gym ", min_duration=6, max_duration=30, per_page=20)
    assert [v["id"] for v in out] == [2]
    assert out[0] | {"files": None} == {
        "id": 2, "url": "https://www.pexels.com/video/gym-2/", "author": "Ann Lee",
        "author_url": "https://www.pexels.com/@ann", "duration_s": 12, "width": 1080,
        "height": 1920, "image": "https://images.pexels.com/videos/2/pictures/preview-0.jpg",
        "files": None}
    assert out[0]["files"][1] == {"quality": "hd", "file_type": "video/mp4", "width": 1080,
                                  "height": 1920, "link": HD}
    req = route.calls.last.request
    assert req.headers["Authorization"] == KEY  # header auth, never the URL
    assert KEY not in str(req.url)
    assert dict(req.url.params) == {"query": "gym", "orientation": "portrait",
                                    "size": "medium", "per_page": "20", "page": "1"}
    assert KEY not in caplog.text


@pytest.mark.parametrize("status, message", [(401, "refused the API key"),
                                             (429, "rate limit"), (500, "HTTP 500")])
@respx.mock
def test_search_errors(store, cfg, status, message):
    respx.get(SEARCH).mock(return_value=httpx.Response(status, json={"error": "x"}))
    with pytest.raises(ValueError, match=message):
        stock.search(store, cfg, "gym")


def test_not_configured(store, tmp_path):
    for key in (None, "  "):
        cfg = _settings(media_root=str(tmp_path), pexels_api_key=key)
        assert not stock.configured(cfg)
        with pytest.raises(stock.NotConfigured, match="PEXELS_API_KEY"):
            stock.search(store, cfg, "gym")
        with pytest.raises(stock.NotConfigured):
            stock.add_clip(store, cfg, 42)


@needs_ffmpeg
@respx.mock
def test_ingest_records_licence_credit_and_ads(store, cfg, clip_bytes):
    api = respx.get(VIDEO_API).mock(return_value=httpx.Response(200, json=video()))
    hd = respx.get(HD).mock(return_value=httpx.Response(200, content=clip_bytes))
    clip = stock.add_clip(store, cfg, 42)
    assert hd.called and not respx.get(UHD).called
    assert api.calls.last.request.headers["Authorization"] == KEY
    assert all(KEY not in str(c.request.url) and "authorization" not in c.request.headers
               for c in hd.calls)  # the key never leaves for the file host
    assert clip["provider"] == "pexels" and clip["external_id"] == "42"
    assert clip["rights_basis"] == "licensed" and clip["audio_rights"] == "no_audio"
    assert clip["author"] == "Ann Lee" and clip["url"] == "https://www.pexels.com/video/gym-42/"
    assert clip["licence"] == "Pexels License" and clip["ads_allowed"] is True
    assert clip["attribution"] == "Video by Ann Lee on Pexels"
    assert "Pexels License" in clip["rights_note"]
    assert rights.can_publish(clip) and rights.can_advertise(clip)
    assert (Path(cfg.media_root) / clip["local_path"]).is_file()
    assert list(Path(cfg.media_root).glob(".stock-*")) == []  # temp folder gone
    # the same video again: the stored clip, no second download
    assert stock.add_clip(store, cfg, 42)["id"] == clip["id"] and hd.call_count == 1


@needs_ffmpeg
@respx.mock
def test_ingest_size_cap_falls_back_to_a_smaller_file(store, tmp_path, clip_bytes):
    cfg = _settings(media_root=str(tmp_path / "m"), pexels_api_key=KEY,
                    max_clip_mb=(len(clip_bytes) + 1) / 1e6)
    respx.get(VIDEO_API).mock(return_value=httpx.Response(200, json=video()))
    respx.get(HD).mock(return_value=httpx.Response(200, content=clip_bytes + b"x" * 10))
    sd = respx.get(SD).mock(return_value=httpx.Response(200, content=clip_bytes))
    assert stock.add_clip(store, cfg, 42)["rights_basis"] == "licensed" and sd.called

    cfg = _settings(media_root=str(tmp_path / "m2"), pexels_api_key=KEY, max_clip_mb=0.0001)
    respx.get(UHD).mock(return_value=httpx.Response(200, content=clip_bytes))
    store2 = type(store)(":memory:")
    with pytest.raises(ValueError, match="larger than"):
        stock.add_clip(store2, cfg, 42)
    assert store2.list_sources() == []


@respx.mock
def test_ingest_refuses_other_hosts_and_no_portrait(store, cfg):
    evil = "https://cdn.evil.com/42.mp4"
    files = [{"file_type": "video/mp4", "width": 1080, "height": 1920, "link": evil}]
    respx.get(VIDEO_API).mock(return_value=httpx.Response(200, json=video(files=files)))
    other = respx.get(evil).mock(return_value=httpx.Response(200, content=b"x"))
    with pytest.raises(ValueError, match="not a Pexels file host"):
        stock.add_clip(store, cfg, 42)
    assert not other.called and store.list_sources() == []

    respx.get(VIDEO_API).mock(return_value=httpx.Response(200, json=video(files=[])))
    with pytest.raises(ValueError, match="no portrait file"):
        stock.add_clip(store, cfg, 42)
    respx.get(VIDEO_API).mock(return_value=httpx.Response(404, json={}))
    with pytest.raises(KeyError):
        stock.add_clip(store, cfg, 42)


@respx.mock
def test_routes(store, cfg, tmp_path):
    respx.get(SEARCH).mock(return_value=httpx.Response(200, json={"videos": [video()]}))
    with TestClient(create_app(cfg, store=store), base_url=LOCAL) as tc:
        assert tc.get("/api/stock").json() == {"configured": True, "provider": "pexels"}
        r = tc.get("/api/stock/search", params={"q": "gym"})
        assert r.status_code == 200 and r.json()[0]["author"] == "Ann Lee"
        assert tc.get("/api/stock/search").status_code == 422
        respx.get(VIDEO_API).mock(return_value=httpx.Response(404, json={}))
        assert tc.post("/api/stock/add", json={"result_id": 42}).status_code == 404
        assert tc.post("/api/stock/add", json={"result_id": "x"}).status_code == 422
    off = _settings(media_root=str(tmp_path / "off"))
    with TestClient(create_app(off, store=store), base_url=LOCAL) as tc:
        assert tc.get("/api/stock").json()["configured"] is False
        r = tc.get("/api/stock/search", params={"q": "gym"})
        assert r.status_code == 503 and r.json()["error"] == "stock_not_configured"
        assert tc.post("/api/stock/add", json={"result_id": 42}).status_code == 503


@respx.mock
async def test_mcp_tools(monkeypatch, store, cfg):
    monkeypatch.setattr(srv, "store", lambda: store)
    monkeypatch.setattr(srv, "get_settings", lambda: cfg)
    respx.get(SEARCH).mock(return_value=httpx.Response(200, json={"videos": [video()]}))
    out = await srv.search_stock("gym", max_duration_s=30)
    assert [v["id"] for v in out["results"]] == [42]
    monkeypatch.setattr(srv, "get_settings", lambda: _settings(media_root=cfg.media_root))
    with pytest.raises(ToolError, match="PEXELS_API_KEY"):
        await srv.add_stock_clip(42)
