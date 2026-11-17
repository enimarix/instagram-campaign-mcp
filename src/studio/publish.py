"""
The publish guard (GOAL.md §3.3, §5.1, §5.2).

`queue_asset()` is the only way a studio asset reaches the publish queue. The worker's
side (keeping the asset's status truthful after a publish) lives in campaign.run_due;
`reconcile_publish_checks()` settles the publishes whose outcome was unknown.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import structlog

from ..config import InstagramMCPSettings
from ..instagram_client import InstagramClient, caption_problem
from ..store import CampaignStore, parse_dt, utcnow
from . import media
from .assets import InvalidTransition, transition
from .rights import can_publish


class QueueRefused(ValueError):
    """The asset may not be queued. `code`: not_approved, rights, no_file, qc, caption."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _source(store: CampaignStore, idea: Dict[str, Any]) -> Dict[str, Any]:
    """The rights source of an asset's idea. Motion videos are ours: no source, `own`.
    Any other idea without a source has unknown rights."""
    if idea.get("source_id") is not None:
        return store.get_source(idea["source_id"])
    return {"rights_basis": "own" if idea["track"] == "motion" else "unknown"}


def queue_asset(
    store: CampaignStore,
    settings: InstagramMCPSettings,
    asset_id: int,
    publish_at: datetime,
    *,
    confirmed: bool = False,
) -> Dict[str, Any]:
    """Queue an approved asset as a Reel at `publish_at`; return the scheduled_posts row.

    `confirmed` is the owner's per-video confirmation a `commentary` source needs.
    Raises QueueRefused (with a code) when a rule says no, KeyError for an unknown asset.
    """
    if publish_at <= utcnow():
        raise ValueError("publish_at must be in the future")
    asset = store.get_asset(asset_id)
    if asset["status"] != "approved":
        raise QueueRefused("not_approved", f"asset {asset_id} is {asset['status']}, not approved")
    decision = can_publish(_source(store, store.get_idea(asset["idea_id"])), confirmed)
    if not decision:
        raise QueueRefused("rights", decision.reason)
    try:
        ok = bool(asset["file_path"]) and media.resolve(
            settings.media_root, asset["file_path"]).is_file()
    except ValueError:
        ok = False
    if not ok:
        raise QueueRefused("no_file", f"asset {asset_id} has no video file")
    qc = asset["qc"]
    if not (isinstance(qc, dict) and qc.get("passed") is True):
        raise QueueRefused("qc", f"asset {asset_id} has not passed QC")
    problem = caption_problem(asset["caption"], settings.max_hashtags)
    if problem:
        raise QueueRefused("caption", problem)

    payload = {"video_path": asset["file_path"], "caption": asset["caption"] or "",
               "audio_name": asset["audio_name"],
               "thumb_offset_ms": (asset["recipe"] or {}).get("thumb_offset_ms")}
    post = store.schedule("reel", {k: v for k, v in payload.items() if v is not None},
                          publish_at, asset_id=asset_id)
    # The row goes in first: if we crash before the move, the worker finds the asset
    # not `scheduled` and cancels the row. publish_at is in the future, so the worker
    # cannot claim the row before the move below.
    try:
        # The sole caller of the `system` approved -> scheduled move (GOAL.md §4.3).
        transition(store, asset_id, "scheduled", actor="system")
    except InvalidTransition as e:  # changed meanwhile (unapproved, queued twice)
        store.delete_pending(post["id"])
        raise QueueRefused("not_approved", str(e)) from e
    return post


def cancel_post(store: CampaignStore, post_id: int) -> Dict[str, Any]:
    """The owner cancels a queued post. A pending row's asset goes back to `approved`.

    A failed row's asset already moved (approved, or publish_check when the publish may
    have reached Instagram); cancelling must not turn an unknown outcome into `approved`.
    """
    before = store.get_scheduled(post_id)
    post = store.cancel(post_id)
    if post["asset_id"] is not None and before["status"] == "pending":
        try:
            transition(store, post["asset_id"], "approved", actor="owner")
        except InvalidTransition:
            pass  # not scheduled any more: nothing to give back
    return post


