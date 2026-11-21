"""The Lemo film runner (step 173): the one agent run with a shell. The guard tests fail if
its command, workspace or environment loosen; the rest drive a fake `claude` executable
that delivers a tiny film."""

import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from src.agent import film, runner, schedule
from src.config import InstagramMCPSettings
from src.studio import gpu_run, lemo, media, work_orders
from src.studio.assets import transition
from src.store import to_iso, utcnow

TOKEN = "IGQ-film-secret-789"
SAMPLE = Path(__file__).resolve().parents[1] / "src" / "studio" / "samples" / "sample.mp4"
# Written out again on purpose: loosening the film runner must touch this test too.
TOOLS = {"Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill"}
MUST_DISALLOW = {"PowerShell", "WebSearch", "WebFetch", "Agent", "NotebookEdit"}

FAKE = r'''
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
mode = os.environ.get("FAKE_CLAUDE", "success")
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": mode != "signed_out"}))
    sys.exit(0)
seen = {"args": args, "cwd": os.getcwd(), "env": dict(os.environ),
        "brief": Path("BRIEF.md").read_text(encoding="utf-8")}
Path(os.environ["FAKE_CLAUDE_SEEN"]).write_text(json.dumps(seen))
if mode == "sleep":
    time.sleep(60)
if mode in ("success", "QC"):
    Path("film").mkdir(exist_ok=True)
    Path("film/final.mp4").write_bytes(Path(os.environ["FAKE_FILM"]).read_bytes())
    Path("film/post.json").write_text(json.dumps({
        "hook": "Où partent vos calories ?", "script": "Disons 2 000 kcal par jour.",
        "caption": "Où partent vos 2 000 kcal ? Envoyez ça à un ami.",
        "description": "Un diorama isométrique.",
        "sources": [{"title": "FAO 2004", "url": "https://www.fao.org/x"},
                    {"title": "a book, no link"}]}), encoding="utf-8")
ok = mode != "fail"
print(json.dumps({"type": "result", "subtype": "success" if ok else "error_max_turns",
                  "is_error": not ok, "result": "film made" if ok else None, "num_turns": 90,
                  "total_cost_usd": 4.2, "usage": {"output_tokens": 20}}))
sys.exit(0 if ok else 1)
'''


def _fake_cli(tmp_path: Path) -> str:
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE, encoding="utf-8")
    if sys.platform == "win32":
        exe = tmp_path / "claude.cmd"
        exe.write_text(f'@"{sys.executable}" "{script}" %*\n')
    else:
        exe = tmp_path / "claude"
        exe.write_text(f"#!{sys.executable}\n{FAKE}")
        exe.chmod(0o755)
    return str(exe)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    lib = tmp_path / "lemo-opuscar"
    (lib / "styles" / "watercolor").mkdir(parents=True)
    (lib / "styles" / "watercolor" / "style.json").write_text(json.dumps(
        {"slug": "watercolor", "en": "Watercolor Brush", "line": "A painted walk."}))
    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: lemo-opuscar\n---\n")
    (skill / "scripts" / "setup.sh").write_text("echo LIB=x\n")
    monkeypatch.setenv("FAKE_CLAUDE_SEEN", str(tmp_path / "seen.json"))
    monkeypatch.setenv("FAKE_FILM", str(SAMPLE))
    s = InstagramMCPSettings(
        _env_file=None, instagram_access_token=TOKEN, database_path=":memory:",
        agent_workspace=str(tmp_path / "ws"), agent_log_dir=str(tmp_path / "logs"),
        media_root=str(tmp_path / "media"), claude_bin=_fake_cli(tmp_path),
        lemo_library=str(lib), lemo_skill_dir=str(skill))
    monkeypatch.setattr(lemo, "get_settings", lambda: s)
    return s


@pytest.fixture
def judged(monkeypatch):
    """No worker in tests: the render + QC of the delivered film is judged at once."""
    verdict = {"status": "ready"}

    def wait(store, asset_id, wait_s, poll_s):
        if verdict["status"] == "failed":
            store.update_asset(asset_id, qc={"passed": False, "reasons": ["too dark"]})
        return transition(store, asset_id, verdict["status"], actor="worker")

    monkeypatch.setattr(film, "_wait_render", wait)
    return verdict


def _order(store, style="lemo:watercolor", text="Où partent les calories ?"):
    return work_orders.create_video(store, text, style)


def _flag(cmd, name):
    return cmd[cmd.index(name) + 1]


