"""
Command-line runner for the publishing queue and insight collection.

Meta's API publishes immediately; it has no "post at 18:00" option. Something
has to be awake at 18:00 to publish. Use one of:

  python -m src.scheduler worker              # keeps running, checks every minute
                                              # (`daemon` is the old name, still works)
  python -m src.scheduler run-due             # one pass (for cron / Task Scheduler)
  python -m src.scheduler run-due --wait-until-next  # stay awake until the next slot
                                              # (<= 15 min away), then one pass (wake task)
  python -m src.scheduler collect --limit 30  # snapshot insights (run daily)
  python -m src.scheduler collect --stories-only  # live Stories (run hourly)
  python -m src.scheduler rank                # print the winner ranking
  python -m src.scheduler facts [--date D]    # yesterday's (or D's) daily facts as JSON
  python -m src.scheduler serve               # studio REST API on 127.0.0.1:8765
  python -m src.scheduler up                  # website + API + worker in one process
                                              # (+ the voice service: TTS_SERVER_PYTHON)
  python -m src.scheduler dev seed --days 3   # fake demo batch for website work
  python -m src.scheduler token status        # access token validity and expiry
  python -m src.scheduler token refresh       # new 60-day token (needs app id/secret)
  python -m src.scheduler agent run daily-produce  # locked-down Claude Code run (058)
  python -m src.scheduler agent check         # is the Claude Code CLI there and signed in?
  python -m src.scheduler agent run-due       # run playbooks due per AGENT_SCHEDULE (061)
  python -m src.scheduler agent install-schedule [--remove]  # OS autostart + daily runs
  python -m src.scheduler downloader setup|update|status  # Reel downloader service (063a)
  python -m src.scheduler restore <backup> [--yes]  # put a nightly backup back (097)
  python -m src.scheduler doctor              # is everything installed? (100)

Stories expire after 24h and are judged on a snapshot taken at 20h or later,
so they must be snapshotted often; the worker does it every hour (src/worker.py).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import subprocess
import sys
from contextlib import nullcontext, suppress
from datetime import date
from typing import Awaitable, Callable, Optional

from . import settings_overrides, worker
from .campaign import collect_insights, rank, run_due
from .config import InstagramMCPSettings, get_settings
from .instagram_client import InstagramAPIError, InstagramClient
from .logging_setup import configure_logging
from .store import CampaignStore, to_iso, utcnow
from .studio import downloader_service, tts_service

NOT_CONFIGURED = ("Instagram not configured (set INSTAGRAM_ACCESS_TOKEN "
                  "and INSTAGRAM_BUSINESS_ACCOUNT_ID in .env)")


async def _after_grace(settings: InstagramMCPSettings, start: Callable[[], Awaitable[None]],
                       ) -> None:
    """start() once the startup grace is over (166: the PC froze twice when heavy work began
    within a minute of logon)."""
    await asyncio.sleep(settings.guard_startup_grace_min * 60)
    await start()


async def _worker(settings: InstagramMCPSettings, interval: int = 60,
                  stories_every: int = 60,
                  voice_pid: Callable[[], Optional[int]] = lambda: None) -> None:
    """The worker of `up` and `worker`: the render loop, the agent catch-up and the Reel
    downloader service always (none needs Instagram), publishing when Instagram is
    configured, the resource guard's watchdog (166). Renders and agent runs wait for the
    startup grace. Setup mode: say so once; renders still run."""
    try:
        from .agent.schedule import catch_up_loop
        from .studio.guard import watchdog_loop

        store = CampaignStore(settings.database_path)
        if settings.guard_startup_grace_min:
            print(f"startup grace: no render or agent run for {settings.guard_startup_grace_min:g}"
                  " min", file=sys.stderr, flush=True)
        renders = asyncio.create_task(_after_grace(
            settings, lambda: worker.render_loop(store, settings)))
        agents = asyncio.create_task(_after_grace(
            settings, lambda: catch_up_loop(store, settings)))
        downloader = asyncio.create_task(worker.downloader_loop(store, settings))
        fresh = asyncio.create_task(settings_overrides.refresh_loop(store, settings))
        watchdog = asyncio.create_task(watchdog_loop(store, voice_pid) if settings.guard_watchdog
                                       else asyncio.sleep(0))
        try:
            if settings.instagram_configured:
                async with InstagramClient(settings, store=store) as client:
                    await worker.run(client, store, settings, interval, stories_every)
            else:
                print(f"worker: {NOT_CONFIGURED}; publishing is idle, renders run.",
                      file=sys.stderr, flush=True)
                while not renders.done():  # no publish cycle beats here; `restore` checks it
                    with suppress(sqlite3.Error):
                        store.set_state("heartbeat_at", to_iso(utcnow()))
                    await asyncio.wait({renders}, timeout=interval)
                await renders
        finally:
            for task in (renders, agents, downloader, fresh, watchdog):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            store.close()
    except Exception as e:  # noqa: BLE001 - e.g. a newer DB schema: say so, keep the API up
        print(f"worker stopped: {e!r}; publishing and renders are off until restart.",
              file=sys.stderr, flush=True)


async def _up(host: str, port: int) -> None:
    """API (uvicorn) and worker in one event loop; when uvicorn stops (Ctrl+C), the worker too."""
    import uvicorn

    from .api.app import create_app

    settings = get_settings()
    configure_logging(settings.log_level)
    _close_dead_runs(settings)
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host=host, port=port))
    voice = _start_voice(settings)
    task = asyncio.create_task(_worker_after_voice(settings, voice))
    try:
        await server.serve()
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        if voice is not None:
            downloader_service.stop(voice)


def _close_dead_runs(settings: InstagramMCPSettings) -> None:
    """Agent runs the last stop orphaned show as failed before the website opens (155)."""
    from .agent.runner import close_dead_runs

    try:
        store = CampaignStore(settings.database_path)
        try:
            for run in close_dead_runs(store):
                print(f"agent run {run['id']} ({run['playbook']}): its runner is gone,"
                      " closed as failed", file=sys.stderr, flush=True)
        finally:
            store.close()
    except Exception as e:  # noqa: BLE001 - e.g. a newer DB schema: the worker says so
        print(f"agent runs not checked: {e!r}", file=sys.stderr, flush=True)


def _start_voice(settings: InstagramMCPSettings):
    """The voice service child (TTS_SERVER_PYTHON, step 038), or None."""
    if not settings.tts_server_python:
        return None
    try:
        return tts_service.spawn(settings)
    except (OSError, ValueError) as e:
        print(f"voice service not started: {e}", file=sys.stderr, flush=True)
        return None


async def _worker_after_voice(settings: InstagramMCPSettings, voice) -> None:
    """The worker, once the voice service answers (it voices renders and agent runs)."""
    if voice is not None and not await tts_service.wait_ready(settings, voice):
        print(f"voice service not ready (see {tts_service.LOG_PATH}); voiced renders will"
              " fail until it is", file=sys.stderr, flush=True)
    await _worker(settings, voice_pid=lambda: voice and tts_service.worker_pid(settings))


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    store = CampaignStore(settings.database_path)
    try:
        settings_overrides.refresh(store, settings)
        if args.command == "rank":
            print(json.dumps(rank(store, settings, campaign=args.campaign), indent=2, default=str))
            return 0
        if args.command in ("worker", "daemon"):
            print(f"Worker running, checking every {args.interval}s. Ctrl+C to stop.",
                  file=sys.stderr)
            await _worker(settings, args.interval, args.stories_every)
            return 0
        if args.command == "token":
            return await _token(args, settings, store)
        if args.command == "facts":
            return await _facts(args, settings, store)
        if args.command == "learnings":  # `learnings refresh`: no Instagram needed
            from .learning.evidence import refresh_learnings

            print(json.dumps(refresh_learnings(store, settings, utcnow()), indent=2))
            return 0
        if not settings.instagram_configured:
            # Setup mode: nothing to publish or measure yet. Exit 0 so cron and
            # Task Scheduler don't flag a failure.
            print(f"{args.command}: {NOT_CONFIGURED}; skipping.", file=sys.stderr)
            return 0
        async with InstagramClient(settings, store=store) as client:
            if args.command == "run-due":
                result = (await worker.run_due_after_wait(client, store, settings)
                          if args.wait_until_next else
                          await run_due(client, store, settings=settings))
                print(json.dumps(result, indent=2))
            elif args.command == "collect":
                limit = 0 if args.stories_only else args.limit
                print(json.dumps(await collect_insights(client, store, limit=limit), indent=2))
        return 0
    finally:
        store.close()


async def _facts(args: argparse.Namespace, settings: InstagramMCPSettings,
                 store: CampaignStore) -> int:
    """`facts [--date]`: the stored facts, computed when missing (comments need Instagram)."""
    from .learning.facts import facts_for

    async with (InstagramClient(settings, store=store) if settings.instagram_configured
                else nullcontext()) as client:
        try:
            result = await facts_for(store, settings, day=args.date, client=client,
                                     now=utcnow())
        except ValueError as e:
            print(f"facts: {e}", file=sys.stderr)
            return 1
    print(json.dumps(result, indent=2, default=str))
    return 0


async def _token(args: argparse.Namespace, settings: InstagramMCPSettings,
                 store: CampaignStore) -> int:
    """`token status|refresh`. The token itself is never printed."""
    from pathlib import Path

    from .config import ENV_FILE
    from .studio.token import RefreshRefused, refresh_token, token_status

    if not settings.instagram_access_token:
        print("token: no INSTAGRAM_ACCESS_TOKEN set (setup mode); nothing to check.",
              file=sys.stderr)
        return 0
    async with InstagramClient(settings, store=store) as client:
        try:
            if args.token_command == "status":
                status = await token_status(client, settings)
                if status.get("error"):  # Meta's message, never the token
                    print(f"token status: {status['error']}", file=sys.stderr)
                    return 1
                print(json.dumps(status, indent=2))
                return 0
            result = await refresh_token(client, settings, Path(ENV_FILE))
        except RefreshRefused as e:
            print(f"token refresh: refused, {e}.", file=sys.stderr)
            return 1
        except InstagramAPIError as e:  # Meta's message, never the token
            print(f"token {args.token_command}: {e.message}", file=sys.stderr)
            return 1
    expires = result["expires_at"]
    print(f"refreshed, expires on {expires[:10] if expires else 'never'}"
          " (restart the studio and MCP server to use it)")
    return 0


def _dev_seed(args: argparse.Namespace) -> int:
    import random
    from pathlib import Path

    from .studio.seed import local_today, refusal, seed

    settings = get_settings()
    db = Path(args.db or settings.database_path)
    production = db.resolve() == Path(settings.database_path).resolve()
    store = CampaignStore(str(db))
    try:
        why = refusal(store, production_live=production and settings.instagram_configured)
        if why and not args.force:
            print(f"dev seed: refused, {why}. Use --force to seed anyway.", file=sys.stderr)
            return 1
        # a scratch --db keeps its media next to it (tests); the configured DB uses MEDIA_ROOT
        media_root = Path(settings.media_root) if production else db.parent / "media"
        summary = seed(store, media_root, args.days, random.Random(args.seed),
                       local_today(settings.timezone))
    finally:
        store.close()
    print(json.dumps(summary, indent=2))
    return 0


# --- agent (058) ---------------------------------------------------------
def _agent(args: argparse.Namespace) -> int:
    from .agent import schedule
    from .agent.runner import AgentError, preflight, run_agent

    settings = get_settings()
    try:
        if args.agent_command == "check":
            print(f"agent check: ok, {preflight(settings)} is signed in.")
            return 0
        if args.agent_command == "install-schedule":
            try:
                print(schedule.install_schedule(settings, remove=args.remove))
            except (OSError, subprocess.SubprocessError) as e:
                print(f"agent install-schedule: {e!r}", file=sys.stderr)
                return 1
            return 0
        store = CampaignStore(settings.database_path)
        settings_overrides.refresh(store, settings)  # the work packets use them
        if args.agent_command == "run-due":
            try:
                runs = schedule.run_due(store, settings)
            finally:
                store.close()
            print(json.dumps(runs, indent=2, default=str))
            return 0 if all(r["status"] == "succeeded" for r in runs) else 1
        try:
            run = run_agent(store, settings, args.playbook, max_turns=args.max_turns,
                            timeout_s=args.timeout * 60 if args.timeout else None,
                            dry_run=args.dry_run)
        finally:
            store.close()
    except AgentError as e:
        print(f"agent {args.agent_command}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(run, indent=2, default=str))
    return 0 if run["status"] == "succeeded" else 1


# --- downloader (063a) ----------------------------------------------------
def _downloader(args: argparse.Namespace) -> int:
    from .studio import downloader_service as svc

    settings = get_settings()
    try:
        if args.downloader_command == "setup":
            result = svc.setup()
        elif args.downloader_command == "update":
            result = asyncio.run(svc.update(settings))
        else:
            store = CampaignStore(settings.database_path)
            try:
                result = {**svc.status(store, settings), "commit": svc.commit()}
            finally:
                store.close()
    except svc.DownloaderError as e:
        print(f"downloader {args.downloader_command}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


# --- restore (097) --------------------------------------------------------
def _restore(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .studio.housekeeping import RestoreRefused, restore_database

    settings = get_settings()
    backup = Path(args.backup)
    try:
        plan = restore_database(settings, backup, utcnow(), dry_run=True)
        print(f"Restore {plan['backup']} (schema {plan['backup_schema']}) over"
              f" {plan['database']}; the current database is kept as {plan['set_aside']}.")
        if not args.yes:
            if not sys.stdin.isatty():
                print("restore: not interactive, add --yes to go ahead.", file=sys.stderr)
                return 1
            if input("Go ahead? [y/N] ").strip().lower() not in ("y", "yes"):
                print("restore: cancelled.", file=sys.stderr)
                return 1
        result = restore_database(settings, backup, utcnow())
    except RestoreRefused as e:
        print(f"restore: refused, {e}.", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


# --- style requests (156) -----------------------------------------------------
def _style_requests(args: argparse.Namespace) -> int:
    """The lead's hand-off: the requests as JSON (`list --status accepted`: what to build
    next), and `mark ID building|live` as the style step moves."""
    from .studio import style_requests

    store = CampaignStore(get_settings().database_path)
    try:
        if args.style_command == "mark":
            result = style_requests.mark(store, args.id, args.status)
        else:
            result = style_requests.list_requests(store, args.status, args.limit)
    except (KeyError, ValueError) as e:
        print(f"style-requests: {e}", file=sys.stderr)
        return 1
    finally:
        store.close()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


# --- doctor (100) ---------------------------------------------------------
def _doctor() -> int:
    from .studio.doctor import checks

    yes, no = "✔", "✖"
    try:
        (yes + no).encode(sys.stdout.encoding or "ascii")
    except (UnicodeEncodeError, LookupError):  # e.g. a cp1252 pipe (Git Bash on Windows)
        yes, no = "ok", "XX"
    results = checks(get_settings())
    for c in results:
        print(f"{yes if c['ok'] else no} {c['name']}: {c['detail']}")
        if c["fix"]:
            print(f"    -> {c['fix']}")
    failed = sum(not c["ok"] for c in results)
    print("All set." if not failed else f"{failed} to fix (see -> above).")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ig-campaign")
    sub = parser.add_subparsers(dest="command", required=True)
    rd = sub.add_parser("run-due", help="Publish queued posts that are due, then exit")
    rd.add_argument("--wait-until-next", action="store_true",
                    help="Keep the PC awake and wait for the next slot if it is due within "
                         "15 min, then run once (the wake task's action)")
    d = sub.add_parser("worker", aliases=["daemon"],
                       help="Render queued videos; publish queued posts as they come due")
    d.add_argument("--interval", type=int, default=60)
    d.add_argument("--stories-every", type=int, default=60, metavar="MINUTES",
                   help="Snapshot live Stories this often (0 = off). Default 60.")
    c = sub.add_parser("collect", help="Snapshot insights of recent posts")
    c.add_argument("--limit", type=int, default=25)
    c.add_argument("--stories-only", action="store_true",
                   help="Only snapshot live Stories (cheap; run hourly)")
    r = sub.add_parser("rank", help="Print winner ranking from stored snapshots")
    r.add_argument("--campaign")
    f = sub.add_parser("facts", help="Print the daily facts (no AI) as JSON")
    f.add_argument("--date", type=date.fromisoformat, metavar="YYYY-MM-DD",
                   help="Owner-local day (default: yesterday)")
    sub.add_parser("learnings", help="Learnings checked against the numbers").add_subparsers(
        dest="learnings_command", required=True).add_parser(
        "refresh", help="Re-evaluate every learning with a tag predicate now (the worker does"
                        " it nightly)")
    for name, help_ in (("serve", "Run the studio REST API"),
                        ("up", "Run the studio: website, API and publishing worker together")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("--host", default="127.0.0.1")
        s.add_argument("--port", type=int, default=8765)
    dev = sub.add_parser("dev", help="Developer tools").add_subparsers(dest="dev_command",
                                                                       required=True)
    ds = dev.add_parser("seed", help="Fill a database with a fake demo batch")
    ds.add_argument("--db", help="SQLite file (default: the configured database)")
    ds.add_argument("--days", type=int, default=3)
    ds.add_argument("--force", action="store_true",
                    help="Seed even a non-empty or live production database")
    ds.add_argument("--seed", type=int, help="Random seed, for a reproducible batch")
    t = sub.add_parser("token", help="Access token: status or refresh").add_subparsers(
        dest="token_command", required=True)
    t.add_parser("status", help="Validity, expiry and scopes (the token is never printed)")
    t.add_parser("refresh", help="Swap for a new long-lived token, rewrite it in .env")
    agent = sub.add_parser("agent", help="Unattended Claude Code runs").add_subparsers(
        dest="agent_command", required=True)
    ar = agent.add_parser("run", help="Run a playbook from agent/playbooks/, locked down")
    ar.add_argument("playbook", help="Playbook name, e.g. daily-produce")
    ar.add_argument("--dry-run", action="store_true", help="The playbook's dry-run mode")
    ar.add_argument("--max-turns", type=int, help="Default AGENT_MAX_TURNS")
    ar.add_argument("--timeout", type=float, metavar="MIN",
                    help="Wall-clock limit in minutes (default AGENT_TIMEOUT_MINUTES)")
    agent.add_parser("check", help="Preflight only: CLI found and signed in")
    agent.add_parser("run-due", help="Run every playbook due per AGENT_SCHEDULE, in turn")
    ais = agent.add_parser("install-schedule",
                           help="Start `up` at logon and the daily runs via the OS scheduler")
    ais.add_argument("--remove", action="store_true", help="Remove those OS tasks instead")
    dl = sub.add_parser("downloader", help="The Reel downloader service (vendor/)"
                        ).add_subparsers(dest="downloader_command", required=True)
    dl.add_parser("setup", help="npm ci + build in the submodule, then npm audit (logged)")
    dl.add_parser("update", help="Move to upstream's latest commit; roll back if the health "
                                 "check fails (stop the worker first)")
    dl.add_parser("status", help="Built?, port, commit and the last health check")
    rs = sub.add_parser("restore", help="Replace the database with a backup (stop the studio"
                                         " first; the current one is kept aside)")
    rs.add_argument("backup", help="A backup file, e.g. data/backups/studio-2026-11-17.db")
    rs.add_argument("--yes", action="store_true", help="Don't ask (needed when not interactive)")
    sr = sub.add_parser("style-requests", help="Styles the agent asked for (156): the"
                        " accepted ones are the next style steps").add_subparsers(
        dest="style_command", required=True)
    srl = sr.add_parser("list", help="Print them as JSON, newest first")
    srl.add_argument("--status", choices=("proposed", "accepted", "declined", "building",
                                          "live"))
    srl.add_argument("--limit", type=int, default=100)
    srm = sr.add_parser("mark", help="accepted -> building (step started) -> live (merged)")
    srm.add_argument("id", type=int)
    srm.add_argument("status", choices=("building", "live"))
    sub.add_parser("doctor", help="Check what the studio needs (ffmpeg, Node, website, "
                                  "downloader, Claude Code, .env); changes nothing")
    args = parser.parse_args(argv)
    if args.command == "agent" and args.agent_command == "run" and (
            (args.max_turns is not None and args.max_turns < 1)
            or (args.timeout is not None and args.timeout <= 0)):
        parser.error("--max-turns and --timeout must be > 0")
    if args.command == "dev" and args.days < 1:
        parser.error("--days must be >= 1")
    if args.command in ("worker", "daemon") and args.interval <= 0:
        parser.error("--interval must be > 0")
    if args.command in ("worker", "daemon") and args.stories_every < 0:
        parser.error("--stories-every must be >= 0")
    configure_logging()
    if args.command == "dev":
        sys.exit(_dev_seed(args))
    if args.command == "agent":
        sys.exit(_agent(args))
    if args.command == "downloader":
        sys.exit(_downloader(args))
    if args.command == "restore":
        sys.exit(_restore(args))
    if args.command == "doctor":
        sys.exit(_doctor())
    if args.command == "style-requests":
        sys.exit(_style_requests(args))
    if args.command in ("serve", "up"):
        from .api.auth import bind_error

        error = bind_error(args.host, get_settings())
        if error:
            parser.exit(2, f"{args.command}: {error}\n")
    if args.command == "serve":
        import uvicorn

        from .api.app import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port)
        return
    try:
        if args.command == "up":
            asyncio.run(_up(args.host, args.port))
            return
        sys.exit(asyncio.run(_run(args)))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
