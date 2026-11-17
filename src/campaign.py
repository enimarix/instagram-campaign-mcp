"""
Campaign layer: ties the Graph API client to the local store.

- publish(kind, payload): one entry point for image/carousel/reel/story
- run_due(): publish what is due, after the late-slot and gap rules (hold_queue) and
  unless the pause switch is on (is_paused)
- collect_insights(): snapshot insights of recent posts (and live Stories)
- collect_online_followers(): store today's followers-online-per-hour (slot weights)
- rank(): score posts against the account baseline
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

import structlog

from .config import InstagramMCPSettings, get_settings
from .instagram_client import (
    PUBLISH_QUOTA_SUBCODE,
    InstagramAPIError,
    InstagramClient,
    InvalidMedia,
    RateLimitExceeded,
    caption_problem,
)
from .learning.slots import plan_slots_from_settings
from .scoring import ScoringConfig, compare_variants, score_posts
from .store import CampaignStore, parse_dt, to_iso, utcnow
from .studio.assets import InvalidTransition, transition

logger = structlog.get_logger(__name__)

STORY_FIELDS = "id,media_type,media_product_type,media_url,permalink,timestamp"
MAX_ATTEMPTS = 3
RETRY_MINUTES = 15
BACKOFF_MINUTES = 60      # rate limit or daily publishing quota reached
HEARTBEAT_SECONDS = 60    # keeps a long publish from looking "stuck"
# Meta error subcodes that will never succeed on retry (bad media, bad ratio...).
PERMANENT_SUBCODES = {2207026, 2207004, 2207005, 2207009, 2207010, 2207052, 2207053}
REPLAN_LOOKAHEAD_DAYS = 7


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
        "reel": [],
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
    if kind == "reel" and bool(payload.get("video_url")) == bool(payload.get("video_path")):
        raise ValueError("A reel needs exactly one of video_url or video_path")
    if kind == "reel" and payload.get("trial_graduation") not in (None, "MANUAL", "SS_PERFORMANCE"):
        raise ValueError("trial_graduation must be MANUAL or SS_PERFORMANCE")
    problem = caption_problem(payload.get("caption"))
    if problem:
        raise ValueError(problem)


def _asset_outcome(store: CampaignStore, asset_id: Optional[int], to_status: str) -> None:
    """Keep a queued studio asset's status truthful after its publish (GOAL.md §4.3).
    Never raises: the post's own outcome is already recorded."""
    if asset_id is None:
        return
    try:
        transition(store, asset_id, to_status, actor="worker")
    except InvalidTransition as e:
        logger.warning("asset_outcome_not_applied", asset_id=asset_id, error=str(e))


def is_paused(store: CampaignStore, settings: InstagramMCPSettings) -> bool:
    """The pause switch: the website's flag in the database wins over PUBLISHING_PAUSED."""
    flag = store.get_state("paused")
    return settings.publishing_paused if flag is None else bool(flag)


def _next_free_slot(store: CampaignStore, settings: InstagramMCPSettings,
                    taken: List[datetime], now: datetime) -> datetime:
    day = now.astimezone(ZoneInfo(settings.timezone)).date()
    profile = store.online_followers_profile()
    for d in range(REPLAN_LOOKAHEAD_DAYS):
        slots = plan_slots_from_settings(settings, day + timedelta(days=d), 1, taken, now=now,
                                         hourly_profile=profile)
        if slots:
            return slots[0]
    # ponytail: a week full of posts is not a real case; then just go after the last one.
    return max(taken + [now]) + timedelta(minutes=settings.min_slot_gap_minutes)


