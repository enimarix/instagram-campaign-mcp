"""
Housekeeping the worker runs once a day (GOAL.md §3.2, §4.3, §7): archive stale `ready`
assets, delete the files of long-archived ones, back up the database. Plus the disk floor
the render loop checks before it starts a render.

The bench (`ready` + `liked`) is never emptied by age alone: a liked asset is archived only
once past its best_before. An asset's archive time is its `updated_at` (archived is final,
so only rare edits such as a verdict change move it, which only delays the purge).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

import structlog

from ..config import InstagramMCPSettings
from ..store import CampaignStore, parse_dt, to_iso
from . import media
from .assets import InvalidTransition, transition
from .storage import free_bytes

logger = structlog.get_logger(__name__)

ALL = -1  # SQLite LIMIT -1: no limit
PATH_FIELDS = ("file_path", "preview_path", "poster_path", "thumbnail_path")
BACKUP_PREFIX = "studio-"  # studio-YYYY-MM-DD.db: names sort by date


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
    return purged


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
    target = sqlite3.connect(tmp)
    try:
        with store._tx() as c:
            c.backup(target)
    finally:
        target.close()
    os.replace(tmp, dest)
    for old in sorted(folder.glob(f"{BACKUP_PREFIX}*.db"))[:-settings.backup_keep]:
        old.unlink()
    store.set_state("last_backup", to_iso(now))
    return str(dest)


def disk_ok(settings: InstagramMCPSettings) -> bool:
    """Free space on the media root's disk is at least min_free_disk_gb (False when the disk
    can't be read, e.g. an unplugged drive: renders could not be written there either)."""
    try:
        return free_bytes(settings.media_root) >= settings.min_free_disk_gb * 1024**3
    except OSError:
        return False
