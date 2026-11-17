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

Stories expire after 24h and are judged on a snapshot taken at 20h or later,
so they must be snapshotted often; the daemon does it every hour.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

from .campaign import collect_insights, rank, run_due
from .config import get_settings
from .instagram_client import InstagramClient
from .logging_setup import configure_logging
from .store import CampaignStore


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
            print(f"{args.command}: Instagram not configured (set INSTAGRAM_ACCESS_TOKEN "
                  "and INSTAGRAM_BUSINESS_ACCOUNT_ID in .env); skipping.", file=sys.stderr)
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
                last_stories = float("-inf")
                while True:
                    try:
                        result = await run_due(client, store)
                    except Exception as e:  # noqa: BLE001 - keep the daemon alive
                        print(f"run_due failed: {e!r}", file=sys.stderr, flush=True)
                    else:
                        if any(result[k] for k in ("published", "retrying", "failed",
                                                   "recovered_stuck")):
                            print(json.dumps(result), flush=True)
                    if args.stories_every and (
                        time.monotonic() - last_stories >= args.stories_every * 60
                    ):
                        last_stories = time.monotonic()
                        try:
                            await collect_insights(client, store, limit=0)
                        except Exception as e:  # noqa: BLE001
                            print(f"story snapshot failed: {e!r}", file=sys.stderr, flush=True)
                    await asyncio.sleep(args.interval)
        return 0
    finally:
        store.close()


def main() -> None:
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
    s = sub.add_parser("serve", help="Run the studio REST API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "daemon" and args.interval <= 0:
        parser.error("--interval must be > 0")
    if args.command == "daemon" and args.stories_every < 0:
        parser.error("--stories-every must be >= 0")
    configure_logging()
    if args.command == "serve":
        import uvicorn

        from .api.app import create_app
        from .api.auth import bind_error

        error = bind_error(args.host, get_settings())
        if error:
            parser.exit(2, f"serve: {error}\n")
        uvicorn.run(create_app(), host=args.host, port=args.port)
        return
    try:
        sys.exit(asyncio.run(_run(args)))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
