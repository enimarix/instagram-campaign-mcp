"""
Permission tracker (step 065, GOAL.md §5.1): the owner asks a creator whether a clip may be
reused as is, not only as commentary.

Each request is recorded (requested / granted / denied, by which channel, when, the proof,
whether ads are allowed) with a message draft the owner edits, copies and sends
themselves. Nothing here contacts anyone, and the agent profile has no tool for it.
Once granted, the owner attaches the creator's file: it goes through the clip intake checks
(063) and the source becomes `rights_basis = permission`, with the proof and the date as its
rights note and the ads flag. A denied request leaves the source as it was: commentary use
only, under the remix rules (069).
"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from ..config import InstagramMCPSettings
from ..store import CampaignStore, to_iso, utcnow
from . import brand, downloader, media, reactions, sources

CHANNELS = ("dm", "email", "other")
ANSWERS = ("granted", "denied")
FIELDS = ("source_id", "creator", "channel", "status", "requested_at", "answered_at",
          "proof_note", "ads_allowed")
CREATOR_MAX = 100
NOTE_MAX = 1000
# Polite, names the clip, asks for a credited repost and about ads, promises nothing.
DRAFT = (
    "Hi {creator}! I run {name} ({handle}) on Instagram, and I really liked {clip}.\n\n"
    "Would you be OK with us reposting it on our account, with clear credit to you "
    "({credit} in the caption and on screen)?\n\n"
    "And may we also use it in a paid ad? Just tell us if not: a no is completely fine.\n\n"
    "Thank you!"
)


def _source(store: CampaignStore, target: Union[int, str]) -> Dict[str, Any]:
    """The source of a request: a source id, or a Reel link (an inspiration); {url} alone
    for a link no source holds yet."""
    if isinstance(target, int):
        return store.get_source(target)  # KeyError: no such source
    url, source = downloader._find_source(store, target)  # ValueError: not a Reel link
    return source or {"url": url}


def _creator(source: Dict[str, Any], creator: Optional[str]) -> Optional[str]:
    name = (creator or source.get("author") or "").strip().lstrip("@").strip()
    if len(name) > CREATOR_MAX:
        raise ValueError(f"the creator is at most {CREATOR_MAX} characters")
    return name or None


def _note(note: Optional[str]) -> Optional[str]:
    note = (note or "").strip() or None
    if note and len(note) > NOTE_MAX:
        raise ValueError(f"the note is at most {NOTE_MAX} characters")
    return note


def draft(store: CampaignStore, target: Union[int, str], creator: Optional[str] = None,
          *, brand_kit: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """{creator, url, message}: the message the owner may send (never sent by the studio)."""
    source = _source(store, target)
    name = _creator(source, creator)
    kit = brand_kit or brand.load_brand()
    url = source.get("url")
    return {"creator": name, "url": url, "message": DRAFT.format(
        creator=f"@{name}" if name else "there", name=kit["name"], handle=kit["handle"],
        clip=f"your video {url}" if url else "one of your videos",
        credit=f"@{name}" if name else "your handle")}


_SELECT = ("SELECT p.*, s.url, s.rights_basis, s.local_path IS NOT NULL AS has_file"
           " FROM permission_requests p JOIN sources s ON s.id = p.source_id")


def get_request(store: CampaignStore, request_id: int) -> Dict[str, Any]:
    """The request with its source's url, rights_basis and whether it holds a file."""
    with store._tx() as c:
        row = c.execute(f"{_SELECT} WHERE p.id=?", (request_id,)).fetchone()
    if not row:
        raise KeyError(f"No permission request with id {request_id}")
    return _row(row)


def _row(row: sqlite3.Row) -> Dict[str, Any]:
    out = dict(row)
    out["ads_allowed"], out["has_file"] = bool(out["ads_allowed"]), bool(out["has_file"])
    return out


def list_requests(store: CampaignStore, status: Optional[str] = None,
                  limit: int = 100) -> List[Dict[str, Any]]:
    """Newest first, each like get_request()."""
    where = " WHERE p.status=?" if status else ""
    with store._tx() as c:
        rows = c.execute(f"{_SELECT}{where} ORDER BY p.id DESC LIMIT ?",
                         ([status] if status else []) + [limit]).fetchall()
    return [_row(r) for r in rows]


