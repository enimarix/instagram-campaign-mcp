"""Store migrations and multi-thread / multi-instance SQLite access."""

import sqlite3
import threading
from datetime import timedelta

import pytest

from src.store import MIGRATIONS, SCHEMA, CampaignStore, SchemaVersionError, utcnow


def _user_version(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _old_db(path):
    """A database as the pre-migration code left it: SCHEMA, user_version 0, data."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO scheduled_posts (kind, payload, publish_at, created_at, updated_at)"
        " VALUES ('image', '{\"image_url\": \"https://x/1.jpg\"}', '2026-01-01T00:00:00+00:00',"
        " '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
    )
    conn.execute("INSERT INTO post_labels (media_id, campaign, created_at)"
                 " VALUES ('m1', 'launch', '2026-01-01T00:00:00+00:00')")
    conn.execute("INSERT INTO insight_snapshots (media_id, captured_at, metrics)"
                 " VALUES ('m1', '2026-01-02T00:00:00+00:00', '{\"reach\": 10}')")
    conn.commit()
    conn.close()
    assert _user_version(path) == 0


def test_old_database_upgrades_without_data_loss_and_reopen_is_idempotent(tmp_path):
    db = str(tmp_path / "old.db")
    _old_db(db)
    for _ in range(2):  # second open: nothing to migrate, nothing lost
        s = CampaignStore(db)
        try:
            assert [p["payload"] for p in s.list_scheduled()] == [{"image_url": "https://x/1.jpg"}]
            assert s.get_label("m1")["campaign"] == "launch"
            assert s.snapshot_history()["m1"][0]["metrics"] == {"reach": 10}
        finally:
            s.close()
        assert _user_version(db) == len(MIGRATIONS)


def test_newer_schema_version_is_refused(tmp_path):
    db = str(tmp_path / "new.db")
    CampaignStore(db).close()
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version={len(MIGRATIONS) + 1}")
    conn.close()
    with pytest.raises(SchemaVersionError, match="schema version"):
        CampaignStore(db)
    (tmp_path / "new.db").unlink()  # the failed open closed its connection


def test_file_connection_pragmas(tmp_path):
    s = CampaignStore(str(tmp_path / "p.db"))
    try:
        c = s._conn
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert c.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        s.close()


def test_memory_store_works_from_other_threads(store):
    p = store.schedule("image", {"image_url": "https://x/1.jpg"}, utcnow())
    errors = []

    def use():
        try:
            assert store.get_scheduled(p["id"])["id"] == p["id"]
            store.schedule("image", {"image_url": "https://x/2.jpg"}, utcnow())
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    t = threading.Thread(target=use)
    t.start()
    t.join()
    assert errors == []
    assert len(store.list_scheduled()) == 2


def test_file_store_works_from_another_thread(tmp_path):
    s = CampaignStore(str(tmp_path / "t.db"))
    errors = []

    def use():
        try:
            s.schedule("image", {"image_url": "https://x/1.jpg"}, utcnow())
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    try:
        t = threading.Thread(target=use)
        t.start()
        t.join()
        assert errors == []
        assert len(s.list_scheduled()) == 1
    finally:
        s.close()  # also closes the other thread's connection


def test_two_stores_write_concurrently_from_two_threads(tmp_path):
    db = str(tmp_path / "c.db")
    stores = [CampaignStore(db), CampaignStore(db)]
    errors = []
    start = threading.Barrier(2)

    def write(s, tag):
        try:
            start.wait()
            for i in range(200):
                s.schedule("image", {"image_url": f"https://x/{tag}{i}.jpg"},
                           utcnow() + timedelta(hours=1))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    try:
        threads = [threading.Thread(target=write, args=(s, t)) for s, t in zip(stores, "ab")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(stores[0].list_scheduled(limit=1000)) == 400
    finally:
        for s in stores:
            s.close()
