"""
Campaign layer: ties the Graph API client to the local store.

- publish(kind, payload): one entry point for image/carousel/reel/story
- run_due(): publish what is due, after the late-slot and gap rules (hold_queue) and
  unless the pause switch is on (is_paused)
- collect_insights(): snapshot insights of recent posts (and live Stories)
- collect_due_insights(): the worker's age schedule (SNAPSHOT_POINTS); marks deleted posts
- snapshot_account(): the daily account row (followers, reach by follow type, views)
- collect_online_followers(): store today's followers-online-per-hour (slot weights)
- rank(): score posts against the account baseline
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import structlog

from .config import InstagramMCPSettings, get_settings
from .instagram_client import (
    MISSING_OBJECT,
    PUBLISH_QUOTA_SUBCODE,
    InstagramAPIError,
    InstagramClient,
    InvalidMedia,
    RateLimitExceeded,
    caption_problem,
)
from .learning.slots import plan_slots_from_settings
from .scoring import ScoringConfig, _is_matured, compare_variants, score_posts
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
SLOT_RESULT_DAYS = 90  # like the batch mix (mix.INDEX_DAYS)
# A post is snapshotted once as it crosses each of these ages (GOAL.md §3.4).
SNAPSHOT_POINTS = tuple(timedelta(hours=h) for h in (1, 3, 6, 12, 24, 48, 24 * 7, 24 * 30))
SNAPSHOT_GRACE = timedelta(days=1)  # a worker that was off may still take the 30 d point


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


def slot_inputs(store: CampaignStore, settings: InstagramMCPSettings,
                now: datetime) -> Tuple[Dict[int, float], List[Tuple[time, float]]]:
    """What the slot planner learns from (step 087): (followers online per UTC hour,
    [(owner-local time of day posted, engagement index)] of the matured Reels published in
    the last SLOT_RESULT_DAYS). Every planner caller goes through here."""
    from .learning.analytics import scored_posts  # analytics imports this module

    tz, cfg = ZoneInfo(settings.timezone), scoring_config(settings)
    since = now - timedelta(days=SLOT_RESULT_DAYS)
    results = []
    # ponytail: scores every post on each call (like the breakdowns); cache if slow.
    for snap, s in scored_posts(store, settings):
        if (s["group"] == "REELS" and s["engagement_index"] is not None and snap["posted_at"]
                and _is_matured(snap, cfg)):
            at = parse_dt(snap["posted_at"])
            if at >= since:
                results.append((at.astimezone(tz).time(), s["engagement_index"]))
    return store.online_followers_profile(), results


def free_slot(store: CampaignStore, settings: InstagramMCPSettings,
              taken: List[datetime], now: datetime, inputs=None) -> Optional[datetime]:
    """The planner's next slot within REPLAN_LOOKAHEAD_DAYS, None when every day is full.
    `inputs`: slot_inputs() when the caller already has them."""
    day = now.astimezone(ZoneInfo(settings.timezone)).date()
    profile, results = inputs or slot_inputs(store, settings, now)
    for d in range(REPLAN_LOOKAHEAD_DAYS):
        slots = plan_slots_from_settings(settings, day + timedelta(days=d), 1, taken, now=now,
                                         hourly_profile=profile, results=results)
        if slots:
            return slots[0]
    return None


def _next_free_slot(store: CampaignStore, settings: InstagramMCPSettings,
                    taken: List[datetime], now: datetime, inputs=None) -> datetime:
    # ponytail: a week full of posts is not a real case; then just go after the last one.
    return free_slot(store, settings, taken, now, inputs) or (
        max(taken + [now]) + timedelta(minutes=settings.min_slot_gap_minutes))


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
        _save_snapshot(store, m, ins, now)
        captured += 1
    return {"captured": captured, "skipped": skipped, "errors": errors}


def _save_snapshot(store: CampaignStore, m: Dict[str, Any], ins: Dict[str, Any],
                   now: datetime) -> None:
    store.add_snapshot(
        media_id=m["id"],
        metrics=ins["metrics"],
        media_product_type=m.get("media_product_type"),
        media_type=m.get("media_type"),
        posted_at=m["timestamp"],
        caption=m.get("caption"),
        permalink=m.get("permalink"),
        captured_at=now,
    )


def due_snapshot_points(posted_at: datetime, existing_snapshot_times: List[datetime],
                        now: datetime) -> List[timedelta]:
    """The SNAPSHOT_POINTS the post has crossed with no snapshot taken at or after them.
    A snapshot covers every point up to its age, so one snapshot settles a backlog and each
    point is taken at most once. Nothing once the post is past the last point + grace."""
    age = now - posted_at
    if age > SNAPSHOT_POINTS[-1] + SNAPSHOT_GRACE:
        return []
    taken = max((t - posted_at for t in existing_snapshot_times), default=None)
    return [p for p in SNAPSHOT_POINTS if p <= age and (taken is None or taken < p)]


async def collect_due_insights(
    client: InstagramClient,
    store: CampaignStore,
    now: datetime,
    spare: Callable[[], bool] = lambda: True,
) -> Dict[str, Any]:
    """Snapshot the posts that crossed an age point (due_snapshot_points). Candidates: the
    account's media of the last SNAPSHOT_POINTS[-1] + grace, plus posts the store knows. A
    known post Instagram reports missing gets `deleted_at` and keeps its snapshots (GOAL.md
    §3.4). Stops when `spare()` turns False (the worker's share of the request budget)."""
    since = now - SNAPSHOT_POINTS[-1] - SNAPSHOT_GRACE
    known = store.snapshot_times(since)
    media: Dict[str, Dict[str, Any]] = {}
    cursor: Optional[str] = None
    while True:
        page = await client.get_media_posts(limit=50, after=cursor)
        recent = [m for m in page["posts"]
                  if m.get("timestamp") and parse_dt(m["timestamp"]) >= since]
        media.update((m["id"], m) for m in recent)
        cursor = page.get("next_cursor")
        if not cursor or not recent:
            break
    for mid, k in known.items():
        media.setdefault(mid, {"id": mid, "timestamp": k["posted_at"],
                               "media_product_type": k["media_product_type"],
                               "media_type": k["media_type"]})

    captured, deleted, errors = 0, [], []
    for m in media.values():
        times = [parse_dt(t) for t in known.get(m["id"], {}).get("times", [])]
        if not due_snapshot_points(parse_dt(m["timestamp"]), times, now):
            continue
        if not spare():
            errors.append({"media_id": m["id"], "error": "request budget spent"})
            break
        try:
            ins = await client.get_media_insights(m["id"],
                                                  media_product_type=m.get("media_product_type"))
        except RateLimitExceeded as e:
            errors.append({"media_id": m["id"], "error": e.message})
            break
        except InstagramAPIError as e:
            if (e.error_code, e.error_subcode) == MISSING_OBJECT and m["id"] in known:
                store.mark_deleted(m["id"], now)
                deleted.append(m["id"])
            else:
                errors.append({"media_id": m["id"], "error": e.message})
            continue
        _save_snapshot(store, m, ins, now)
        captured += 1
    return {"captured": captured, "deleted": deleted, "errors": errors}


async def snapshot_account(client: InstagramClient, store: CampaignStore,
                           day: date) -> Dict[str, Any]:
    """Save the account row of owner-local `day`: followers now, reach and views over the
    24 h before (Meta's default range), and reach by follow_type when Meta answers it."""
    profile = await client.get_profile_info()
    insights = await client.get_account_insights(["reach", "views"])
    totals = {i.get("name"): (i.get("total_value") or {}).get("value") for i in insights}
    raw: Dict[str, Any] = {"followers_count": profile.get("followers_count"),
                           "insights": insights}
    split: Dict[str, Any] = {}
    try:
        raw["reach_by_follow_type"] = await client.get_account_insights(
            ["reach"], breakdown="follow_type")
        split = {r["dimension_values"][0]: r.get("value")
                 for i in raw["reach_by_follow_type"]
                 for b in (i.get("total_value") or {}).get("breakdowns", [])
                 for r in b.get("results", []) if r.get("dimension_values")}
    except RateLimitExceeded:
        raise
    except InstagramAPIError as e:
        logger.info("reach_follow_type_unavailable", error=e.message)
    values = {"followers": profile.get("followers_count"), "reach": totals.get("reach"),
              "views": totals.get("views"), "reach_followers": split.get("FOLLOWER"),
              "reach_non_followers": split.get("NON_FOLLOWER")}
    store.save_account_snapshot(day, raw, **values)
    return values


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
        near_age=store.snapshots_near_age,
    )


def variants(store: CampaignStore, settings: InstagramMCPSettings, campaign: str) -> Dict[str, Any]:
    return compare_variants(_score_all(store, settings), campaign)


def campaigns(store: CampaignStore) -> List[str]:
    """The distinct campaign names in post_labels, sorted (the A/B page's picker)."""
    return sorted({lb["campaign"] for lb in store.labels().values() if lb["campaign"]})


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
