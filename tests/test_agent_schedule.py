"""Step 061: scheduled agent runs and autostart (src/agent/schedule.py)."""

import asyncio
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.agent import runner, runs, schedule
from src.api.app import create_app
from src.config import InstagramMCPSettings

from .conftest import LOCAL

UTC = timezone.utc
# 2026-11-17 02:30 UTC = 03:30 in Paris (winter, UTC+1)
NOW = datetime(2026, 11, 17, 2, 30, tzinfo=UTC)


@pytest.fixture
def agent_dir(tmp_path, monkeypatch):
    d = tmp_path / "agent"
    (d / "playbooks").mkdir(parents=True)
    (d / "playbooks" / "daily-produce.md").write_text("Produce.\n")
    monkeypatch.setattr(schedule, "AGENT_DIR", d)
    monkeypatch.setattr(runs, "AGENT_DIR", d)
    return d


def cfg(**kw):
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                                database_path=":memory:", **{"timezone": "Europe/Paris", **kw})


def started_at(store, run_id, when):
    with store._tx() as c:
        c.execute("UPDATE agent_runs SET started_at=? WHERE id=?",
                  (when.isoformat(), run_id))


def test_parse_schedule():
    assert schedule.parse_schedule(" a@03:00, b-2@23:59 ,") == [
        ("a", schedule.time(3)), ("b-2", schedule.time(23, 59))]
    assert schedule.parse_schedule("") == []
    for bad in ("a@3:00", "a@24:00", "a", "../a@03:00", "a@03:00,a@04:00"):
        with pytest.raises(ValueError):
            schedule.parse_schedule(bad)
    with pytest.raises(ValidationError):
        cfg(agent_schedule="daily-produce@25:00")


def test_due_before_and_after_the_time(store, agent_dir):
    s = cfg()  # daily-produce@03:00 Paris = 02:00 UTC
    assert schedule.due_runs(store, s, NOW - timedelta(minutes=31)) == []
    assert schedule.due_runs(store, s, NOW) == ["daily-produce"]


def test_not_due_when_ran_today_or_running(store, agent_dir):
    s = cfg()
    run = store.start_agent_run("daily-produce")
    assert schedule.due_runs(store, s, NOW) == []  # running
    store.finish_agent_run(run["id"], "failed")
    assert schedule.due_runs(store, s, NOW) == []  # started today (failed counts)
    started_at(store, run["id"], NOW - timedelta(days=1))
    assert schedule.due_runs(store, s, NOW) == ["daily-produce"]


def test_stale_running_row_does_not_block(store, agent_dir):
    run = store.start_agent_run("daily-produce")
    started_at(store, run["id"], NOW - timedelta(days=3))
    assert schedule.due_runs(store, cfg(), NOW) == ["daily-produce"]
    assert store._get("agent_runs", run["id"])["status"] == "failed"


def test_missing_playbook_is_skipped(store, agent_dir):
    s = cfg(agent_schedule="later@01:00,daily-produce@02:00")
    assert schedule.due_runs(store, s, NOW) == ["daily-produce"]


def test_owner_local_day_boundary(store, agent_dir):
    # Tokyo is UTC+9: 2026-11-17 16:00 UTC is already 01:00 on the 18th there
    s = cfg(timezone="Asia/Tokyo", agent_schedule="daily-produce@00:30")
    run = store.start_agent_run("daily-produce")
    store.finish_agent_run(run["id"], "succeeded")
    started_at(store, run["id"], datetime(2026, 11, 17, 14, 0, tzinfo=UTC))  # 23:00 Tokyo
    assert schedule.due_runs(store, s, datetime(2026, 11, 17, 16, 0, tzinfo=UTC)) == [
        "daily-produce"]
    started_at(store, run["id"], datetime(2026, 11, 17, 15, 40, tzinfo=UTC))  # 00:40 the 18th
    assert schedule.due_runs(store, s, datetime(2026, 11, 17, 16, 0, tzinfo=UTC)) == []


