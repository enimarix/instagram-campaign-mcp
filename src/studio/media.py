"""
Where an asset's files live: `<media root>/<batch date>/<asset id>/`.

The store keeps paths relative to the media root, POSIX style (`2026-11-17/12/preview.mp4`),
so the data folder can move. `resolve()` is the only way back to a real file, and it never
leaves the root: the API serves whatever it returns.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path, PurePosixPath
from typing import Optional, Union
from urllib.parse import quote

PathLike = Union[str, Path]


def asset_dir(media_root: PathLike, batch_date: Union[date, str], asset_id: int) -> Path:
    """The asset's folder, created if needed."""
    folder = Path(media_root) / str(batch_date) / str(int(asset_id))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def relative(media_root: PathLike, path: PathLike) -> str:
    """`path` as stored: relative to the root, POSIX. ValueError if it is outside the root."""
    return Path(path).resolve().relative_to(Path(media_root).resolve()).as_posix()


def resolve(media_root: PathLike, rel: str) -> Path:
    """The real file for a stored relative path. ValueError for anything that could escape
    the root: absolute paths, drive letters, backslashes, `..`, symlinks pointing outside."""
    if (not rel or rel.startswith("/") or "\\" in rel or ":" in rel or "\0" in rel
            or ".." in PurePosixPath(rel).parts):
        raise ValueError(f"not a media path: {rel!r}")
    root = Path(media_root).resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"outside the media root: {rel!r}")
    return path


def media_url(rel: Optional[str]) -> Optional[str]:
    """Where the website fetches a stored file; None when there is no file."""
    return f"/api/media/{quote(rel)}" if rel else None
