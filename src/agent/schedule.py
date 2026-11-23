"""Scheduled agent runs and autostart (061).

AGENT_SCHEDULE (`playbook@HH:MM,...`, owner-local TIMEZONE) says when each playbook runs;
`playbook@mon 04:00` runs weekly, on that weekday only (096). due_runs() is the one place
that decides: a playbook is due once its time today has passed (on its weekday, if it has
one), it has no run started today, it isn't running and its file exists. Three callers:

- `ig-campaign agent run-due` (the OS tasks' action): runs each due playbook in turn;
- the `up` / `worker` process: catch_up() after the startup grace and every CATCH_UP_EVERY,
  starting due runs detached one at a time, each once the last run and its renders are done
  (166) (a run missed while the PC was off starts after the next logon, same day),
  and the light run the owner's scheduled work orders (136) and change requests (147) ask
  for, or new capability re-wakes (156) (order_run), then the check run of finished
  renders (188c, check_run); before those, the Lemo-Opuscar order
  at the head of the heavy line (studio/line.py, 186) goes to the film runner (film_run,
  173), even while renders wait behind it;
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
from ..studio import checks, line, styles, work_orders
from . import film
from .packet import RUNS
from .runner import (
    AGENT_DIR,
    DEAD_RUN,
    PLAYBOOK_NAME,
    REPO,
    AgentError,
    AgentRunRefused,
    _playbook_file,
    check_lock,
    close_dead_runs,
    preflight,
    run_agent,
)

logger = structlog.get_logger(__name__)

CATCH_UP_EVERY = 60.0  # s: a work order's run starts within a minute of its debounce
ORDER_PLAYBOOK = "daily-revise"  # the light run (packet.RUNS)
# the runs that see orders or change requests: one started after the newest has them
ORDER_READERS = tuple(p for p, (_, s) in RUNS.items()
                      if s and ("work_orders" in s or "revisions" in s))
# the newest thing the light run is for: a scheduled order, or a wanting-changes comment
# (written or edited by the owner; the agent's digest doesn't touch updated_at) on an asset
# still `revision_requested` (147). MAX skips NULLs; both columns are to_iso(). Lemo-Opuscar
# orders are the film runner's (173), never the light run's.
_AGENT_ORDER = "status = 'scheduled' AND substr(COALESCE(style, ''), 1, 5) <> 'lemo:'"
_NEWEST_WORK = (
    "SELECT MAX(t) FROM (SELECT MAX(scheduled_at) AS t FROM work_orders"
    f" WHERE {_AGENT_ORDER}"
    " UNION ALL SELECT MAX(f.updated_at) FROM feedback f JOIN assets a ON a.id = f.asset_id"
    " WHERE f.wants_changes = 1 AND a.status = 'revision_requested')")
# 156: something the light run would look at again when the studio can make more
_WAITING = ("SELECT EXISTS (SELECT 1 FROM assets WHERE status = 'revision_requested')"
            f" OR EXISTS (SELECT 1 FROM work_orders WHERE {_AGENT_ORDER})")
# what catch_up starts first: the Lemo film at the head of the line (186: heavy work by
# arrival, not after the runs), else a due playbook, else the light run for the orders,
# else the check run for finished renders (188c); the Planning page (185) lists them in
# this order
CATCH_UP_ORDER = ("film", "playbook", "orders", "checks")
CAPABILITIES_KEY = "style_capabilities"  # worker_state: {styles, gained_at}
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
    another process started meanwhile is skipped. Nothing while the studio is paused
    (line.pause, checked before each one): the runs stay due for the catch-up."""
    rows = []
    for playbook in due_runs(store, settings, now()):
        if line.paused(store):
            break
        try:
            rows.append(run(store, settings, playbook))
        except AgentRunRefused:
            continue
    return rows


