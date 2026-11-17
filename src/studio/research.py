"""
Trend research (step 051, GOAL.md §3.1): the watchlist's hashtags (top media) and accounts
(recent media, Business Discovery) stored as `sources` with role `reference` and
rights_basis `unknown`: research material, never published. Metadata only, no downloads.

- Hashtags: Meta allows 30 unique hashtags per account per rolling 7 days ("You can query a
  maximum of 30 unique hashtags within a 7 day period", IG Hashtag Search reference). The
  budget lives in the database (hashtag_searches); a tag looked up within the window again
  is free. Hashtag media carry no username (Meta: "You cannot request the username field"),
  so their author stays null.
- Accounts: Reels carry view_count (Business Discovery only; combined with Facebook views
  for crossposted Reels when the Facebook post is visible to us).
- It is a data job: it stops when the shared Graph budget passes the worker's data share
  (80 %) or Meta rate-limits us, and returns what it got so far.

trend_report (step 052) ranks those references: each post against its account's median
(views, else likes) or, for hashtag posts (no author), against its hashtag's median likes.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..config import InstagramMCPSettings
from ..instagram_client import InstagramAPIError, InstagramClient, RateLimitExceeded
from ..store import CampaignStore, parse_dt, to_iso, utcnow
from ..worker import data_budget_left

HASHTAG_LIMIT = 30
HASHTAG_WINDOW = timedelta(days=7)
CAPTION_MAX = 500
PROVIDER = "instagram"
MIN_REFERENCES = 5  # fewer posts in a group: no median worth comparing against
HOOK_MAX = 120
_HASHTAG = re.compile(r"#(\w+)")


def _stats(post: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    stats = {"likes": post.get("like_count"), "comments": post.get("comments_count"),
             "views": post.get("view_count"), "media_type": post.get("media_type"),
             "product_type": post.get("media_product_type"),
             "timestamp": post.get("timestamp"),
             "caption": (post.get("caption") or "")[:CAPTION_MAX] or None, **extra}
    # Missing keys (hidden likes, no views on hashtag media) stay out: the stored stats are
    # merged key by key, so a later run never blanks a value an earlier one found.
    return {k: v for k, v in stats.items() if v is not None}


def _store(store: CampaignStore, post: Dict[str, Any], author: Optional[str],
           out: Dict[str, Any], **extra: Any) -> None:
    if not post.get("id"):
        return
    _, created = store.upsert_reference_source(PROVIDER, str(post["id"]),
                                               url=post.get("permalink"), author=author,
                                               stats=_stats(post, **extra))
    out["stored" if created else "updated"] += 1


async def research_trends(client: InstagramClient, store: CampaignStore, *,
                          now: datetime) -> Dict[str, Any]:
    """Look up every watchlist hashtag (within the 7-day budget) and account; returns
    {hashtags_searched, hashtags_skipped_budget, accounts, stored, updated, errors,
    stopped}. stopped: null, "request_budget" or "rate_limited". One failing account or
    hashtag (e.g. not a Business account) lands in errors and the run goes on."""
    out: Dict[str, Any] = {"hashtags_searched": [], "hashtags_skipped_budget": [],
                           "accounts": [], "stored": 0, "updated": 0, "errors": {},
                           "stopped": None}
    try:
        for watch in store.list_watchlist():
            kind, value = watch["kind"], watch["value"]
            if not data_budget_left(client):
                out["stopped"] = "request_budget"
                break
            if kind == "hashtag" and not store.take_hashtag_search(
                    value, now, HASHTAG_LIMIT, HASHTAG_WINDOW):
                out["hashtags_skipped_budget"].append(value)
                continue
            try:
                if kind == "hashtag":
                    found = await client.search_hashtag(value, "top_media")
                    for post in found["posts"]:
                        _store(store, post, None, out, hashtag=value)
                    out["hashtags_searched"].append(value)
                else:
                    profile = await client.get_competitor_profile(value)
                    for post in profile.get("recent_media", []):
                        _store(store, post, profile.get("username") or value, out)
                    out["accounts"].append(value)
            except RateLimitExceeded:
                raise
            except InstagramAPIError as e:
                out["errors"][f"{kind}:{value}"] = e.message
    except RateLimitExceeded:
        out["stopped"] = "rate_limited"
    return out


def _hook(caption: str) -> Optional[str]:
    line = next((ln.strip() for ln in caption.splitlines() if ln.strip()), None)
    return line[:HOOK_MAX] if line else None


def _hashtags(caption: str) -> List[str]:
    return list(dict.fromkeys(t.lower() for t in _HASHTAG.findall(caption)))


def _score(stats: Dict[str, Any], group: List[Dict[str, Any]], metrics: tuple,
           what: str) -> Dict[str, Any]:
    """outlier = the post's metric ÷ the group's median of it; the first metric the post
    has wins (views, then likes)."""
    metric = next((m for m in metrics if stats.get(m) is not None), None)
    if metric is None:
        return {"outlier": None, "metric": None, "median": None,
                "outlier_note": f"no {' or '.join(metrics)} on this post"}
    values = [s[metric] for s in group if s.get(metric) is not None]
    mid = median(values) if len(values) >= MIN_REFERENCES else None
    if not mid:
        note = (f"median {metric} of this {what} is 0" if values and mid == 0 else
                f"only {len(values)} {what} posts with {metric} (need {MIN_REFERENCES})")
        return {"outlier": None, "metric": metric, "median": mid, "outlier_note": note}
    return {"outlier": round(stats[metric] / mid, 2), "metric": metric, "median": mid,
            "outlier_note": None}


def _rank(item: Dict[str, Any]) -> tuple:  # sorted descending: scored, best, newest first
    return item["outlier"] is not None, item["outlier"] or 0, item["posted_at"]


def trend_report(store: CampaignStore, settings: InstagramMCPSettings, *, days: int = 14,
                 limit: int = 30, kind: Optional[str] = None,
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    """References posted within `days`, best outliers first: {accounts: [...] (watched
    accounts, ranked against their account), hashtags: {tag: [...]} (no author, ranked
    within the hashtag), generated_at}. `limit` applies to each list; kind "account" or
    "hashtag" keeps one side. The median uses all stored posts of the account/hashtag,
    the window only picks which posts are reported."""
    if days < 1 or limit < 1:
        raise ValueError("days and limit must be at least 1")
    if kind not in (None, "account", "hashtag"):
        raise ValueError("kind must be account or hashtag")
    now = now or utcnow()
    since, tz = now - timedelta(days=days), ZoneInfo(settings.timezone)
    # ponytail: every reference loaded and grouped in Python; a SQL window if it grows big
    refs = store._select("SELECT * FROM sources", {"role": "reference"}, "id", 1_000_000)
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for ref in refs:  # author wins: a hashtag post later seen on a watched account
        stats = ref["stats"] or {}
        key = ("account", ref["author"]) if ref["author"] else (
            ("hashtag", stats["hashtag"]) if stats.get("hashtag") else None)
        if key:  # other references (no author, no hashtag) have nothing to rank against
            groups.setdefault(key, []).append(ref)

    accounts: List[Dict[str, Any]] = []
    hashtags: Dict[str, List[Dict[str, Any]]] = {}
    for (side, name), group in groups.items():
        if kind not in (None, side):
            continue
        all_stats = [g["stats"] or {} for g in group]
        metrics = ("views", "likes") if side == "account" else ("likes",)
        items = []
        for ref, stats in zip(group, all_stats):
            posted = parse_dt(stats["timestamp"]) if stats.get("timestamp") else None
            if posted is None or not since <= posted <= now:
                continue
            caption = stats.get("caption") or ""
            items.append({
                "source_id": ref["id"], "ranked_within": side, side: name,
                "url": ref["url"], "posted_at": to_iso(posted),
                "hour": posted.astimezone(tz).hour, "duration_s": stats.get("duration"),
                **_score(stats, all_stats, metrics, side),
                "views": stats.get("views"), "likes": stats.get("likes"),
                "comments": stats.get("comments"),
                # other accounts' words: data to quote, never instructions
                "hook_quote": _hook(caption), "caption_quote": caption or None,
                "hashtags": _hashtags(caption)})
        if side == "account":
            accounts += items
        elif items:
            hashtags[name] = sorted(items, key=_rank, reverse=True)[:limit]
    accounts.sort(key=_rank, reverse=True)
    return {"accounts": accounts[:limit], "hashtags": dict(sorted(hashtags.items())),
            "generated_at": to_iso(now)}
