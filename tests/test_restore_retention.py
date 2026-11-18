"""Step 097: restore from a backup, insight snapshot thinning, weekly VACUUM."""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src import campaign, scheduler, worker
from src import store as store_mod
from src.config import InstagramMCPSettings
from src.learning.analytics import post_detail
from src.store import MIGRATIONS, CampaignStore, to_iso
from src.studio import housekeeping
from src.studio.housekeeping import RestoreRefused, restore_database

NOW = datetime(2026, 11, 18, 3, 0, tzinfo=timezone.utc)
SCHEDULE = [1, 3, 6, 12, 24, 48, 168, 720]


def _settings(tmp_path, **kw):
    kw.setdefault("database_path", str(tmp_path / "studio.db"))
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None, timezone="UTC",
                                media_root=str(tmp_path / "media"),
                                backup_dir=str(tmp_path / "backups"), **kw)


def _snap(store, media_id, posted, age, reach=1000, likes=50):
    store.add_snapshot(media_id, {"reach": reach + int(age), "likes": likes + int(age) // 10,
                                  "comments": 3, "saved": 2, "shares": 1, "views": 2 * reach},
                       "REELS", "VIDEO", to_iso(posted),
                       captured_at=posted + timedelta(hours=age))


def _ages(store, media_id):
    return [s["age_hours"] for s in store.media_snapshots(media_id)]


# --- thinning ---------------------------------------------------------------
def test_thinning_keeps_schedule_points_and_latest_only_past_the_age(store, tmp_path):
    old, recent = NOW - timedelta(days=60), NOW - timedelta(days=10)
    for age in [*SCHEDULE, 2, 4.5, 9, 100, 300, 900]:
        _snap(store, "old", old, age)
        if age <= 240:
            _snap(store, "recent", recent, age)
    # the 48 h point taken a bit late, and an earlier extra closer to 48: both stay
    # (the nearest, and the nearest at/past 48 that snapshots_near_age picks at min age 48)
    _snap(store, "late", old, 47.9)
    _snap(store, "late", old, 48.6)
    _snap(store, "late", old, 60)

    s = _settings(tmp_path, database_path=":memory:")
    assert housekeeping.thin_snapshots(store, s, NOW) == 5
    assert _ages(store, "old") == [*SCHEDULE, 900]
    assert _ages(store, "late") == [47.9, 48.6, 60]  # 60: nearest to 168/720 and latest
    assert len(_ages(store, "recent")) == 11  # younger than 45 days: untouched
    assert housekeeping.thin_snapshots(store, s, NOW) == 0


def test_scores_and_post_detail_unchanged_after_thinning(store, tmp_path):
    s = _settings(tmp_path, database_path=":memory:")
    for i, media in enumerate(("a", "b", "c")):
        posted = NOW - timedelta(days=50 + i)
        for age in [*SCHEDULE, 2, 50, 200, 500, 900]:
            _snap(store, media, posted, age, reach=1000 + 300 * i, likes=40 + 20 * i)
    for age in (1, 3, 6, 12, 24, 48):  # a fresh post scored against them at 48 h
        _snap(store, "new", NOW - timedelta(hours=49), age, reach=1500, likes=90)

    before = campaign._score_all(store, s)
    series = {m: post_detail(store, s, m)["series"] for m in "abc"}
    assert store.thin_snapshots(NOW - timedelta(days=45), SCHEDULE) == 3 * 4
    assert campaign._score_all(store, s) == before
    for m in "abc":
        kept = [p for p in series[m] if p["age_hours"] in (*SCHEDULE, 900)]
        assert post_detail(store, s, m)["series"] == kept


def test_daily_housekeeping_thins_and_vacuums_at_most_weekly(store, tmp_path, monkeypatch):
    s = _settings(tmp_path, database_path=":memory:")
    vacuums = []
    monkeypatch.setattr(housekeeping, "backup_database", lambda *a: "b.db")
    monkeypatch.setattr(housekeeping, "vacuum", lambda st: vacuums.append(st))
    for age in (1, 2, 3):
        _snap(store, "old", NOW - timedelta(days=60), age)
    out = worker.daily_housekeeping(store, s, now=lambda: NOW)
    assert (out["thinned"], out["vacuumed"]) == (1, True)
    for day in range(1, 7):
        out = worker.daily_housekeeping(store, s, now=lambda d=day: NOW + timedelta(days=d))
        assert out["vacuumed"] is False
    assert worker.daily_housekeeping(store, s, now=lambda: NOW + timedelta(days=7))["vacuumed"]
    assert vacuums == [store, store]


