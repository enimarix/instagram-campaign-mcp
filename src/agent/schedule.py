"""Scheduled agent runs and autostart (061).

AGENT_SCHEDULE (`playbook@HH:MM,...`, owner-local TIMEZONE) says when each playbook runs;
`playbook@mon 04:00` runs weekly, on that weekday only (096). due_runs() is the one place
that decides: a playbook is due once its time today has passed (on its weekday, if it has
one), it has no run started today, it isn't running and its file exists. Three callers:

- `ig-campaign agent run-due` (the OS tasks' action): runs each due playbook in turn;
- the `up` / `worker` process: catch_up() at start and every CATCH_UP_EVERY, starting due
  runs detached (a run missed while the PC was off starts at the next logon, same day),
  and the light run the owner's scheduled work orders ask for (order_run, 136);
- the website's Settings page: overview() (next and last run per playbook).

install_schedule() registers the OS side: on Windows a logon task for `up` and one daily
(or weekly) task per playbook that wakes the PC (-WakeToRun -StartWhenAvailable);
elsewhere a crontab block between markers (`@reboot ... up`, `M H * * D|* ... agent
run-due`). A weekly run missed while the PC was off waits for the next week.
"""

from __future__ import annotations

import asyncio
import re
import shlex
import subprocess
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import structlog

from ..config import InstagramMCPSettings
from ..store import CampaignStore, parse_iso, to_iso, utcnow
from ..studio import work_orders
from .packet import RUNS
from .runner import (
    AGENT_DIR,
    PLAYBOOK_NAME,
    REPO,
    AgentError,
    AgentRunRefused,
    _playbook_file,
    check_lock,
    preflight,
    run_agent,
)

logger = structlog.get_logger(__name__)

CATCH_UP_EVERY = 60.0  # s: a work order's run starts within a minute of its debounce
ORDER_PLAYBOOK = "daily-revise"  # the light run (packet.RUNS)
ORDER_READERS = tuple(p for p, (_, s) in RUNS.items() if s and "work_orders" in s)
ORDER_RETRY = timedelta(minutes=10)  # a failed preflight is asked again after this
UP_TASK = "IGCampaignUp"
AGENT_TASK = "IGCampaignAgent-"  # + playbook
CRON_BEGIN, CRON_END = "# ig-campaign begin", "# ig-campaign end"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # datetime.weekday() order
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_ENTRY = re.compile(rf"^([^@\s]+)@(?:({'|'.join(DAYS)}) )?([01]\d|2[0-3]):([0-5]\d)$")


def parse_schedule(value: str) -> List[Tuple[str, time, Optional[int]]]:
    """`daily-produce@03:00, weekly-ads@mon 04:00` -> [(playbook, time, weekday 0=Monday
    or None = daily)]; ValueError when malformed."""
    out = []
    for part in filter(None, (p.strip() for p in value.split(","))):
        m = _ENTRY.match(part)
        if not m or not PLAYBOOK_NAME.match(m[1]):
            raise ValueError(f"bad agent schedule entry {part!r} (want playbook@HH:MM or "
                             "playbook@mon HH:MM)")
        out.append((m[1], time(int(m[3]), int(m[4])), DAYS.index(m[2]) if m[2] else None))
    if len({p for p, _, _ in out}) != len(out):
        raise ValueError("a playbook appears twice in the agent schedule")
    return out


def _local(settings: InstagramMCPSettings, now: datetime) -> datetime:
    return now.astimezone(ZoneInfo(settings.timezone))