def capability_gained(store: CampaignStore, now: datetime) -> Optional[datetime]:
    """When the studio last gained capability (156): an enabled style or a template it did
    not have (styles.capabilities, compared with the copy in worker_state). The first look
    only records it; a style turned off changes the copy, not the time; no Node: the last
    known time. None: never.
    ponytail: the registry is cached per process (motion.list_templates), so a new template
    counts after the studio restarts; while Node fails, each look runs it again."""
    seen = store.get_state(CAPABILITIES_KEY) or {}
    gained = seen.get("gained_at")
    try:
        now_has = styles.capabilities(store)
    except Exception as e:  # noqa: BLE001 - e.g. a broken styles.json: never block the orders
        logger.warning("style_capabilities_unreadable", error=repr(e))
        now_has = None
    if now_has is not None and now_has != seen.get("styles"):
        had = seen.get("styles")
        if had is not None and any(t not in had.get(s, ()) for s, ts in now_has.items()
                                   for t in ts):
            gained = to_iso(now)
        store.set_state(CAPABILITIES_KEY, {"styles": now_has, "gained_at": gained})
    return parse_iso(gained) if gained else None


def _runs_today(store: CampaignStore, settings: InstagramMCPSettings, now: datetime,
                key: str) -> Tuple[str, int]:
    """(owner-local day, at-once `key` runs started that day): key order | check."""
    day = _local(settings, now).date().isoformat()
    used = store.get_state(f"{key}_runs") or {}
    return day, used.get("count", 0) if used.get("day") == day else 0


def _gate(store: CampaignStore, settings: InstagramMCPSettings, now: datetime,
          newest: datetime, readers: Tuple[str, ...], key: str, cap: int) -> Optional[str]:
    """Why an at-once run (key order | check) would not start for work as new as `newest`:
    `seen` (a reader started since: it has it), `daily_cap`, `preflight` (failed less than
    ORDER_RETRY ago), else None."""
    # ponytail: the last 10 runs per reader; more than 10 since the newest request is unseen.
    since = [r for p in readers for r in store.list_agent_runs(p, limit=10)
             if parse_iso(r["started_at"]) >= newest]
    if any(r["summary"] != DEAD_RUN for r in since):
        return "seen"
    # a run a restart killed never had them (155), nor the start that made it
    started = store.get_state(f"{key}_run_started_at")  # before its own row exists
    if started and parse_iso(started) >= newest and not any(
            parse_iso(r["started_at"]) >= parse_iso(started) for r in since):
        return "seen"
    if _runs_today(store, settings, now, key)[1] >= cap:
        return "daily_cap"
    failed = store.get_state(f"{key}_preflight_failed_at")
    if failed and now - parse_iso(failed) < ORDER_RETRY:
        return "preflight"
    return None


def _launch(store: CampaignStore, settings: InstagramMCPSettings, now: datetime, key: str,
            playbook: str, start: Callable[..., Any], check: Optional[Callable[..., Any]]
            ) -> Optional[str]:
    """Preflight, then start `playbook`, counted in today's `key` runs. None when started,
    else the AgentError's text (the CLI is missing or signed out, or no such playbook: asked
    again ORDER_RETRY later). AgentRunRefused (it runs already) is raised.
    ponytail: the preflight (`claude auth status`, ~1 s) blocks the worker's loop once per
    at-once run; move it to a thread if it ever gets slow."""
    try:
        (check or preflight)(settings)  # looked up per call: tests patch it
        start(store, settings, playbook)
    except AgentRunRefused:
        raise
    except AgentError as e:
        store.set_state(f"{key}_preflight_failed_at", to_iso(now))
        return str(e)
    day, count = _runs_today(store, settings, now, key)
    store.set_state(f"{key}_preflight_failed_at", None)
    store.set_state(f"{key}_run_started_at", to_iso(now))
    store.set_state(f"{key}_runs", {"day": day, "count": count + 1})
    return None


