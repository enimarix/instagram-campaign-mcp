"""
Alerts (step 098): what needs the owner's attention, for the website's bell.

Computed on every call from state that already exists (no event pipeline): failed
publishes, publishes waiting for a check, re-planned late slots, the token, the latest run
of each agent playbook, a QC failure spike in the last batch, a stale worker heartbeat, the
Reel downloader's health and skipped DM picks. Experiment and ad alerts come with their
steps (086's facts warning, ads 089+).

An alert's `id` is stable (kind, or kind:subject), so the owner can dismiss it: the time is
kept in worker state, and the alert stays hidden until its `since` moves past that time
(a new failure, a new run, a new heartbeat that went stale again).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..agent.packet import SKIPPED
from ..config import InstagramMCPSettings
from ..instagram_client import InstagramAPIError, InstagramClient
from ..store import CampaignStore, parse_dt, to_iso
from ..worker import ALIVE_WITHIN
from . import downloader_service, token

STATE_KEY = "alerts_dismissed"
FAILED_WITHIN = timedelta(days=7)  # failed publishes this recent
RECENT = timedelta(days=1)  # re-plans and skipped DM picks
CHECK_STUCK = timedelta(minutes=30)  # reconcile runs every 10 min: longer is stuck
TOKEN_WARN_DAYS = 10
QC_SPIKE = 0.3  # share of the last batch that failed QC
FORGET_AFTER = timedelta(days=30)  # dismissals older than this are dropped
DETAIL_MAX = 300


def _alert(kind: str, subject: Any, severity: str, title: str, detail: str, link: str,
           since: Optional[str]) -> Dict[str, Any]:
    return {"id": f"{kind}:{subject}" if subject is not None else kind, "kind": kind,
            "severity": severity, "title": title, "detail": detail[:DETAIL_MAX],
            "link": link, "since": since}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _publishes(store: CampaignStore, now: datetime) -> List[Dict[str, Any]]:
    out = []
    for p in store.list_scheduled("failed", limit=500):
        if now - parse_dt(p["updated_at"]) > FAILED_WITHIN:
            continue
        link = f"/assets/{p['asset_id']}" if p.get("asset_id") else "/calendar"
        out.append(_alert("publish_failed", p["id"], "error", "A post failed to publish",
                          p.get("error") or "No reason was recorded.", link, p["updated_at"]))
    for a in store.list_assets(status="publish_check", limit=500):
        if now - parse_dt(a["updated_at"]) >= CHECK_STUCK:
            out.append(_alert(
                "publish_check", a["id"], "warn", "A publish needs a check",
                "It may have reached Instagram. Look on the account; if the post is not "
                "there, release the video so it can be scheduled again.",
                f"/assets/{a['id']}", a["updated_at"]))
    return out


def _replanned(store: CampaignStore, now: datetime) -> List[Dict[str, Any]]:
    moved = [p for p in store.list_scheduled("pending", limit=500)
             if (p.get("error") or "").startswith("Re-planned")
             and now - parse_dt(p["updated_at"]) <= RECENT]
    if not moved:
        return []
    last = max(moved, key=lambda p: p["updated_at"])
    return [_alert("replanned", None, "info",
                   f"{_plural(len(moved), 'post')} moved to a later slot",
                   f"Latest: {last['error'].removeprefix('Re-planned: ')}.", "/calendar",
                   last["updated_at"])]


def _token(t: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not t or not t.get("configured") or t.get("valid") is None:
        return []
    days, expires = t.get("days_left"), t.get("expires_at")
    fix = "Run ig-campaign token refresh." if t.get("can_refresh") and t["valid"] \
        else "Paste a new token in .env (see README, Token)."
    if not t["valid"] or (days is not None and days < 0):
        return [_alert("token", "invalid", "error", "The Instagram token expired or is invalid",
                       f"Publishing is stopped. {fix}", "/settings", expires)]
    if days is None or days > TOKEN_WARN_DAYS:
        return []
    when = "today" if days == 0 else f"in {_plural(days, 'day')}"
    since = to_iso(parse_dt(expires) - timedelta(days=TOKEN_WARN_DAYS))
    return [_alert("token", "expiring", "warn", f"The Instagram token expires {when}",
                   f"Publishing stops then. {fix}", "/settings", since)]


def _agent_runs(store: CampaignStore) -> List[Dict[str, Any]]:
    """The latest finished run of each playbook: failed (or stopped at its turn or budget
    limit), or done but leaving part of its work packet."""
    out, seen = [], set()
    for r in store.list_agent_runs(limit=200):
        if r["status"] == "running" or r["playbook"] in seen:
            continue
        seen.add(r["playbook"])
        summary = r.get("summary") or ""
        subtype = str((r.get("usage") or {}).get("subtype") or "")
        if r["status"] == "failed":
            title = (f"Agent run {r['playbook']} stopped at its limit"
                     if subtype.startswith("error_max") else f"Agent run {r['playbook']} failed")
            out.append(_alert("agent_run", r["playbook"], "error", title,
                              summary.splitlines()[0] if summary else "See its log.",
                              "/agent", r["finished_at"]))
        elif r["status"] == "succeeded" and summary != SKIPPED and "\nwork packet: " in summary:
            out.append(_alert("agent_run", r["playbook"], "warn",
                              f"Agent run {r['playbook']} left work undone",
                              summary.rsplit("\nwork packet: ", 1)[1], "/agent",
                              r["finished_at"]))
    return out


def _qc_spike(store: CampaignStore) -> List[Dict[str, Any]]:
    with store._tx() as c:
        rows = c.execute("SELECT batch_date, status, qc, updated_at FROM assets WHERE"
                         " batch_date = (SELECT MAX(batch_date) FROM assets)").fetchall()
    failed = [r for r in rows
              if r[1] == "failed" and json.loads(r[2] or "{}").get("passed") is False]
    if not rows or len(failed) < QC_SPIKE * len(rows):
        return []
    return [_alert("qc_spike", rows[0][0], "warn",
                   f"{len(failed)} of {len(rows)} videos of the {rows[0][0]} batch failed",
                   "Quality check or render failures, more than usual: check the render log "
                   "and the templates.", "/agent",
                   max(r[3] for r in failed))]


def _worker(store: CampaignStore, now: datetime) -> List[Dict[str, Any]]:
    beat = store.get_state("heartbeat_at")
    if beat is None or now - parse_dt(beat) < ALIVE_WITHIN:
        return []  # never started (setup mode) or alive
    return [_alert("worker", None, "error", "The publishing worker is not running",
                   f"Last heartbeat {beat[:16].replace('T', ' ')} UTC. Start it with "
                   "ig-campaign up; nothing publishes meanwhile.", "/settings", beat)]


def _downloader(store: CampaignStore) -> List[Dict[str, Any]]:
    health = store.get_state(downloader_service.STATE_KEY) or {}
    if health.get("status") not in ("down", "broken"):
        return []
    what = "is down" if health["status"] == "down" else "answers but finds no video"
    detail = health.get("detail") or "DM picks and Reel downloads wait until it works."
    return [_alert("downloader", None, "warn", f"The Reel downloader {what}", detail,
                   "/settings", health.get("checked_at"))]


def _dm_skipped(store: CampaignStore, now: datetime) -> List[Dict[str, Any]]:
    with store._tx() as c:
        rows = c.execute("SELECT sender_username, skip_reason, updated_at FROM dm_picks"
                         " WHERE status='skipped' AND updated_at >= ? ORDER BY updated_at"
                         " DESC", (to_iso(now - RECENT),)).fetchall()
    if not rows:
        return []
    who, reason, at = rows[0]
    return [_alert("dm_skipped", None, "info",
                   f"{_plural(len(rows), 'DM pick')} skipped today",
                   f"Latest, from @{who}: {reason}", "/settings", at)]


async def alerts(store: CampaignStore, settings: InstagramMCPSettings, now: datetime,
                 client: Optional[InstagramClient] = None) -> List[Dict[str, Any]]:
    """[{id, kind, severity info|warn|error, title, detail, link, since}], newest first,
    without the dismissed ones. Reads only (the token status is cached for an hour)."""
    try:
        t = await token.token_status(client, settings)
    except InstagramAPIError:  # e.g. bad app credentials: the Settings page shows it
        t = None
    found = [*_publishes(store, now), *_replanned(store, now), *_token(t),
             *_agent_runs(store), *_qc_spike(store), *_worker(store, now),
             *_downloader(store), *_dm_skipped(store, now)]
    dismissed = store.get_state(STATE_KEY) or {}
    shown = [a for a in found if a["id"] not in dismissed
             or (a["since"] is not None and parse_dt(a["since"]) > parse_dt(dismissed[a["id"]]))]
    return sorted(shown, key=lambda a: parse_dt(a["since"]) if a["since"] else now,
                  reverse=True)


def dismiss(store: CampaignStore, alert_id: str, now: datetime) -> Dict[str, Any]:
    """Hide an alert until it changes. Dismissals older than FORGET_AFTER are dropped."""
    kept = {k: v for k, v in (store.get_state(STATE_KEY) or {}).items()
            if now - parse_dt(v) < FORGET_AFTER}
    kept[alert_id] = to_iso(now)
    store.set_state(STATE_KEY, kept)
    return {"id": alert_id, "dismissed_at": kept[alert_id]}
