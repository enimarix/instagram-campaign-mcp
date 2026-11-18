"""
Studio funnel and taste metrics (step 077, GOAL.md §2.1, §3.2). Computed from the DB, no AI.

Window: assets whose owner-local `batch_date` falls in the last `days` days, today included.
Every metric below is about the assets of the window (feedback reasons too).

- produced: the asset reached `ready` or `failed` (a QC result is stored).
- reviewed: the owner acted on it: verdict liked/disliked, approved (approved_at set), a
  comment, or a status only the owner can lead to (revision_requested, approved, scheduled,
  publish_check, published). An archive alone does not count: the data can't tell the
  owner's archive from the worker's.
- liked: verdict liked. approved: approved_at set (unapprove clears it).
- published: status published, or a published queue row with the asset's id.
- winner: the published post scores `winner` (src/scoring.py, same path as 074).
- like-rate = liked / reviewed per batch day, plus a 7-day rolling value (sums over the
  day and the 6 before). The taste metric.
- approval rate = approved / reviewed: shown, but capped by MAX_POSTS_PER_DAY, so it says
  more about the posting limit than about taste.
- calibration: per batch day with at least 5 reviewed assets carrying a self_score, how many
  of the agent's top 5 (by self_score) the owner liked; plus the mean self_score of liked
  vs disliked assets.
- waste: liked assets archived without ever being approved, after their best_before. No
  archive actor or date is stored: the archive date is the owner-local date of updated_at,
  minus DELETE_ARCHIVED_FILES_DAYS once housekeeping purged the files (that edit moves
  updated_at). Count and the render minutes spent on them (sum of render_jobs.render_ms).
- reasons: how often each feedback reason code was given, with its taxonomy label.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from ..campaign import scoring_config
from ..config import InstagramMCPSettings
from ..scoring import score_posts
from ..store import CampaignStore, parse_dt
from ..studio.seed import local_today
from .learnings import _labels

GROUPS = ("day", "track", "template", "hook_type")
STAGES = ("produced", "reviewed", "liked", "approved", "published", "winner")
ROLLING_DAYS = 7
TOP_N = 5
APPROVAL_NOTE = "capped by the posts-per-day limit"

_ASSETS_SQL = """
SELECT a.id, a.batch_date AS day, i.track, i.hook_type, a.status, a.verdict, a.self_score,
       a.best_before, a.updated_at, a.approved_at IS NOT NULL AS approved,
       a.file_path IS NULL AS purged,
       CASE WHEN json_extract(a.recipe, '$.kind') = 'motion'
            THEN json_extract(a.recipe, '$.template') END AS template,
       a.qc IS NOT NULL AS produced,
       (a.verdict != 'none' OR a.approved_at IS NOT NULL
        OR a.status IN ('revision_requested','approved','scheduled','publish_check','published')
        OR EXISTS (SELECT 1 FROM feedback f WHERE f.asset_id = a.id)) AS reviewed,
       (a.status = 'published' OR EXISTS (SELECT 1 FROM scheduled_posts p
        WHERE p.asset_id = a.id AND p.status = 'published')) AS published,
       (SELECT COALESCE(SUM(render_ms), 0) FROM render_jobs r WHERE r.asset_id = a.id)
           AS render_ms
FROM assets a JOIN ideas i ON i.id = a.idea_id
WHERE a.batch_date >= ? AND a.batch_date <= ?
"""


def _window(settings: InstagramMCPSettings, days: int,
            now: Optional[datetime]) -> Tuple[date, date]:
    if days < 1:
        raise ValueError("days must be at least 1")
    today = local_today(settings.timezone, now)
    return today - timedelta(days=days - 1), today


def _assets(store: CampaignStore, since: date, until: date) -> List[Dict[str, Any]]:
    with store._tx() as c:  # ponytail: one row per asset, a few thousand a year
        rows = [dict(r) for r in c.execute(_ASSETS_SQL, (since.isoformat(), until.isoformat()))]
    for r in rows:
        r["liked"] = r["verdict"] == "liked"
    return rows


def _winners(store: CampaignStore, settings: InstagramMCPSettings) -> set:
    """Asset ids whose post scores `winner` against the account's other posts."""
    labels = store.labels()
    latest = store.latest_snapshots()
    scored = score_posts(latest, scoring_config(settings), labels,
                         near_age=store.snapshots_near_age)
    return {(labels.get(s["media_id"]) or {}).get("asset_id")
            for s in scored if s["verdict"] == "winner"} - {None}


def _rate(num: int, den: int) -> Optional[float]:
    return round(num / den, 3) if den else None