def test_next_runs_today_or_tomorrow():
    s = cfg(agent_schedule="daily-produce@03:00,review@04:00")
    first, second = schedule.next_runs(s, NOW)  # 03:30 Paris
    assert first["next_at"].isoformat() == "2026-11-18T03:00:00+01:00"
    assert second["next_at"].isoformat() == "2026-11-17T04:00:00+01:00"
    assert second["time"] == "04:00"


def test_run_due_runs_each_in_turn(store, agent_dir):
    (agent_dir / "playbooks" / "review.md").write_text("Review.\n")
    s = cfg(agent_schedule="daily-produce@03:00,review@03:10")
    calls = []

    def fake_run(store_, settings, playbook):
        calls.append(playbook)
        if playbook == "review":
            raise runner.AgentRunRefused("started elsewhere")
        return {"playbook": playbook, "status": "succeeded"}

    rows = schedule.run_due(store, s, run=fake_run, now=lambda: NOW)
    assert calls == ["daily-produce", "review"] and rows == [
        {"playbook": "daily-produce", "status": "succeeded"}]
    assert schedule.run_due(store, cfg(agent_schedule=""), run=fake_run) == []


def test_cli_run_due_exit_codes(monkeypatch):
    from src import scheduler

    monkeypatch.setattr(scheduler, "get_settings", lambda: cfg())
    for rows, code in (([], 0), ([{"status": "succeeded"}], 0), ([{"status": "failed"}], 1)):
        monkeypatch.setattr(schedule, "run_due", lambda *a, rows=rows, **kw: rows)
        with pytest.raises(SystemExit) as e:
            scheduler.main(["agent", "run-due"])
        assert e.value.code == code


def test_catch_up_starts_detached_and_never_raises(store, agent_dir, capsys):
    s = cfg()
    started = []
    assert schedule.catch_up(store, s, start=lambda st, se, p: started.append(p),
                             now=lambda: NOW) == ["daily-produce"]
    assert started == ["daily-produce"]

    def refused(*a):
        raise runner.AgentRunRefused("already running")

    assert schedule.catch_up(store, s, start=refused, now=lambda: NOW) == []

    def broken():
        raise RuntimeError("database is locked")

    assert schedule.catch_up(store, s, start=refused, now=broken) == []
    assert "database is locked" in capsys.readouterr().err


async def test_catch_up_loop_repeats(store, agent_dir, monkeypatch):
    starts = []
    monkeypatch.setattr(schedule, "utcnow", lambda: NOW)
    task = asyncio.create_task(schedule.catch_up_loop(
        store, cfg(), interval=0.01, start=lambda st, se, p: starts.append(p)))
    for _ in range(100):
        await asyncio.sleep(0.01)
        if len(starts) >= 2:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert starts[:2] == ["daily-produce", "daily-produce"]  # fake starter writes no row


def test_windows_command():
    s = cfg(agent_schedule="daily-produce@03:00,review@14:30")
    cmd = schedule.windows_command(s, exe=r"C:\it's\python.exe", now=NOW)
    script = cmd[-1]
    assert cmd[:4] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
    assert "Unregister-ScheduledTask" in script.split("Register-ScheduledTask -TaskName")[0]
    assert script.count("-WakeToRun -StartWhenAvailable") == 2
    assert "-AtLogOn -User" in script and "-TaskName 'IGCampaignUp'" in script
    assert "-TaskName 'IGCampaignAgent-daily-produce'" in script
    assert "-TaskName 'IGCampaignAgent-review'" in script
    assert r"-Execute 'C:\it''s\python.exe'" in script
    assert "'-m src.scheduler up'" in script and "'-m src.scheduler agent run-due'" in script
    assert f"-WorkingDirectory '{runner.REPO}'" in script
    local = datetime(2026, 11, 17, 13, 30, tzinfo=UTC).astimezone()  # 14:30 Paris
    assert f"-Daily -At '{local.strftime('%Y-%m-%dT%H:%M:%S')}'" in script

    removed = schedule.windows_command(s, remove=True, now=NOW)[-1]
    assert "Unregister-ScheduledTask" in removed and "Register-ScheduledTask -TaskName" \
        not in removed and "'IGCampaignAgent-*'" in removed


