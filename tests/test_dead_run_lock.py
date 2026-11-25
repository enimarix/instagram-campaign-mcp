"""Step 155: a run whose runner process is gone (studio restart) frees its lock at once
(src/agent/runner.py close_dead_runs / check_lock, src/agent/proc.py). The process probe
is faked, except the real-probe test on this process and a child that already exited."""

import os
import subprocess
import sys

import pytest

from src import scheduler
from src import store as store_mod
from src.agent import proc, runner
from src.config import InstagramMCPSettings
from src.store import CampaignStore
from src.studio import work_orders

from .test_dm_work_orders import Clock, Starts, cfg
from .test_revision_wakes import _ask, _run

LOCK_S = 3600


@pytest.fixture
def clock(monkeypatch):
    c = Clock()  # every stamp (feedback, runs) and the lock's age on one clock
    for mod in (work_orders, store_mod, runner):
        monkeypatch.setattr(mod, "utcnow", c)
    return c


@pytest.fixture
def probe(monkeypatch):
    """proc.started faked: pid -> creation time; a pid not listed is gone."""
    alive = {}
    monkeypatch.setattr(proc, "started", alive.get)
    return alive


def test_dead_runner_is_closed_and_the_order_run_fires(store, clock, probe):
    probe[4242] = 111
    held = store.start_agent_run("daily-revise", 4242, 111)
    clock.set(1)
    _ask(store)
    f = Starts()
    assert _run(store, 10, f=f) is None  # a live runner holds the lock
    del probe[4242]  # the studio restarted: the runner died with it
    assert _run(store, 11, f=f) == "daily-revise" and f.runs == ["daily-revise"]
    row = store.list_agent_runs("daily-revise")[0]
    assert row["id"] == held["id"] and row["status"] == "failed"
    assert row["summary"] == runner.DEAD_RUN


def test_live_runner_refuses(store, probe):
    probe[4242] = 111
    store.start_agent_run("hello", 4242, 111)
    with pytest.raises(runner.AgentRunRefused):
        runner.check_lock(store, "hello", LOCK_S)


def test_reused_pid_is_a_dead_runner(store, probe):
    probe[4242] = 222  # another process got the pid
    store.start_agent_run("hello", 4242, 111)
    runner.check_lock(store, "hello", LOCK_S)
    assert store.running_agent_run("hello") is None


def test_old_row_without_pid_keeps_the_24h_rule(store, clock, probe):
    held = store.start_agent_run("hello")  # before 155: no pid, the probe can't help
    clock.set(23 * 60)
    with pytest.raises(runner.AgentRunRefused):
        runner.check_lock(store, "hello", LOCK_S)
    clock.set(25 * 60)
    runner.check_lock(store, "hello", LOCK_S)
    assert store.list_agent_runs("hello")[0]["id"] == held["id"]
    assert store.list_agent_runs("hello")[0]["summary"] == "stale: the runner died"


def test_up_closes_dead_runs_of_every_playbook_at_start(tmp_path, probe, capsys):
    db = tmp_path / "studio.db"
    store = CampaignStore(str(db))
    probe[7] = 1
    dead = [store.start_agent_run(p, 99, 5)["id"] for p in ("daily-produce", "daily-revise")]
    live = store.start_agent_run("daily-learn", 7, 1)["id"]
    old = store.start_agent_run("weekly-ads")["id"]
    store.close()
    scheduler._close_dead_runs(InstagramMCPSettings(_env_file=None, database_path=str(db)))
    store = CampaignStore(str(db))
    try:
        status = {r["id"]: r["status"] for r in store.list_agent_runs()}
    finally:
        store.close()
    assert [status[i] for i in (*dead, live, old)] == ["failed", "failed", "running", "running"]
    assert "closed as failed" in capsys.readouterr().err


def test_real_probe():
    me = proc.started(os.getpid())
    assert me is not None and not proc.is_gone(os.getpid(), me)
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert proc.started(child.pid) is None and proc.is_gone(child.pid, None)
    assert proc.is_gone(0, None) is False and proc.started(-1) is None


def test_a_run_killed_after_the_request_does_not_have_it(store, clock, probe):
    s, f = cfg(max_order_runs_per_day=2), Starts()
    _ask(store)
    assert _run(store, 3, s, f) == "daily-revise"  # the at-once run starts...
    clock.set(3)
    probe[4242] = 111
    store.start_agent_run("daily-revise", 4242, 111)  # ...its row, after the request
    assert _run(store, 5, s, f) is None  # it runs: one at a time
    del probe[4242]  # the studio restarted
    assert _run(store, 6, s, f) == "daily-revise" and len(f.runs) == 2  # next tick
    clock.set(6)
    store.start_agent_run("daily-revise", 4243, 1)  # dies too
    assert _run(store, 9, s, f) is None and len(f.runs) == 2  # today's 2 at-once runs used


def test_only_a_run_that_handled_everything_saw_the_request(store, clock, probe):
    _ask(store)  # a failed run (usage limit, crash) or one that left work unhandled: not seen
    for at, status, summary in ((3, "failed", "error_max_turns"),
                                (11, "succeeded", "done\nwork packet: 1 of 1 revisions not"
                                 " handled: #1")):
        clock.set(at)
        run = store.start_agent_run("daily-revise", 4242, 111)
        store.finish_agent_run(run["id"], status, summary=summary)
        assert _run(store, at + 7) == "daily-revise"
    clock.set(20)
    run = store.start_agent_run("daily-revise", 4242, 111)
    store.finish_agent_run(run["id"], "succeeded", summary="done")
    assert _run(store, 27) is None
