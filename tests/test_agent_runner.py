"""The locked-down agent runner (GOAL.md §4, third rule). The guard tests fail if the run
command or the workspace ever loosens; the rest drive a fake `claude` executable."""

import json
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

from src.agent import proc, runner
from src.config import APP_HOME, InstagramMCPSettings
from src.store import to_iso, utcnow

TOKEN = "IGQ-secret-token-123"
# Written out again on purpose: loosening the runner must touch this test too.
ALLOWED = {"mcp__studio__*", "WebSearch", "WebFetch"}
BUILTINS_OK = {"Read", "Glob", "Grep", "WebSearch", "WebFetch", "Skill", "ToolSearch"}
MUST_DISALLOW = {"Bash", "PowerShell", "Edit", "Write", "NotebookEdit"}

FAKE = r'''
import json, os, sys, time
args = sys.argv[1:]
mode = os.environ.get("FAKE_CLAUDE", "success")
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": mode != "signed_out", "email": "owner@example.com"}))
    sys.exit(0)
with open(os.environ["FAKE_CLAUDE_SEEN"], "w") as f:
    json.dump({"args": args, "cwd": os.getcwd(),
               "memory": os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY")}, f)
print("fake stderr line", file=sys.stderr)
if mode == "sleep":
    time.sleep(60)
ok = mode == "success"
print(json.dumps({"type": "result", "subtype": "success" if ok else "error_max_turns",
                  "is_error": not ok, "result": "made 3 ideas" if ok else None,
                  "num_turns": 7, "duration_ms": 1234, "total_cost_usd": 0.42,
                  "usage": {"input_tokens": 10, "output_tokens": 20},
                  "permission_denials": [{"tool_name": "Bash"}]}))
sys.exit(0 if ok else 1)
'''


def _fake_cli(tmp_path: Path) -> str:
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE)
    if sys.platform == "win32":
        exe = tmp_path / "claude.cmd"
        exe.write_text(f'@"{sys.executable}" "{script}" %*\n')
    else:
        exe = tmp_path / "claude"
        exe.write_text(f"#!{sys.executable}\n{FAKE}")
        exe.chmod(0o755)
    return str(exe)


@pytest.fixture
def agent_dir(tmp_path):
    d = tmp_path / "agent"
    (d / "playbooks").mkdir(parents=True)
    (d / "playbooks" / "hello.md").write_text("Say hello.\n")
    (d / "skills" / "hook-guide").mkdir(parents=True)
    (d / "skills" / "hook-guide" / "SKILL.md").write_text("---\nname: hook-guide\n---\n")
    (d / "skills" / "README.md").write_text("not a skill\n")
    return d


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_SEEN", str(tmp_path / "seen.json"))
    return InstagramMCPSettings(
        _env_file=None, instagram_access_token=TOKEN, facebook_app_secret="app-secret-456",
        database_path=":memory:",
        agent_workspace=str(tmp_path / "ws"), agent_log_dir=str(tmp_path / "logs"),
        claude_bin=_fake_cli(tmp_path), agent_max_turns=40)


def _flag(cmd, name):
    return cmd[cmd.index(name) + 1]


# --- guard: the run command and workspace never loosen ----------------------------
def test_command_is_locked_down(cfg, agent_dir):
    config = runner.prepare_workspace(cfg, "hello", agent_dir=agent_dir)
    cmd = runner.build_command(cfg, "hello", config)
    assert cmd[:2] == [cfg.claude_bin, "-p"]
    disallowed = set(_flag(cmd, "--disallowedTools").split(","))
    assert MUST_DISALLOW <= disallowed
    assert set(_flag(cmd, "--allowedTools").split(",")) <= ALLOWED
    builtins = set(_flag(cmd, "--tools").split(","))
    assert builtins <= BUILTINS_OK and not builtins & disallowed
    assert "--strict-mcp-config" in cmd and _flag(cmd, "--mcp-config") == str(config)
    assert _flag(cmd, "--permission-mode") == "dontAsk"
    assert _flag(cmd, "--permission-prompts") == "none"
    assert _flag(cmd, "--setting-sources") == "project"
    assert _flag(cmd, "--output-format") == "json"
    assert _flag(cmd, "--max-turns") == "40"
    assert "--dangerously-skip-permissions" not in cmd and "bypassPermissions" not in cmd
    for flag in ("--allowedTools", "--disallowedTools", "--tools", "--mcp-config",
                 "--permission-mode", "--setting-sources", "--settings", "--add-dir",
                 "--plugin-dir"):
        assert cmd.count(flag) <= 1  # no second flag widening the first
    assert TOKEN not in " ".join(cmd)


