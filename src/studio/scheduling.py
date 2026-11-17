"""
Scheduling an approved asset from the website (GOAL.md §3.2): the planner proposes a
slot, the owner accepts it or picks another time, the publish guard queues it.

Approve and schedule are two owner steps on the detail page; the review feed's one-tap
Approve (approve_and_queue, step 115) does both at once.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..campaign import _next_free_slot, free_slot
from ..config import InstagramMCPSettings
from ..store import CampaignStore, parse_dt, to_iso
from .assets import InvalidTransition, transition
from .publish import _source, cancel_post, queue_asset
from .seed import local_today


def _taken(store: CampaignStore, now: datetime) -> List[datetime]:
    """Queued slots plus the last day's publishes (same reading as campaign.hold_queue)."""
    return [parse_dt(r["publish_at"] if r["status"] == "pending" else r["updated_at"])
            for r in store.queue_times(since=now - timedelta(days=1))]


def _slot(settings: InstagramMCPSettings, at: datetime) -> Dict[str, str]:
    return {"publish_at": to_iso(at),
            "local": at.astimezone(ZoneInfo(settings.timezone)).isoformat(timespec="seconds")}


def propose_slot(
    store: CampaignStore, settings: InstagramMCPSettings, asset_id: int, now: datetime
) -> Dict[str, Any]:
    """The next free slot (today or the next days) for the asset, with the planner's rules
    and the audience profile. `needs_confirmation`: a `commentary` source needs the
    owner's per-video confirmation at queue time (§5.1). KeyError for an unknown asset."""
    asset = store.get_asset(asset_id)
    rights = _source(store, store.get_idea(asset["idea_id"])).get("rights_basis")
    at = _next_free_slot(store, settings, _taken(store, now), now)
    return {**_slot(settings, at), "needs_confirmation": rights == "commentary"}


def schedule_asset(
    store: CampaignStore,
    settings: InstagramMCPSettings,
    asset_id: int,
    publish_at: datetime,
    confirmed: bool = False,
) -> Dict[str, Any]:
    """Queue the approved asset at `publish_at` through the publish guard (QueueRefused /
    ValueError pass through); return {post, asset}."""
    post = queue_asset(store, settings, asset_id, publish_at, confirmed=confirmed)
    return {"post": post, "asset": store.get_asset(asset_id)}


def approve_and_queue(
    store: CampaignStore,
    settings: InstagramMCPSettings,
    asset_id: int,
    now: datetime,
    confirmed: bool = False,
) -> Dict[str, Any]:
    """The feed's one-tap Approve (step 115): ready -> approved, then queued into the
    planner's next free slot. No free slot within the planner's week: approved only
    (`slot` None) and the owner picks a time in the Calendar. Any refusal (rights, QC,
    file, caption) takes the approval back, so the asset stays `ready`, and passes through.
    Returns {asset, post, slot}."""
    status = store.get_asset(asset_id)["status"]
    if status != "ready":  # scheduled -> approved is also an owner move: not this one
        raise InvalidTransition(f"asset {asset_id} is {status}, not ready")
    transition(store, asset_id, "approved", actor="owner")
    try:
        at = free_slot(store, settings, _taken(store, now), now)
        post = queue_asset(store, settings, asset_id, at, confirmed=confirmed) if at else None
    except Exception:
        transition(store, asset_id, "ready", actor="owner")
        raise
    return {"asset": store.get_asset(asset_id), "post": post,
            "slot": _slot(settings, at) if at else None}


def pending_post(store: CampaignStore, asset_id: int) -> Optional[Dict[str, Any]]:
    """The asset's pending queue row, or None."""
    rows = store._select("SELECT * FROM scheduled_posts",  # no store method (store.py: 026)
                         {"asset_id": asset_id, "status": "pending"}, "id DESC", 1)
    return rows[0] if rows else None


def slot(store: CampaignStore, settings: InstagramMCPSettings, asset_id: int) -> Dict[str, Any]:
    """Where a scheduled asset sits: {post_id, publish_at, local}. KeyError when none."""
    store.get_asset(asset_id)  # unknown asset → KeyError
    row = pending_post(store, asset_id)
    if row is None:
        raise KeyError(f"asset {asset_id} has no queued slot")
    return {"post_id": row["id"], **_slot(settings, parse_dt(row["publish_at"]))}


def unschedule(store: CampaignStore, asset_id: int) -> Dict[str, Any]:
    """Cancel the asset's pending row: scheduled -> approved. Returns the asset."""
    status = store.get_asset(asset_id)["status"]
    row = pending_post(store, asset_id)
    if status != "scheduled" or row is None:
        raise InvalidTransition(f"asset {asset_id} is {status}, not waiting in the queue")
    cancel_post(store, row["id"])
    return store.get_asset(asset_id)


def unapprove(store: CampaignStore, asset_id: int) -> Dict[str, Any]:
    """The owner takes the approval back: a scheduled asset loses its slot first, then
    approved -> ready. publish_check / published refuse (InvalidTransition)."""
    if store.get_asset(asset_id)["status"] == "scheduled":
        unschedule(store, asset_id)
    return transition(store, asset_id, "ready", actor="owner")


def bench(store: CampaignStore, settings: InstagramMCPSettings, now: datetime) -> Dict[str, Any]:
    """Liked videos not yet approved, from every batch (GOAL.md §3.2 "the bench"): freshest
    best_before first (none last), then self_score. Past best_before (owner-local) is left out
    even before housekeeping archives it. `suggestion`: the freshest one for the next free
    slot when that slot is within 24 h; the owner still approves it."""
    today = local_today(settings.timezone, now).isoformat()
    # ponytail: 500 = the store's page cap; a bench that long is weeks of supply anyway.
    rows = [a for a in store.list_assets(status="ready", verdict="liked", limit=500)
            if not a["best_before"] or a["best_before"] >= today]
    rows.sort(key=lambda a: (a["best_before"] is None, a["best_before"] or "",
                             -(a["self_score"] or 0)))
    suggestion = None
    if rows:
        at = _next_free_slot(store, settings, _taken(store, now), now)
        if at - now <= timedelta(hours=24):
            suggestion = {"asset_id": rows[0]["id"], **_slot(settings, at)}
    return {"assets": rows, "supply_days": math.ceil(len(rows) / settings.max_posts_per_day),
            "max_posts_per_day": settings.max_posts_per_day, "suggestion": suggestion}
