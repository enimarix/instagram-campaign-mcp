"""
The publishing worker (GOAL.md §3.3): `ig-campaign worker` (alias `daemon`) and `up` run it.

Every cycle writes a heartbeat, then runs `campaign.run_due` (pause switch, late-slot and
gap rules live there, so `run-due` and the MCP tool obey them too), then the data jobs
(data_jobs: publish-check reconcile, insight age schedule, daily account snapshot and
followers online) and snapshots live Stories hourly. On Windows it keeps one one-shot Task Scheduler task that wakes the PC a
few minutes before the next pending slot; elsewhere that part does nothing.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

import structlog

from .campaign import (
    collect_due_insights,
    collect_insights,
    collect_online_followers,
    is_paused,
    run_due,
    snapshot_account,
)
from .config import InstagramMCPSettings
from .instagram_client import InstagramClient
from .store import CampaignStore, parse_dt, to_iso, utcnow
from .studio.publish import reconcile_publish_checks

logger = structlog.get_logger(__name__)

ALIVE_WITHIN = timedelta(minutes=3)
WAKE_TASK = "IGCampaignWake"
WAKE_LEAD = timedelta(minutes=5)
REPORTED = ("published", "retrying", "failed", "recovered_stuck", "replanned")
# Publishing keeps priority: data jobs start nothing once this share of the hourly Graph
# budget (RATE_LIMIT_REQUESTS_PER_HOUR, shared by worker, API and MCP server) is used.
DATA_SHARE = 0.8
INSIGHTS_EVERY = timedelta(minutes=15)
RECONCILE_EVERY = timedelta(minutes=10)  # it lists media while an asset waits for a check


def next_slot(store: CampaignStore) -> Optional[str]:
    """publish_at of the earliest pending post (ISO UTC), or None."""
    rows = store.list_scheduled("pending", limit=1)
    return rows[0]["publish_at"] if rows else None


async def cycle(client: InstagramClient, store: CampaignStore, settings: InstagramMCPSettings,
                now: Callable[[], datetime] = utcnow) -> Dict[str, Any]:
    """One worker pass: heartbeat, then run_due. Never raises (the loop must live)."""
    try:
        store.set_state("heartbeat_at", to_iso(now()))
        result = await run_due(client, store, settings=settings, now=now)
    except Exception as e:  # noqa: BLE001 - keep the worker alive
        print(f"run_due failed: {e!r}", file=sys.stderr, flush=True)
        result = {"error": repr(e)}
    try:
        store.set_state("last_run_at", to_iso(now()))
        store.set_state("last_result", result)
    except Exception as e:  # noqa: BLE001 - e.g. database locked for too long
        print(f"worker state not saved: {e!r}", file=sys.stderr, flush=True)
    return result


def data_budget_left(client: InstagramClient) -> bool:
    return client.budget.used() < client.budget.per_hour * DATA_SHARE


def _every(store: CampaignStore, key: str, period: timedelta, now: datetime) -> bool:
    """True (and the time is recorded) when the job last ran `period` ago or never."""
    last = store.get_state(key)
    if last is not None and now - parse_dt(last) < period:
        return False
    store.set_state(key, to_iso(now))
    return True


async def data_jobs(client: InstagramClient, store: CampaignStore,
                    settings: InstagramMCPSettings,
                    now: Callable[[], datetime] = utcnow) -> Dict[str, Any]:
    """The scheduled Graph reads, each skipped while the budget is past DATA_SHARE. Daily
    jobs run once per owner-local day and retry next tick until they succeed. Never raises."""
    t = now()
    today = t.astimezone(ZoneInfo(settings.timezone)).date()
    out: Dict[str, Any] = {}

    async def job(name: str, make: Callable[[], Awaitable[Any]]) -> bool:
        if not data_budget_left(client):
            out[name] = "skipped: request budget"
            return False
        try:
            out[name] = await make()
            return True
        except Exception as e:  # noqa: BLE001 - one failing job must not stop the others
            out[name] = {"error": repr(e)}
            return False

    if _every(store, "reconcile_at", RECONCILE_EVERY, t):
        await job("reconcile", lambda: reconcile_publish_checks(client, store))
    if _every(store, "insights_at", INSIGHTS_EVERY, t):
        await job("insights", lambda: collect_due_insights(client, store, t,
                                                           lambda: data_budget_left(client)))
    for key, make in (("account_day", lambda: snapshot_account(client, store, today)),
                      ("online_followers_day",
                       lambda: collect_online_followers(client, store, today))):
        if store.get_state(key) != today.isoformat() and await job(key, make):
            store.set_state(key, today.isoformat())
    return out


async def run(client: InstagramClient, store: CampaignStore, settings: InstagramMCPSettings,
              interval: int = 60, stories_every: int = 60) -> None:
    """Publish due posts every `interval` s and snapshot live Stories; runs until cancelled."""
    last_stories = float("-inf")
    woken_for = None
    while True:
        result = await cycle(client, store, settings)
        if result.get("error") or any(result.get(k) for k in REPORTED):
            print(json.dumps(result), flush=True)
        try:
            jobs = await data_jobs(client, store, settings)
            if jobs:
                print(json.dumps({"data_jobs": jobs}, default=str), flush=True)
        except Exception as e:  # noqa: BLE001 - e.g. database locked for too long
            print(f"data jobs failed: {e!r}", file=sys.stderr, flush=True)
        slot = next_slot(store)
        if slot and slot != woken_for and parse_dt(slot) > utcnow():  # queue changed
            woken_for = slot
            await asyncio.to_thread(register_wake, parse_dt(slot))
        if stories_every and time.monotonic() - last_stories >= stories_every * 60:
            last_stories = time.monotonic()
            try:
                await collect_insights(client, store, limit=0)
            except Exception as e:  # noqa: BLE001
                print(f"story snapshot failed: {e!r}", file=sys.stderr, flush=True)
        await asyncio.sleep(interval)


def status(store: CampaignStore, settings: InstagramMCPSettings,
           now: Callable[[], datetime] = utcnow) -> Dict[str, Any]:
    heartbeat = store.get_state("heartbeat_at")
    return {
        "heartbeat_at": heartbeat,
        "alive": heartbeat is not None and now() - parse_dt(heartbeat) < ALIVE_WITHIN,
        "paused": is_paused(store, settings),
        "next_slot": next_slot(store),
        "last_result": store.get_state("last_result"),
    }


def set_paused(store: CampaignStore, settings: InstagramMCPSettings,
               paused: bool) -> Dict[str, Any]:
    store.set_state("paused", paused)
    return status(store, settings)


def _ps(s: str) -> str:
    """A PowerShell single-quoted string."""
    return "'" + s.replace("'", "''") + "'"


def wake_task_command(slot: datetime, exe: str = sys.executable) -> List[str]:
    """PowerShell that (re)registers the one-shot wake task WAKE_LEAD before `slot`, in this
    machine's local time; its action runs `ig-campaign run-due` (via `exe -m src.scheduler`)."""
    at = (slot - WAKE_LEAD).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
    script = (
        f"$a = New-ScheduledTaskAction -Execute {_ps(exe)} -Argument '-m src.scheduler run-due'; "
        f"$t = New-ScheduledTaskTrigger -Once -At {_ps(at)}; "
        "$s = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable; "
        f"Register-ScheduledTask -TaskName {_ps(WAKE_TASK)} -Action $a -Trigger $t -Settings $s"
        " -Force | Out-Null"
    )
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]


def register_wake(slot: datetime, run: Callable[..., Any] = subprocess.run) -> bool:
    """Windows only; a failure is logged, never raised. True when the task was registered."""
    if sys.platform != "win32":
        return False
    try:
        run(wake_task_command(slot), check=True, capture_output=True, timeout=60)
    except Exception as e:  # noqa: BLE001 - publishing works without it while the PC is awake
        logger.warning("wake_task_failed", error=repr(e))
        return False
    return True
