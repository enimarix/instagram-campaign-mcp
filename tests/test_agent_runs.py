"""Step 060: agent runs for the website (src/agent/runs.py, src/api/agent.py)."""

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.agent import runner, runs
from src.api.app import create_app
from src.config import InstagramMCPSettings

from .conftest import LOCAL

ORIGIN = {"Origin": LOCAL}


@pytest.fixture
def agent_dir(tmp_path, monkeypatch):
    d = tmp_path / "agent"
    (d / "playbooks").mkdir(parents=True)
    (d / "playbooks" / "README.md").write_text("not a playbook\n")
    (d / "playbooks" / "hello.md").write_text("Say hello.\n")
    (d / "playbooks" / "daily-produce.md").write_text("Produce.\n")
    monkeypatch.setattr(runs, "AGENT_DIR", d)
    return d


@pytest.fixture
def cfg(tmp_path):
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                                database_path=":memory:", agent_log_dir=str(tmp_path / "logs"))


class FakePopen:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))


def test_playbooks_exclude_readme(agent_dir, tmp_path):
    assert runs.list_playbooks() == ["daily-produce", "hello"]
    assert runs.list_playbooks(tmp_path / "nothing") == []


def test_list_runs_flattens_usage(store, cfg):
    run = store.start_agent_run("hello")
    store.finish_agent_run(run["id"], "succeeded", summary="made 3 ideas", log_path="x.log",
                           usage={"num_turns": 7, "total_cost_usd": 0.42, "duration_ms": 1234,
                                  "permission_denials": 1})
    store.start_agent_run("hello")
    newest, done = runs.list_runs(store)
    assert newest["status"] == "running" and newest["cost_usd"] is None
    assert newest["has_log"] is False and newest["duration_s"] >= 0
    assert done == {**done, "num_turns": 7, "cost_usd": 0.42, "permission_denials": 1,
                    "has_log": True, "summary": "made 3 ideas"}
    assert "usage" not in done and "log_path" not in done


def test_log_tail(store, cfg, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "1.log").write_text("".join(f"line {i}\n" for i in range(100)))
    run = store.start_agent_run("hello")
    store.finish_agent_run(run["id"], "failed", log_path=str(logs / "1.log"))
    out = runs.log_tail(store, cfg, run["id"], lines=3)
    assert out["lines"] == ["line 97", "line 98", "line 99"]


def test_log_tail_refused_outside_log_dir(store, cfg, tmp_path):
    (tmp_path / "secret.txt").write_text("nope\n")
    run = store.start_agent_run("hello")
    store.finish_agent_run(run["id"], "failed",
                           log_path=str(tmp_path / "logs" / ".." / "secret.txt"))
    with pytest.raises(PermissionError):
        runs.log_tail(store, cfg, run["id"])
    with pytest.raises(KeyError):  # running, no log yet
        runs.log_tail(store, cfg, store.start_agent_run("hello")["id"])


def test_start_refused_while_running(store, cfg, agent_dir):
    store.start_agent_run("hello")
    popen = FakePopen()
    with pytest.raises(runner.AgentRunRefused):
        runs.start_run(store, cfg, "hello", popen=popen)
    with pytest.raises(runner.AgentError, match="unknown playbook"):
        runs.start_run(store, cfg, "../hello", popen=popen)
    assert popen.calls == []


def test_start_runs_the_cli_detached(store, cfg, agent_dir):
    popen = FakePopen()
    assert runs.start_run(store, cfg, "hello.md", popen=popen) == {
        "started": True, "playbook": "hello"}
    [(argv, kw)] = popen.calls
    assert argv == [sys.executable, "-m", "src.scheduler", "agent", "run", "hello"]
    assert kw["cwd"] == runner.REPO
    assert kw["stdin"] == kw["stdout"] == kw["stderr"] == subprocess.DEVNULL
    if sys.platform == "win32":
        assert kw["creationflags"] & subprocess.DETACHED_PROCESS
    else:
        assert kw["start_new_session"] is True
    assert store.list_agent_runs() == []  # the runner writes the row, not us


def test_routes(store, cfg, agent_dir, tmp_path, monkeypatch):
    popen = FakePopen()
    monkeypatch.setattr(subprocess, "Popen", popen)  # runs.start_run's default
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "1.log").write_text("hello\n")
    done = store.start_agent_run("daily-produce")
    store.finish_agent_run(done["id"], "succeeded", log_path=str(logs / "1.log"))
    with TestClient(create_app(cfg, store=store), base_url=LOCAL, headers=ORIGIN) as tc:
        assert tc.get("/api/agent/playbooks").json() == ["daily-produce", "hello"]
        assert [r["id"] for r in tc.get("/api/agent/runs?limit=5").json()] == [done["id"]]
        assert tc.get(f"/api/agent/runs/{done['id']}/log").json()["lines"] == ["hello"]
        assert tc.get("/api/agent/runs/999/log").status_code == 404

        r = tc.post("/api/agent/runs", json={"playbook": "hello"})
        assert r.status_code == 200 and r.json() == {"started": True, "playbook": "hello"}
        assert len(popen.calls) == 1

        r = tc.post("/api/agent/runs", json={"playbook": "nope"})
        assert r.status_code == 404 and r.json()["error"] == "unknown_playbook"

        store.start_agent_run("hello")
        r = tc.post("/api/agent/runs", json={"playbook": "hello"})
        assert r.status_code == 409 and r.json()["error"] == "already_running"
        assert len(popen.calls) == 1


def test_routes_need_a_session(store, cfg):
    cfg = cfg.model_copy(update={"ui_password": SecretStr("pw")})
    with TestClient(create_app(cfg, store=store), base_url=LOCAL, headers=ORIGIN) as tc:
        assert tc.get("/api/agent/runs").status_code == 401
        assert tc.post("/api/agent/runs", json={"playbook": "hello"}).status_code == 401
