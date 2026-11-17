#!/usr/bin/env python3
"""
Instagram campaign MCP server.

Organic campaign toolkit on the official Instagram Graph API:
publish (image, carousel, Reel, trial Reel, Story), schedule, moderate
comments, research hashtags and competitors, snapshot insights, and score
posts against the account's own baseline to find winners worth promoting.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import campaign as camp
from .config import get_settings
from .instagram_client import InstagramAPIError, InstagramClient, NotConfigured
from .logging_setup import configure_logging
from .store import CampaignStore, parse_dt, parse_iso, to_iso, utcnow
from .studio.publish import cancel_post, refuse_asset_file

configure_logging()

INSTRUCTIONS = """\
Instagram organic campaign toolkit (official Graph API, Business/Creator account).

Typical loop:
1. Research: search_hashtag, get_competitor_profile, rank_posts on past content.
2. Plan & publish: publish_* now, or schedule_post for later. Tag every post with
   campaign + variant + hypothesis so A/B results can be compared.
   Trial Reels (publish_reel trial_graduation) test a Reel on non-followers first.
3. Measure: collect_insights daily. Posts are judged after 48h (Stories after 20h).
4. Decide: rank_posts(only="winner") lists posts beating the account median;
   compare_variants(campaign) says which variant is ahead.

