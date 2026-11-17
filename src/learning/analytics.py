"""
Analytics reads for the website (step 074, GOAL.md §3.4): the account series, the posts
table and one post's detail. Posts are scored by src/scoring.py with per-post indexed
baseline queries (store.snapshots_near_age), never the whole snapshot history.
Lives in src/learning/ (GOAL.md §4.2: analytics feed the learning loop).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..campaign import scoring_config
from ..config import InstagramMCPSettings
from ..scoring import group_of, score_posts
from ..store import ACCOUNT_SNAPSHOT_FIELDS, CampaignStore
from ..studio.media import media_url
from ..studio.seed import local_today

SCORE_KEYS = ("verdict", "why", "engagement_index", "reach_index", "confidence",
              "baseline_posts", "drivers", "watch_ratio", "view_rate")
ROW_SORTS = ("posted_at", "age_hours", "engagement_index", "reach_index", "watch_ratio",
             "view_rate")
METRIC_SORTS = ("views", "reach", "likes", "comments", "saved", "shares",
                "ig_reels_avg_watch_time")
POST_TYPES = ("FEED", "REELS", "STORY")
VERDICTS = ("winner", "promising", "average", "weak", "inconclusive", "no_signal", "too_early",
            "incomplete", "no_baseline")  # src/scoring.py
IDEA_TAGS = ("track", "pillar", "hook_type", "strategy")
CAPTION_CHARS = 120


def account_series(store: CampaignStore, since: date, until: date) -> Dict[str, Any]:
    """Daily account rows in [since, until], oldest first. deltas: change since the
    previous stored day (also when that day is before `since`); None when unknown."""
    days, prev = [], None
    for r in store.account_snapshots():  # ponytail: one row per day, a few hundred a year
        row = {"date": r["date"], **{k: r[k] for k in ACCOUNT_SNAPSHOT_FIELDS}}
        if since.isoformat() <= row["date"] <= until.isoformat():
            days.append({**row, "deltas": {
                k: row[k] - prev[k] if prev and None not in (row[k], prev[k]) else None
                for k in ACCOUNT_SNAPSHOT_FIELDS}})
        prev = row
    return {"since": since.isoformat(), "until": until.isoformat(), "days": days}


def recent_account_series(store: CampaignStore, settings: InstagramMCPSettings, days: int,
                          now: Optional[datetime] = None) -> Dict[str, Any]:
    """The last `days` owner-local days, today included."""
    today = local_today(settings.timezone, now)
    return account_series(store, today - timedelta(days=days - 1), today)


def posts_table(store: CampaignStore, settings: InstagramMCPSettings, *, limit: int = 50,
                offset: int = 0, sort: str = "-posted_at",
                post_type: Optional[str] = None, verdict: Optional[str] = None,
                tagged: Optional[bool] = None) -> Dict[str, Any]:
    """One row per post: latest metrics, score, deletion mark, and the studio asset's owner
    verdict, tags and preview/thumbnail URLs (None for posts made outside the studio).
    sort: a key of ROW_SORTS or METRIC_SORTS, '-' first for descending; posts without the
    value go last. verdict: the score's verdict; tagged: made by the studio (has idea tags)
    or not. ValueError: unknown sort, post type or verdict."""
    desc, key = sort.startswith("-"), sort.lstrip("-")
    if key not in ROW_SORTS + METRIC_SORTS:
        raise ValueError(f"sort must be one of {ROW_SORTS + METRIC_SORTS}, '-' for descending")
    if post_type is not None and post_type.upper() not in POST_TYPES:
        raise ValueError(f"type must be one of {POST_TYPES}")
    if verdict is not None and verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    rows = []
    for snap, s in scored_posts(store, settings):
        asset_id = (s["label"] or {}).get("asset_id")
        if ((post_type and s["group"] != post_type.upper())
                or (verdict and s.get("verdict") != verdict)
                or (tagged is not None and tagged != (asset_id is not None))):
            continue
        rows.append({
            "media_id": snap["media_id"], "permalink": snap["permalink"],
            "posted_at": snap["posted_at"], "product_type": snap["media_product_type"],
            "group": s["group"], "age_hours": snap["age_hours"], "metrics": snap["metrics"],
            "caption": (snap["caption"] or "")[:CAPTION_CHARS],
            "deleted": bool((s["label"] or {}).get("deleted_at")),
            "asset_id": asset_id,
            **{k: s.get(k) for k in SCORE_KEYS},
        })

    def value(row: Dict[str, Any]) -> Any:
        return row[key] if key in ROW_SORTS else row["metrics"].get(key)

    rows = (sorted((r for r in rows if value(r) is not None), key=value, reverse=desc)
            + [r for r in rows if value(r) is None])
    page = rows[offset:offset + limit]
    for row in page:  # only the page's assets are read
        row.update(studio_side(store, row["asset_id"]))
        row.update(_urls(row.pop("asset")))
    return {"total": len(rows), "limit": limit, "offset": offset, "sort": sort, "posts": page}


def scored_posts(store: CampaignStore,
                 settings: InstagramMCPSettings) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """(latest snapshot, score) per post, newest first, scored like rank_posts. The score's
    `label` is the post's post_labels row (None when it has none)."""
    latest = store.latest_snapshots()
    # ponytail: scores every post (one baseline query per matured post) on each call;
    # cache by latest snapshot id if the table gets slow.
    scored = score_posts(latest, scoring_config(settings), store.labels(),
                         near_age=store.snapshots_near_age)
    return list(zip(latest, scored))  # score_posts keeps the input order