def due_runs(store: CampaignStore, settings: InstagramMCPSettings, now: datetime, *,
             agent_dir: Optional[Path] = None) -> List[str]:
    """Playbooks to start now, in schedule order (see module doc). Closes a stale `running`
    row on the way (check_lock), so a crashed run doesn't block the schedule forever."""
    local = _local(settings, now)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    due = []
    for playbook, at, weekday in parse_schedule(settings.agent_schedule):
        if local.time() < at or weekday not in (None, local.weekday()):
            continue
        last = store.list_agent_runs(playbook, limit=1)
        if last and parse_iso(last[0]["started_at"]) >= day_start:
            continue
        try:
            check_lock(store, playbook, settings.agent_timeout_minutes * 60)
            _playbook_file(playbook, agent_dir or AGENT_DIR)
        except AgentRunRefused:
            continue
        except AgentError:
            logger.info("agent_playbook_missing", playbook=playbook)
            continue
        due.append(playbook)
    return due


def next_runs(settings: InstagramMCPSettings, now: datetime) -> List[Dict[str, Any]]:
    """[{playbook, time 'HH:MM' (weekly: 'mon HH:MM') owner-local, weekly, next_at aware
    owner-local datetime}]."""
    local = _local(settings, now)
    out = []
    for playbook, at, weekday in parse_schedule(settings.agent_schedule):
        ahead = 0 if weekday is None else (weekday - local.weekday()) % 7
        if ahead == 0 and local.time() >= at:
            ahead = 1 if weekday is None else 7
        out.append({"playbook": playbook, "weekly": weekday is not None,
                    "time": (f"{DAYS[weekday]} " if weekday is not None else "")
                    + at.strftime("%H:%M"),
                    "next_at": datetime.combine(local.date() + timedelta(days=ahead), at,
                                                tzinfo=local.tzinfo)})
    return out


