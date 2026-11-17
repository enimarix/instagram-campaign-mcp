"""
The publishing worker (GOAL.md §3.3): `ig-campaign worker` (alias `daemon`) and `up` run it.

Every cycle writes a heartbeat, then runs `campaign.run_due` (pause switch, late-slot and
gap rules live there, so `run-due` and the MCP tool obey them too), then the data jobs
(data_jobs: publish-check reconcile, insight age schedule, DM picks, daily account
snapshot, followers online and the daily facts), and snapshots live Stories hourly. On Windows it
keeps one one-shot Task Scheduler task that wakes the PC a few minutes before the next
pending slot (its action, `run-due --wait-until-next`, holds the PC awake and publishes
even when no worker runs), and holds the PC awake itself from AWAKE_BEFORE a slot until the
run handled it; elsewhere that part does nothing.

render_loop() runs beside it (and alone in setup mode: renders need no Instagram): it
renders queued render jobs (src/studio/render.py) in threads, keeping the PC awake meanwhile,
starts none while the media disk is under MIN_FREE_DISK_GB, and runs the daily housekeeping
(src/studio/housekeeping.py: archive stale assets, purge old files, back up the database).
"""

from __future__ import annotations

import asyncio
import functools
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
from .learning import facts
from .store import CampaignStore, parse_dt, to_iso, utcnow
from .studio import dm_picks, housekeeping, power, render
from .studio.power import keep_awake
from .studio.publish import reconcile_publish_checks

logger = structlog.get_logger(__name__)

ALIVE_WITHIN = timedelta(minutes=3)
WAKE_TASK = "IGCampaignWake"
WAKE_LEAD = timedelta(minutes=5)
AWAKE_BEFORE = WAKE_LEAD + timedelta(minutes=5)  # the worker's hold starts this early
WAIT_MAX = timedelta(minutes=15)  # run-due --wait-until-next waits at most this long
REPORTED = ("published", "retrying", "failed", "recovered_stuck", "replanned")
# Publishing keeps priority: data jobs start nothing once this share of the hourly Graph
# budget (RATE_LIMIT_REQUESTS_PER_HOUR, shared by worker, API and MCP server) is used.
DATA_SHARE = 0.8
INSIGHTS_EVERY = timedelta(minutes=15)
RECONCILE_EVERY = timedelta(minutes=10)  # it lists media while an asset waits for a check
DM_PICKS_EVERY = timedelta(minutes=15)  # Reels pinned accounts sent by DM (step 113)
DAILY_RETRY = timedelta(hours=1)  # a failing daily job (e.g. no insights permission) waits
RENDER_TICK = 5.0  # s between queue polls and job heartbeats
RENDER_STALE = timedelta(minutes=10)  # a running job without heartbeat this long is re-queued
DISK_WARN_EVERY = 3600.0  # s between "disk too full" messages


def next_slot(store: CampaignStore) -> Optional[str]:
    """publish_at of the earliest pending post (ISO UTC), or None."""
    rows = store.list_scheduled("pending", limit=1)
    return rows[0]["publish_at"] if rows else None


def slot_near(store: CampaignStore, settings: InstagramMCPSettings, now: datetime) -> bool:
    """The next pending post is due within AWAKE_BEFORE, or overdue but not yet late (the
    next run publishes it). Paused: never (overdue posts then wait indefinitely)."""
    slot = next_slot(store)
    if slot is None or is_paused(store, settings):
        return False
    at = parse_dt(slot)
    return now - timedelta(minutes=settings.max_late_minutes) <= at <= now + AWAKE_BEFORE


def hold_for_slot(store: CampaignStore, settings: InstagramMCPSettings, now: datetime,
                  held: bool) -> bool:
    """Take or drop the worker's keep-awake hold for a near slot; returns whether it is held."""
    try:
        near = slot_near(store, settings, now)
    except Exception as e:  # noqa: BLE001 - e.g. database locked: keep the hold as it is
        print(f"slot hold check failed: {e!r}", file=sys.stderr, flush=True)
        return held
    if near and not held:
        power.hold()
    elif held and not near:
        power.release()
    return near


