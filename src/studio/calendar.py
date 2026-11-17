"""
The Calendar page (GOAL.md §3.3): the publish queue by owner-local day, and the owner's
actions on a row (reschedule, cancel, re-plan a failed one).
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..campaign import _next_free_slot
from ..config import InstagramMCPSettings
from ..store import CampaignStore, parse_dt, to_iso, utcnow
from .assets import InvalidTransition
from .media import media_url
from .publish import cancel_post
from .scheduling import _taken, propose_slot, schedule_asset

MAX_DAYS = 62
EXCERPT = 80
REPLANNED = "Re-planned: "  # campaign.hold_queue's note in the row's error field


def _row(r: Dict[str, Any], tz: ZoneInfo) -> Dict[str, Any]:
    caption = " ".join((json.loads(r["payload"]).get("caption") or "").split())
    error = r["error"]
    return {
        "id": r["id"], "kind": r["kind"], "status": r["status"], "attempts": r["attempts"],
        "publish_at": r["publish_at"],
        "local": parse_dt(r["publish_at"]).astimezone(tz).isoformat(timespec="seconds"),
        "caption": caption[:EXCERPT] + ("…" if len(caption) > EXCERPT else ""),
        "asset_id": r["asset_id"], "preview_url": media_url(r["preview_path"]),
        "permalink": r["permalink"], "error": error,
        "replanned": r["status"] == "pending" and (error or "").startswith(REPLANNED),
    }


def calendar(
    store: CampaignStore, settings: InstagramMCPSettings, start: date, end: date
) -> Dict[str, Any]:
    """Queue rows by owner-local day from `start` to `end` (inclusive, ≤ MAX_DAYS), every
    day listed even when empty, plus the `publish_check` assets (not tied to a day).
    ValueError for a reversed or too long range."""
    days = (end - start).days + 1
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"from..to must cover 1 to {MAX_DAYS} days")
    tz = ZoneInfo(settings.timezone)
    lo = datetime.combine(start, time(), tzinfo=tz)
    hi = datetime.combine(end + timedelta(days=1), time(), tzinfo=tz)
    with store._tx() as c:  # no store method for a time range (store.py belongs to 034)
        rows = c.execute(
            "SELECT p.*, a.preview_path FROM scheduled_posts p"
            " LEFT JOIN assets a ON a.id = p.asset_id"
            " WHERE p.publish_at >= ? AND p.publish_at < ? ORDER BY p.publish_at, p.id",
            (to_iso(lo), to_iso(hi)),
        ).fetchall()
    by_day: Dict[str, List[Dict[str, Any]]] = {
        str(start + timedelta(days=i)): [] for i in range(days)}
    for r in rows:
        row = _row(dict(r), tz)
        by_day[row["local"][:10]].append(row)
    return {"days": [{"date": d, "posts": p} for d, p in by_day.items()],
            "publish_check": store.list_assets(status="publish_check", limit=500)}


def reschedule(store: CampaignStore, post_id: int, publish_at: datetime) -> Dict[str, Any]:
    """Move a row to `publish_at` (the store refuses published / in-flight rows and a
    studio asset's row unless pending). ValueError for a time in the past."""
    if publish_at <= utcnow():
        raise ValueError("publish_at must be in the future")
    return store.reschedule(post_id, publish_at)


def replan(
    store: CampaignStore, settings: InstagramMCPSettings, post_id: int, *,
    confirmed: bool = False, now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Give a failed row a new slot from the planner. Returns the row that will publish.

    - A plain (non-asset) row is rescheduled in place to the next free slot.
    - A studio asset's row is never revived (the publish guard must look again): the
      asset is queued anew through schedule_asset, which needs it back to `approved`
      (a publish_check asset must be released first), and the failed row is cancelled
      so the calendar shows only the new one. `confirmed`: a commentary clip's check.
    InvalidTransition when the row has not failed.
    """
    now = now or utcnow()
    post = store.get_scheduled(post_id)
    if post["status"] != "failed":
        raise InvalidTransition(f"post {post_id} is {post['status']}, not failed")
    if post["asset_id"] is None:
        return store.reschedule(post_id, _next_free_slot(store, settings, _taken(store, now), now))
    at = parse_dt(propose_slot(store, settings, post["asset_id"], now)["publish_at"])
    new = schedule_asset(store, settings, post["asset_id"], at, confirmed)["post"]
    cancel_post(store, post_id)
    return new