def overview(store: CampaignStore, settings: InstagramMCPSettings, now: datetime, *,
             agent_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """The Settings page row: each playbook's next run (ISO), whether its file exists, and
    its last run, if any."""
    out = []
    for r in next_runs(settings, now):
        last = store.list_agent_runs(r["playbook"], limit=1)
        exists = ((agent_dir or AGENT_DIR) / "playbooks" / f"{r['playbook']}.md").is_file()
        out.append({**r, "next_at": r["next_at"].isoformat(), "exists": exists,
                    "last_run": {k: last[0][k] for k in ("id", "status", "started_at",
                                                         "finished_at")} if last else None})
    return out


def run_due(store: CampaignStore, settings: InstagramMCPSettings, *,
            run: Callable[..., Dict[str, Any]] = run_agent,
            now: Callable[[], datetime] = utcnow) -> List[Dict[str, Any]]:
    """`agent run-due`: each due playbook in the foreground, one after another. A playbook
    another process started meanwhile is skipped."""
    rows = []
    for playbook in due_runs(store, settings, now()):
        try:
            rows.append(run(store, settings, playbook))
        except AgentRunRefused:
            continue
    return rows


def order_run(store: CampaignStore, settings: InstagramMCPSettings, now: datetime, *,
              start: Callable[..., Any], check: Optional[Callable[..., Any]] = None
              ) -> Optional[str]:
    """136: the owner's scheduled work orders start the light run (ORDER_PLAYBOOK) at once.
    Returns it when started, else None. It starts when the newest scheduled order is
    ORDER_RUN_DEBOUNCE_MINUTES old (sends batch into one run), no run that reads work
    orders started since (it has them) or still runs (one run at a time), fewer than
    MAX_ORDER_RUNS_PER_DAY order runs started today (owner-local), and the agent preflight
    passes (asked again ORDER_RETRY after a failure). Otherwise the orders keep waiting and
    their blocked_reason says why when it is the cap, the preflight or the playbook."""
    with store._tx() as c:
        newest = c.execute("SELECT MAX(scheduled_at) FROM work_orders"
                           " WHERE status='scheduled'").fetchone()[0]
    if newest is None:
        return None
    newest = parse_iso(newest)
    if now - newest < timedelta(minutes=settings.order_run_debounce_minutes):
        return None
    started = store.get_state("order_run_started_at")  # before its own row exists
    if started and parse_iso(started) >= newest:
        return None
    for playbook in ORDER_READERS:
        last = store.list_agent_runs(playbook, limit=1)
        if last and parse_iso(last[0]["started_at"]) >= newest:
            return None
        try:
            check_lock(store, playbook, settings.agent_timeout_minutes * 60)
        except AgentRunRefused:
            return None
    day = _local(settings, now).date().isoformat()
    used = store.get_state("order_runs") or {}
    count = used.get("count", 0) if used.get("day") == day else 0
    if count >= settings.max_order_runs_per_day:
        work_orders.set_blocked(store, f"today's {settings.max_order_runs_per_day} at-once"
                                " runs are used: it waits for the next scheduled run")
        return None
    failed = store.get_state("order_preflight_failed_at")
    if failed and now - parse_iso(failed) < ORDER_RETRY:
        return None
    # ponytail: the preflight (`claude auth status`, ~1 s) blocks the worker's loop once
    # per order run; move it to a thread if it ever gets slow.
    try:
        (check or preflight)(settings)  # looked up per call: tests patch it
        start(store, settings, ORDER_PLAYBOOK)
    except AgentRunRefused:
        return None
    except AgentError as e:  # the CLI is missing or signed out, or no such playbook
        store.set_state("order_preflight_failed_at", to_iso(now))
        work_orders.set_blocked(store, f"the agent cannot start: {e}")
        return None
    store.set_state("order_preflight_failed_at", None)
    store.set_state("order_run_started_at", to_iso(now))
    store.set_state("order_runs", {"day": day, "count": count + 1})
    work_orders.set_blocked(store, None)
    return ORDER_PLAYBOOK


def catch_up(store: CampaignStore, settings: InstagramMCPSettings, *,
             start: Optional[Callable[..., Any]] = None,
             now: Optional[Callable[[], datetime]] = None) -> List[str]:
    """Start each due playbook detached (runs.start_run), then the work orders' run if they
    need one (order_run). Never raises: the worker lives."""
    from .runs import start_run

    now = now or utcnow  # looked up per call (a default argument would freeze it)

    started = []
    try:
        for playbook in due_runs(store, settings, now()):
            try:
                (start or start_run)(store, settings, playbook)
                started.append(playbook)
            except AgentError as e:
                print(f"agent catch-up: {e}", file=sys.stderr, flush=True)
        if order_run(store, settings, now(), start=start or start_run):
            started.append(ORDER_PLAYBOOK)
    except Exception as e:  # noqa: BLE001 - e.g. database locked: next tick
        print(f"agent catch-up failed: {e!r}", file=sys.stderr, flush=True)
    if started:
        print(f"agent catch-up: started {', '.join(started)}", file=sys.stderr, flush=True)
    return started


async def catch_up_loop(store: CampaignStore, settings: InstagramMCPSettings,
                        interval: float = CATCH_UP_EVERY,
                        start: Optional[Callable[..., Any]] = None) -> None:
    """The worker's side: catch_up now, then every `interval` s, until cancelled. In the
    loop thread: it takes milliseconds, and no thread may still use the store at close."""
    while True:
        catch_up(store, settings, start=start)
        await asyncio.sleep(interval)


# --- OS registration ---------------------------------------------------------------------

def windows_command(settings: InstagramMCPSettings, *, remove: bool = False,
                    exe: str = sys.executable, now: Optional[datetime] = None) -> List[str]:
    """PowerShell that drops every IGCampaign* schedule task, then (unless remove) registers
    the logon task for `up` and one daily, PC-waking task per scheduled playbook. Current
    user, no admin; runs on battery too (a laptop is the studio)."""
    from ..worker import _ps  # here: config's validator imports this module, keep it light

    def action(args: str) -> str:
        return (f"New-ScheduledTaskAction -Execute {_ps(exe)} -Argument "
                f"{_ps('-m src.scheduler ' + args)} -WorkingDirectory {_ps(str(REPO))}")

    battery = "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries"
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$old = @(Get-ScheduledTask -TaskName {_ps(UP_TASK)}, {_ps(AGENT_TASK + '*')} "
        "-ErrorAction SilentlyContinue)",
        "if ($old) { $old | Unregister-ScheduledTask -Confirm:$false }",
    ]
    if not remove:
        lines += [
            f"$a = {action('up')}",
            "$t = New-ScheduledTaskTrigger -AtLogOn -User ($env:USERDOMAIN + '\\' + $env:USERNAME)",
            # no 72 h limit: `up` runs until logoff
            f"$s = New-ScheduledTaskSettingsSet {battery} -ExecutionTimeLimit ([TimeSpan]::Zero)",
            f"Register-ScheduledTask -TaskName {_ps(UP_TASK)} -Action $a -Trigger $t -Settings $s"
            " -Force | Out-Null",
        ]
        for r in next_runs(settings, now or utcnow()):
            at = r["next_at"].astimezone()  # the OS uses this machine's clock
            when = (f"-Weekly -DaysOfWeek {DAY_NAMES[at.weekday()]}" if r["weekly"]
                    else "-Daily")
            lines += [
                f"$a = {action('agent run-due')}",
                f"$t = New-ScheduledTaskTrigger {when} -At "
                f"{_ps(at.strftime('%Y-%m-%dT%H:%M:%S'))}",
                f"$s = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable {battery}",
                f"Register-ScheduledTask -TaskName {_ps(AGENT_TASK + r['playbook'])} -Action $a"
                " -Trigger $t -Settings $s -Force | Out-Null",
            ]
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "; ".join(lines)]


