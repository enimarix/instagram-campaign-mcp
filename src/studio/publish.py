"""
The publish guard (GOAL.md §3.3, §5.1, §5.2).

`queue_asset()` is the only way a studio asset reaches the publish queue. The worker's
side (keeping the asset's status truthful after a publish) lives in campaign.run_due.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from ..config import InstagramMCPSettings
from ..instagram_client import caption_problem
from ..store import CampaignStore, utcnow
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
    problem = caption_problem(asset["caption"])
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