def post_detail(store: CampaignStore, media_id: str) -> Dict[str, Any]:
    """One post: its own snapshot series (oldest first), tags, hypothesis, source asset with
    preview URL and the owner's feedback when the studio made it. KeyError: unknown media."""
    snaps = store.media_snapshots(media_id)
    if not snaps:
        raise KeyError(f"No snapshots for media {media_id}")
    last, label = snaps[-1], store.get_label(media_id) or {}
    studio = studio_side(store, label.get("asset_id"))
    asset = studio.pop("asset")
    return {
        "media_id": media_id, "permalink": last["permalink"], "posted_at": last["posted_at"],
        "product_type": last["media_product_type"], "group": group_of(last),
        "caption": last["caption"], "deleted": bool(label.get("deleted_at")),
        "campaign": label.get("campaign"), "variant": label.get("variant"),
        **studio,
        "hypothesis": studio["hypothesis"] or label.get("hypothesis"),
        **_urls(asset),
        "feedback": store.list_feedback(asset_id=asset["id"], limit=1000) if asset else [],
        "series": [{"captured_at": s["captured_at"], "age_hours": s["age_hours"],
                    "metrics": s["metrics"]} for s in snaps],
    }


def _urls(asset: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """The studio video (preview, else master) and thumbnail URLs; None outside the studio."""
    asset = asset or {}
    return {"preview_url": media_url(asset.get("preview_path") or asset.get("file_path")),
            "thumbnail_url": media_url(asset.get("thumbnail_path"))}


def studio_side(store: CampaignStore, asset_id: Optional[int]) -> Dict[str, Any]:
    """The studio side of a post: asset, owner verdict, idea tags and hypothesis."""
    if asset_id is None:
        return {"asset": None, "asset_id": None, "owner_verdict": None, "tags": None,
                "hypothesis": None}
    asset = store.get_asset(asset_id)
    idea = store.get_idea(asset["idea_id"])
    return {
        "asset": asset, "asset_id": asset_id, "owner_verdict": asset["verdict"],
        "tags": {**{k: idea[k] for k in IDEA_TAGS}, "template": (asset["recipe"] or {}).get("template")},
        "hypothesis": idea["hypothesis"],
    }