# --- guard: the command, workspace and environment never loosen ----------------------
def test_command_is_locked_down(cfg):
    ws = film.prepare_workspace(cfg, 7, "brief")
    cmd = film.build_command(cfg, ws)
    assert cmd[:2] == [cfg.claude_bin, "-p"]
    assert set(_flag(cmd, "--tools").split(",")) == TOOLS
    assert MUST_DISALLOW <= set(_flag(cmd, "--disallowedTools").split(","))
    allowed = _flag(cmd, "--allowedTools").split(",")
    assert [a for a in allowed if a.startswith(("Edit", "Write"))] == [
        f"Edit({runner._rule_path(ws)}/**)"]  # writes in its workspace only
    assert set(allowed) - {allowed[-1]} == {"Bash", "Read", "Glob", "Grep", "Skill"}
    assert "--strict-mcp-config" in cmd and "--mcp-config" not in cmd  # no MCP server
    assert _flag(cmd, "--permission-mode") == "dontAsk"
    assert _flag(cmd, "--permission-prompts") == "none"
    assert _flag(cmd, "--setting-sources") == "project"
    assert "--dangerously-skip-permissions" not in cmd and "bypassPermissions" not in cmd
    for f in ("--allowedTools", "--disallowedTools", "--tools", "--settings", "--add-dir",
              "--plugin-dir", "--setting-sources"):
        assert cmd.count(f) <= 1
    assert TOKEN not in " ".join(cmd)


def test_workspace_holds_brief_skill_and_deny_rules(cfg, tmp_path):
    ws = film.prepare_workspace(cfg, 7, "the brief")
    assert ws == (tmp_path / "ws" / "films" / "7").resolve()
    assert (ws / "BRIEF.md").read_text(encoding="utf-8") == "the brief"
    skills = ws / ".claude" / "skills"
    assert [p.name for p in skills.iterdir()] == ["lemo-opuscar"]
    assert (skills / "lemo-opuscar" / "scripts" / "setup.sh").is_file()
    deny = json.loads((ws / ".claude" / "settings.json").read_text())["permissions"]["deny"]
    assert "Read(//**/.env)" in deny


@pytest.mark.parametrize("where", [runner.REPO, runner.REPO / "agent"])
def test_workspace_inside_the_repo_is_refused(cfg, where):
    cfg.agent_workspace = str(where)
    with pytest.raises(runner.AgentError, match="outside|git repository"):
        film.prepare_workspace(cfg, 7, "brief")


def test_a_foreign_claude_folder_is_never_replaced(cfg, tmp_path):
    (tmp_path / "ws" / "films" / "7" / ".claude").mkdir(parents=True)
    with pytest.raises(runner.AgentError, match="not made by"):
        film.prepare_workspace(cfg, 7, "brief")


def test_missing_skill_is_a_clear_error(cfg, tmp_path):
    cfg.lemo_skill_dir = str(tmp_path / "nope")
    with pytest.raises(runner.AgentError, match="skill is not installed"):
        film.skill_dir(cfg)


