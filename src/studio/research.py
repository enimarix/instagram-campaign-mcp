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
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from ..instagram_client import InstagramAPIError, InstagramClient, RateLimitExceeded
from ..store import CampaignStore
from ..worker import data_budget_left

HASHTAG_LIMIT = 30
HASHTAG_WINDOW = timedelta(days=7)
CAPTION_MAX = 500
PROVIDER = "instagram"


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
