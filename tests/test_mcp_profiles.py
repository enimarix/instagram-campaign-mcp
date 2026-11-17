"""MCP tool profiles: `agent` sees exactly the allow-list, `full` sees everything."""

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

import src.instagram_mcp_server as srv
from src.config import InstagramMCPSettings

# Written out again on purpose: changing the allow-list must touch this test too.
AGENT_ALLOWED = {
    "validate_access_token", "get_profile_info", "get_account_insights",
    "get_publishing_limit", "get_media_posts", "get_media_insights", "get_comments",
    "search_hashtag", "get_competitor_profile", "list_scheduled_posts", "rank_posts",
    "compare_variants", "list_motion_templates", "preview_motion", "render_motion",
    "create_idea", "get_render_status", "get_asset_frames", "wait_for_renders",
    "submit_asset", "list_assets",
    "get_feedback", "mark_feedback_digested", "list_revision_requests", "add_learning",
    "update_learning", "list_learnings", "get_creative_brief",
    "add_to_watchlist", "list_watchlist", "remove_from_watchlist", "research_trends",
    "get_trend_report",
}
NEVER_FOR_AGENT = {
    "publish_image", "publish_carousel", "publish_reel", "publish_story",
    "schedule_post", "reschedule_post", "cancel_scheduled_post", "run_due_posts",
    "reply_to_comment", "comment_on_media", "hide_comment", "delete_comment",
    "send_dm", "get_conversations", "get_conversation_messages", "label_post",
    "get_account_pages", "collect_insights",
}


async def _names(profile):
    return {t.name for t in await srv.build_server(profile).list_tools()}


async def test_agent_sees_exactly_the_allow_list():
    assert srv.AGENT_TOOLS == AGENT_ALLOWED
    assert await _names("agent") == AGENT_ALLOWED


async def test_agent_never_sees_writes_dms_or_relabels():
    assert not (await _names("agent")) & NEVER_FOR_AGENT


async def test_full_sees_every_tool():
    full = await _names("full")
    assert full == {t.name for t in await srv.mcp.list_tools()}
    # Every tool is placed in exactly one list: a new tool fails here until it is.
    assert full == AGENT_ALLOWED | NEVER_FOR_AGENT


async def test_agent_cannot_call_hidden_tool_by_name():
    with pytest.raises(ToolError, match="Unknown tool"):
        await srv.build_server("agent").call_tool(
            "publish_image", {"image_url": "https://example.com/a.jpg", "caption": "x"})


def test_build_server_rejects_unknown_profile():
    with pytest.raises(ValueError):
        srv.build_server("admin")


def test_profile_setting(monkeypatch):
    monkeypatch.delenv("IG_MCP_PROFILE", raising=False)
    assert InstagramMCPSettings(_env_file=None).ig_mcp_profile == "full"
    monkeypatch.setenv("IG_MCP_PROFILE", "agent")
    assert InstagramMCPSettings(_env_file=None).ig_mcp_profile == "agent"
    monkeypatch.setenv("IG_MCP_PROFILE", "Agnet")
    with pytest.raises(ValidationError):
        InstagramMCPSettings(_env_file=None)
