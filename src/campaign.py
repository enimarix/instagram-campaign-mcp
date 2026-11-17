"""
Campaign layer: ties the Graph API client to the local store.

- publish(kind, payload): one entry point for image/carousel/reel/story
- run_due(): publish everything in the queue whose time has come
- collect_insights(): snapshot insights of recent posts (and live Stories)
- rank(): score posts against the account baseline
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

import structlog

from .config import InstagramMCPSettings
from .instagram_client import (
    InstagramAPIError,
    InstagramClient,
    RateLimitExceeded,
)
from .scoring import ScoringConfig, compare_variants, score_posts
from .store import CampaignStore, parse_dt, utcnow

logger = structlog.get_logger(__name__)

STORY_FIELDS = "id,media_type,media_product_type,media_url,permalink,timestamp"
MAX_ATTEMPTS = 3
RETRY_MINUTES = 15
# Meta error subcodes that will never succeed on retry (bad media, bad ratio...).
PERMANENT_SUBCODES = {2207026, 2207004, 2207005, 2207009, 2207010, 2207052, 2207053}


async def publish(client: InstagramClient, kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if kind == "image":
        return await client.publish_image(**payload)
    if kind == "carousel":
        return await client.publish_carousel(**payload)
    if kind == "reel":
        return await client.publish_reel(**payload)
    if kind == "story":
        return await client.publish_story(**payload)
    raise InstagramAPIError(f"Unknown post kind: {kind}")


def validate_payload(kind: str, payload: Dict[str, Any]) -> None:
    """Cheap checks at scheduling time so mistakes surface now, not at 3am."""
    required = {
        "image": ["image_url"],
        "carousel": ["items"],
        "reel": ["video_url"],
        "story": [],
    }[kind]
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise ValueError(f"{kind} post is missing: {', '.join(missing)}")
    if kind == "carousel" and not 2 <= len(payload["items"]) <= 10:
        raise ValueError("A carousel needs 2 to 10 items")
    if kind == "story" and bool(payload.get("image_url")) == bool(payload.get("video_url")):
        raise ValueError("A story needs exactly one of image_url or video_url")
    caption = payload.get("caption") or ""
    if len(caption) > 2200:
        raise ValueError("Caption must be 2200 characters or less")
    if caption.count("#") > 30:
        raise ValueError("Instagram allows at most 30 hashtags per caption")


async def run_due(client: InstagramClient, store: CampaignStore, limit: int = 10) -> Dict[str, Any]:
    stuck = store.recover_stuck()
    published, failed, retrying = [], [], []
    for _ in range(limit):
        # Claim one at a time so nothing is left in 'publishing' if we stop early.
        claimed = store.claim_due(limit=1)
        if not claimed:
            break
        post = claimed[0]
        try:
            result = await publish(client, post["kind"], post["payload"])
            store.mark_published(post["id"], result["media_id"], result.get("permalink"))
            published.append({"id": post["id"], **result})
        except RateLimitExceeded as e:
            store.mark_failed(post["id"], f"Rate limited: {e.message}", retry_in_minutes=60)
            retrying.append({"id": post["id"], "error": e.message})
            break  # stop hammering the API this round
        except InstagramAPIError as e:
            if e.network:
                # The request may have reached Meta; retrying could double-post.
                msg = f"{e.message} - check Instagram before retrying (reschedule_post)"
                store.mark_failed(post["id"], msg, retry_in_minutes=None)
                failed.append({"id": post["id"], "error": msg})
                continue
            permanent = e.error_subcode in PERMANENT_SUBCODES
            if not permanent and post["attempts"] < MAX_ATTEMPTS:
                store.mark_failed(post["id"], e.message, retry_in_minutes=RETRY_MINUTES)
                retrying.append({"id": post["id"], "error": e.message})
            else:
                store.mark_failed(post["id"], e.message, retry_in_minutes=None)
                failed.append({"id": post["id"], "error": e.message})
        except Exception as e:  # noqa: BLE001 - never leave a post stuck in 'publishing'
            store.mark_failed(post["id"], f"Unexpected: {e}", retry_in_minutes=None)
            failed.append({"id": post["id"], "error": str(e)})
    return {
        "published": published,
        "retrying": retrying,
        "failed": failed,
        "recovered_stuck": stuck,
    }


async def collect_insights(
    client: InstagramClient,
    store: CampaignStore,
    limit: int = 25,
    max_age_days: int = 30,
    include_stories: bool = True,
) -> Dict[str, Any]:
    now = utcnow()
    media: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while len(media) < limit:
        page = await client.get_media_posts(limit=min(50, limit - len(media)), after=cursor)
        media.extend(page["posts"])
        cursor = page.get("next_cursor")
        if not cursor or not page["posts"]:
            break

    if include_stories:
        try:
            stories = await client._make_request(
                "GET", f"{client.account_id}/stories", params={"fields": STORY_FIELDS}
            )
            for s in stories.get("data", []):
                s.setdefault("media_product_type", "STORY")
                media.append(s)
        except InstagramAPIError as e:
            logger.info("stories_unavailable", error=e.message)

    captured, skipped, errors = 0, 0, []
    for m in media:
        ts = m.get("timestamp")
        if not ts:
            skipped += 1
            continue
        age = now - parse_dt(ts)
        if age < timedelta(hours=1) or age > timedelta(days=max_age_days):
            skipped += 1
            continue
        try:
            ins = await client.get_media_insights(
                m["id"], media_product_type=m.get("media_product_type") or "FEED"
            )
        except RateLimitExceeded as e:
            errors.append({"media_id": m["id"], "error": e.message})
            break
        except InstagramAPIError as e:
            errors.append({"media_id": m["id"], "error": e.message})
            continue
        store.add_snapshot(
            media_id=m["id"],
            metrics=ins["metrics"],
            media_product_type=m.get("media_product_type"),
            media_type=m.get("media_type"),
            posted_at=ts,
            caption=m.get("caption"),
            permalink=m.get("permalink"),
            captured_at=now,
        )
        captured += 1
    return {"captured": captured, "skipped": skipped, "errors": errors}


def scoring_config(settings: InstagramMCPSettings) -> ScoringConfig:
    return ScoringConfig(
        min_age_hours=settings.winner_min_age_hours,
        min_reach=settings.winner_min_reach,
        winner_threshold=settings.winner_threshold,
        baseline_window=settings.baseline_window,
    )


def rank(
    store: CampaignStore,
    settings: InstagramMCPSettings,
    campaign: Optional[str] = None,
    only: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    labels = store.labels()
    scored = score_posts(store.latest_snapshots(), scoring_config(settings), labels)
    if campaign:
        scored = [s for s in scored if (s.get("label") or {}).get("campaign") == campaign]
    if only:
        scored = [s for s in scored if s["verdict"] == only]
    ranked = sorted(
        scored,
        key=lambda r: (r["engagement_index"] is not None, r["engagement_index"] or 0),
        reverse=True,
    )
    counts: Dict[str, int] = {}
    for s in scored:
        counts[s["verdict"]] = counts.get(s["verdict"], 0) + 1
    return {"summary": counts, "posts": ranked[:limit]}


def variants(store: CampaignStore, settings: InstagramMCPSettings, campaign: str) -> Dict[str, Any]:
    scored = score_posts(store.latest_snapshots(), scoring_config(settings), store.labels())
    return compare_variants(scored, campaign)
