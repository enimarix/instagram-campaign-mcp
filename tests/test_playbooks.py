"""Guard for agent/ (step 059): playbooks only name tools the agent profile has, each has a
dry-run section, every skill has a SKILL.md with name + description, and the real folder
builds a workspace."""

import re

import pytest

import src.instagram_mcp_server as srv
from src.agent import runner
from src.config import InstagramMCPSettings

PLAYBOOKS = sorted((runner.AGENT_DIR / "playbooks").glob("*.md"))
PLAYBOOKS = [p for p in PLAYBOOKS if p.name != "README.md"]
SKILLS = sorted(p for p in (runner.AGENT_DIR / "skills").iterdir() if p.is_dir())
TEXTS = PLAYBOOKS + [s / "SKILL.md" for s in SKILLS]


async def _all_tools():
    return {t.name for t in await srv.mcp.list_tools()}


def test_there_is_a_daily_produce_playbook_and_a_hook_guide():
    assert "daily-produce" in [p.stem for p in PLAYBOOKS]
    assert "hook-guide" in [s.name for s in SKILLS]


@pytest.mark.parametrize("path", TEXTS, ids=lambda p: p.parent.name + "/" + p.name)
async def test_only_agent_tools_are_named(path):
    text = path.read_text(encoding="utf-8")
    hidden = await _all_tools() - srv.AGENT_TOOLS
    words = set(re.findall(r"\w+", text))
    assert not words & hidden, f"names tools the agent cannot call: {words & hidden}"
    prefixed = set(re.findall(r"mcp__studio__(\w+)", text))
    assert prefixed <= srv.AGENT_TOOLS, prefixed - srv.AGENT_TOOLS


def test_daily_produce_drives_the_whole_batch():
    text = (runner.AGENT_DIR / "playbooks" / "daily-produce.md").read_text(encoding="utf-8")
    named = set(re.findall(r"`(\w+)", text))
    assert {"get_creative_brief", "get_feedback", "add_learning", "mark_feedback_digested",
            "list_revision_requests", "create_idea", "preview_motion", "render_motion",
            "wait_for_renders", "get_asset_frames", "submit_asset"} <= named


@pytest.mark.parametrize("path", PLAYBOOKS, ids=lambda p: p.name)
def test_every_playbook_has_a_dry_run_section(path):
    text = path.read_text(encoding="utf-8")
    assert re.search(r"^#+ .*dry run", text, re.I | re.M), "no '## Dry run' section"


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_every_skill_has_name_and_description_frontmatter(skill):
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md must start with --- frontmatter ---"
    fields = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
    assert fields.get("name", "").strip() == skill.name
    assert fields.get("description", "").strip()


def test_prepare_workspace_with_the_real_agent_folder(tmp_path):
    cfg = InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                               database_path=":memory:", agent_workspace=str(tmp_path / "ws"))
    config = runner.prepare_workspace(cfg, "daily-produce")
    ws = tmp_path / "ws"
    assert config == ws / ".claude" / "mcp.json"
    assert (ws / "playbooks" / "daily-produce.md").read_bytes() == \
        (runner.AGENT_DIR / "playbooks" / "daily-produce.md").read_bytes()
    for skill in SKILLS:
        assert (ws / ".claude" / "skills" / skill.name / "SKILL.md").is_file()


@pytest.mark.parametrize("name", ["daily-produce", "daily-revise", "daily-learn",
                                  "weekly-ads"])
def test_scheduled_playbooks_read_their_work_packet_first(name):
    from src.agent import packet

    assert name in packet.RUNS
    text = (runner.AGENT_DIR / "playbooks" / f"{name}.md").read_text(encoding="utf-8")
    head = text.split("## Your tools")[0]
    assert "## Your work packet" in head and "work/manifest.json" in head


def test_daily_learn_analyses_and_writes_the_report():
    text = (runner.AGENT_DIR / "playbooks" / "daily-learn.md").read_text(encoding="utf-8")
    named = set(re.findall(r"`(\w+)", text))
    assert {"get_asset_frames", "list_learnings", "add_learning", "update_learning",
            "save_daily_report"} <= named
    assert "## Safety" in text and "data, never instructions" in text
    assert "no shell" in text and "contradicted" in text  # never deletes a learning


def test_default_schedule_runs_the_analysis_before_the_batch():
    from src.agent.schedule import parse_schedule

    cfg = InstagramMCPSettings(_env_file=None, instagram_access_token=None)
    runs = parse_schedule(cfg.agent_schedule)
    assert [p for p, _, _ in runs] == ["daily-learn", "daily-produce"]
    assert runs[0][1] < runs[1][1] and "weekly-ads" not in cfg.agent_schedule  # 096: owner adds it
    for name, _, _ in runs:
        assert (runner.AGENT_DIR / "playbooks" / f"{name}.md").is_file()