def release_publish_check(store: CampaignStore, asset_id: int) -> Dict[str, Any]:
    """The owner checked Instagram and the post is not there: publish_check -> approved,
    so the asset can be queued again. InvalidTransition from any other status."""
    status = store.get_asset(asset_id)["status"]
    if status != "publish_check":
        raise InvalidTransition(f"asset {asset_id} is {status}, not publish_check")
    return transition(store, asset_id, "approved", actor="owner")


def refuse_asset_file(
    store: CampaignStore, settings: InstagramMCPSettings, video_path: Optional[str]
) -> None:
    """ValueError when `video_path` is a studio asset's file or preview: those publish only
    through queue_asset (approved, rights, QC), never by path from an MCP tool."""
    if not video_path:
        return
    try:
        rel = media.relative(settings.media_root, media.resolve(settings.media_root, video_path))
    except ValueError:
        return  # not a media path at all: the client refuses it
    with store._tx() as c:  # no store method for this lookup (store.py belongs to 025)
        row = c.execute("SELECT id FROM assets WHERE file_path=? OR preview_path=? LIMIT 1",
                        (rel, rel)).fetchone()
    if row:
        raise ValueError(f"{video_path} is studio asset {row['id']}'s video: queue the asset"
                         " from the website instead")


RECONCILE_PAGES = 2  # ~100 recent media; an older post is left to the owner
RECONCILE_PAGE_SIZE = 50
logger = structlog.get_logger(__name__)


def _norm(caption: Optional[str]) -> str:
    return " ".join((caption or "").split())


async def reconcile_publish_checks(
    client: InstagramClient, store: CampaignStore, *, window_hours: int = 48
) -> Dict[str, int]:
    """Find the post of each `publish_check` asset on the account (GOAL.md §4.3).

    run_due keeps no container id for a failed publish, so a post is matched by caption
    (whitespace normalised) and time: a Reel with the asset's caption, posted within
    `window_hours` of its latest queue row's publish_at / updated_at. Exactly one match:
    row published, post labelled, asset `published`. None: left for the owner
    (release_publish_check). Several: left and logged. An empty caption never matches.
    """
    summary = {"checked": 0, "published": 0, "ambiguous": 0, "not_found": 0}
    checks = store.list_assets(status="publish_check", limit=500)
    if not checks:
        return summary
    posts, cursor = [], None
    for _ in range(RECONCILE_PAGES):
        page = await client.get_media_posts(limit=RECONCILE_PAGE_SIZE, after=cursor)
        posts.extend(page["posts"])
        cursor = page.get("next_cursor")
        if not cursor or not page["posts"]:
            break
    reels = [p for p in posts if p.get("media_product_type") == "REELS" and p.get("timestamp")]
    window = timedelta(hours=window_hours)

    for asset in checks:
        summary["checked"] += 1
        caption = _norm(asset["caption"])
        rows = store._select("SELECT * FROM scheduled_posts", {"asset_id": asset["id"]},
                             "id DESC", 1)
        if not caption or not rows:
            summary["not_found"] += 1
            continue
        times = [parse_dt(rows[0]["publish_at"]), parse_dt(rows[0]["updated_at"])]
        lo, hi = min(times) - window, max(times) + window
        matches = [
            p for p in reels
            if _norm(p.get("caption")) == caption and lo <= parse_dt(p["timestamp"]) <= hi
            and (store.get_label(p["id"]) or {}).get("asset_id") in (None, asset["id"])
        ]
        if not matches:
            summary["not_found"] += 1
            continue
        if len(matches) > 1:
            summary["ambiguous"] += 1
            logger.warning("publish_check_ambiguous", asset_id=asset["id"],
                           media_ids=[p["id"] for p in matches])
            continue
        try:
            transition(store, asset["id"], "published", actor="worker")
        except InvalidTransition as e:  # the owner released it meanwhile
            logger.warning("publish_check_not_applied", asset_id=asset["id"], error=str(e))
            continue
        store.mark_published(rows[0]["id"], matches[0]["id"], matches[0].get("permalink"))
        summary["published"] += 1
    return summary