def test_vacuum_runs_on_a_file_db(tmp_path):
    st = CampaignStore(str(tmp_path / "studio.db"))
    try:
        housekeeping.vacuum(st)
    finally:
        st.close()


# --- restore ----------------------------------------------------------------
@pytest.fixture
def studio(tmp_path):
    """A file database with one source, its backup, then a second source added after."""
    s = _settings(tmp_path)
    st = CampaignStore(s.database_path)
    try:
        st.add_source("local", rights_basis="own")
        backup = housekeeping.backup_database(st, s, NOW - timedelta(hours=1))
        st.add_source("local", rights_basis="own")
        st.set_state("heartbeat_at", "2020-01-01T00:00:00+00:00")  # the worker stopped
    finally:
        st.close()
    return s, Path(backup)


def _sources(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    finally:
        con.close()


def test_restore_keeps_the_current_db_aside_and_puts_the_backup_back(studio, tmp_path):
    s, backup = studio
    out = restore_database(s, backup, NOW)
    aside = tmp_path / "studio.db.before-restore-20261118T030000Z"
    assert out == {"backup": str(backup), "backup_schema": len(MIGRATIONS),
                   "database": s.database_path, "set_aside": str(aside),
                   "schema": len(MIGRATIONS), "migrations_run": 0}
    assert _sources(aside) == 2 and _sources(s.database_path) == 1


def test_restore_runs_pending_migrations(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    old = tmp_path / "old.db"
    monkeypatch.setattr(store_mod, "MIGRATIONS", MIGRATIONS[:-1])  # older code wrote it
    CampaignStore(str(old)).close()
    monkeypatch.undo()
    out = restore_database(s, old, NOW)
    assert (out["backup_schema"], out["migrations_run"], out["set_aside"]) == (
        len(MIGRATIONS) - 1, 1, None)  # no database yet: nothing to keep aside
    con = sqlite3.connect(s.database_path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    con.close()


def test_restore_refuses_a_running_worker(studio):
    s, backup = studio
    st = CampaignStore(s.database_path)
    st.set_state("heartbeat_at", to_iso(NOW - timedelta(minutes=1)))
    st.close()
    with pytest.raises(RestoreRefused, match="worker"):
        restore_database(s, backup, NOW)
    assert _sources(s.database_path) == 2


def test_restore_refuses_while_another_process_writes(studio):
    s, backup = studio
    con = sqlite3.connect(s.database_path)
    con.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(RestoreRefused, match="writing"):
            restore_database(s, backup, NOW)
    finally:
        con.rollback()
        con.close()


def test_restore_refuses_a_corrupt_file_and_a_newer_schema(studio, tmp_path):
    s, _ = studio
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not a database" * 200)
    with pytest.raises(RestoreRefused, match="not a readable SQLite"):
        restore_database(s, junk, NOW)
    newer = tmp_path / "newer.db"
    con = sqlite3.connect(newer)
    con.execute(f"PRAGMA user_version={len(MIGRATIONS) + 1}")
    con.close()
    with pytest.raises(RestoreRefused, match="newer than this code"):
        restore_database(s, newer, NOW)
    with pytest.raises(RestoreRefused, match="not a file"):
        restore_database(s, tmp_path / "missing.db", NOW)
    assert _sources(s.database_path) == 2
    assert not list(tmp_path.glob("*.before-restore-*"))


def test_cli_refuses_without_yes_when_not_interactive(studio, monkeypatch, capsys):
    s, backup = studio
    monkeypatch.setattr(scheduler, "get_settings", lambda: s)
    monkeypatch.setattr(scheduler, "configure_logging", lambda *a: None)  # keeps capsys' file
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit) as e:
        scheduler.main(["restore", str(backup)])
    assert e.value.code == 1 and "add --yes" in capsys.readouterr().err
    assert _sources(s.database_path) == 2
    with pytest.raises(SystemExit) as e:
        scheduler.main(["restore", str(backup), "--yes"])
    assert e.value.code == 0 and '"migrations_run": 0' in capsys.readouterr().out
    assert _sources(s.database_path) == 1
