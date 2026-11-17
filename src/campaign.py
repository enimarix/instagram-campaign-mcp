"""
Campaign layer: ties the Graph API client to the local store.

- publish(kind, payload): one entry point for image/carousel/reel/story
- run_due(): publish everything in the queue whose time has come
- collect_insights(): snapshot insights of recent posts (and live Stories)
- collect_online_followers(): store today's followers-online-per-hour (slot weights)
- rank(): score posts against the account baseline
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import structlog

from .config import InstagramMCPSettings
from .instagram_client import (
    PUBLISH_QUOTA_SUBCODE,
    InstagramAPIError,
    InstagramClient,
    InvalidMedia,
    RateLimitExceeded,
    caption_problem,
)
from .scoring import ScoringConfig, compare_variants, score_posts
from .store import CampaignStore, parse_dt, utcnow

logger = structlog.get_logger(__name__)

STORY_FIELDS = "id,media_type,media_product_type,media_url,permalink,timestamp"
MAX_ATTEMPTS = 3
RETRY_MINUTES = 15
BACKOFF_MINUTES = 60      # rate limit or daily publishing quota reached
HEARTBEAT_SECONDS = 60    # keeps a long publish from looking "stuck"
# Meta error subcodes that will never succeed on retry (bad media, bad ratio...).
PERMANENT_SUBCODES = {2207026, 2207004, 2207005, 2207009, 2207010, 2207052, 2207053}


async def _with_heartbeat(store: CampaignStore, post_id: int, coro: Any) -> Any:
    """Run a publish while refreshing the post's claim, so another process's
    recover_stuck() doesn't fail a publish that is merely slow (long videos,
    carousels of videos)."""
    task = asyncio.ensure_future(coro)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
            if done:
                return task.result()
            store.touch(post_id)
    finally:
        if not task.done():
            task.cancel()


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
    }.get(kind)
    if required is None:
        raise ValueError(f"Unknown post kind: {kind}")
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise ValueError(f"{kind} post is missing: {', '.join(missing)}")
    if kind == "carousel" and not 2 <= len(payload["items"]) <= 10:
        raise ValueError("A carousel needs 2 to 10 items")
    if kind == "story" and bool(payload.get("image_url")) == bool(payload.get("video_url")):
        raise ValueError("A story needs exactly one of image_url or video_url")
    if kind == "reel" and payload.get("trial_graduation") not in (None, "MANUAL", "SS_PERFORMANCE"):
        raise ValueError("trial_graduation must be MANUAL or SS_PERFORMANCE")
    problem = caption_problem(payload.get("caption"))
    if problem:
        raise ValueError(problem)


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
            result = await _with_heartbeat(
                store, post["id"], publish(client, post["kind"], post["payload"])
            )
            store.mark_published(post["id"], result["media_id"], result.get("permalink"))
            published.append({"id": post["id"], **result})
        except RateLimitExceeded as e:
            store.mark_failed(post["id"], f"Rate limited: {e.message}",
                              retry_in_minutes=BACKOFF_MINUTES, count_attempt=False)
            retrying.append({"id": post["id"], "error": e.message})
            break  # stop hammering the API this round
        except InstagramAPIError as e:
            if e.error_subcode == PUBLISH_QUOTA_SUBCODE and not e.maybe_published:
                # ~100 API posts per rolling 24h: wait, don't burn attempts.
                msg = f"Daily publishing quota reached: {e.message}"
                store.mark_failed(post["id"], msg, retry_in_minutes=BACKOFF_MINUTES,
                                  count_attempt=False)
                retrying.append({"id": post["id"], "error": msg})
                break
            if e.maybe_published:
                # media_publish may have reached Meta; retrying could double-post.
                msg = f"{e.message} - check Instagram before retrying (reschedule_post)"
                store.mark_failed(post["id"], msg, retry_in_minutes=None)
                failed.append({"id": post["id"], "error": msg})
                continue
            permanent = isinstance(e, InvalidMedia) or e.error_subcode in PERMANENT_SUBCODES
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


async def collect_online_followers(
    client: InstagramClient, store: CampaignStore, today: date
) -> Dict[str, Any]:
    """Save followers online per UTC hour under `today` (once a day; re-runs overwrite)."""
    hours = await client.get_online_followers()
    if not hours:
        return {"available": False, "saved": 0}
    return {"available": True, "saved": store.save_online_followers(today, hours)}


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
    scored = _score_all(store, settings)
    if campaign:
        scored = [s for s in scored if (s.get("label") or {}).get("campaign") == campaign]
    # Summary covers every post in scope, before the `only` filter.
    counts: Dict[str, int] = {}
    for s in scored:
        counts[s["verdict"]] = counts.get(s["verdict"], 0) + 1
    if only:
        scored = [s for s in scored if s["verdict"] == only]
    ranked = sorted(
        scored,
        key=lambda r: (r["engagement_index"] is not None, r["engagement_index"] or 0),
        reverse=True,
    )
    return {"summary": counts, "posts": ranked[:limit]}


def _score_all(store: CampaignStore, settings: InstagramMCPSettings) -> List[Dict[str, Any]]:
    return score_posts(
        store.latest_snapshots(),
        scoring_config(settings),
        store.labels(),
        history=store.snapshot_history(),
    )


def variants(store: CampaignStore, settings: InstagramMCPSettings, campaign: str) -> Dict[str, Any]:
    return compare_variants(_score_all(store, settings), campaign)


async def account_status(client: InstagramClient) -> Dict[str, Any]:
    """Profile, token validity and publishing quota, for the studio's account page.
    An invalid token is reported, not raised; other Graph errors propagate."""
    if not await client.validate_access_token():
        return {"token_valid": False, "profile": None, "publishing_limit": None}
    return {
        "token_valid": True,
        "profile": await client.get_profile_info(),
        "publishing_limit": await client.get_publishing_limit(),
    }