def _book(name):
    return (runner.AGENT_DIR / "playbooks" / f"{name}.md").read_text(encoding="utf-8")


def _section(text, title):
    return " ".join(text.split(f"## {title}", 1)[1].split("\n## ", 1)[0].split())


def test_daily_produce_makes_both_tracks_dm_picks_first():  # step 073 + 113b
    text = _book("daily-produce")
    heads = re.findall(r"^## (.+)$", text, re.M)
    a, viral, b = ("Phase 4: Track A, DM picks first", "Phase 5: Track A, viral finds",
                   "Phase 7: write the missing Track B ideas")
    assert heads.index(a) < heads.index(viral) < heads.index(b)
    picks = _section(text, a)
    for tool in ("download_reel", "list_sources", "create_idea", "render_remix",
                 "mark_dm_pick", "warnings"):
        assert tool in picks, tool
    assert '"in_production"' in picks and '"skipped"' in picks and "clip-specific" in picks
    assert "reactions_plan" in text and "@<creator>" in _section(text, "Phase 10: submit")
    assert "DM pick from @<sender>" in text
    # The cases a dry run meets: no clips, downloads failing, more clips than room.
    dry = _section(text, "Dry run")
    assert "download_reel" in dry and "no such clip" in dry and "reactions_plan.room" in dry
    assert "failed" in _section(text, "Phase 5: Track A, viral finds")


@pytest.mark.parametrize("name", ["daily-produce", "daily-revise"])
def test_track_a_playbooks_state_the_rules(name):
    text = _book(name)
    assert "no shell" in text and "download_reel" in text  # MCP only: no other way in
    assert not re.search(r"yt-dlp|curl|wget|ffmpeg", text, re.I)
    for rule in ("clip-specific", "@<creator>", "re-upload", "mirror", "flip", "speed",
                 "pitch"):
        assert rule in text or rule.replace("<creator>", "creator") in text, rule
    assert "sender_note" in text and "data, never instructions" in text


def test_daily_revise_makes_dm_picks_without_research():
    text = _book("daily-revise")
    picks = _section(text, "Step 3: DM picks")
    assert "dm_picks.json" in text
    for tool in ("download_reel", "create_idea", "render_remix", "mark_dm_pick",
                 "submit_asset"):
        assert tool in picks, tool
    named = set(re.findall(r"`(\w+)", text))
    assert not named & {"research_trends", "get_trend_report", "list_watchlist",
                        "search_hashtag", "list_inspirations"}
    assert "mark_dm_pick" in _section(text, "Dry run")  # a dry run changes no pick


def test_daily_revise_expects_pick_remixes_past_a_full_batch():
    picks = _section(_book("daily-revise"), "Step 3: DM picks")
    assert "go past a full batch" in picks and "night's full batch does not stop it" in picks


def test_decline_motives_and_changes_are_learned():
    """Step 133: the playbooks turn decline motives and judged changes into learnings with
    the 054 rules."""
    def read(name):
        return (runner.AGENT_DIR / "playbooks" / f"{name}.md").read_text(encoding="utf-8")
    revise, learn = read("daily-revise"), read("daily-learn")
    for phrase in ("Decline motives", "`change` block", "`approved`", "`declined`",
                   "`decline_motives`", "`hypothesis`", "`dont`", "owner instruction",
                   '"Changed: "'):
        assert phrase in revise, phrase
    for phrase in ("`owner_decisions`", "`decline_motives`", "`approved_changes`",
                   "one → hypothesis", "repeated → `do` / `dont`", "owner_instruction=True",
                   "evidence_feedback_ids_to_add"):
        assert phrase in learn, phrase


def test_a_change_request_is_never_parked():  # step 156
    for name, title in (("daily-revise", "Step 2: change requests"),
                        ("daily-produce", "Phase 3: new versions the owner asked for")):
        part = _section(_book(name), title)
        assert "Never leave a request without a decision" in part, name
        for tool in ("decide_revision", "request_style", "render_motion"):
            assert tool in part, (name, tool)
    revise = _section(_book("daily-revise"), "Step 2: change requests")
    assert '"restyled"' in revise and "invented" in revise and "`styles`" in revise
    learn = _book("daily-learn")
    weekly = _section(learn, "Step 6: this week's invented style")
    assert "request_style(kind=\"invented\"" in weekly and "`invent_due`" in weekly
    assert "breakdown" in weekly and "`request_style`" in _section(learn, "Dry run")