def request_permission(store: CampaignStore, target: Union[int, str], channel: str,
                       note: Optional[str] = None, *, creator: Optional[str] = None,
                       brand_kit: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Record that the owner asked (or will ask) the creator: {request, draft}. `note`:
    where and how, kept as the start of the proof. ValueError when the channel is unknown,
    no creator is known, or the source already has an open request."""
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {', '.join(CHANNELS)}")
    note = _note(note)
    source = _source(store, target)
    name = _creator(source, creator)
    if not name:
        raise ValueError("say who the creator is: the credit needs their name")
    if "id" not in source:  # a new link becomes a reference source (rights unknown)
        source = store.add_source("inspiration", role="reference", url=source["url"])
    try:
        row = store._insert("permission_requests", FIELDS, {
            "source_id": source["id"], "creator": name, "channel": channel,
            "status": "requested", "requested_at": to_iso(utcnow()), "proof_note": note})
    except sqlite3.IntegrityError as e:  # idx_permission_open
        raise ValueError("this clip already has an open permission request") from e
    return {"request": get_request(store, row["id"]),
            "draft": draft(store, source["id"], name, brand_kit=brand_kit)}


def answer(store: CampaignStore, request_id: int, status: str,
           proof_note: Optional[str] = None, ads_allowed: bool = False) -> Dict[str, Any]:
    """The creator's answer to an open request. A yes needs the proof (where and when they
    said it); ads count only when they agreed in writing. The source itself changes only
    when the file is attached; a no leaves it as it was."""
    if status not in ANSWERS:
        raise ValueError(f"status must be one of {', '.join(ANSWERS)}")
    req = get_request(store, request_id)
    if req["status"] != "requested":
        raise ValueError(f"this request was already answered ({req['status']})")
    proof = _note(proof_note) or req["proof_note"]
    if status == "granted" and not proof:
        raise ValueError("write where and when the creator said yes (the proof)")
    store._update("permission_requests", FIELDS, request_id, {
        "status": status, "answered_at": to_iso(utcnow()), "proof_note": proof,
        "ads_allowed": int(status == "granted" and bool(ads_allowed))})
    return get_request(store, request_id)


def attach_granted_file(store: CampaignStore, settings: InstagramMCPSettings, request_id: int,
                        path: Path, *, audio_rights: Optional[str] = None) -> Dict[str, Any]:
    """MOVE the creator's file into the request's source, which becomes a `permission` clip
    (credit to the creator, the proof + date as its rights note, the ads flag). Same checks
    as the clip inbox (063); ValueError when refused (the file stays where it was)."""
    req = get_request(store, request_id)
    if req["status"] != "granted":
        raise ValueError("attach a file only once the creator said yes")
    when = req["answered_at"][:10]
    note = f"Permission from @{req['creator']} by {req['channel']} on {when}: {req['proof_note']}"
    sources.check_rights("permission", note, author=req["creator"])
    path = Path(path)
    stats, audio_rights = sources.probe_clip(settings, path, audio_rights)
    source_id = req["source_id"]
    dest = sources.move_into(path, Path(settings.media_root) / "sources" / str(source_id),
                             "clip" + path.suffix.lower())
    store.patch_source_stats(source_id, stats)
    with store._tx() as c:  # ponytail: a store setter once store.py is free
        c.execute("UPDATE sources SET role='clip', author=?, rights_basis='permission',"
                  " rights_note=?, audio_rights=?, ads_allowed=?, local_path=? WHERE id=?",
                  (req["creator"], note, audio_rights, int(req["ads_allowed"]),
                   media.relative(settings.media_root, dest), source_id))
    return sources.with_attribution(store.get_source(source_id))


async def upload_granted_file(store: CampaignStore, settings: InstagramMCPSettings,
                              request_id: int, chunks: AsyncIterator[bytes], filename: str,
                              content_length: Optional[int], *,
                              audio_rights: Optional[str] = None) -> Dict[str, Any]:
    """Stream an upload to disk under max_clip_mb (reactions.UploadTooLarge past it), then
    attach_granted_file() it. Refused before reading the body when the request is not
    granted; the partial file never stays behind."""
    if get_request(store, request_id)["status"] != "granted":
        raise ValueError("attach a file only once the creator said yes")
    suffix = Path(filename or "").suffix.lower()
    if suffix not in sources.VIDEO_EXTS:
        raise ValueError(f"upload a video file ({', '.join(sources.VIDEO_EXTS)})")
    cap = settings.max_clip_mb * 1_000_000
    if content_length is not None and content_length > cap:
        raise reactions.UploadTooLarge(f"the file is larger than {settings.max_clip_mb:g} MB")
    folder = Path(settings.media_root) / "sources" / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"upload-{uuid.uuid4().hex}{suffix}"
    try:
        await reactions.save_upload(chunks, tmp, cap)
        return await asyncio.to_thread(attach_granted_file, store, settings, request_id, tmp,
                                       audio_rights=audio_rights)
    finally:
        tmp.unlink(missing_ok=True)
