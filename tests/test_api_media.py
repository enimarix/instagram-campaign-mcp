"""Step 011: media layout helper and GET /api/media (Range, traversal, session)."""

import os
from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.studio.media import asset_dir, media_url, relative, resolve

from .conftest import LOCAL

DATA = bytes(range(256)) * 4  # 1024 bytes, every offset distinguishable


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "media"
    folder = asset_dir(root, date(2026, 11, 17), 12)
    (folder / "preview.mp4").write_bytes(DATA)
    (folder / "thumb.webp").write_bytes(b"RIFF")
    (tmp_path / "secret.txt").write_text("outside")
    return root


def _settings(root, **kw):
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                                database_path=":memory:", media_root=str(root), **kw)


@pytest.fixture
def tc(root, store):
    with TestClient(create_app(_settings(root), store=store), base_url=LOCAL) as c:
        yield c


def test_helper_layout_and_round_trip(root, tmp_path):
    folder = asset_dir(root, "2026-11-17", 12)
    assert folder == root / "2026-11-17" / "12" and folder.is_dir()
    rel = relative(root, folder / "preview.mp4")
    assert rel == "2026-11-17/12/preview.mp4"
    assert resolve(root, rel) == (folder / "preview.mp4").resolve()
    assert media_url(rel) == "/api/media/2026-11-17/12/preview.mp4"
    assert media_url(None) is None and media_url("") is None
    with pytest.raises(ValueError):
        relative(root, tmp_path / "secret.txt")
    for bad in ("../secret.txt", "a/../../secret.txt", "/etc/passwd", "C:/Windows/win.ini",
                "C:secret", "..\\secret.txt", "a\\..\\..\\secret.txt", "", "a\0b"):
        with pytest.raises(ValueError):
            resolve(root, bad)


def test_full_file_and_content_types(tc):
    r = tc.get("/api/media/2026-11-17/12/preview.mp4")
    assert r.status_code == 200 and r.content == DATA
    assert r.headers["content-type"] == "video/mp4"
    assert r.headers["accept-ranges"] == "bytes"
    assert tc.get("/api/media/2026-11-17/12/thumb.webp").headers["content-type"] == "image/webp"


def test_range_requests(tc):
    url = "/api/media/2026-11-17/12/preview.mp4"
    r = tc.get(url, headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and r.content == DATA[100:200]
    assert r.headers["content-range"] == "bytes 100-199/1024"
    assert r.headers["accept-ranges"] == "bytes"
    r = tc.get(url, headers={"Range": "bytes=1000-"})  # open-ended: the player's first seek
    assert r.status_code == 206 and r.content == DATA[1000:]
    assert r.headers["content-range"] == "bytes 1000-1023/1024"
    assert tc.get(url, headers={"Range": "bytes=5000-"}).status_code == 416


def test_missing_file_is_json_404(tc):
    for url in ("/api/media/2026-11-17/12/nope.mp4", "/api/media/2026-11-17/12"):
        r = tc.get(url)
        assert r.status_code == 404 and r.json() == {"error": "not_found"}


@pytest.mark.parametrize("url", [
    "/api/media/..%2f..%2fsecret.txt",
    "/api/media/2026-11-17/%2e%2e/%2e%2e/%2e%2e/secret.txt",
    "/api/media/..%5csecret.txt",
    "/api/media/2026-11-17%5c..%5c..%5csecret.txt",
    "/api/media/%2fetc%2fpasswd",
    "/api/media//etc/passwd",
    "/api/media/C:%5cWindows%5cwin.ini",
    "/api/media/C:/Windows/win.ini",
])
def test_traversal_never_leaves_the_root(tc, url):
    r = tc.get(url)
    assert r.status_code == 400  # refused by the resolver, not by luck of routing
    assert b"outside" not in r.content and "error" in r.json()


def test_symlink_out_of_root_refused(tc, root, tmp_path):
    try:
        os.symlink(tmp_path / "secret.txt", root / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("no symlink rights on this OS/account")
    r = tc.get("/api/media/link.txt")
    assert r.status_code == 400 and b"outside" not in r.content


def test_media_needs_session_with_password(root, store):
    with TestClient(create_app(_settings(root, ui_password="pw"), store=store),
                    base_url=LOCAL) as c:
        url = "/api/media/2026-11-17/12/preview.mp4"
        assert c.get(url).status_code == 401
        assert c.post("/api/login", json={"password": "pw"},
                      headers={"Origin": LOCAL}).status_code == 200
        assert c.get(url).content == DATA


def test_asset_responses_carry_media_urls(tc, store):
    idea = store.add_idea("motion")
    a = store.add_asset(idea["id"], file_path="2026-11-17/12/master.mp4",
                        preview_path="2026-11-17/12/preview.mp4")
    listed = tc.get("/api/assets").json()[0]
    assert listed["preview_url"] == "/api/media/2026-11-17/12/preview.mp4"
    assert listed["file_url"] == "/api/media/2026-11-17/12/master.mp4"
    assert listed["thumbnail_url"] is None
    one = tc.get(f"/api/assets/{a['id']}").json()
    assert one["preview_url"] == listed["preview_url"]
    assert tc.get(one["preview_url"]).content == DATA