Media must be at a public HTTPS URL; Instagram downloads it. Reels may instead use
video_path (relative to the studio media root), uploaded directly. Scheduled posts are
published by `python -m src.scheduler daemon` (or run_due_posts) - the API itself
cannot schedule. Publishing is irreversible: confirm captions and media with the
user before publishing on their behalf.
"""

mcp = MCPServer(name="instagram-campaign-mcp", instructions=INSTRUCTIONS, version="2.0.0")

_client: Optional[InstagramClient] = None
_store: Optional[CampaignStore] = None

READ = ToolAnnotations(read_only_hint=True, open_world_hint=True)
LOCAL_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
LOCAL_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
PUBLISH = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                          idempotent_hint=False, open_world_hint=True)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)


def client() -> InstagramClient:
    global _client
    if _client is None:
        try:
            _client = InstagramClient(get_settings())
        except NotConfigured as e:  # setup mode: store-only tools still work
            raise ToolError(e.message) from e
        except Exception as e:  # noqa: BLE001 - usually missing env vars
            raise ToolError(f"Configuration error: {e}. Check your .env file.") from e
    return _client


def store() -> CampaignStore:
    global _store
    if _store is None:
        _store = CampaignStore(get_settings().database_path)
    return _store


def _err(e: InstagramAPIError) -> ToolError:
    parts = []
    if e.error_code:
        parts.append(f"code {e.error_code}")
    if e.error_subcode:
        parts.append(f"subcode {e.error_subcode}")
    detail = f" ({', '.join(parts)})" if parts else ""
    return ToolError(f"Instagram API error: {e.message}{detail}")


def _when(value: str, name: str = "publish_at") -> datetime:
    """ISO time; without an offset it is read in the configured time zone."""
    try:
        dt = parse_iso(value)
    except ValueError as e:
        raise ToolError(f"{name} must be ISO 8601, e.g. 2026-11-20T18:30: {e}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(get_settings().timezone))
    return parse_dt(dt.isoformat())


def _not_an_asset(video_path: Optional[str]) -> None:
    """Studio assets publish only through queue_asset (the website), never by path."""
    try:
        refuse_asset_file(store(), get_settings(), video_path)
    except ValueError as e:
        raise ToolError(str(e)) from e


def _label(result: Dict[str, Any], kind: str, campaign: Optional[str],
           variant: Optional[str], hypothesis: Optional[str]) -> Dict[str, Any]:
    if campaign or variant or hypothesis:
        result["label"] = store().label_post(result["media_id"], campaign, variant, hypothesis, kind)
    return result


# ----------------------------------------------------------------------
# Account
# ----------------------------------------------------------------------
@mcp.tool(annotations=READ)
async def validate_access_token() -> Dict[str, Any]:
    """Check that the configured access token works."""
    return {"valid": await client().validate_access_token()}


@mcp.tool(annotations=READ)
async def get_account_pages() -> Dict[str, Any]:
    """List Facebook Pages for this token and their linked Instagram account IDs
    (use the id as INSTAGRAM_BUSINESS_ACCOUNT_ID)."""
    try:
        return {"pages": await client().get_account_pages()}
    except InstagramAPIError as e:
        raise _err(e)


@mcp.tool(annotations=READ)
async def get_profile_info(account_id: Optional[str] = None) -> Dict[str, Any]:
    """Profile of the configured account: username, bio, followers, post count."""
    try:
        return await client().get_profile_info(account_id)
    except InstagramAPIError as e:
        raise _err(e)


@mcp.tool(annotations=READ)
async def get_account_insights(
    metrics: Optional[List[str]] = None,
    period: Literal["day", "week", "days_28"] = "day",
    since: Optional[str] = None,
    until: Optional[str] = None,
    breakdown: Optional[str] = None,
) -> Dict[str, Any]:
    """Account-level insights. Default metrics: reach, views, accounts_engaged,
    total_interactions. Others: likes, comments, saves, shares, replies,
    follows_and_unfollows, profile_links_taps. since/until: ISO dates (max 30 days)."""
    try:
        data = await client().get_account_insights(
            metrics, period,
            int(_when(since, "since").timestamp()) if since else None,
            int(_when(until, "until").timestamp()) if until else None,
            breakdown,
        )
        return {"insights": data}
    except InstagramAPIError as e:
        raise _err(e)


@mcp.tool(annotations=READ)
async def get_publishing_limit() -> Dict[str, Any]:
    """How many API posts were published in the last 24h vs the quota."""
    try:
        return await client().get_publishing_limit()
    except InstagramAPIError as e:
        raise _err(e)


# ----------------------------------------------------------------------
# Media read
# ----------------------------------------------------------------------
@mcp.tool(annotations=READ)
async def get_media_posts(limit: int = 25, after: Optional[str] = None) -> Dict[str, Any]:
    """Recent posts (newest first) with type, caption, permalink, likes, comments.
    Pass next_cursor as `after` for the next page."""
    try:
        return await client().get_media_posts(limit, after)
    except InstagramAPIError as e:
        raise _err(e)


@mcp.tool(annotations=READ)
async def get_media_insights(media_id: str, metrics: Optional[List[str]] = None) -> Dict[str, Any]:
    """Insights for one post. Metrics are picked automatically for feed posts,
    Reels or Stories unless given."""
    try:
        return await client().get_media_insights(media_id, metrics)
    except InstagramAPIError as e:
        raise _err(e)


# ----------------------------------------------------------------------
# Publishing (immediate)
# ----------------------------------------------------------------------
@mcp.tool(annotations=PUBLISH)
async def publish_image(
    image_url: str,
    caption: str = "",
    alt_text: Optional[str] = None,
    collaborators: Optional[List[str]] = None,
    location_id: Optional[str] = None,
    campaign: Optional[str] = None,
    variant: Optional[str] = None,
    hypothesis: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish a single-image feed post now. Image must be a public HTTPS JPEG
    (Instagram's API does not take PNG) with an aspect ratio between 4:5 and
    1.91:1. campaign/variant/hypothesis are stored locally for A/B comparison."""
    try:
        res = await client().publish_image(image_url, caption, alt_text, location_id,
                                           None, collaborators)
    except InstagramAPIError as e:
        raise _err(e)
    return _label(res, "image", campaign, variant, hypothesis)


