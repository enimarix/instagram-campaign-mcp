"""
The publishing worker (GOAL.md §3.3): `ig-campaign worker` (alias `daemon`) and `up` run it.

Every cycle writes a heartbeat, then runs `campaign.run_due` (pause switch, late-slot and
gap rules live there, so `run-due` and the MCP tool obey them too) and snapshots live
Stories hourly. On Windows it keeps one one-shot Task Scheduler task that wakes the PC a
few minutes before the next pending slot; elsewhere that part does nothing.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import structlog

from .campaign import collect_insights, is_paused, run_due
from .config import InstagramMCPSettings
from .instagram_client import InstagramClient
from .store import CampaignStore, parse_dt, to_iso, utcnow

logger = structlog.get_logger(__name__)

ALIVE_WITHIN = timedelta(minutes=3)
WAKE_TASK = "IGCampaignWake"
WAKE_LEAD = timedelta(minutes=5)
REPORTED = ("published", "retrying", "failed", "recovered_stuck", "replanned")


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


async def run(client: InstagramClient, store: CampaignStore, settings: InstagramMCPSettings,
              interval: int = 60, stories_every: int = 60) -> None:
    """Publish due posts every `interval` s and snapshot live Stories; runs until cancelled."""
    last_stories = float("-inf")
    woken_for = None
    while True:
        result = await cycle(client, store, settings)
        if result.get("error") or any(result.get(k) for k in REPORTED):
            print(json.dumps(result), flush=True)
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
