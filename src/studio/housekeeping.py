"""
Housekeeping the worker runs once a day (GOAL.md §3.2, §4.3, §7): archive stale `ready`
assets, delete the files of long-archived ones (and the renders' leftovers and old cache files,
prune_leftovers), back up the database, thin old insight
snapshots (VACUUM weekly). Plus the disk floor the render loop checks before it starts a
render, and the restore from a backup (`ig-campaign restore`, step 097).

The bench (`ready` + `liked`) is never emptied by age alone: a liked asset is archived only
once past its best_before. An asset's archive time is its `updated_at` (archived is final,
so only rare edits such as a verdict change move it, which only delays the purge).
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from contextlib import suppress
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import structlog

from ..config import InstagramMCPSettings
from ..store import MIGRATIONS, CampaignStore, parse_dt, to_iso
from . import media
from .assets import InvalidTransition, transition
from .storage import free_bytes

logger = structlog.get_logger(__name__)

ALL = -1  # SQLite LIMIT -1: no limit
PATH_FIELDS = ("file_path", "preview_path", "poster_path", "thumbnail_path")
BACKUP_PREFIX = "studio-"  # studio-YYYY-MM-DD.db: names sort by date
# prune_leftovers (2026-11-25): the renders' temporary folders (tempfile prefixes in
# cinematic.py, motion.py, troupe.py, macro3d.py) and the media caches that grew forever
WORK_DIRS = ("*/*/cinematic-*", "*/*/motion-*", "troupe/troupe-*", "macro3d/macro3d-*",
             "previews/*/tmp*", "endcards/endcard-*")
CACHES = ("troupe", "macro3d", "voice", "previews", "endcards")
CACHE_KEEP_DAYS = 30


def archive_stale(store: CampaignStore, settings: InstagramMCPSettings, today: date) -> List[int]:
    """`ready` assets never reviewed for archive_unreviewed_days (by batch date), and liked
    ones past their best_before, move to archived (actor worker). Returns their ids."""
    cutoff = (today - timedelta(days=settings.archive_unreviewed_days)).isoformat()
    archived = []
    for a in store.list_assets(status="ready", limit=ALL):
        unreviewed = a["verdict"] == "none" and a["batch_date"] <= cutoff
        expired = (a["verdict"] == "liked" and a["best_before"]
                   and a["best_before"] < today.isoformat())
        if not (unreviewed or expired):
            continue
        try:
            transition(store, a["id"], "archived", actor="worker")
        except InvalidTransition:  # the owner acted on it meanwhile
            continue
        archived.append(a["id"])
    return archived


def purge_archived_files(store: CampaignStore, settings: InstagramMCPSettings,
                         today: date) -> List[int]:
    """Delete the files of assets archived more than delete_archived_files_days ago and clear
    their paths. Only `archived` rows (published ones keep their files). A path outside the
    media root is never deleted, only cleared; a file that can't be deleted (in use) keeps
    its path and is retried next time. Returns the ids whose files were handled."""
    cutoff = today - timedelta(days=settings.delete_archived_files_days)
    purged = []
    for a in store.list_assets(status="archived", limit=ALL):
        if parse_dt(a["updated_at"]).date() > cutoff:
            continue
        cleared = {}
        for field in PATH_FIELDS:
            if not a[field]:
                continue
            try:
                media.resolve(settings.media_root, a[field]).unlink(missing_ok=True)
            except ValueError:
                logger.warning("purge_refused_path", asset_id=a["id"], path=a[field])
            except OSError as e:
                logger.warning("purge_failed", asset_id=a["id"], path=a[field], error=repr(e))
                continue
            cleared[field] = None
        if cleared:
            store.update_asset(a["id"], **cleared)
            purged.append(a["id"])
    logger.info("pruned_leftovers", deleted=prune_leftovers(store, settings, today))
    return purged


def prune_leftovers(store: CampaignStore, settings: InstagramMCPSettings, today: date) -> int:
    """Delete the work folders a killed or crashed render left (WORK_DIRS, older than a day)
    and the cache files (CACHES) older than CACHE_KEEP_DAYS, except a file an asset that is
    not archived still names (a voice its recipe plays). Run by purge_archived_files. Returns
    how many went. ponytail: by mtime, so a shot still reused after 30 days renders again once."""
    root = Path(settings.media_root)
    midnight = datetime.combine(today, datetime.min.time()).timestamp()
    with store._tx() as c:
        refs = "\n".join(" ".join(map(str, r)) for r in c.execute(
            f"SELECT recipe, {', '.join(PATH_FIELDS)} FROM assets WHERE status <> 'archived'"))
    gone = 0
    for pattern in WORK_DIRS:
        for d in root.glob(pattern):
            if d.is_dir() and d.stat().st_mtime < midnight - 86400:
                shutil.rmtree(d, ignore_errors=True)
                gone += 1
    for cache in CACHES:
        for f in (root / cache).rglob("*"):
            if (f.is_file() and f.stat().st_mtime < midnight - CACHE_KEEP_DAYS * 86400
                    and media.relative(root, f) not in refs):
                with suppress(OSError):  # in use: next time
                    f.unlink()
                    gone += 1
    return gone


def backup_database(store: CampaignStore, settings: InstagramMCPSettings, now: datetime) -> str:
    """Copy the database with SQLite's online backup API (consistent under WAL) to
    backup_dir/studio-<owner-local date>.db, keep the newest backup_keep, record
    `last_backup` in worker state. Returns the backup's path."""
    folder = Path(settings.backup_dir)
    folder.mkdir(parents=True, exist_ok=True)
    day = now.astimezone(ZoneInfo(settings.timezone)).date()
    dest = folder / f"{BACKUP_PREFIX}{day.isoformat()}.db"
    tmp = dest.with_suffix(".tmp")  # never leave a half-written backup under the real name
    tmp.unlink(missing_ok=True)
    with store._tx() as c:
        _backup(c, tmp)
    os.replace(tmp, dest)
    for old in sorted(folder.glob(f"{BACKUP_PREFIX}*.db"))[:-settings.backup_keep]:
        old.unlink()
    store.set_state("last_backup", to_iso(now))
    return str(dest)


