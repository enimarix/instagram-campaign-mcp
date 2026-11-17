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