def funnel(store: CampaignStore, settings: InstagramMCPSettings, *, days: int = 30,
           group_by: str = "day", now: Optional[datetime] = None) -> Dict[str, Any]:
    """Stage counts per group, with like and approval rates. ValueError: bad group_by/days."""
    if group_by not in GROUPS:
        raise ValueError(f"group_by must be one of {GROUPS}")
    since, until = _window(settings, days, now)
    rows = _assets(store, since, until)
    winners = _winners(store, settings) if any(r["published"] for r in rows) else set()
    groups: Dict[Any, Counter] = defaultdict(Counter)
    for r in rows:
        r["winner"] = r["published"] and r["id"] in winners
        for stage in STAGES:
            groups[r[group_by]][stage] += bool(r[stage])

    def stats(c: Counter) -> Dict[str, Any]:
        return {**{s: c[s] for s in STAGES}, "like_rate": _rate(c["liked"], c["reviewed"]),
                "approval_rate": _rate(c["approved"], c["reviewed"])}

    return {
        "since": since.isoformat(), "until": until.isoformat(), "group_by": group_by,
        "approval_rate_note": APPROVAL_NOTE,
        "groups": [{"key": k, **stats(groups[k])}
                   for k in sorted(groups, key=lambda k: (k is None, k or ""))],
        "totals": stats(sum(groups.values(), Counter())),
    }


def taste(store: CampaignStore, settings: InstagramMCPSettings, *, days: int = 30,
          now: Optional[datetime] = None) -> Dict[str, Any]:
    """Like-rate series (with 7-day rolling), calibration, waste and feedback reasons."""
    since, until = _window(settings, days, now)
    rows = _assets(store, since - timedelta(days=ROLLING_DAYS - 1), until)
    by_day: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_day[r["day"]].append(r)
    window = [r for r in rows if r["day"] >= since.isoformat()]

    series = []
    for n in range(days):
        d = since + timedelta(days=n)
        past = [r for k in range(ROLLING_DAYS)
                for r in by_day[(d - timedelta(days=k)).isoformat()] if r["reviewed"]]
        day_rows = [r for r in past if r["day"] == d.isoformat()]
        liked = sum(r["liked"] for r in day_rows)
        series.append({
            "date": d.isoformat(), "reviewed": len(day_rows), "liked": liked,
            "like_rate": _rate(liked, len(day_rows)),
            "rolling_7d": _rate(sum(r["liked"] for r in past), len(past)),
        })

    calibration = []
    for day in sorted({r["day"] for r in window}):
        scored = [r for r in by_day[day] if r["reviewed"] and r["self_score"] is not None]
        if len(scored) >= TOP_N:
            top = sorted(scored, key=lambda r: (-r["self_score"], r["id"]))[:TOP_N]
            calibration.append({"date": day, "scored": len(scored),
                                "top_liked": sum(r["liked"] for r in top), "top_n": TOP_N})

    def mean_score(verdict: str) -> Optional[float]:
        s = [r["self_score"] for r in window
             if r["verdict"] == verdict and r["self_score"] is not None]
        return round(sum(s) / len(s), 2) if s else None

    def archived_on(r: Dict[str, Any]) -> str:
        day = parse_dt(r["updated_at"]).astimezone(ZoneInfo(settings.timezone)).date()
        # ponytail: purge runs ~delete_archived_files_days after the archive; an archive
        # date column would make this exact.
        if r["purged"]:
            day -= timedelta(days=settings.delete_archived_files_days)
        return day.isoformat()

    wasted = [r for r in window
              if r["liked"] and r["status"] == "archived" and not r["approved"]
              and r["best_before"] and r["best_before"] < archived_on(r)]

    return {
        "since": since.isoformat(), "until": until.isoformat(),
        "like_rate": series,
        "calibration": {"days": calibration,
                        "mean_self_score": {"liked": mean_score("liked"),
                                            "disliked": mean_score("disliked")}},
        "waste": {"count": len(wasted), "asset_ids": [r["id"] for r in wasted],
                  "render_minutes": round(sum(r["render_ms"] for r in wasted) / 60000, 1)},
        "reasons": _reasons(store, since, until),
    }


def _reasons(store: CampaignStore, since: date, until: date) -> List[Dict[str, Any]]:
    """Feedback reason codes given on the window's assets, most frequent first."""
    with store._tx() as c:
        rows = c.execute(
            "SELECT j.value AS code, COUNT(*) AS n FROM feedback f, json_each(f.reason_codes) j"
            " WHERE f.asset_id IN (SELECT id FROM assets WHERE batch_date >= ?"
            " AND batch_date <= ?) GROUP BY j.value ORDER BY n DESC, j.value",
            (since.isoformat(), until.isoformat())).fetchall()
    labels = _labels()
    return [{"code": r["code"], "label": labels.get(r["code"], r["code"]), "count": r["n"]}
            for r in rows]