def thin_snapshots(store: CampaignStore, settings: InstagramMCPSettings, now: datetime) -> int:
    """Posts older than snapshot_thin_after_days keep only their age-schedule snapshots
    (campaign.SNAPSHOT_POINTS) and the latest: what scoring, the post series and retention
    read. Returns the number of snapshots dropped."""
    from ..campaign import SNAPSHOT_POINTS  # campaign imports studio modules

    return store.thin_snapshots(now - timedelta(days=settings.snapshot_thin_after_days),
                                [p.total_seconds() / 3600 for p in SNAPSHOT_POINTS])


def vacuum(store: CampaignStore) -> None:
    """Give the space of deleted rows back to the disk (rewrites the file; run rarely)."""
    with store._tx() as c:
        c.execute("VACUUM")


class RestoreRefused(Exception):
    """The backup can't (or must not) replace the database now."""


def _in_use(db: Path, now: datetime) -> Optional[str]:
    """Why the database looks in use (a fresh worker heartbeat, a write lock), else None.
    Raw SQLite: the current file may be the broken one being replaced."""
    from ..worker import ALIVE_WITHIN  # the worker imports this module

    if not db.exists():
        return None
    con = sqlite3.connect(db, timeout=1)
    try:
        try:
            row = con.execute(
                "SELECT value FROM worker_state WHERE key='heartbeat_at'").fetchone()
        except sqlite3.DatabaseError:  # no worker_state yet, or unreadable: nothing to check
            row = None
        if row and now - parse_dt(json.loads(row[0])) < ALIVE_WITHIN:
            return "the worker (or `up`) is running: stop it first"
        try:
            con.execute("BEGIN IMMEDIATE")
            con.rollback()
        except sqlite3.OperationalError:
            return "another process is writing to the database: stop it first"
        except sqlite3.DatabaseError:  # not a database at all: nobody can be using it
            pass
    finally:
        con.close()
    return None


