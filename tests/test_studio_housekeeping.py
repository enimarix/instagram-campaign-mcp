"""Step 027: housekeeping (archive rules, file purge, database backup, disk floor, daily run)."""

import asyncio
import sqlite3
import threading
import time
from collections import namedtuple
from contextlib import suppress
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import worker
from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.store import CampaignStore
from src.studio import housekeeping, render, storage
from src.studio.assets import set_verdict, transition

from .conftest import LOCAL

TODAY = date(2026, 11, 17)
T = datetime(2026, 11, 17, 2, 0, tzinfo=timezone.utc)
PATHS = ("video.mp4", "preview.mp4", "poster.jpg", "thumb.jpg")


def _settings(tmp_path, **kw):
    kw.setdefault("database_path", ":memory:")
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None, timezone="UTC",
                                media_root=str(tmp_path / "media"),
                                backup_dir=str(tmp_path / "backups"), **kw)


def _asset(store, status="ready", batch_date=TODAY, verdict="none", best_before=None):
    a = store.add_asset(store.add_idea("motion")["id"], batch_date=batch_date,
                        best_before=best_before)
    moves = {"ready": [("ready", "worker")],
             "approved": [("ready", "worker"), ("approved", "owner")],
             "scheduled": [("ready", "worker"), ("approved", "owner"), ("scheduled", "system")],
             "publish_check": [("ready", "worker"), ("approved", "owner"),
                               ("scheduled", "system"), ("publish_check", "worker")],
             "published": [("ready", "worker"), ("approved", "owner"), ("scheduled", "system"),
                           ("published", "worker")],
             "archived": [("ready", "worker"), ("archived", "owner")]}[status]
    for to, actor in moves:
        transition(store, a["id"], to, actor=actor)
    if verdict != "none":
        set_verdict(store, a["id"], verdict)
    return store.get_asset(a["id"])["id"]


def _with_files(store, settings, asset_id, archived_days_ago):
    a = store.get_asset(asset_id)
    folder = f"{a['batch_date']}/{asset_id}"
    path = Path(settings.media_root) / folder
    path.mkdir(parents=True, exist_ok=True)
    for name in PATHS:
        (path / name).write_bytes(b"x")
    store.update_asset(asset_id, **{f: f"{folder}/{n}"
                                    for f, n in zip(housekeeping.PATH_FIELDS, PATHS)})
    _age(store, asset_id, archived_days_ago)
    return path


def _age(store, asset_id, days):
    with store._tx() as c:
        c.execute("UPDATE assets SET updated_at=? WHERE id=?",
                  ((T - timedelta(days=days)).isoformat(timespec="seconds"), asset_id))


def test_archive_rules(store, tmp_path):
    s = _settings(tmp_path)  # archive_unreviewed_days 7
    old = TODAY - timedelta(days=7)
    stale = _asset(store, batch_date=old)
    fresh = _asset(store, batch_date=TODAY - timedelta(days=6))
    liked_old = _asset(store, batch_date=old - timedelta(days=30), verdict="liked")  # bench
    liked_kept = _asset(store, batch_date=old, verdict="liked", best_before="2026-11-17")
    liked_expired = _asset(store, batch_date=TODAY, verdict="liked", best_before="2026-11-16")
    disliked = _asset(store, batch_date=old, verdict="disliked")
    others = [_asset(store, st, batch_date=old)
              for st in ("approved", "scheduled", "publish_check", "published")]
    assert sorted(housekeeping.archive_stale(store, s, TODAY)) == [stale, liked_expired]
    status = {i: store.get_asset(i)["status"] for i in
              (stale, fresh, liked_old, liked_kept, liked_expired, disliked, *others)}
    assert [i for i, st in status.items() if st == "archived"] == [stale, liked_expired]
    assert [status[i] for i in others] == ["approved", "scheduled", "publish_check", "published"]
    assert housekeeping.archive_stale(store, s, TODAY) == []  # idempotent


def test_purge(store, tmp_path):
    s = _settings(tmp_path)  # delete_archived_files_days 14
    old = _asset(store, "archived")
    old_dir = _with_files(store, s, old, 14)
    recent = _asset(store, "archived")
    recent_dir = _with_files(store, s, recent, 13)
    published = _asset(store, "published")
    published_dir = _with_files(store, s, published, 400)
    gone = _asset(store, "archived")  # files already missing: fine
    store.update_asset(gone, file_path="2026-01-01/x/video.mp4")
    _age(store, gone, 30)
    outside = tmp_path / "keep.mp4"
    outside.write_bytes(b"k")
    escaping = _asset(store, "archived")
    store.update_asset(escaping, file_path="../keep.mp4", preview_path=str(outside))
    _age(store, escaping, 30)

    assert sorted(housekeeping.purge_archived_files(store, s, TODAY)) == sorted(
        [old, gone, escaping])
    assert not any((old_dir / n).exists() for n in PATHS)
    assert all((recent_dir / n).exists() for n in PATHS)
    assert all((published_dir / n).exists() for n in PATHS)
    assert outside.exists()  # refused, only the row forgets it
    for i in (old, gone, escaping):
        assert all(store.get_asset(i)[f] is None for f in housekeeping.PATH_FIELDS)
    assert store.get_asset(published)["file_path"] is not None
    assert housekeeping.purge_archived_files(store, s, TODAY) == []


