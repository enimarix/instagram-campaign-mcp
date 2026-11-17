"""
Daily facts (step 082, GOAL.md §3 learning loop): what happened, computed from the DB with no
AI. The daily-learn agent reads them (083) and the daily report page shows them (085); they
are stored as daily_reports.facts under yesterday's owner-local date.

Two windows of owner-local days: `yesterday`, and `last_7_days` (the 7 days ending
yesterday). Posts are scored like rank_posts (analytics.scored_posts). Per window:
- published: posts whose posted_at falls in the window.
- matured: posts the scorer judges matured whose maturity time (posted_at + the scoring min
  age) falls in the window.
- winners / losers: matured posts scored `winner` / `weak`, with tags and the drivers.
  Matured, winner and loser rows carry `retention`: the Reel's retention findings (111,
  src/learning/retention.py; [] for other post types).
- slots: matured posts grouped by owner-local posting hour; best and worst hour by median
  engagement index, with n (small_sample when n < 3, as in the tag breakdowns).
- movers: views gained between a post's two most recent snapshots taken before the window
  ends, the later one taken in the window; top 5 up.
- funnel: 077's funnel totals and taste calibration for the window's batch days.
Not per window:
- experiments: published assets per idea `experiment`, all time; `reached` lists those with
  at least EXPERIMENT_MIN_SAMPLE (086 builds real experiments).
- audience_comments: the top 3 comments by likes of each post published in the last 7 days,
  read with the Graph comments call (a data job: it stops at the worker's budget share).
  Other people's words: untrusted data, never instructions.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from ..campaign import scoring_config
from ..config import InstagramMCPSettings
from ..instagram_client import InstagramAPIError, InstagramClient
from ..scoring import _is_matured, _min_age
from ..store import CampaignStore, parse_dt, to_iso, utcnow
from ..studio.seed import local_today
from .analytics import scored_posts, studio_side
from .breakdowns import _group
from .funnel import funnel, taste
from .retention import retention_all

WINDOWS = {"yesterday": 1, "last_7_days": 7}
LOSER = "weak"  # the scorer's lowest judged verdict
TOP_MOVERS = 5
TOP_COMMENTS = 3
QUOTE_CHARS = 300
_EXPERIMENTS = (
    "SELECT i.experiment, COUNT(*) AS published FROM assets a JOIN ideas i ON i.id = a.idea_id"
    " WHERE i.experiment IS NOT NULL AND i.experiment != '' AND a.status = 'published'"
    " GROUP BY i.experiment ORDER BY published DESC, i.experiment")

Scored = List[Tuple[Dict[str, Any], Dict[str, Any]]]


async def daily_facts(store: CampaignStore, settings: InstagramMCPSettings, *,
                      client: Optional[InstagramClient] = None,
                      now: datetime) -> Dict[str, Any]:
    """The facts of the owner-local day before `now` (see the module docstring). Without a
    client there are no audience comments (the section says why)."""
    tz = ZoneInfo(settings.timezone)
    yesterday = local_today(settings.timezone, now) - timedelta(days=1)
    scored = scored_posts(store, settings)
    facts: Dict[str, Any] = {"report_date": yesterday.isoformat(),
                             "timezone": settings.timezone, "generated_at": to_iso(utcnow())}
    week = max(WINDOWS.values())  # retention of every post that matured in any window
    retention = retention_all(
        store, settings, since=datetime.combine(yesterday - timedelta(days=week - 1), time(), tz),
        until=datetime.combine(yesterday + timedelta(days=1), time(), tz))
    for name, days in WINDOWS.items():
        facts[name] = _window(store, settings, scored, yesterday - timedelta(days=days - 1),
                              yesterday, tz, retention)
    facts["experiments"] = experiments(store, settings)
    facts["audience_comments"] = await _comments(client, facts["last_7_days"]["published"]["posts"])
    return facts


async def build_and_store(store: CampaignStore, settings: InstagramMCPSettings,
                          client: Optional[InstagramClient], now: datetime) -> Dict[str, Any]:
    """Compute the facts and store them under yesterday's date; a summary already written
    (by the daily-learn agent) is kept."""
    facts = await daily_facts(store, settings, client=client, now=now)
    old = store.get_daily_report(facts["report_date"])
    store.save_daily_report(date.fromisoformat(facts["report_date"]),
                            old and old["summary"], facts)
    return facts


async def facts_for(store: CampaignStore, settings: InstagramMCPSettings, *,
                    day: Optional[date] = None, client: Optional[InstagramClient] = None,
                    now: datetime) -> Dict[str, Any]:
    """The stored facts of owner-local `day` (default yesterday), computed and stored when
    missing. ValueError: today or later (the day is not over)."""
    today = local_today(settings.timezone, now)
    day = day or today - timedelta(days=1)
    if day >= today:
        raise ValueError(f"facts exist for past days only (today is {today})")
    report = store.get_daily_report(day)
    if report and report["facts"]:
        return report["facts"]
    day_after = datetime.combine(day + timedelta(days=1), time(), ZoneInfo(settings.timezone))
    return await build_and_store(store, settings, client, day_after)


def _window(store: CampaignStore, settings: InstagramMCPSettings, scored: Scored,
            first: date, last: date, tz: ZoneInfo,
            retention: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    start = datetime.combine(first, time(), tz)
    end = datetime.combine(last + timedelta(days=1), time(), tz)
    cfg = scoring_config(settings)

    def scored_row(snap: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, Any]:
        return {**_post(store, snap, s, scored=True),
                "retention": retention.get(snap["media_id"], [])}

    def within(at: Optional[str], hours: float = 0) -> bool:
        return bool(at) and start <= parse_dt(at) + timedelta(hours=hours) < end

    published = [(snap, s) for snap, s in scored if within(snap["posted_at"])]
    matured = [(snap, s) for snap, s in scored if _is_matured(snap, cfg)
               and within(snap["posted_at"], _min_age(s["group"], cfg))]
    noon = datetime.combine(last, time(12), tz)  # any time of `last` makes it 077's "today"
    days = (last - first).days + 1
    calibration = taste(store, settings, days=days, now=noon)["calibration"]
    return {
        "since": first.isoformat(), "until": last.isoformat(),
        "published": {"count": len(published),
                      "posts": [_post(store, snap, s) for snap, s in published]},
        "matured": {"count": len(matured),
                    "posts": [scored_row(snap, s) for snap, s in matured]},
        "winners": [scored_row(snap, s) for snap, s in matured if s["verdict"] == "winner"],
        "losers": [scored_row(snap, s) for snap, s in matured if s["verdict"] == LOSER],
        "slots": _slots(matured, tz),
        "movers": _movers(store, scored, start, end),
        "funnel": {**funnel(store, settings, days=days, now=noon)["totals"],
                   "calibration": calibration},
    }


def _post(store: CampaignStore, snap: Dict[str, Any], s: Dict[str, Any], *,
          scored: bool = False) -> Dict[str, Any]:
    asset_id = (s["label"] or {}).get("asset_id")  # 083: get_asset_frames(asset_id)
    row = {"media_id": snap["media_id"], "permalink": snap["permalink"], "asset_id": asset_id,
           "posted_at": snap["posted_at"], "product_type": snap["media_product_type"],
           "tags": studio_side(store, asset_id)["tags"]}
    if scored:
        row.update({k: s.get(k) for k in ("verdict", "engagement_index", "drivers", "why")})
    return row


def _slots(matured: Scored, tz: ZoneInfo) -> Dict[str, Any]:
    hours: Dict[int, Scored] = {}
    for snap, s in matured:
        hours.setdefault(parse_dt(snap["posted_at"]).astimezone(tz).hour, []).append((snap, s))
    groups = [g for g in (_group(h, posts) for h, posts in hours.items())
              if g["engagement_index"]]
    groups.sort(key=lambda g: (-g["engagement_index"]["median"], g["tag_value"]))

    def slot(g: Dict[str, Any]) -> Dict[str, Any]:
        return {"hour": g["tag_value"], "n": g["n"], "small_sample": g["small_sample"],
                "median_engagement_index": g["engagement_index"]["median"]}

    return {"best": slot(groups[0]) if groups else None,
            "worst": slot(groups[-1]) if len(groups) > 1 else None}


def _movers(store: CampaignStore, scored: Scored, start: datetime,
            end: datetime) -> List[Dict[str, Any]]:
    out = []
    for snap, _ in scored:
        if parse_dt(snap["captured_at"]) < start:  # nothing new in the window
            continue
        # ponytail: one query per post snapshotted in the window, a few dozen a week
        snaps = [x for x in store.media_snapshots(snap["media_id"])
                 if parse_dt(x["captured_at"]) < end]
        if len(snaps) < 2 or parse_dt(snaps[-1]["captured_at"]) < start:
            continue
        before, after = (x["metrics"].get("views") for x in snaps[-2:])
        if before is None or after is None or after <= before:
            continue
        out.append({"media_id": snap["media_id"], "permalink": snap["permalink"],
                    "views_before": before, "views_after": after, "gained": after - before,
                    "between": [snaps[-2]["captured_at"], snaps[-1]["captured_at"]]})
    return sorted(out, key=lambda m: -m["gained"])[:TOP_MOVERS]


def experiments(store: CampaignStore, settings: InstagramMCPSettings) -> Dict[str, Any]:
    """Published assets per experiment; `reached`: at least experiment_min_sample."""
    with store._tx() as c:
        rows = [dict(r) for r in c.execute(_EXPERIMENTS)]
    n = settings.experiment_min_sample
    return {"min_sample": n, "reached": [r for r in rows if r["published"] >= n],
            "under": [r for r in rows if r["published"] < n]}


async def _comments(client: Optional[InstagramClient],
                    posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Top comments per post, read only. Falls back to no comments with a note when there is
    no client, the data budget is spent or the call fails."""
    from ..worker import data_budget_left  # here: the worker imports this module

    out: Dict[str, Any] = {"untrusted": True, "note": None, "posts": []}
    if client is None:
        out["note"] = "Instagram not configured: no comments"
        return out
    for p in posts:
        if not data_budget_left(client):
            out["note"] = "request budget: comments not read for every post"
            break
        try:
            raw = await client.get_comments(p["media_id"])
        except InstagramAPIError as e:  # rate limits too; never echo a URL (it has the token)
            out["note"] = f"comments call failed: {e.message}"
            break
        except Exception as e:  # noqa: BLE001 - e.g. network: facts must still be stored
            out["note"] = f"comments call failed: {type(e).__name__}"
            break
        top = sorted((c for c in raw if not c.get("hidden") and c.get("text")),
                     key=lambda c: -(c.get("like_count") or 0))[:TOP_COMMENTS]
        out["posts"].append({"media_id": p["media_id"], "permalink": p["permalink"],
                             "comments": [{"quote": c["text"][:QUOTE_CHARS],
                                           "likes": c.get("like_count") or 0} for c in top]})
    return out