def test_mcp_config_holds_only_our_server_in_agent_profile(cfg, agent_dir):
    config = runner.prepare_workspace(cfg, "hello", agent_dir=agent_dir)
    text = config.read_text()
    servers = json.loads(text)["mcpServers"]
    assert list(servers) == [runner.SERVER]
    assert servers[runner.SERVER]["env"]["IG_MCP_PROFILE"] == "agent"
    assert servers[runner.SERVER]["args"] == ["-m", "src.instagram_mcp_server"]
    assert TOKEN not in text
    allowed_mcp = [t for t in _flag(runner.build_command(cfg, "hello", config),
                                    "--allowedTools").split(",") if t.startswith("mcp__")]
    assert allowed_mcp == [f"mcp__{runner.SERVER}__*"]


@pytest.mark.parametrize("where", [runner.REPO, runner.REPO / "agent" / "ws", APP_HOME,
                                   Path(APP_HOME) / "data" / "ws", runner.REPO.parent])
def test_workspace_inside_repo_or_app_home_is_refused(cfg, agent_dir, where):
    cfg.agent_workspace = str(where)
    with pytest.raises(runner.AgentError, match="outside|git repository"):
        runner.prepare_workspace(cfg, "hello", agent_dir=agent_dir)


def test_default_settings_in_tests_never_point_at_the_real_machine():
    """Step 160 (tests/conftest.py): a default-settings run can't reach the live workspace."""
    s = InstagramMCPSettings(_env_file=None)
    tmp = Path(tempfile.gettempdir()).resolve()
    for path in (s.agent_workspace, s.agent_log_dir, s.gpu_lock_path, s.database_path,
                 s.media_root, s.backup_dir, s.claude_bin):
        assert tmp in Path(path).resolve().parents, path


def test_workspace_refuses_a_foreign_claude_folder(cfg, agent_dir, tmp_path):
    (tmp_path / "ws" / ".claude").mkdir(parents=True)
    with pytest.raises(runner.AgentError, match="not made by"):
        runner.prepare_workspace(cfg, "hello", agent_dir=agent_dir)


def test_workspace_is_refreshed_with_playbook_skills_and_deny_rules(cfg, agent_dir, tmp_path):
    runner.prepare_workspace(cfg, "hello", agent_dir=agent_dir)
    ws = tmp_path / "ws"
    (ws / ".claude" / "skills" / "old-skill").mkdir()
    runner.prepare_workspace(cfg, "hello.md", agent_dir=agent_dir)
    assert (ws / "playbooks" / "hello.md").read_text() == "Say hello.\n"
    assert json.loads((ws / "voices.json").read_text(encoding="utf-8"))["voices"]  # 038
    assert sorted(p.name for p in (ws / ".claude" / "skills").iterdir()) == ["hook-guide"]
    deny = json.loads((ws / ".claude" / "settings.json").read_text())["permissions"]["deny"]
    assert "Read(//**/.env)" in deny
    assert any(r.endswith("/data/**)") for r in deny)


def test_unknown_or_path_like_playbook_is_refused(cfg, agent_dir):
    for name in ("nope", "../hello", "Hello"):
        with pytest.raises(runner.AgentError, match="unknown playbook"):
            runner.prepare_workspace(cfg, name, agent_dir=agent_dir)


