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


@pytest.mark.parametrize("name", ["daily-produce", "daily-revise", "daily-learn"])
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
    assert [p for p, _ in runs] == ["daily-learn", "daily-produce"]
    assert runs[0][1] < runs[1][1]
    for name, _ in runs:
        assert (runner.AGENT_DIR / "playbooks" / f"{name}.md").is_file()
