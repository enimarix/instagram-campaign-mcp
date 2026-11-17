"""
Command-line runner for the publishing queue and insight collection.

Meta's API publishes immediately; it has no "post at 18:00" option. Something
has to be awake at 18:00 to publish. Use one of:

  python -m src.scheduler daemon              # keeps running, checks every minute
  python -m src.scheduler run-due             # one pass (for cron / Task Scheduler)
  python -m src.scheduler collect --limit 30  # snapshot insights (run daily)
  python -m src.scheduler rank                # print the winner ranking
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .campaign import collect_insights, rank, run_due
from .config import get_settings
from .instagram_client import InstagramClient
from .logging_setup import configure_logging
from .store import CampaignStore


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    store = CampaignStore(settings.database_path)
    try:
        if args.command == "rank":
            print(json.dumps(rank(store, settings, campaign=args.campaign), indent=2, default=str))
            return 0
        async with InstagramClient(settings) as client:
            if args.command == "run-due":
                print(json.dumps(await run_due(client, store), indent=2))
            elif args.command == "collect":
                print(json.dumps(await collect_insights(client, store, limit=args.limit), indent=2))
            elif args.command == "daemon":
                print(f"Scheduler running, checking every {args.interval}s. Ctrl+C to stop.",
                      file=sys.stderr)
                while True:
                    result = await run_due(client, store)
                    if any(result[k] for k in ("published", "retrying", "failed")):
                        print(json.dumps(result), flush=True)
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
    c = sub.add_parser("collect", help="Snapshot insights of recent posts")
    c.add_argument("--limit", type=int, default=25)
    r = sub.add_parser("rank", help="Print winner ranking from stored snapshots")
    r.add_argument("--campaign")
    args = parser.parse_args()
    configure_logging()
    try:
        sys.exit(asyncio.run(_run(args)))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