def test_backup_copies_a_wal_db_and_rotates(tmp_path):
    db = tmp_path / "studio.db"
    store = CampaignStore(str(db))
    try:
        s = _settings(tmp_path, database_path=str(db), backup_keep=3)
        ids = [_asset(store) for _ in range(3)]
        assert (tmp_path / "studio.db-wal").exists()  # rows still in the WAL
        path = housekeeping.backup_database(store, s, T)
        assert path.endswith("studio-2026-11-17.db")
        copy = sqlite3.connect(path)
        try:
            assert [r[0] for r in copy.execute("SELECT id FROM assets ORDER BY id")] == ids
        finally:
            copy.close()
        assert store.get_state("last_backup") == "2026-11-17T02:00:00+00:00"
        for d in range(1, 6):
            housekeeping.backup_database(store, s, T + timedelta(days=d))
        names = sorted(p.name for p in (tmp_path / "backups").iterdir())
        assert names == ["studio-2026-11-20.db", "studio-2026-11-21.db", "studio-2026-11-22.db"]
    finally:
        store.close()


def test_storage_route_reports_last_backup(store, tmp_path):
    s = _settings(tmp_path)
    with TestClient(create_app(s, store=store), base_url=LOCAL) as tc:
        assert tc.get("/api/storage").json()["last_backup"] is None
        housekeeping.backup_database(store, s, T)
        assert tc.get("/api/storage").json()["last_backup"] == "2026-11-17T02:00:00+00:00"
        assert tc.get("/api/worker/status").json()["disk_ok"] is True


def test_disk_ok_with_fake_usage(tmp_path, monkeypatch):
    usage = namedtuple("usage", "total used free")
    s = _settings(tmp_path, min_free_disk_gb=5)
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda p: usage(0, 0, 4 * 1024**3))
    assert housekeeping.disk_ok(s) is False
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda p: usage(0, 0, 5 * 1024**3))
    assert housekeeping.disk_ok(s) is True

    def unplugged(p):
        raise FileNotFoundError(p)

    monkeypatch.setattr(storage.shutil, "disk_usage", unplugged)
    assert housekeeping.disk_ok(s) is False


async def test_disk_floor_blocks_claiming(store, tmp_path, monkeypatch, capsys):
    checks = []
    monkeypatch.setattr(housekeeping, "disk_ok", lambda settings: checks.append(1) or False)
    a = store.add_asset(store.add_idea("motion")["id"])
    render.enqueue_render(store, a["id"])
    ran = []
    loop = asyncio.create_task(worker.render_loop(store, _settings(tmp_path), run=ran.append,
                                                  interval=0.02))
    deadline = time.monotonic() + 2  # poll, not a fixed sleep: slow CI runners (027b)
    while len(checks) < 3 and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    loop.cancel()
    with suppress(asyncio.CancelledError):
        await loop
    assert len(checks) >= 3  # several ticks ran under the floor
    assert ran == [] and [j["state"] for j in store.list_render_jobs()] == ["queued"]
    assert capsys.readouterr().err.count("no render starts") == 1  # once per hour


def test_daily_housekeeping_once_a_day_retried_hourly(store, tmp_path, monkeypatch):
    s = _settings(tmp_path)
    calls = []

    def backup(store_, settings, now):
        calls.append(now)
        if len(calls) == 1:
            raise OSError("disk full")
        return "b.db"

    monkeypatch.setattr(housekeeping, "backup_database", backup)
    with pytest.raises(OSError):
        worker.daily_housekeeping(store, s, now=lambda: T)
    assert worker.daily_housekeeping(store, s, now=lambda: T + timedelta(minutes=30)) is None
    out = worker.daily_housekeeping(store, s, now=lambda: T + timedelta(minutes=61))
    assert out == {"archived": [], "purged": [], "backup": "b.db"}
    assert worker.daily_housekeeping(store, s, now=lambda: T + timedelta(hours=5)) is None
    assert worker.daily_housekeeping(store, s, now=lambda: T + timedelta(days=1)) is not None
    assert len(calls) == 3


@pytest.mark.parametrize("attempt", range(3))
async def test_shutdown_waits_for_housekeeping_thread_before_store_closes(tmp_path, monkeypatch,
                                                                          attempt):
    store = CampaignStore(str(tmp_path / "studio.db"))
    started, release, seen = threading.Event(), threading.Event(), []

    def slow_housekeeping(store_, settings):
        started.set()
        release.wait(5)
        seen.append(len(store_.list_assets()))  # the read that crashed once the store closed

    monkeypatch.setattr(worker, "daily_housekeeping", slow_housekeeping)
    loop = asyncio.create_task(worker.render_loop(store, _settings(tmp_path), interval=0.01))
    assert await asyncio.to_thread(started.wait, 5)
    loop.cancel()  # what scheduler._worker does before store.close()
    await asyncio.sleep(0.05)
    assert not loop.done()  # still waiting for the thread
    release.set()
    with suppress(asyncio.CancelledError):
        await loop
    assert seen == [0]
    store.close()


def test_close_waits_for_a_running_transaction_then_refuses_use(tmp_path):
    store = CampaignStore(str(tmp_path / "studio.db"))
    in_tx, go, seen = threading.Event(), threading.Event(), []

    def reader():
        with store._tx() as c:
            in_tx.set()
            go.wait(5)
            seen.append(c.execute("SELECT count(*) FROM assets").fetchone()[0])
        with pytest.raises(sqlite3.ProgrammingError):
            store.list_assets()
        seen.append("refused")

    t = threading.Thread(target=reader)
    t.start()
    assert in_tx.wait(5)
    closer = threading.Thread(target=store.close)
    closer.start()
    closer.join(0.1)
    assert closer.is_alive()  # blocked until the reader's transaction ends
    go.set()
    closer.join(5)
    t.join(5)
    assert seen == [0, "refused"]
    errors = []

    def new_thread():  # gets no new connection either
        try:
            store.list_assets()
        except sqlite3.ProgrammingError as e:
            errors.append(e)

    t = threading.Thread(target=new_thread)
    t.start()
    t.join(5)
    assert len(errors) == 1