def _backup_version(path: Path) -> int:
    """The backup's schema version, once it passed PRAGMA integrity_check and this code can
    open it (not newer than MIGRATIONS)."""
    if not path.is_file():
        raise RestoreRefused(f"{path} is not a file")
    try:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            check = con.execute("PRAGMA integrity_check").fetchone()[0]
            version = con.execute("PRAGMA user_version").fetchone()[0]
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        raise RestoreRefused(f"{path} is not a readable SQLite database ({e})") from e
    if check != "ok":
        raise RestoreRefused(f"{path} failed the integrity check: {check}")
    if version > len(MIGRATIONS):
        raise RestoreRefused(f"{path} has schema version {version}, newer than this code"
                             f" ({len(MIGRATIONS)}): update the code first")
    return version


def restore_database(settings: InstagramMCPSettings, backup: Path, now: datetime, *,
                     dry_run: bool = False) -> Dict[str, Any]:
    """Replace the database with `backup` (`ig-campaign restore`). Refuses while it is in
    use or when the backup is corrupt or newer than the code. The current database is first
    copied aside to <db>.before-restore-<UTC time> (its raw bytes if it is unreadable). The
    backup is copied with SQLite's backup API (consistent under WAL) next to the database,
    then moved over it; CampaignStore opens the result so pending migrations run.
    dry_run: only the checks, returns the plan. RestoreRefused says why not."""
    db = Path(settings.database_path)
    if settings.database_path == ":memory:":
        raise RestoreRefused("the database is in memory")
    if db.exists() and db.resolve() == backup.resolve():
        raise RestoreRefused("the backup is the database itself")
    version = _backup_version(backup)
    why = _in_use(db, now)
    if why:
        raise RestoreRefused(why)
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    aside = db.with_name(f"{db.name}.before-restore-{stamp}") if db.exists() else None
    plan = {"backup": str(backup), "backup_schema": version, "database": str(db),
            "set_aside": str(aside) if aside else None}
    if dry_run:
        return plan
    if aside:
        current = sqlite3.connect(db)
        try:
            _backup(current, aside)
        except sqlite3.DatabaseError:  # not even readable: keep its bytes as they are
            for suffix in ("", "-wal"):
                if Path(f"{db}{suffix}").exists():
                    shutil.copy2(f"{db}{suffix}", f"{aside}{suffix}")
        finally:
            current.close()
    db.parent.mkdir(parents=True, exist_ok=True)
    tmp = db.with_name(f"{db.name}.restore-tmp")
    tmp.unlink(missing_ok=True)  # a crashed earlier restore's leftover
    src = sqlite3.connect(f"{backup.resolve().as_uri()}?mode=ro", uri=True)
    try:
        _backup(src, tmp)
    finally:
        src.close()
    for suffix in ("-wal", "-shm"):  # the old WAL (copied aside) must not replay onto it
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    os.replace(tmp, db)
    store = CampaignStore(str(db))  # runs the migrations newer than the backup
    try:
        with store._tx() as c:
            schema = c.execute("PRAGMA user_version").fetchone()[0]
    finally:
        store.close()
    return {**plan, "schema": schema, "migrations_run": schema - version}


def _backup(source: sqlite3.Connection, dest: Path) -> None:
    """source's database into the file `dest` with SQLite's online backup API."""
    target = sqlite3.connect(dest)
    try:
        source.backup(target)
    finally:
        target.close()


def disk_ok(settings: InstagramMCPSettings) -> bool:
    """Free space on the media root's disk is at least min_free_disk_gb (False when the disk
    can't be read, e.g. an unplugged drive: renders could not be written there either)."""
    try:
        return free_bytes(settings.media_root) >= settings.min_free_disk_gb * 1024**3
    except OSError:
        return False