def test_env_has_no_secret_and_no_env_file_name(cfg, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SOME_API_KEY=abc\n")
    monkeypatch.setattr(film, "ENV_FILE", env_file)
    monkeypatch.setenv("SOME_API_KEY", "abc")
    monkeypatch.setenv("HIDDEN_COPY", f"x{TOKEN}x")
    monkeypatch.setenv("IG_MCP_HOME", "D:/studio")
    env = film.film_env(cfg)
    assert "SOME_API_KEY" not in env and "HIDDEN_COPY" not in env
    assert not any(k.startswith("IG_MCP_") for k in env)
    assert not any(TOKEN in v for v in env.values())
    assert "PATH" in {k.upper() for k in env} and env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert env["LEMO_OPUSCAR_HOME"] == cfg.lemo_library


# --- orders in a Lemo style ----------------------------------------------------------
def test_lemo_styles_are_checked_in_the_library(store, cfg):
    assert _order(store)["style"] == "lemo:watercolor"
    for bad in ("lemo:nope", "lemo:../x", "lemo:"):
        with pytest.raises(ValueError, match="unknown Lemo-Opuscar style"):
            _order(store, bad)


def test_lemo_orders_never_reach_the_agent(store, cfg, settings):
    order = _order(store)
    assert work_orders.for_agent(store) == []
    settings.order_run_debounce_minutes = 0
    started = []
    assert schedule.order_run(store, settings, utcnow() + timedelta(minutes=5),
                              start=lambda *a: started.append(a), check=lambda s: None) is None
    assert not started
    work_orders.set_blocked(store, "agent reason")  # the agent's wait reason is not theirs
    assert work_orders.get_order(store, order["id"])["blocked_reason"] is None


def test_a_change_order_may_remake_a_video_in_a_lemo_style(store, cfg):
    idea = store.add_idea("motion", hook="h")
    asset = store.add_asset(idea["id"])
    order = work_orders.restyle(store, asset["id"], "lemo:watercolor")
    assert order["style"] == "lemo:watercolor" and "Watercolor Brush" in order["instruction"]


# --- runs with the fake CLI ----------------------------------------------------------
def test_a_film_reaches_the_inbox(store, cfg, judged, tmp_path):
    order = _order(store)
    run = film.run_film(store, cfg, order["id"])
    assert run["status"] == "succeeded" and run["playbook"] == film.PLAYBOOK
    assert run["usage"]["total_cost_usd"] == 4.2 and "film made" in run["summary"]
    seen = json.loads((tmp_path / "seen.json").read_text())
    assert Path(seen["cwd"]).resolve() == (tmp_path / "ws" / "films" / str(order["id"]))
    assert "watercolor" in seen["brief"] and "Où partent les calories ?" in seen["brief"]
    assert "$" not in seen["brief"].replace("$LIB", "")  # every placeholder filled in
    assert not any(TOKEN in v for v in seen["env"].values())
    done = work_orders.get_order(store, order["id"])
    assert done["status"] == "in_feed"
    asset = store.get_asset(done["asset_id"])
    assert asset["status"] == "ready" and asset["caption"].startswith("Où partent vos")
    rel = asset["recipe"]["inputs"]["source"]
    assert rel == f"films/{order['id']}/final.mp4"
    assert media.resolve(cfg.media_root, rel).read_bytes() == SAMPLE.read_bytes()
    assert store.list_render_jobs(asset_id=asset["id"])
    idea = store.get_idea(asset["idea_id"])
    assert idea["style"] == "lemo:watercolor" and idea["track"] == "motion"
    assert idea["hook"] == "Où partent vos calories ?"
    assert idea["citations"] == [{"url": "https://www.fao.org/x", "title": "FAO 2004"}]
    assert TOKEN not in Path(run["log_path"]).read_text()


@pytest.mark.parametrize("mode, why", [("fail", "error_max_turns"),
                                       ("nothing", "delivered no film/final.mp4"),
                                       ("QC", "QC")])
def test_a_failed_film_skips_the_order_with_the_reason(store, cfg, judged, monkeypatch,
                                                       mode, why):
    monkeypatch.setenv("FAKE_CLAUDE", mode)
    if mode == "QC":
        judged["status"] = "failed"
    order = _order(store)
    run = film.run_film(store, cfg, order["id"])
    assert run["status"] == "failed" and why in run["summary"]
    done = work_orders.get_order(store, order["id"])
    assert done["status"] == "skipped" and why in done["skip_reason"]


def test_timeout_kills_the_film(store, cfg, judged, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE", "sleep")
    cfg.lemo_film_max_min = 0.05  # 3 s
    order = _order(store)
    run = film.run_film(store, cfg, order["id"])
    assert run["status"] == "failed" and "timed out" in run["summary"]
    assert work_orders.get_order(store, order["id"])["status"] == "skipped"
    assert store.running_agent_run(film.PLAYBOOK) is None


def test_one_film_at_a_time_and_a_daily_cap(store, cfg, judged):
    first, second = _order(store), _order(store, text="Les protéines")
    held = store.start_agent_run(film.PLAYBOOK, os.getpid())
    with pytest.raises(runner.AgentRunRefused):
        film.run_film(store, cfg, first["id"])
    store.finish_agent_run(held["id"], "succeeded")
    cfg.lemo_films_per_day = 2
    film.run_film(store, cfg, first["id"])
    with pytest.raises(runner.AgentError, match="films du jour"):
        film.run_film(store, cfg, second["id"])
    assert work_orders.get_order(store, second["id"])["status"] == "scheduled"


# --- the worker's catch-up -----------------------------------------------------------
def test_catch_up_hands_the_oldest_lemo_order_to_the_film_runner(store, cfg):
    first, _ = _order(store), _order(store, text="Les protéines")
    started = []
    assert schedule.film_run(store, cfg, utcnow(), start=lambda s, c, i: started.append(i),
                             check=lambda s: None) == first["id"]
    assert started == [first["id"]]


def test_catch_up_says_why_lemo_orders_wait(store, cfg):
    order = _order(store)
    cfg.lemo_films_per_day = 0
    assert schedule.film_run(store, cfg, utcnow(), start=None, check=None) is None
    assert "films du jour" in work_orders.get_order(store, order["id"])["blocked_reason"]
    cfg.lemo_films_per_day = 3

    def signed_out(s):
        raise runner.AgentError("not signed in")

    assert schedule.film_run(store, cfg, utcnow(), start=None, check=signed_out) is None
    assert "not signed in" in work_orders.get_order(store, order["id"])["blocked_reason"]
    assert store.get_state("order_preflight_failed_at")


def test_an_order_a_dead_film_left_is_skipped(store, cfg):
    order = _order(store)
    idea = store.add_idea("motion", hook="h", style="lemo:watercolor")
    work_orders.start(store, order["id"], idea)
    store.set_state("order_preflight_failed_at", to_iso(utcnow()))  # nothing new starts
    assert schedule.film_run(store, cfg, utcnow(), start=None) is None
    done = work_orders.get_order(store, order["id"])
    assert done["status"] == "skipped" and done["skip_reason"] == film.INTERRUPTED


def test_the_film_brief_is_not_an_agent_playbook(cfg):
    from src.agent.runs import list_playbooks

    assert film.PLAYBOOK not in list_playbooks()
    with pytest.raises(runner.AgentError, match="unknown playbook"):
        runner._playbook_file(film.PLAYBOOK, runner.AGENT_DIR)


# --- the GPU lock wrapper ------------------------------------------------------------
def test_gpu_run_runs_the_command_under_the_lock_and_returns_its_code(capsys):
    assert gpu_run.main(["--", sys.executable, "-c", "raise SystemExit(3)"]) == 3
    assert gpu_run.main([]) == 2 and "usage" in capsys.readouterr().err
