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
  python -m src.scheduler serve               # studio REST API on 127.0.0.1:8765
  python -m src.scheduler up                  # website + API + worker in one process
  python -m src.scheduler dev seed --days 3   # fake demo batch for website work
  python -m src.scheduler token status        # access token validity and expiry
  python -m src.scheduler token refresh       # new 60-day token (needs app id/secret)
  python -m src.scheduler agent run daily-produce  # locked-down Claude Code run (058)
  python -m src.scheduler agent check         # is the Claude Code CLI there and signed in?

Stories expire after 24h and are judged on a snapshot taken at 20h or later,
so they must be snapshotted often; the worker does it every hour (src/worker.py).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import suppress

from . import worker
from .campaign import collect_insights, rank, run_due
from .config import InstagramMCPSettings, get_settings
from .instagram_client import InstagramAPIError, InstagramClient
from .logging_setup import configure_logging
from .store import CampaignStore

NOT_CONFIGURED = ("Instagram not configured (set INSTAGRAM_ACCESS_TOKEN "
                  "and INSTAGRAM_BUSINESS_ACCOUNT_ID in .env)")


async def _worker(settings: InstagramMCPSettings, interval: int = 60,
                  stories_every: int = 60) -> None:
    """The worker of `up` and `worker`: the render loop always (renders need no Instagram),
    publishing when Instagram is configured. Setup mode: say so once; renders still run."""
    try:
        store = CampaignStore(settings.database_path)
        renders = asyncio.create_task(worker.render_loop(store, settings))
        try:
            if settings.instagram_configured:
                async with InstagramClient(settings, store=store) as client:
                    await worker.run(client, store, settings, interval, stories_every)
            else:
                print(f"worker: {NOT_CONFIGURED}; publishing is idle, renders run.",
                      file=sys.stderr, flush=True)
                await renders
        finally:
            renders.cancel()
            with suppress(asyncio.CancelledError):
                await renders
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
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host=host, port=port))
    task = asyncio.create_task(_worker(settings))
    try:
        await server.serve()
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    store = CampaignStore(settings.database_path)
    try:
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
                print(json.dumps(await token_status(client, settings), indent=2))
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
    from .agent.runner import AgentError, preflight, run_agent

    settings = get_settings()
    try:
        if args.agent_command == "check":
            print(f"agent check: ok, {preflight(settings)} is signed in.")
            return 0
        store = CampaignStore(settings.database_path)
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