def order_wait(store: CampaignStore, settings: InstagramMCPSettings, now: datetime,
               gained: Optional[datetime] = None) -> Tuple[Optional[str], Optional[datetime]]:
    """Why the light run would not start now, read-only (order_run and the Planning page,
    185, share it): (None, newest) when it would, else (why, newest): `nothing` (no order or
    change request waits), `order_grace` (newest less than ORDER_RUN_DEBOUNCE_MINUTES old),
    `seen` (a run that reads them started since: it has them), `daily_cap`, `preflight`
    (failed less than ORDER_RETRY ago): _gate. newest: the newest request, or `gained` (new
    capability) while something waits (156)."""
    with store._tx() as c:
        newest = c.execute(_NEWEST_WORK).fetchone()[0]
        times = [parse_iso(newest)] if newest else []
        if gained and c.execute(_WAITING).fetchone()[0]:
            times.append(gained)
    if not times:
        return "nothing", None
    newest = max(times)
    if now - newest < timedelta(minutes=settings.order_run_debounce_minutes):
        return "order_grace", newest
    return _gate(store, settings, now, newest, ORDER_READERS, "order",
                 settings.max_order_runs_per_day), newest


def order_run(store: CampaignStore, settings: InstagramMCPSettings, now: datetime, *,
              start: Callable[..., Any], check: Optional[Callable[..., Any]] = None
              ) -> Optional[str]:
    """The owner's scheduled work orders (136) and change requests (147) start the light
    run (ORDER_PLAYBOOK) at once. Returns it when started, else None. It starts when the
    newest of them (_NEWEST_WORK) is ORDER_RUN_DEBOUNCE_MINUTES old (sends batch into one
    run), no run that reads them started since (it has them: a request it left waiting
    wakes nothing until a newer one comes; a run closed as dead by a restart doesn't
    count, 155) or still runs (one run at a time), fewer than
    MAX_ORDER_RUNS_PER_DAY at-once runs started today (owner-local), and the agent
    preflight passes (asked again ORDER_RETRY after a failure): order_wait. Otherwise they
    keep waiting and the orders' blocked_reason says why when it is the cap, the preflight
    or the playbook. New capability (capability_gained: a style or template went live)
    counts as the newest request while a video waits for changes or an order is scheduled
    (156), so every one is looked at again."""
    gained = capability_gained(store, now)
    for playbook in ORDER_READERS:  # first: it closes a run whose runner is gone (155)
        try:
            check_lock(store, playbook, settings.agent_timeout_minutes * 60)
        except AgentRunRefused:
            return None
    why, _ = order_wait(store, settings, now, gained)
    if why == "daily_cap":
        work_orders.set_blocked(store, f"today's {settings.max_order_runs_per_day} at-once"
                                " runs are used: it waits for the next scheduled run")
    if why:
        return None
    try:
        error = _launch(store, settings, now, "order", ORDER_PLAYBOOK, start, check)
    except AgentRunRefused:
        return None
    work_orders.set_blocked(store, error and f"the agent cannot start: {error}")
    return None if error else ORDER_PLAYBOOK


def check_wait(store: CampaignStore, settings: InstagramMCPSettings, now: datetime
               ) -> Tuple[Optional[str], Optional[datetime]]:
    """Why the check run (188c) would not start now, read-only (check_run and the Planning
    page share it): (None, newest) when it would, else (why, newest): `nothing` (no render
    waits for its check, checks.waiting), `check_grace` (the newest finished less than
    CHECK_RUN_DEBOUNCE_MINUTES ago), `seen`, `daily_cap` (MAX_CHECK_RUNS_PER_DAY),
    `preflight`: _gate. newest: when the newest waiting render finished."""
    newest = checks.newest(store, now)
    if newest is None:
        return "nothing", None
    if now - newest < timedelta(minutes=settings.check_run_debounce_minutes):
        return "check_grace", newest
    return _gate(store, settings, now, newest, (checks.PLAYBOOK,), "check",
                 settings.max_check_runs_per_day), newest


def check_run(store: CampaignStore, settings: InstagramMCPSettings, now: datetime, *,
              start: Callable[..., Any], check: Optional[Callable[..., Any]] = None
              ) -> Optional[str]:
    """Renders waiting for their check (188c) start the light check run (checks.PLAYBOOK)
    at once: check_wait, then the preflight. Returns it when started, else None. The rest
    of the batch still in the line holds it back through catch_up's busy() (a render waiting
    on its timer or held does not), and nothing starts while another run runs."""
    try:  # first: it closes a run whose runner is gone (155)
        check_lock(store, checks.PLAYBOOK, settings.agent_timeout_minutes * 60)
    except AgentRunRefused:
        return None
    if check_wait(store, settings, now)[0]:
        return None
    try:
        error = _launch(store, settings, now, "check", checks.PLAYBOOK, start, check)
    except AgentRunRefused:
        return None
    return None if error else checks.PLAYBOOK