@mcp.tool(annotations=PUBLISH)
async def publish_carousel(
    items: List[Dict[str, str]],
    caption: str = "",
    collaborators: Optional[List[str]] = None,
    location_id: Optional[str] = None,
    campaign: Optional[str] = None,
    variant: Optional[str] = None,
    hypothesis: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish a carousel now. items: 2-10 of {"image_url": ...} or {"video_url": ...}
    (optional "alt_text" on images). Images must be JPEG. All slides are cropped to
    the first slide's ratio (4:5 to 1.91:1)."""
    try:
        res = await client().publish_carousel(items, caption, location_id, collaborators)
    except InstagramAPIError as e:
        raise _err(e)
    return _label(res, "carousel", campaign, variant, hypothesis)


@mcp.tool(annotations=PUBLISH)
async def publish_reel(
    video_url: Optional[str] = None,
    caption: str = "",
    cover_url: Optional[str] = None,
    thumb_offset_ms: Optional[int] = None,
    share_to_feed: bool = True,
    trial_graduation: Optional[Literal["MANUAL", "SS_PERFORMANCE"]] = None,
    audio_name: Optional[str] = None,
    collaborators: Optional[List[str]] = None,
    campaign: Optional[str] = None,
    variant: Optional[str] = None,
    hypothesis: Optional[str] = None,
    video_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish a Reel now (MP4/MOV H.264+AAC, 9:16 recommended, max 300 MB). Give exactly
    one of video_url (public HTTPS) or video_path (file relative to the media root).
    trial_graduation makes it a trial Reel shown to non-followers first:
    SS_PERFORMANCE = Instagram shares it to followers if it performs,
    MANUAL = you decide in the app. Waits for video processing (can take minutes)."""
    _not_an_asset(video_path)
    try:
        res = await client().publish_reel(
            video_url, caption, cover_url, thumb_offset_ms, share_to_feed,
            audio_name, collaborators, None, trial_graduation, video_path=video_path,
        )
    except InstagramAPIError as e:
        raise _err(e)
    if trial_graduation:
        res["trial"] = trial_graduation
    return _label(res, "reel", campaign, variant, hypothesis)


@mcp.tool(annotations=PUBLISH)
async def publish_story(
    image_url: Optional[str] = None,
    video_url: Optional[str] = None,
    campaign: Optional[str] = None,
    variant: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish a Story now (exactly one of image_url / video_url, 9:16; images JPEG).
    The API cannot add stickers, links or text overlays: bake them into the media."""
    try:
        res = await client().publish_story(image_url, video_url)
    except InstagramAPIError as e:
        raise _err(e)
    return _label(res, "story", campaign, variant, None)


# ----------------------------------------------------------------------
# Scheduling
# ----------------------------------------------------------------------
@mcp.tool(annotations=LOCAL_WRITE)
async def schedule_post(
    kind: Literal["image", "carousel", "reel", "story"],
    publish_at: str,
    caption: str = "",
    image_url: Optional[str] = None,
    video_url: Optional[str] = None,
    items: Optional[List[Dict[str, str]]] = None,
    cover_url: Optional[str] = None,
    alt_text: Optional[str] = None,
    share_to_feed: bool = True,
    trial_graduation: Optional[Literal["MANUAL", "SS_PERFORMANCE"]] = None,
    collaborators: Optional[List[str]] = None,
    campaign: Optional[str] = None,
    variant: Optional[str] = None,
    hypothesis: Optional[str] = None,
    video_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Queue a post for later. A reel takes video_url or video_path (relative to the
    media root). publish_at is ISO 8601; without an offset it is read
    in the configured time zone (default Europe/Paris), e.g. "2026-11-20T18:30".
    Needs the scheduler running (python -m src.scheduler daemon) or run_due_posts."""
    _not_an_asset(video_path)
    payload: Dict[str, Any]
    if kind == "image":
        payload = {"image_url": image_url, "caption": caption, "alt_text": alt_text,
                   "collaborators": collaborators}
    elif kind == "carousel":
        payload = {"items": items or [], "caption": caption, "collaborators": collaborators}
    elif kind == "reel":
        payload = {"video_url": video_url, "video_path": video_path,
                   "caption": caption, "cover_url": cover_url,
                   "share_to_feed": share_to_feed, "trial_graduation": trial_graduation,
                   "collaborators": collaborators}
    else:
        payload = {"image_url": image_url, "video_url": video_url}
    payload = {k: v for k, v in payload.items() if v is not None}
    try:
        camp.validate_payload(kind, payload)
    except ValueError as e:
        raise ToolError(str(e)) from e
    when = _when(publish_at)
    if when < utcnow():
        raise ToolError(f"publish_at {to_iso(when)} is in the past")
    post = store().schedule(kind, payload, when, campaign, variant, hypothesis)
    post["publish_at_local"] = when.astimezone(ZoneInfo(get_settings().timezone)).isoformat()
    return post


@mcp.tool(annotations=LOCAL_READ)
async def list_scheduled_posts(
    status: Optional[Literal["pending", "publishing", "published", "failed", "cancelled"]] = None,
    campaign: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """Show the publishing queue, optionally filtered by status or campaign."""
    return {"posts": store().list_scheduled(status, campaign, limit)}


@mcp.tool(annotations=LOCAL_WRITE)
async def cancel_scheduled_post(post_id: int) -> Dict[str, Any]:
    """Cancel a pending or failed scheduled post (a pending studio asset goes back to
    approved)."""
    try:
        return cancel_post(store(), post_id)
    except (KeyError, ValueError) as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=LOCAL_WRITE)
async def reschedule_post(post_id: int, publish_at: str) -> Dict[str, Any]:
    """Move a pending/failed/cancelled post to a new time (re-arms it)."""
    when = _when(publish_at)
    try:
        return store().reschedule(post_id, when)
    except (KeyError, ValueError) as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=PUBLISH)
async def run_due_posts() -> Dict[str, Any]:
    """Publish every queued post whose time has come. Same as one scheduler pass."""
    try:
        return await camp.run_due(client(), store())
    except InstagramAPIError as e:
        raise _err(e)


# ----------------------------------------------------------------------
# Comments
# ----------------------------------------------------------------------
@mcp.tool(annotations=READ)
async def get_comments(media_id: str, limit: int = 50) -> Dict[str, Any]:
    """Top-level comments on a post (with first-level replies)."""
    try:
        return {"comments": await client().get_comments(media_id, limit)}
    except InstagramAPIError as e:
        raise _err(e)


@mcp.tool(annotations=PUBLISH)
async def reply_to_comment(comment_id: str, message: str) -> Dict[str, Any]:
    """Reply publicly to a top-level comment."""
    try:
        return await client().reply_to_comment(comment_id, message)
    except InstagramAPIError as e:
        raise _err(e)


@mcp.tool(annotations=PUBLISH)
async def comment_on_media(media_id: str, message: str) -> Dict[str, Any]:
    """Add a comment from the account on one of its own posts (e.g. a pinned CTA)."""
    try:
        return await client().comment_on_media(media_id, message)
    except InstagramAPIError as e:
        raise _err(e)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                      idempotent_hint=True, open_world_hint=True))
async def hide_comment(comment_id: str, hide: bool = True) -> Dict[str, Any]:
    """Hide (or unhide) a comment. Reversible, unlike delete."""
    try:
        return await client().hide_comment(comment_id, hide)
    except InstagramAPIError as e:
        raise _err(e)


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_comment(comment_id: str) -> Dict[str, Any]:
    """Permanently delete a comment. Prefer hide_comment unless the user asked."""
    try:
        return await client().delete_comment(comment_id)
    except InstagramAPIError as e:
        raise _err(e)


# ----------------------------------------------------------------------
# Research
# ----------------------------------------------------------------------
@mcp.tool(annotations=READ)
async def search_hashtag(
    hashtag: str, edge: Literal["top_media", "recent_media"] = "top_media", limit: int = 25
) -> Dict[str, Any]:
    """Top or recent public posts for a hashtag. Meta caps lookups at 30 unique
    hashtags per 7 days, so pick them deliberately."""
    try:
        return await client().search_hashtag(hashtag, edge, limit)
    except InstagramAPIError as e:
        raise _err(e)


@mcp.tool(annotations=READ)
async def get_competitor_profile(username: str, media_limit: int = 12) -> Dict[str, Any]:
    """Public stats and recent posts (likes, comments, captions) of another
    Business/Creator account, for benchmarking."""
    try:
        return await client().get_competitor_profile(username, media_limit)
    except InstagramAPIError as e:
        raise _err(e)


# ----------------------------------------------------------------------
# Measurement & winners
# ----------------------------------------------------------------------
@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                      open_world_hint=True))
async def collect_insights(
    limit: int = 25, max_age_days: int = 30, stories_only: bool = False
) -> Dict[str, Any]:
    """Snapshot insights of recent posts (and live Stories) into the local store.
    Run daily; scoring uses the latest snapshot of each post. Stories are only
    judged on a snapshot taken 20-24h after posting: the scheduler daemon takes
    those hourly, or call this with stories_only=True."""
    try:
        return await camp.collect_insights(
            client(), store(), 0 if stories_only else limit, max_age_days)
    except InstagramAPIError as e:
        raise _err(e)


@mcp.tool(annotations=LOCAL_READ)
async def rank_posts(
    campaign: Optional[str] = None,
    only: Optional[Literal["winner", "promising", "average", "weak", "too_early",
                           "inconclusive", "incomplete", "no_baseline",
                           "no_signal"]] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Score posts vs the account's own median (same type: feed/Reels/Stories),
    with baseline posts read at a similar age. engagement_index 1.0 = typical.
    A winner has enough reach (default 300) and either engagement >= the
    threshold (default 1.5x) or reach >= 2x the median with engagement >= 1.0x.
    Winners are the candidates to promote as ads. summary counts every post in
    scope, before the `only` filter."""
    return camp.rank(store(), get_settings(), campaign, only, limit)


@mcp.tool(annotations=LOCAL_READ)
async def compare_variants(campaign: str) -> Dict[str, Any]:
    """Compare A/B variants inside a campaign (by the variant labels given at
    publish/schedule time). Says when the gap is too small or the sample too thin."""
    return camp.variants(store(), get_settings(), campaign)


@mcp.tool(annotations=LOCAL_WRITE)
async def label_post(
    media_id: str,
    campaign: Optional[str] = None,
    variant: Optional[str] = None,
    hypothesis: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach campaign/variant/hypothesis to an existing post (e.g. one published
    from the app) so it counts in compare_variants."""
    return store().label_post(media_id, campaign, variant, hypothesis)


# ----------------------------------------------------------------------
# DMs (requires instagram_manage_messages)
# ----------------------------------------------------------------------
@mcp.tool(annotations=READ)
async def get_conversations(page_id: Optional[str] = None, limit: int = 25) -> Dict[str, Any]:
    """Instagram DM conversations (needs instagram_manage_messages). page_id defaults
    to the Facebook Page linked to the configured Instagram account."""
    try:
        return {"conversations": await client().get_conversations(page_id, limit)}
    except InstagramAPIError as e:
        raise _err(e)


@mcp.tool(annotations=READ)
async def get_conversation_messages(
    conversation_id: str, limit: int = 25, page_id: Optional[str] = None
) -> Dict[str, Any]:
    """Messages in one DM conversation."""
    try:
        return {"messages": await client().get_conversation_messages(
            conversation_id, limit, page_id)}
    except InstagramAPIError as e:
        raise _err(e)


@mcp.tool(annotations=PUBLISH)
async def send_dm(recipient_id: str, message: str, page_id: Optional[str] = None) -> Dict[str, Any]:
    """Reply to a DM (only within 24h of the user's last message; user must write first).
    recipient_id is the Instagram-scoped ID from get_conversation_messages."""
    try:
        return await client().send_dm(recipient_id, message, page_id)
    except InstagramAPIError as e:
        raise _err(e)


# ----------------------------------------------------------------------
# Tool profiles
# ----------------------------------------------------------------------
# The ONLY tools the unattended agent sees (IG_MCP_PROFILE=agent), GOAL.md §4 second
# rule and §5.2: nothing that publishes, schedules, messages, moderates, relabels or
# reads private DMs. This is an allow-list, never a deny-list: every new tool is out of
# `agent` until it is deliberately added here (tests/test_mcp_profiles.py pins the set).
# collect_insights stays out until the shared request budget (step 026) exists.
AGENT_TOOLS = frozenset({
    "validate_access_token",
    "get_profile_info",
    "get_account_insights",
    "get_publishing_limit",
    "get_media_posts",
    "get_media_insights",
    "get_comments",
    "search_hashtag",
    "get_competitor_profile",
    "list_scheduled_posts",
    "rank_posts",
    "compare_variants",
})


def build_server(profile: Literal["full", "agent"]) -> MCPServer:
    """A server exposing the tools of `profile`. Tools left out are not registered at
    all, so they are neither listed nor callable by name."""
    if profile not in ("full", "agent"):
        raise ValueError(f"Unknown MCP profile {profile!r} (use 'full' or 'agent')")
    # ponytail: reads the SDK's private registry; tests/test_mcp_profiles.py breaks loudly
    # if an mcp upgrade renames it.
    tools = [t for t in mcp._tool_manager.list_tools()
             if profile == "full" or t.name in AGENT_TOOLS]
    return MCPServer(name=mcp.name, instructions=INSTRUCTIONS, version="2.0.0", tools=tools)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    transport = settings.mcp_transport if settings.mcp_transport in (
        "stdio", "streamable-http") else "stdio"
    build_server(settings.ig_mcp_profile).run(transport=transport)


if __name__ == "__main__":
    main()
