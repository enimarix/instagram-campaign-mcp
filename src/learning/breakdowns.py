"""
Tag breakdowns (step 076, GOAL.md §3.4): "what works", the engagement index and medians of
reach / views / watch time grouped by one tag. Only matured posts of one post type count,
scored exactly like rank_posts (analytics.scored_posts). Posts made outside the studio show
as "untagged" (duration "unknown"); the slot hour is owner-local and known for every post.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median, quantiles
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..campaign import scoring_config
from ..config import InstagramMCPSettings
from ..scoring import _is_matured
from ..store import CampaignStore, parse_dt
from .analytics import IDEA_TAGS, POST_TYPES, scored_posts, studio_side

TAGS = IDEA_TAGS + ("template", "hour", "duration")
# Output name -> metric key in the snapshot. 075 adds watch_ratio / view_rate here.
METRICS = {"reach": "reach", "views": "views",
           "avg_watch_time": "ig_reels_avg_watch_time",
           "total_watch_time": "ig_reels_video_view_total_time"}
SMALL_SAMPLE = 3
UNTAGGED, UNKNOWN = "untagged", "unknown"


def duration_bucket(seconds: Optional[float]) -> str:
    if seconds is None:
        return UNKNOWN
    return ("<15 s" if seconds < 15 else "15–30 s" if seconds < 30
            else "30–60 s" if seconds < 60 else "60 s+")


def tag_breakdown(store: CampaignStore, settings: InstagramMCPSettings, *, tag: str,
                  post_type: str, days: int = 90,
                  now: Optional[datetime] = None) -> Dict[str, Any]:
    """Matured `post_type` posts published in the last `days`, grouped by `tag`; groups by
    median engagement index (highest first, no index last). ValueError: unknown tag/type."""
    if tag not in TAGS:
        raise ValueError(f"tag must be one of {TAGS}")
    post_type = (post_type or "").upper()
    if post_type not in POST_TYPES:
        raise ValueError(f"type must be one of {POST_TYPES}")
    since = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    tz, cfg = ZoneInfo(settings.timezone), scoring_config(settings)

    groups: Dict[Any, List[Any]] = {}
    for snap, s in scored_posts(store, settings):
        if (s["group"] != post_type or not _is_matured(snap, cfg) or not snap["posted_at"]
                or parse_dt(snap["posted_at"]) < since):
            continue
        groups.setdefault(_value(store, settings, tag, snap, s, tz), []).append((snap, s))

    out = [_group(value, posts) for value, posts in groups.items()]
    out.sort(key=lambda g: -(g["engagement_index"] or {"median": -1})["median"])
    return {"tag": tag, "post_type": post_type, "days": days, "since": since.isoformat(),
            "groups": out}


def _value(store: CampaignStore, settings: InstagramMCPSettings, tag: str,
           snap: Dict[str, Any], s: Dict[str, Any], tz: ZoneInfo) -> Any:
    if tag == "hour":
        return parse_dt(snap["posted_at"]).astimezone(tz).hour
    # ponytail: two reads per post (asset + idea); one joined query if this gets slow.
    studio = studio_side(store, (s["label"] or {}).get("asset_id"))
    if tag == "duration":
        return duration_bucket(studio["asset"] and studio["asset"]["duration"])
    return (studio["tags"] or {}).get(tag) or UNTAGGED


def _group(value: Any, posts: List[Any]) -> Dict[str, Any]:
    eng = [s["engagement_index"] for _, s in posts if s["engagement_index"] is not None]
    row: Dict[str, Any] = {"tag_value": value, "n": len(posts),
                           "small_sample": len(posts) < SMALL_SAMPLE, "engagement_index": None}
    if eng:
        p25, _, p75 = quantiles(eng, n=4, method="inclusive") if len(eng) > 1 else eng * 3
        row["engagement_index"] = {"median": round(median(eng), 2), "p25": round(p25, 2),
                                   "p75": round(p75, 2)}
    for name, key in METRICS.items():
        vals = [snap["metrics"][key] for snap, _ in posts
                if snap["metrics"].get(key) is not None]
        if vals or name in ("reach", "views"):  # watch times only when some post has them
            row[name] = {"median": round(median(vals), 2) if vals else None}
    return row
