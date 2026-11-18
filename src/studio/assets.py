"""
Asset lifecycle (GOAL.md §4.3).

`transition()` is the only way an asset's status changes. MOVES is the GOAL.md
lifecycle table, one entry per row: (from, to) -> who may make that move. Any
other move, or the right move by the wrong actor, raises InvalidTransition.
`verdict` is separate: set_verdict() never touches status.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Set, Tuple

from ..instagram_client import caption_problem
from ..store import CampaignStore, to_iso, utcnow
from .dm_picks import mark_posted

ACTORS = ("owner", "agent", "worker", "system")
VERDICTS = ("none", "liked", "disliked")

MOVES: Dict[Tuple[str, str], Set[str]] = {
    ("rendering", "ready"): {"worker"},  # QC passed
    ("rendering", "failed"): {"worker"},
    ("failed", "rendering"): {"agent", "owner"},  # re-render
    ("needs_reaction", "rendering"): {"owner"},  # owner uploads a reaction take
    ("ready", "approved"): {"owner"},  # owner only
    ("ready", "revision_requested"): {"owner"},  # comment that asks for changes
    ("revision_requested", "archived"): {"system"},  # when the new version is ready
    # owner; worker when unreviewed for N days, or liked and past best_before
    ("ready", "archived"): {"owner", "worker"},
    ("approved", "ready"): {"owner"},  # unapprove
    # studio.publish.queue_asset() only: the sole "system" caller of this move
    ("approved", "scheduled"): {"system"},
    # owner cancels the slot; worker when the publish failed for good and
    # certainly did not reach Instagram
    ("scheduled", "approved"): {"owner", "worker"},
    ("scheduled", "publish_check"): {"worker"},  # publish may have reached Instagram
    ("publish_check", "published"): {"worker"},  # reconcile job found the post
    ("publish_check", "approved"): {"owner"},  # owner only, post is not on Instagram
    ("scheduled", "published"): {"worker"},
}

# from -> allowed targets (published and archived are final)
ALLOWED: Dict[str, Set[str]] = {}
for _frm, _to in MOVES:
    ALLOWED.setdefault(_frm, set()).add(_to)


class InvalidTransition(ValueError):
    """A status move the lifecycle table does not allow (or a stale one)."""


def transition(
    store: CampaignStore, asset_id: int, to_status: str, *, actor: str
) -> Dict[str, Any]:
    """Move an asset to `to_status` if the table allows it for `actor`; return the asset."""
    if actor not in ACTORS:
        raise ValueError(f"actor must be one of {ACTORS}, not {actor!r}")
    asset = store.get_asset(asset_id)
    frm = asset["status"]
    who = MOVES.get((frm, to_status))
    if who is None or actor not in who:
        targets = ", ".join(
            f"{to} ({'/'.join(sorted(MOVES[(frm, to)]))})" for to in sorted(ALLOWED.get(frm, ()))
        )
        raise InvalidTransition(
            f"asset {asset_id}: {frm} -> {to_status} is not allowed for {actor}; "
            f"allowed from {frm}: {targets or 'none'}"
        )
    # The owner's approval stamps approved_at, unapprove clears it. Coming back to
    # approved from scheduled / publish_check keeps the original approval time.
    stamp: Dict[str, Any] = {}
    if (frm, to_status) == ("ready", "approved"):
        stamp["approved_at"] = to_iso(utcnow())
    elif (frm, to_status) == ("approved", "ready"):
        stamp["approved_at"] = None
    if not store._set_asset_status(asset_id, frm, to_status, **stamp):
        raise InvalidTransition(
            f"asset {asset_id} is no longer {frm} (changed meanwhile);"
            f" {frm} -> {to_status} not applied"
        )
    if to_status == "published":  # every publish path (run_due, reconcile) passes here
        mark_posted(store, asset_id)
    if actor == "owner" and frm == "ready" and asset["parent_asset_id"]:
        _change_decided(store, asset["parent_asset_id"])
    return store.get_asset(asset_id)


def _change_decided(store: CampaignStore, before_id: int) -> None:
    """The owner decided on a revised video (approved, declined, archived or sent back
    again): the change requests on the version it replaced come back to the agent's
    feedback (undigested), now carrying the outcome, so the agent learns what worked and
    what did not (step 133)."""
    with store._tx() as c:
        c.execute("UPDATE feedback SET digested_at = NULL"
                  " WHERE asset_id = ? AND wants_changes = 1", (before_id,))


def set_verdict(store: CampaignStore, asset_id: int, verdict: str) -> Dict[str, Any]:
    """Like / dislike / clear. Never moves status."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, not {verdict!r}")
    return store.update_asset(asset_id, verdict=verdict)


EDITABLE = ("caption", "best_before", "description")
DESCRIPTION_CHARS = 400


def edit_asset(store: CampaignStore, asset_id: int, **fields: Any) -> Dict[str, Any]:
    """Owner edits: caption (Instagram's limits), best_before (local date YYYY-MM-DD or None)
    and description (what happens in the video, 1-DESCRIPTION_CHARS characters).

    Only the keys given change; ValueError names the problem.
    """
    unknown = set(fields) - set(EDITABLE)
    if unknown:
        raise ValueError(f"only {' and '.join(EDITABLE)} can be edited,"
                         f" not {', '.join(sorted(unknown))}")
    if "caption" in fields:
        status = store.get_asset(asset_id)["status"]
        if status in ("scheduled", "publish_check", "published"):
            raise ValueError(f"the caption can't change once the asset is {status}"
                             " (cancel the queued post first)")
        problem = caption_problem(fields["caption"])
        if problem:
            raise ValueError(problem)
    best_before = fields.get("best_before")
    if best_before is not None:
        try:  # round trip: fromisoformat takes more formats on 3.11+, we want YYYY-MM-DD only
            ok = date.fromisoformat(best_before).isoformat() == best_before
        except (TypeError, ValueError):
            ok = False
        if not ok:
            raise ValueError(f"best_before must be a date YYYY-MM-DD, not {best_before!r}")
    if "description" in fields:
        text = fields["description"].strip() if isinstance(fields["description"], str) else ""
        if not 1 <= len(text) <= DESCRIPTION_CHARS:
            raise ValueError(f"description must be 1-{DESCRIPTION_CHARS} characters")
        fields["description"] = text
    return store.update_asset(asset_id, **fields)
