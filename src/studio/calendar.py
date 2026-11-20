"""
The Calendar page (GOAL.md §3.3): the publish queue by owner-local day, and the owner's
actions on a row (reschedule, cancel, re-plan a failed one).
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..campaign import _next_free_slot
from ..config import InstagramMCPSettings
from ..learning.slots import parse_windows
from ..store import CampaignStore, parse_dt, to_iso, utcnow
from .assets import InvalidTransition
from .media import media_url
from .publish import cancel_post
from .scheduling import _taken, propose_slot, schedule_asset

MAX_DAYS = 62
EXCERPT = 80
REPLANNED = "Re-planned: "  # campaign.hold_queue's note in the row's error field
LIVE = ("pending", "publishing", "published")  # a row that still goes / went out
HOT = 3  # hot_hours: this many best hours of the audience profile are hot
MAX_HOT_DAYS = 14


def _local(at: str, tz: ZoneInfo) -> str:
    return parse_dt(at).astimezone(tz).isoformat(timespec="seconds")


def _row(r: Dict[str, Any], tz: ZoneInfo) -> Dict[str, Any]:
    caption = " ".join((json.loads(r["payload"]).get("caption") or "").split())
    moved = r["moved_id"] is not None
    error = None if moved else r["error"]  # the old failure is no longer the story
    return {
        "id": r["id"], "kind": r["kind"], "status": r["status"], "attempts": r["attempts"],
        "publish_at": r["publish_at"], "local": _local(r["publish_at"], tz),
        "caption": caption[:EXCERPT] + ("…" if len(caption) > EXCERPT else ""),
        "asset_id": r["asset_id"], "preview_url": media_url(r["preview_path"]),
        "permalink": r["permalink"], "error": error,
        "replanned": r["status"] == "pending" and (error or "").startswith(REPLANNED),
        "moved_to": {"id": r["moved_id"], "publish_at": r["moved_at"],
                     "local": _local(r["moved_at"], tz)} if moved else None,
    }


def calendar(
    store: CampaignStore, settings: InstagramMCPSettings, start: date, end: date
) -> Dict[str, Any]:
    """Queue rows by owner-local day from `start` to `end` (inclusive, ≤ MAX_DAYS), every
    day listed even when empty, plus the `publish_check` assets (not tied to a day).
    A cancelled row whose asset has a later live row (re-planned, or queued again) carries
    `moved_to` {id, publish_at, local} of the newest one, even outside the range.
    ValueError for a reversed or too long range."""
    days = (end - start).days + 1
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"from..to must cover 1 to {MAX_DAYS} days")
    tz = ZoneInfo(settings.timezone)
    lo = datetime.combine(start, time(), tzinfo=tz)
    hi = datetime.combine(end + timedelta(days=1), time(), tzinfo=tz)
    with store._tx() as c:  # no store method for a time range (store.py belongs to 034)
        rows = c.execute(
            "SELECT p.*, a.preview_path, m.id AS moved_id, m.publish_at AS moved_at"
            " FROM scheduled_posts p LEFT JOIN assets a ON a.id = p.asset_id"
            " LEFT JOIN scheduled_posts m ON p.status = 'cancelled' AND m.id = ("
            "  SELECT n.id FROM scheduled_posts n WHERE n.asset_id = p.asset_id"
            "  AND n.id > p.id AND n.status IN (?, ?, ?) ORDER BY n.id DESC LIMIT 1)"
            " WHERE p.publish_at >= ? AND p.publish_at < ? ORDER BY p.publish_at, p.id",
            (*LIVE, to_iso(lo), to_iso(hi)),
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
    """Give a failed row a new slot from the planner. Returns the row that will publish,
    with its owner-local `local` time (the page tells the owner where it went).

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
        new = store.reschedule(post_id, _next_free_slot(store, settings, _taken(store, now), now))
    else:
        at = parse_dt(propose_slot(store, settings, post["asset_id"], now)["publish_at"])
        new = schedule_asset(store, settings, post["asset_id"], at, confirmed)["post"]
        cancel_post(store, post_id)
    return {**new, "local": _local(new["publish_at"], ZoneInfo(settings.timezone))}


def hot_hours(
    store: CampaignStore, settings: InstagramMCPSettings, days: int = MAX_HOT_DAYS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """The Reschedule picker: every coming owner-local hour of the next `days` days (today
    first), scored with the planner's own audience data (store.online_followers_profile,
    followers online per UTC hour: what slots.window_weights weighs the windows with).

    Per hour: `publish_at` (its start, UTC) and `local`, `followers` (None: no data for that
    hour), `score` 0..1 (share of the best hour), `hot` (among the HOT best hours of the
    profile) and `taken` (ids of the pending / in-flight posts inside that hour). With no
    audience data yet `has_data` is False, and the hours inside the planner's posting
    windows are the hot ones (score 1). ValueError for `days` outside 1..MAX_HOT_DAYS.
    """
    if not 1 <= days <= MAX_HOT_DAYS:
        raise ValueError(f"days must be 1 to {MAX_HOT_DAYS}")
    now = now or utcnow()
    tz = ZoneInfo(settings.timezone)
    profile = {h: f for h, f in store.online_followers_profile().items() if f and f > 0}
    best = sorted(profile.values(), reverse=True)
    windows = parse_windows(settings.posting_windows)
    taken: Dict[datetime, List[int]] = {}
    for r in store.queue_times(since=now):
        if r["status"] != "published":
            hour = parse_dt(r["publish_at"]).replace(minute=0, second=0, microsecond=0)
            taken.setdefault(hour, []).append(r["id"])
    first = now.astimezone(tz).date()
    out = []
    for i in range(days):
        day, hours, seen = first + timedelta(days=i), [], set()
        for h in range(24):
            # ponytail: a DST gap/overlap hour collapses onto another instant; skip repeats.
            at = datetime.combine(day, time(h), tzinfo=tz).astimezone(timezone.utc)
            if at <= now or at in seen:
                continue
            seen.add(at)
            followers = profile.get(at.hour)
            if best:
                score = (followers or 0) / best[0]
                hot = followers is not None and followers >= best[:HOT][-1]
            else:
                hot = any(a.hour <= h and time(h) < b for a, b in windows)
                score = float(hot)
            hours.append({"hour": h, "publish_at": to_iso(at), "local": _local(to_iso(at), tz),
                          "followers": followers, "score": round(score, 3), "hot": hot,
                          "taken": taken.get(at, [])})
        out.append({"date": str(day), "hours": hours})
    return {"has_data": bool(best), "posting_windows": settings.posting_windows, "days": out}