def hold_queue(store: CampaignStore, settings: InstagramMCPSettings,
               now: datetime) -> List[Dict[str, Any]]:
    """Late slots are re-planned, not fired (GOAL.md §3.3). Before anything is claimed, a
    due post more than max_late_minutes late, or within min_slot_gap_minutes of a publish
    (done, in flight or this run's), moves to the next free slot. So at most one due post
    goes out per run. Returns the moves."""
    gap = timedelta(minutes=settings.min_slot_gap_minutes)
    max_late = timedelta(minutes=settings.max_late_minutes)
    rows = store.queue_times(since=now - timedelta(days=1))
    sent = [parse_dt(r["updated_at"]) for r in rows if r["status"] != "pending"]
    pending = sorted((parse_dt(r["publish_at"]), r["id"]) for r in rows
                     if r["status"] == "pending")
    planned = [at for at, _ in pending if at > now]
    moved = []
    for at, post_id in pending:
        if at > now:
            break
        late = now - at > max_late
        if not late and all(abs(now - t) >= gap for t in sent):
            sent.append(now)  # this one goes out now
            continue
        new = _next_free_slot(store, settings, sent + planned, now)
        reason = (f"{int((now - at).total_seconds() // 60)} min late" if late
                  else f"less than {settings.min_slot_gap_minutes} min after another post")
        if store.move_pending(post_id, new, f"Re-planned: {reason}"):
            planned.append(new)
            moved.append({"id": post_id, "from": to_iso(at), "to": to_iso(new),
                          "reason": reason})
            logger.info("post_replanned", post_id=post_id, to=to_iso(new), reason=reason)
    return moved


async def run_due(
    client: InstagramClient,
    store: CampaignStore,
    limit: int = 10,
    *,
    settings: Optional[InstagramMCPSettings] = None,
    now: Callable[[], datetime] = utcnow,
) -> Dict[str, Any]:
    settings = settings or get_settings()
    stuck = store.recover_stuck()
    for asset_id in store.unsettled_assets():  # interrupted publishes: outcome unknown
        _asset_outcome(store, asset_id, "publish_check")
    published, failed, retrying, replanned = [], [], [], []
    paused = is_paused(store, settings)
    t = now()
    if not paused:
        replanned = hold_queue(store, settings, t)
    for _ in range(0 if paused else limit):
        # Claim one at a time so nothing is left in 'publishing' if we stop early.
        claimed = store.claim_due(now=t, limit=1)
        if not claimed:
            break
        post = claimed[0]
        if post["asset_id"] is not None:
            # Unapproved, cancelled or awaiting a check since it was queued: never publish.
            status = store.get_asset(post["asset_id"])["status"]
            if status != "scheduled":
                msg = f"Cancelled: asset {post['asset_id']} is {status}, not scheduled"
                store.cancel_claimed(post["id"], msg)
                failed.append({"id": post["id"], "error": msg})
                continue
        try:
            result = await _with_heartbeat(
                store, post["id"], publish(client, post["kind"], post["payload"])
            )
            store.mark_published(post["id"], result["media_id"], result.get("permalink"))
            published.append({"id": post["id"], **result})
            _asset_outcome(store, post["asset_id"], "published")
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
                _asset_outcome(store, post["asset_id"], "publish_check")
                continue
            permanent = isinstance(e, InvalidMedia) or e.error_subcode in PERMANENT_SUBCODES
            if not permanent and post["attempts"] < MAX_ATTEMPTS:
                store.mark_failed(post["id"], e.message, retry_in_minutes=RETRY_MINUTES)
                retrying.append({"id": post["id"], "error": e.message})
            else:
                store.mark_failed(post["id"], e.message, retry_in_minutes=None)
                failed.append({"id": post["id"], "error": e.message})
                _asset_outcome(store, post["asset_id"], "approved")  # failed for good, not on Instagram
        except Exception as e:  # noqa: BLE001 - never leave a post stuck in 'publishing'
            store.mark_failed(post["id"], f"Unexpected: {e}", retry_in_minutes=None)
            failed.append({"id": post["id"], "error": str(e)})
            _asset_outcome(store, post["asset_id"], "publish_check")  # may have reached Instagram
    return {
        "published": published,
        "retrying": retrying,
        "failed": failed,
        "recovered_stuck": stuck,
        "replanned": replanned,
        "paused": paused,
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