def film_run(store: CampaignStore, settings: InstagramMCPSettings, now: datetime, *,
             start: Callable[..., Any], check: Optional[Callable[..., Any]] = None
             ) -> Optional[int]:
    """The scheduled Lemo-Opuscar order at the head of the heavy line (line.next_in_line,
    186) starts the film runner (173). Returns its id when started, else None. Not while a
    film runs (one at a time; orders a dead film left in_production are skipped first,
    film.close_orphans), nor past LEMO_FILMS_PER_DAY, nor while the agent preflight fails
    (asked again ORDER_RETRY later); the Lemo orders' blocked_reason says why when it is the
    cap or the preflight."""
    try:
        film.check_film(store, settings, now)
    except AgentRunRefused:
        return None
    except AgentError as e:  # today's films are made
        if film.next_order(store):
            work_orders.set_blocked(store, str(e), films=True)
        return None
    film.close_orphans(store)
    first = line.next_in_line(store, settings, now)  # None too while the preflight fails
    if not first or first["kind"] != "film":
        return None
    order = work_orders.get_order(store, first["id"])
    try:
        (check or preflight)(settings)
        start(store, settings, order["id"])
    except AgentError as e:  # the CLI is missing or signed out
        store.set_state("order_preflight_failed_at", to_iso(now))
        work_orders.set_blocked(store, f"le film ne peut pas démarrer : {e}", films=True)
        return None
    work_orders.set_blocked(store, None, films=True)
    return order["id"]


def busy(store: CampaignStore, *, queued: bool = True,
         now: Optional[datetime] = None) -> Optional[str]:
    """Why the catch-up starts no run now (166: never back to back), else None: a run is
    running (one whose runner is gone is closed first, 155), or renders are running or
    queued (one waiting on its timer does not count, 186). queued=False (the film): only a
    running render counts, the queued ones wait behind it in the line."""
    close_dead_runs(store)
    if store.running_agent_runs(limit=1):
        return "an agent run is running"
    if store.list_render_jobs("running", limit=1) or queued and line.head(
            [i for i in line.waiting(store) if i["kind"] == "render"], now or utcnow()):
        return "renders are waiting"
    return None


def catch_up(store: CampaignStore, settings: InstagramMCPSettings, *,
             start: Optional[Callable[..., Any]] = None,
             now: Optional[Callable[[], datetime]] = None,
             start_film: Optional[Callable[..., Any]] = None) -> List[str]:
    """Start the Lemo film at the head of the line (film_run, runs.start_film), else the
    first due playbook detached (runs.start_run), else the work orders' run if they need
    one (order_run), else the check run for finished renders (check_run, 188c); nothing
    while busy(): one run, then the next waits for it and its
    renders (a film only for a running render, 186); nothing while the studio is paused
    (line.pause, 187). Never raises: the worker lives.
    ponytail: a run's row appears a second or two after its start, well within a tick."""
    from .runs import start_film as start_film_run
    from .runs import start_run

    now = now or utcnow  # looked up per call (a default argument would freeze it)

    def playbook() -> Optional[str]:
        for name in due_runs(store, settings, now()):
            try:
                (start or start_run)(store, settings, name)
                return name
            except AgentError as e:
                print(f"agent catch-up: {e}", file=sys.stderr, flush=True)
        return None

    def film() -> Optional[str]:
        order_id = film_run(store, settings, now(), start=start_film or start_film_run)
        return None if order_id is None else f"film {order_id}"

    steps = {"playbook": playbook, "film": film,
             "orders": lambda: order_run(store, settings, now(), start=start or start_run),
             "checks": lambda: check_run(store, settings, now(), start=start or start_run)}
    started = []
    try:
        if line.paused(store):  # the owner paused the studio: nothing starts
            return started
        for step in CATCH_UP_ORDER:
            if busy(store, queued=step != "film", now=now()):
                continue
            got = steps[step]()
            if got:
                started.append(got)
                break
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
