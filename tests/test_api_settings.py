"""Step 028: GET /api/storage (media/db sizes, one-minute walk cache, session)."""

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.studio import storage

from .conftest import LOCAL

ORIGIN = {"Origin": LOCAL}


def _settings(tmp_path, **kw):
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                                database_path=str(tmp_path / "studio.db"),
                                media_root=str(tmp_path / "media"), **kw)


def test_sizes_and_cache(tmp_path):
    media = tmp_path / "media"
    (media / "2026-11-17" / "12").mkdir(parents=True)
    (media / "2026-11-17" / "12" / "video.mp4").write_bytes(b"x" * 1000)
    (media / "poster.jpg").write_bytes(b"y" * 24)
    (tmp_path / "studio.db").write_bytes(b"d" * 300)
    (tmp_path / "studio.db-wal").write_bytes(b"w" * 50)
    t = [0.0]
    out = storage.storage(str(media), str(tmp_path / "studio.db"), clock=lambda: t[0])
    assert out["media_bytes"] == 1024 and out["db_bytes"] == 350
    assert out["free_bytes"] > 0 and out["last_backup"] is None

    (media / "new.mp4").write_bytes(b"z" * 100)
    t[0] = 59.0  # within the minute: the cached walk
    assert storage.storage(str(media), ":memory:", clock=lambda: t[0])["media_bytes"] == 1024
    t[0] = 61.0
    out = storage.storage(str(media), ":memory:", clock=lambda: t[0])
    assert out["media_bytes"] == 1124 and out["db_bytes"] == 0


def test_missing_media_root(tmp_path):
    out = storage.storage(str(tmp_path / "not" / "yet"), str(tmp_path / "none.db"))
    assert out["media_bytes"] == 0 and out["db_bytes"] == 0 and out["free_bytes"] > 0


def test_route_needs_a_session(tmp_path, store):
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "a.mp4").write_bytes(b"x" * 10)
    with TestClient(create_app(_settings(tmp_path, ui_password="pw"), store=store),
                    base_url=LOCAL) as tc:
        assert tc.get("/api/storage").status_code == 401
        assert tc.post("/api/login", json={"password": "pw"}, headers=ORIGIN).status_code == 200
        r = tc.get("/api/storage")
        assert r.status_code == 200
        assert r.json()["media_bytes"] == 10 and set(r.json()) == {
            "media_bytes", "db_bytes", "free_bytes", "last_backup"}