# --- runs with the fake CLI ---------------------------------------------------------
def test_success_records_usage_and_a_log_without_secrets(cfg, agent_dir, store, tmp_path,
                                                         monkeypatch):
    run = runner.run_agent(store, cfg, "hello", agent_dir=agent_dir, timeout_s=60)
    assert run["status"] == "succeeded" and run["summary"] == "made 3 ideas"
    assert run["pid"] == os.getpid() and run["pid_started"] == proc.started(os.getpid())
    usage = run["usage"]
    assert usage["total_cost_usd"] == 0.42 and usage["num_turns"] == 7
    assert usage["usage"]["output_tokens"] == 20 and usage["permission_denials"] == 1
    seen = json.loads((tmp_path / "seen.json").read_text())
    assert Path(seen["cwd"]).resolve() == (tmp_path / "ws").resolve()
    assert seen["memory"] == "1" and "--strict-mcp-config" in seen["args"]
    log = Path(run["log_path"]).read_text()
    assert "fake stderr line" in log and "succeeded" in log
    assert TOKEN not in log and "owner@example.com" not in log
    assert runner._secrets(cfg) == [TOKEN, "app-secret-456"]


def test_failure_is_recorded_as_failed(cfg, agent_dir, store, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE", "fail")
    run = runner.run_agent(store, cfg, "hello", agent_dir=agent_dir, timeout_s=60)
    assert run["status"] == "failed" and run["summary"] == "error_max_turns"


def test_timeout_kills_the_cli(cfg, agent_dir, store, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE", "sleep")
    run = runner.run_agent(store, cfg, "hello", agent_dir=agent_dir, timeout_s=3)
    assert run["status"] == "failed" and "timed out" in run["summary"]
    assert store.running_agent_run("hello") is None


def test_signed_out_cli_fails_preflight_with_a_clear_message(cfg, agent_dir, store,
                                                             monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_CLAUDE", "signed_out")
    run = runner.run_agent(store, cfg, "hello", agent_dir=agent_dir, timeout_s=60)
    assert run["status"] == "failed" and "not signed in" in run["summary"]
    assert not (tmp_path / "seen.json").exists()  # the agent never started


def test_missing_cli_fails_preflight(cfg):
    cfg.claude_bin = "no-such-claude-cli"
    with pytest.raises(runner.AgentError, match="not found"):
        runner.preflight(cfg)


def test_lock_held_refuses_a_second_run(cfg, agent_dir, store, tmp_path):
    held = store.start_agent_run("hello")
    with pytest.raises(runner.AgentRunRefused):
        runner.run_agent(store, cfg, "hello", agent_dir=agent_dir, timeout_s=60)
    assert store.running_agent_run("hello")["id"] == held["id"]
    assert not (tmp_path / "seen.json").exists()


def test_stale_lock_is_released(cfg, agent_dir, store):
    held = store.start_agent_run("hello")
    with store._tx() as c:
        c.execute("UPDATE agent_runs SET started_at=? WHERE id=?",
                  (to_iso(utcnow() - timedelta(hours=25)), held["id"]))
    run = runner.run_agent(store, cfg, "hello", agent_dir=agent_dir, timeout_s=60)
    assert run["status"] == "succeeded"
    assert [r["status"] for r in store.list_agent_runs("hello")] == ["succeeded", "failed"]


def test_cli_agent_check(cfg, monkeypatch, capsys):
    from src import scheduler

    monkeypatch.setattr(scheduler, "get_settings", lambda: cfg)
    # configure_logging would bind loggers to capsys's stream, closed after the test.
    monkeypatch.setattr(scheduler, "configure_logging", lambda *a: None)
    with pytest.raises(SystemExit) as done:
        scheduler.main(["agent", "check"])
    assert done.value.code == 0 and "signed in" in capsys.readouterr().out
    monkeypatch.setenv("FAKE_CLAUDE", "signed_out")
    with pytest.raises(SystemExit) as done:
        scheduler.main(["agent", "check"])
    assert done.value.code == 1

