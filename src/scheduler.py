"""
Command-line runner for the publishing queue and insight collection.

Meta's API publishes immediately; it has no "post at 18:00" option. Something
has to be awake at 18:00 to publish. Use one of:

  python -m src.scheduler daemon              # keeps running, checks every minute
  python -m src.scheduler run-due             # one pass (for cron / Task Scheduler)
  python -m src.scheduler collect --limit 30  # snapshot insights (run daily)
  python -m src.scheduler collect --stories-only  # live Stories (run hourly)
  python -m src.scheduler rank                # print the winner ranking
  python -m src.scheduler serve               # studio REST API on 127.0.0.1:8765
  python -m src.scheduler up                  # website + API + daemon in one process
  python -m src.scheduler dev seed --days 3   # fake demo batch for website work

Stories expire after 24h and are judged on a snapshot taken at 20h or later,
so they must be snapshotted often; the daemon does it every hour.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from contextlib import suppress

from .campaign import collect_insights, rank, run_due
from .config import InstagramMCPSettings, get_settings
from .instagram_client import InstagramClient
from .logging_setup import configure_logging
from .store import CampaignStore

NOT_CONFIGURED = ("Instagram not configured (set INSTAGRAM_ACCESS_TOKEN "
                  "and INSTAGRAM_BUSINESS_ACCOUNT_ID in .env)")


async def _daemon(client: InstagramClient, store: CampaignStore, interval: int,
                  stories_every: int) -> None:
    """Publish due posts every `interval` s and snapshot live Stories; runs until cancelled."""
    last_stories = float("-inf")
    while True:
        try:
            result = await run_due(client, store)
        except Exception as e:  # noqa: BLE001 - keep the daemon alive
            print(f"run_due failed: {e!r}", file=sys.stderr, flush=True)
        else:
            if any(result[k] for k in ("published", "retrying", "failed", "recovered_stuck")):
                print(json.dumps(result), flush=True)
        if stories_every and time.monotonic() - last_stories >= stories_every * 60:
            last_stories = time.monotonic()
            try:
                await collect_insights(client, store, limit=0)
            except Exception as e:  # noqa: BLE001
                print(f"story snapshot failed: {e!r}", file=sys.stderr, flush=True)
        await asyncio.sleep(interval)


async def _worker(settings: InstagramMCPSettings, interval: int = 60,
                  stories_every: int = 60) -> None:
    """The publishing part of `up`. Setup mode: say so once and idle; the API keeps serving."""
    if not settings.instagram_configured:
        print(f"worker: {NOT_CONFIGURED}; publishing is idle.", file=sys.stderr, flush=True)
        return
    try:
        store = CampaignStore(settings.database_path)
        try:
            async with InstagramClient(settings) as client:
                await _daemon(client, store, interval, stories_every)
        finally:
            store.close()
    except Exception as e:  # noqa: BLE001 - e.g. a newer DB schema: say so, keep the API up
        print(f"worker stopped: {e!r}; publishing is off until restart.", file=sys.stderr,
              flush=True)


async def _up(host: str, port: int) -> None:
    """API (uvicorn) and worker in one event loop; when uvicorn stops (Ctrl+C), the worker too."""
    import uvicorn

    from .api.app import create_app

    settings = get_settings()
    configure_logging(settings.log_level)
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host=host, port=port))
    worker = asyncio.create_task(_worker(settings))
    try:
        await server.serve()
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    store = CampaignStore(settings.database_path)
    try:
        if args.command == "rank":
            print(json.dumps(rank(store, settings, campaign=args.campaign), indent=2, default=str))
            return 0
        if not settings.instagram_configured:
            # Setup mode: nothing to publish or measure yet. Exit 0 so cron and
            # Task Scheduler don't flag a failure; the daemon exits too.
            print(f"{args.command}: {NOT_CONFIGURED}; skipping.", file=sys.stderr)
            return 0
        async with InstagramClient(settings) as client:
            if args.command == "run-due":
                print(json.dumps(await run_due(client, store), indent=2))
            elif args.command == "collect":
                limit = 0 if args.stories_only else args.limit
                print(json.dumps(await collect_insights(client, store, limit=limit), indent=2))
            elif args.command == "daemon":
                print(f"Scheduler running, checking every {args.interval}s. Ctrl+C to stop.",
                      file=sys.stderr)
                await _daemon(client, store, args.interval, args.stories_every)
        return 0
    finally:
        store.close()


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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ig-campaign")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run-due", help="Publish queued posts that are due, then exit")
    d = sub.add_parser("daemon", help="Publish queued posts as they come due")
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
                        ("up", "Run the studio: website, API and publishing daemon together")):
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
    args = parser.parse_args(argv)
    if args.command == "dev" and args.days < 1:
        parser.error("--days must be >= 1")
    if args.command == "daemon" and args.interval <= 0:
        parser.error("--interval must be > 0")
    if args.command == "daemon" and args.stories_every < 0:
        parser.error("--stories-every must be >= 0")
    configure_logging()
    if args.command == "dev":
        sys.exit(_dev_seed(args))
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
