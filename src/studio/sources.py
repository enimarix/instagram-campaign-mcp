"""
Clip intake (GOAL.md §3.1 Track A, §5.1): how clips the studio may use become `sources`.

A provider turns something (an inbox file, later a stock search hit or a Reel permalink)
into a `clip` source row with its rights recorded. The first one is `local_inbox`: the
owner drops a file into `settings.inbox_dir` and gives its rights on the website. The
folder is a drop zone, never an auto-import: a file becomes a clip only with a rights
basis (never `unknown`), a rights note and, when it has sound, whether the sound is covered.

Files land in `<media_root>/sources/<id>/`, stored relative to the media root.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional, Protocol, Tuple

from ..config import InstagramMCPSettings
from ..store import CampaignStore
from . import ffmpeg, media, rights

AUDIO_RIGHTS = ("covered", "not_covered", "no_audio")
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm", ".mkv")


class SourceProvider(Protocol):
    """Where clips come from. `ingest` stores one clip and returns its `sources` row;
    `item` is the provider's own handle (inbox file name, stock id, Reel permalink)."""

    name: str

    def ingest(self, item: str, **rights_fields: Any) -> Dict[str, Any]: ...


def scan_inbox(settings: InstagramMCPSettings) -> List[Dict[str, Any]]:
    """The video files waiting in the inbox, by name: {name, size_bytes, modified_at}."""
    inbox = Path(settings.inbox_dir)
    if not inbox.is_dir():
        return []
    out = []
    for p in sorted(inbox.iterdir(), key=lambda p: p.name):
        if p.name.startswith(".") or p.suffix.lower() not in VIDEO_EXTS or not p.is_file():
            continue
        st = p.stat()
        out.append({"name": p.name, "size_bytes": st.st_size,
                    "modified_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()})
    return out


def inbox_path(settings: InstagramMCPSettings, name: str) -> Path:
    """The inbox file called `name`. ValueError for anything but a bare file name inside
    the inbox (no folders, `..`, drive letters, hidden files, links leading out);
    KeyError when there is no such file."""
    if (not name or name.startswith(".") or any(c in name for c in "/\\:\0")
            or PurePath(name).name != name):
        raise ValueError(f"not an inbox file name: {name!r}")
    inbox = Path(settings.inbox_dir).resolve()
    path = (inbox / name).resolve()
    if path.parent != inbox:
        raise ValueError(f"outside the inbox: {name!r}")
    if not path.is_file():
        raise KeyError(f"No inbox file {name!r}")
    return path


def check_rights(rights_basis: str, rights_note: Optional[str], *, author: Optional[str] = None,
                 licence: Optional[str] = None) -> None:
    """ValueError unless a clip may be stored with these rights: a known basis other than
    `unknown`, a note, and what the basis needs to be used (rights.can_publish: an author
    for cc/permission/commentary, CC BY or BY-SA for cc)."""
    if rights_basis not in rights.RIGHTS_BASES or rights_basis == "unknown":
        allowed = ", ".join(b for b in rights.RIGHTS_BASES if b != "unknown")
        raise ValueError(f"rights_basis must be one of {allowed}")
    if not (rights_note or "").strip():
        raise ValueError("rights_note is required: say where the clip comes from and why "
                         "we may use it")
    # confirmed=True: commentary's per-video confirmation happens at approval, not intake.
    decision = rights.can_publish({"rights_basis": rights_basis, "author": author},
                                  confirmed=True, licence=licence)
    if not decision:
        raise ValueError(decision.reason)


def probe_clip(settings: InstagramMCPSettings, path: Path, audio_rights: Optional[str]
               ) -> Tuple[Dict[str, Any], str]:
    """(stats, audio_rights) of a clip file within the caps (max_clip_mb, max_clip_seconds).
    ValueError when it is not a video, too big or too long, or has sound and `audio_rights`
    does not say whether the sound is covered (a silent clip is always `no_audio`)."""
    if audio_rights is not None and audio_rights not in AUDIO_RIGHTS:
        raise ValueError(f"audio_rights must be one of {', '.join(AUDIO_RIGHTS)}")
    if path.stat().st_size > settings.max_clip_mb * 1_000_000:
        raise ValueError(f"the clip is larger than {settings.max_clip_mb:g} MB")
    try:
        info = ffmpeg.probe(path)
    except ffmpeg.FFmpegError as e:
        raise ValueError(f"not a video file: {e}") from e
    if not info.video_codec or not info.width or info.duration <= 0:
        raise ValueError("not a video file")
    if info.duration > settings.max_clip_seconds:
        raise ValueError(f"the clip is longer than {settings.max_clip_seconds:g} s")
    if not info.has_audio:
        audio_rights = "no_audio"
    elif audio_rights not in ("covered", "not_covered"):
        raise ValueError("the clip has sound: say whether the sound is covered")
    return ({"duration_s": round(info.duration, 3), "width": info.width,
             "height": info.height, "has_audio": info.has_audio,
             "size_bytes": info.size_bytes, "original_name": path.name}, audio_rights)


def move_into(src: Path, folder: Path, name: str) -> Path:
    """Move `src` to `folder/name` atomically: readers see no file or the whole file."""
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / name
    part = folder / (name + ".part")
    shutil.move(str(src), str(part))  # a copy + delete across disks
    os.replace(part, dest)
    return dest


class LocalInboxProvider:
    """Clips the owner drops into the inbox folder (`settings.inbox_dir`)."""

    name = "local_inbox"

    def __init__(self, store: CampaignStore, settings: InstagramMCPSettings):
        self.store = store
        self.settings = settings

    def ingest(self, item: str, **rights_fields: Any) -> Dict[str, Any]:
        """Store the inbox file named `item` (a bare name, see inbox_path) as a clip."""
        return self.ingest_file(inbox_path(self.settings, item), **rights_fields)

    def ingest_file(self, path: Path, *, rights_basis: str, rights_note: str,
                    audio_rights: Optional[str] = None, author: Optional[str] = None,
                    url: Optional[str] = None, licence: Optional[str] = None
                    ) -> Dict[str, Any]:
        """Check the rights and the file, then MOVE it into `<media_root>/sources/<id>/`
        and return the new `clip` source with its probe stats. ValueError when refused
        (the file stays where it was)."""
        author, url, licence = (v.strip() if v and v.strip() else None
                                for v in (author, url, licence))
        check_rights(rights_basis, rights_note, author=author, licence=licence)
        path = Path(path)
        stats, audio_rights = probe_clip(self.settings, path, audio_rights)
        if licence:
            # ponytail: no sources.licence column yet (store.py is busy); rights.py reads a
            # `licence` key, so list_clips lifts it out of stats. Move to a column later.
            stats["licence"] = rights.cc_licence(licence) or licence
        row = self.store.add_source(
            self.name, role="clip", url=url, author=author, stats=stats,
            rights_basis=rights_basis, rights_note=rights_note.strip(), audio_rights=audio_rights)
        try:
            folder = Path(self.settings.media_root) / "sources" / str(row["id"])
            dest = move_into(path, folder, "clip" + path.suffix.lower())
            rel = media.relative(self.settings.media_root, dest)
            with self.store._tx() as c:  # ponytail: a store setter once store.py is free
                c.execute("UPDATE sources SET local_path=? WHERE id=?", (rel, row["id"]))
        except BaseException:
            with self.store._tx() as c:  # no clip row without its file
                c.execute("DELETE FROM sources WHERE id=?", (row["id"],))
            raise
        return self.store.get_source(row["id"])


def with_attribution(source: Dict[str, Any]) -> Dict[str, Any]:
    """The source plus its `licence` and the credit text a post of it must carry."""
    licence = source.get("licence") or (source.get("stats") or {}).get("licence")
    return {**source, "licence": licence,
            "attribution": rights.attribution(source, licence=licence)}


def list_clips(store: CampaignStore, role: str = "clip", limit: int = 100
               ) -> List[Dict[str, Any]]:
    """Sources of one role, newest first, each with its licence and attribution."""
    rows = store._select("SELECT * FROM sources", {"role": role}, "id DESC", limit)
    return [with_attribution(s) for s in rows]
