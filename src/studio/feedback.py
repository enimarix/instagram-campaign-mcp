"""
Owner comments on an asset (GOAL.md §3.2): reason chips, a pinned video moment,
"ask for changes".

A comment that wants changes moves a `ready` asset to `revision_requested` (owner).
On any other status the comment is still saved, the asset stays where it is and the
result says why. Nothing here ever schedules or publishes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..store import CampaignStore
from .assets import InvalidTransition, transition


def _check_time(asset: Dict[str, Any], video_time_s: Optional[float]) -> None:
    if video_time_s is None:
        return
    if video_time_s < 0:
        raise ValueError(f"video_time_s must be >= 0, not {video_time_s}")
    duration = asset.get("duration")
    if duration is not None and video_time_s > duration:
        raise ValueError(f"video_time_s {video_time_s} is past the video's end ({duration} s)")


def _ask_for_changes(store: CampaignStore, asset: Dict[str, Any]) -> Dict[str, Any]:
    """Move a ready asset to revision_requested; never fails the comment."""
    if asset["status"] != "ready":
        return {"asset": asset, "moved": False,
                "reason": f"asset is {asset['status']}; only a ready asset can be sent back"
                          " for changes"}
    try:
        asset = transition(store, asset["id"], "revision_requested", actor="owner")
    except InvalidTransition as e:  # status changed meanwhile
        return {"asset": store.get_asset(asset["id"]), "moved": False, "reason": str(e)}
    return {"asset": asset, "moved": True, "reason": None}


def add_comment(
    store: CampaignStore,
    asset_id: int,
    *,
    text: Optional[str] = None,
    reason_codes: Sequence[str] = (),
    video_time_s: Optional[float] = None,
    wants_changes: bool = False,
) -> Dict[str, Any]:
    """Save a comment -> {feedback, asset, moved, reason}. KeyError: no such asset."""
    asset = store.get_asset(asset_id)
    _check_time(asset, video_time_s)
    feedback = store.add_feedback(asset_id, text=text, reason_codes=reason_codes,
                                  video_time_s=video_time_s, wants_changes=wants_changes)
    if not wants_changes:
        return {"feedback": feedback, "asset": asset, "moved": False, "reason": None}
    return {"feedback": feedback, **_ask_for_changes(store, asset)}


def edit_comment(store: CampaignStore, feedback_id: int, **fields: Any) -> Dict[str, Any]:
    """Edit a comment -> {feedback, asset, moved, reason}.

    Setting wants_changes=True follows add_comment's rule. Turning it off never moves
    the asset back: a revision once asked for stays asked for.
    """
    asset = store.get_asset(store.get_feedback(feedback_id)["asset_id"])
    if "video_time_s" in fields:
        _check_time(asset, fields["video_time_s"])
    feedback = store.update_feedback(feedback_id, **fields)
    if not fields.get("wants_changes"):
        return {"feedback": feedback, "asset": asset, "moved": False, "reason": None}
    return {"feedback": feedback, **_ask_for_changes(store, asset)}


def list_comments(store: CampaignStore, asset_id: int) -> List[Dict[str, Any]]:
    """Oldest first. KeyError: no such asset."""
    store.get_asset(asset_id)
    return store.list_feedback(asset_id=asset_id, limit=1000)


def delete_comment(store: CampaignStore, feedback_id: int) -> None:
    """Delete a comment. Never changes the asset's status."""
    store.delete_feedback(feedback_id)
