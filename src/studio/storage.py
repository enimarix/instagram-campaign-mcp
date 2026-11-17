"""
Disk usage for the Settings page: media folder, database, free space on the media disk.

Walking the media folder costs a file stat per asset file, so the total is cached for
CACHE_SECONDS per folder: reloading the page stays cheap.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

CACHE_SECONDS = 60.0
_walks: Dict[str, Tuple[float, int]] = {}  # resolved media root -> (taken at, bytes)


def folder_bytes(root: Path) -> int:
    """Total size of the files under `root` (0 when it does not exist). Links are not followed."""
    total = 0
    for folder, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:  # removed while we walked
                pass
    return total


def _file_bytes(path: str) -> int:
    try:
        return os.stat(path).st_size
    except OSError:
        return 0


def storage(media_root: str, database_path: str,
            clock: Callable[[], float] = time.monotonic) -> Dict[str, Any]:
    root = Path(media_root).resolve()
    now = clock()
    hit = _walks.get(str(root))
    if hit is None or now - hit[0] >= CACHE_SECONDS:
        hit = _walks[str(root)] = (now, folder_bytes(root))
    # SQLite in WAL mode keeps recent writes in the -wal file until a checkpoint.
    db = (0 if database_path == ":memory:"
          else sum(_file_bytes(database_path + s) for s in ("", "-wal", "-shm")))
    disk = next((p for p in (root, *root.parents) if p.exists()), root)  # root may not exist yet
    return {"media_bytes": hit[1], "db_bytes": db, "free_bytes": shutil.disk_usage(disk).free,
            "last_backup": None}  # ponytail: backups arrive with step 027
