"""
The daily report (step 083, GOAL.md §3.5 "The late-night analysis"): the daily-learn agent
writes its summary of a day whose facts exist (082), plus optional structured bits kept in
daily_reports.analysis: the best and worst Reels with why, and up to 3 proposed experiments
(one variable each; 086 builds real experiments, until then the next creative brief lists
them under last_daily_report). Re-running overwrites the day's summary and analysis.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ..config import InstagramMCPSettings
from ..store import CampaignStore
from ..studio.media import media_url
from ..studio.seed import local_today

SUMMARY_CHARS = 4000
MAX_PICKS = 3
MAX_EXPERIMENTS = 3
Text = Annotated[str, Field(min_length=1, max_length=500)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Pick(_Strict):
    media_id: Annotated[str, Field(min_length=1, max_length=64)]
    why: Text


class Experiment(_Strict):
    hypothesis: Text
    variable: Annotated[str, Field(min_length=1, max_length=100)]
    variants: Annotated[List[Annotated[str, Field(min_length=1, max_length=200)]],
                        Field(min_length=2, max_length=4)]


_PICKS = TypeAdapter(Annotated[List[Pick], Field(max_length=MAX_PICKS)])
_EXPERIMENTS = TypeAdapter(Annotated[List[Experiment], Field(max_length=MAX_EXPERIMENTS)])


def _matured_ids(facts: Dict[str, Any]) -> set:
    return {p["media_id"] for window in ("yesterday", "last_7_days")
            for p in facts.get(window, {}).get("matured", {}).get("posts", [])}


def save_daily_report(store: CampaignStore, settings: InstagramMCPSettings, report_date: str,
                      summary: str, *, best: Optional[List[Dict[str, Any]]] = None,
                      worst: Optional[List[Dict[str, Any]]] = None,
                      experiments: Optional[List[Dict[str, Any]]] = None,
                      now: datetime) -> Dict[str, Any]:
    """Write the summary (markdown, ≤ SUMMARY_CHARS) and analysis of owner-local
    `report_date` (YYYY-MM-DD, a past day whose facts are stored). best / worst name matured
    posts of the facts. Returns the report row; ValueError on anything invalid."""
    try:
        day = datetime.strptime(report_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValueError(f"report_date must be YYYY-MM-DD, got {report_date!r}") from None
    today = local_today(settings.timezone, now)
    if day >= today:
        raise ValueError(f"reports are for past days only (today is {today})")
    report = store.get_daily_report(day)
    if not report or not report["facts"]:
        raise ValueError(f"no facts for {day}: read get_daily_facts first")
    summary = (summary or "").strip()
    if not summary or len(summary) > SUMMARY_CHARS:
        raise ValueError(f"summary must be 1–{SUMMARY_CHARS} characters, got {len(summary)}")
    analysis = {"best": _PICKS.validate_python(best or []),
                "worst": _PICKS.validate_python(worst or []),
                "experiments": _EXPERIMENTS.validate_python(experiments or [])}
    unknown = {p.media_id for p in analysis["best"] + analysis["worst"]} - _matured_ids(
        report["facts"])
    if unknown:
        raise ValueError(f"not a matured post of the facts: {', '.join(sorted(unknown))}")
    return store.save_daily_analysis(day, summary, {
        k: [m.model_dump() for m in v] for k, v in analysis.items()})


# --- The report page (step 085) ---
ARCHIVE_MAX = 365
TITLE_CHARS = 80
_ARCHIVE = (
    "SELECT report_date, summary,"
    " json_extract(facts, '$.yesterday.published.count') AS published,"
    " json_extract(facts, '$.yesterday.matured.count') AS matured,"
    " COALESCE(json_array_length(analysis, '$.best'), 0) AS best,"
    " COALESCE(json_array_length(analysis, '$.worst'), 0) AS worst,"
    " COALESCE(json_array_length(analysis, '$.experiments'), 0) AS experiments"
    " FROM daily_reports")


def report_archive(store: CampaignStore, limit: int = 60) -> List[Dict[str, Any]]:
    """The stored days, newest first: date, the summary's first line (None on a quiet day the
    agent skipped) and counts. ValueError: limit outside 1–ARCHIVE_MAX."""
    if not 1 <= limit <= ARCHIVE_MAX:
        raise ValueError(f"limit must be 1–{ARCHIVE_MAX}")
    rows = store._select(_ARCHIVE, {}, "report_date DESC", limit)  # store.py is a hot file
    for r in rows:
        r["first_line"] = (r.pop("summary") or "").strip().split("\n", 1)[0].lstrip("# ") or None
    return rows


def report_page(store: CampaignStore, report_date: Optional[str] = None) -> Dict[str, Any]:
    """One stored day (default: the newest with a summary) with `posts`: per media id named in
    best / worst / winners / losers, its permalink, thumbnail, title (caption's first line),
    asset id and retention findings, so the page links to /analytics/posts/:id.
    KeyError: no such day (or no report yet)."""
    report = (store.get_daily_report(report_date) if report_date
              else store.latest_daily_report())
    if not report:
        raise KeyError(f"No daily report for {report_date or 'any day'}")
    facts, analysis = report["facts"] or {}, report.get("analysis") or {}
    rows: Dict[str, Dict[str, Any]] = {}  # facts rows by media id, matured ones carry retention
    for window in ("last_7_days", "yesterday"):
        w = facts.get(window) or {}
        for p in (w.get("matured") or {}).get("posts", []) + w.get("winners", []) \
                + w.get("losers", []):
            rows[p["media_id"]] = {**rows.get(p["media_id"], {}), **p}
    ids = {p["media_id"] for k in ("best", "worst") for p in analysis.get(k, [])}
    ids |= {p["media_id"] for w in ("yesterday", "last_7_days")
            for k in ("winners", "losers") for p in (facts.get(w) or {}).get(k, [])}
    latest = {s["media_id"]: s for s in store.latest_snapshots()} if ids else {}
    posts = {}
    for mid in sorted(ids):
        snap, row = latest.get(mid) or {}, rows.get(mid) or {}
        asset_id = (store.get_label(mid) or {}).get("asset_id")
        caption = (snap.get("caption") or "").strip().split("\n", 1)[0][:TITLE_CHARS]
        posts[mid] = {"media_id": mid, "permalink": snap.get("permalink") or row.get("permalink"),
                      "title": caption or None, "asset_id": asset_id,
                      "thumbnail_url": asset_id and media_url(
                          store.get_asset(asset_id)["thumbnail_path"]),
                      "verdict": row.get("verdict"), "retention": row.get("retention", [])}
    return {"report_date": report["report_date"], "summary": report["summary"],
            "facts": facts, "analysis": analysis, "posts": posts}