def test_cron_block_and_in_place_replace():
    s = cfg(agent_schedule="daily-produce@03:00")
    block = schedule.cron_block(s, exe="/home/me/.venv/bin/python", now=NOW)
    at = datetime(2026, 11, 18, 2, 0, tzinfo=UTC).astimezone()
    lines = block.splitlines()
    assert lines[0] == "# ig-campaign begin" and lines[-1] == "# ig-campaign end"
    assert lines[1].startswith("@reboot cd ") and lines[1].endswith(
        "&& /home/me/.venv/bin/python -m src.scheduler up")
    assert lines[2].startswith(f"{at.minute} {at.hour} * * * cd ")
    assert lines[2].endswith(" agent run-due")

    mine = "MAILTO=me\n0 5 * * * backup\n"
    once = schedule.replace_block(mine, block)
    assert once == mine + block
    old = once.replace("agent run-due", "old")
    other = "# ig-campaign begin\nnew\n# ig-campaign end\n"
    assert schedule.replace_block(old + "1 1 * * * last", other) == (
        mine + other + "1 1 * * * last\n")  # in place, the rest kept
    assert schedule.replace_block(once, "") == mine  # --remove
    assert schedule.replace_block("", block) == block


class FakeRun:
    def __init__(self, crontab=None):
        self.calls, self.crontab = [], crontab

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if argv == ["crontab", "-l"]:
            return subprocess.CompletedProcess(argv, 0 if self.crontab is not None else 1,
                                               self.crontab or "", "no crontab for me")
        return subprocess.CompletedProcess(argv, 0)


def test_install_schedule_injected_runners():
    s = cfg()
    run = FakeRun()
    assert schedule.install_schedule(s, run=run, platform="win32").startswith("Task Sch")
    [(argv, kw)] = run.calls
    assert argv[0] == "powershell.exe" and kw["check"] is True

    run = FakeRun(crontab=None)  # no crontab yet
    schedule.install_schedule(s, run=run, platform="linux")
    assert run.calls[1][0] == ["crontab", "-"]
    assert run.calls[1][1]["input"].startswith("# ig-campaign begin\n@reboot")

    run = FakeRun(crontab="0 5 * * * backup\n" + schedule.cron_block(s))
    schedule.install_schedule(s, remove=True, run=run, platform="linux")
    assert run.calls[1][1]["input"] == "0 5 * * * backup\n"

    def unreadable(argv, **kw):  # never overwrite a crontab we could not read
        assert argv == ["crontab", "-l"]
        return subprocess.CompletedProcess(argv, 1, "", "crontab: Permission denied")

    with pytest.raises(subprocess.CalledProcessError):
        schedule.install_schedule(s, run=unreadable, platform="linux")


def test_schedule_route(store, agent_dir):
    s = cfg(agent_schedule="daily-produce@03:00,later@04:00")
    run = store.start_agent_run("daily-produce")
    store.finish_agent_run(run["id"], "succeeded")
    with TestClient(create_app(s, store=store), base_url=LOCAL,
                    headers={"Origin": LOCAL}) as tc:
        produce, later = tc.get("/api/agent/schedule").json()
    assert produce["playbook"] == "daily-produce" and produce["time"] == "03:00"
    assert produce["exists"] is True and later["exists"] is False
    assert produce["last_run"]["status"] == "succeeded" and later["last_run"] is None
    assert datetime.fromisoformat(produce["next_at"]) > datetime.now(UTC)


async def test_worker_starts_the_catch_up(monkeypatch):
    """Setup mode: the render loop and the catch-up run; both stop with the worker."""
    from src import scheduler

    seen = []

    async def fake_loop(store, settings):
        seen.append(settings.agent_schedule)
        await asyncio.sleep(3600)

    async def renders_done(store, settings):
        await asyncio.sleep(0.01)

    monkeypatch.setattr(schedule, "catch_up_loop", fake_loop)
    monkeypatch.setattr(scheduler.worker, "render_loop", renders_done)
    await scheduler._worker(cfg())
    assert seen == ["daily-produce@03:00"]