async def run_due_after_wait(client: InstagramClient, store: CampaignStore,
                             settings: InstagramMCPSettings,
                             now: Callable[[], datetime] = utcnow,
                             sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
                             max_wait: timedelta = WAIT_MAX) -> Dict[str, Any]:
    """The wake task's action: keep the PC awake, wait for the next pending slot when it is
    due within max_wait (else don't wait), then run_due once. A running worker may publish
    the same post meanwhile: claims are atomic, so only one of them does."""
    with power.keep_awake():
        slot = next_slot(store)
        wait = (parse_dt(slot) - now()).total_seconds() if slot else None
        waited = wait if wait is not None and 0 < wait <= max_wait.total_seconds() else 0
        if waited:
            await sleep(waited + 1)  # +1 s: a timer may fire a little early on Windows
        return {**await run_due(client, store, settings=settings, now=now), "waited_s": waited}


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
    jobs run once per owner-local day, retried hourly until they succeed. A job's error is
    reported in the result, never raised."""
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
    if _every(store, "dm_picks_at", DM_PICKS_EVERY, t):
        await job("dm_picks", lambda: dm_picks.poll_dm_picks(
            client, store, budget_left=lambda: data_budget_left(client)))

    async def daily_facts() -> Dict[str, Any]:  # after the snapshots: yesterday's facts
        return {"report_date": (await facts.build_and_store(store, settings, client, t))
                ["report_date"]}

    for key, make in (("account_day", lambda: snapshot_account(client, store, today)),
                      ("online_followers_day",
                       lambda: collect_online_followers(client, store, today)),
                      ("facts_day", daily_facts)):
        if (store.get_state(key) != today.isoformat()
                and _every(store, f"{key}_tried_at", DAILY_RETRY, t) and await job(key, make)):
            store.set_state(key, today.isoformat())
    return out


async def run(client: InstagramClient, store: CampaignStore, settings: InstagramMCPSettings,
              interval: int = 60, stories_every: int = 60) -> None:
    """Publish due posts every `interval` s and snapshot live Stories; runs until cancelled."""
    last_stories = float("-inf")
    woken_for = None
    held = False
    try:
        while True:
            result = await cycle(client, store, settings)
            if result.get("error") or any(result.get(k) for k in REPORTED):
                print(json.dumps(result), flush=True)
            # stay awake from AWAKE_BEFORE a slot until a run handled it
            held = hold_for_slot(store, settings, utcnow(), held)
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
    finally:
        if held:
            power.release()


def daily_housekeeping(store: CampaignStore, settings: InstagramMCPSettings,
                       now: Callable[[], datetime] = utcnow) -> Optional[Dict[str, Any]]:
    """Archive, purge and back up once per owner-local day; a failure raises and is retried
    at most hourly. Returns what was done, or None when nothing was due."""
    t = now()
    today = t.astimezone(ZoneInfo(settings.timezone)).date()
    if (store.get_state("housekeeping_day") == today.isoformat()
            or not _every(store, "housekeeping_tried_at", DAILY_RETRY, t)):
        return None
    out = {"archived": housekeeping.archive_stale(store, settings, today),
           "purged": housekeeping.purge_archived_files(store, settings, today),
           "backup": housekeeping.backup_database(store, settings, t)}
    store.set_state("housekeeping_day", today.isoformat())
    return out


async def render_loop(store: CampaignStore, settings: InstagramMCPSettings,
                      run: Optional[Callable[[Dict[str, Any]], Any]] = None,
                      interval: float = RENDER_TICK, stale_after: timedelta = RENDER_STALE
                      ) -> None:
    """Render queued jobs, up to settings.render_concurrency at once, each in a thread so
    the loop stays responsive; heartbeat running jobs; keep the PC awake while any runs;
    claim nothing while the media disk is under the floor; run daily_housekeeping between
    batches. Runs until cancelled (a job cut off then is re-queued once its heartbeat is
    stale)."""
    run = run or functools.partial(render.run_job, store, settings.media_root)
    running: Dict[int, asyncio.Task] = {}
    disk_warned = float("-inf")

    def claim() -> None:
        nonlocal disk_warned
        try:
            store.touch_render_jobs(list(running))
            if not housekeeping.disk_ok(settings):
                if time.monotonic() - disk_warned >= DISK_WARN_EVERY:
                    disk_warned = time.monotonic()
                    print(f"render queue: less than {settings.min_free_disk_gb} GB free on the"
                          " media disk; no render starts", file=sys.stderr, flush=True)
                return
            free = settings.render_concurrency - len(running)
            for job in store.claim_render_jobs(free, stale_before=utcnow() - stale_after):
                running[job["id"]] = asyncio.create_task(asyncio.to_thread(run, job))
        except Exception as e:  # noqa: BLE001 - e.g. database locked: try next tick
            print(f"render queue: {e!r}", file=sys.stderr, flush=True)

    housekeeper: Optional[asyncio.Task] = None
    try:
        while True:
            # shielded: a thread can't be cancelled, so the task must stay awaitable below
            housekeeper = asyncio.create_task(
                asyncio.to_thread(daily_housekeeping, store, settings))
            try:
                done_today = await asyncio.shield(housekeeper)
                if done_today:
                    print(json.dumps({"housekeeping": done_today}), flush=True)
            except Exception as e:  # noqa: BLE001 - retried within the hour
                print(f"housekeeping failed: {e!r}", file=sys.stderr, flush=True)
            claim()
            if running:
                with keep_awake():
                    while running:
                        done, _ = await asyncio.wait(running.values(), timeout=interval)
                        for job_id, task in list(running.items()):
                            if task in done:
                                del running[job_id]
                                if task.exception():
                                    print(f"render job {job_id} failed: {task.exception()!r}",
                                          file=sys.stderr, flush=True)
                        claim()
            await asyncio.sleep(interval)
    finally:
        # Cancelled: threads still running housekeeping or renders use the store, which the
        # caller closes next. Let them finish (asyncio.run would wait for them anyway); a
        # render then saves its result instead of being re-queued as stale.
        pending = [t for t in (housekeeper, *running.values()) if t and not t.done()]
        if pending:
            await asyncio.wait(pending)
        for t in pending:
            if not t.cancelled() and t.exception():
                print(f"worker thread failed during shutdown: {t.exception()!r}",
                      file=sys.stderr, flush=True)


def status(store: CampaignStore, settings: InstagramMCPSettings,
           now: Callable[[], datetime] = utcnow) -> Dict[str, Any]:
    heartbeat = store.get_state("heartbeat_at")
    return {
        "heartbeat_at": heartbeat,
        "alive": heartbeat is not None and now() - parse_dt(heartbeat) < ALIVE_WITHIN,
        "paused": is_paused(store, settings),
        "next_slot": next_slot(store),
        "last_result": store.get_state("last_result"),
        "disk_ok": housekeeping.disk_ok(settings),
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
    machine's local time; its action runs `ig-campaign run-due --wait-until-next` (via
    `exe -m src.scheduler`), which keeps the PC awake until the slot and publishes."""
    at = (slot - WAKE_LEAD).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
    script = (
        f"$a = New-ScheduledTaskAction -Execute {_ps(exe)} -Argument "
        "'-m src.scheduler run-due --wait-until-next'; "
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