def cron_block(settings: InstagramMCPSettings, *, exe: str = sys.executable,
               now: Optional[datetime] = None) -> str:
    cmd = f"cd {shlex.quote(str(REPO))} && {shlex.quote(exe)} -m src.scheduler"
    lines = [CRON_BEGIN, f"@reboot {cmd} up"]
    for r in next_runs(settings, now or utcnow()):
        at = r["next_at"].astimezone()  # the OS uses this machine's clock
        dow = (at.weekday() + 1) % 7 if r["weekly"] else "*"  # cron: 0 = Sunday
        lines.append(f"{at.minute} {at.hour} * * {dow} {cmd} agent run-due")
    return "\n".join([*lines, CRON_END]) + "\n"


def replace_block(crontab: str, block: str) -> str:
    """The user's crontab with our marker block replaced in place (appended when absent;
    an empty block removes it). Every other line is kept."""
    if crontab and not crontab.endswith("\n"):
        crontab += "\n"
    lines = crontab.splitlines(keepends=True)
    if CRON_BEGIN + "\n" in lines and CRON_END + "\n" in lines:
        i = lines.index(CRON_BEGIN + "\n")
        j = lines.index(CRON_END + "\n", i)
        return "".join(lines[:i]) + block + "".join(lines[j + 1:])
    return crontab + block


def install_schedule(settings: InstagramMCPSettings, *, remove: bool = False,
                     run: Callable[..., Any] = subprocess.run,
                     platform: str = sys.platform) -> str:
    """Register (or with remove, drop) the OS tasks; returns what was done. Raises
    subprocess.CalledProcessError / OSError when the OS command fails."""
    if platform == "win32":
        run(windows_command(settings, remove=remove), check=True, capture_output=True,
            timeout=60)
        return "Task Scheduler: " + ("removed" if remove else
                                    f"{UP_TASK} at logon, {AGENT_TASK}<playbook> daily or weekly")
    current = run(["crontab", "-l"], capture_output=True, text=True, timeout=60)
    if current.returncode and "no crontab" not in current.stderr:  # never overwrite blind
        raise subprocess.CalledProcessError(current.returncode, "crontab -l",
                                            current.stdout, current.stderr)
    old = "" if current.returncode else current.stdout
    run(["crontab", "-"], input=replace_block(old, "" if remove else cron_block(settings)),
        text=True, check=True, timeout=60)
    return "crontab: " + ("removed" if remove else "@reboot up, daily agent run-due")
