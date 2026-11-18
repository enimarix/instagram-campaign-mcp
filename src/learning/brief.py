"""
Creative brief (step 055, GOAL.md §3): everything the agent needs to plan today's batch, in
one compact JSON. Every list is capped and long texts are cut; no recipe props.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..config import APP_HOME, InstagramMCPSettings
from ..store import CampaignStore
from ..studio.scheduling import bench
from ..studio.seed import local_today
from .experiments import explore_plan
from .learnings import get_feedback, list_learnings, list_revision_requests
from .mix import batch_mix, with_counts
from .quotas import todays_quotas

BIBLE_PATH = APP_HOME / "brand" / "BIBLE.md"
BIBLE_CHARS = 8000
REPORT_CHARS = 2000
NO_BIBLE = "no channel bible yet: follow brand/taxonomy.json and the learnings"
INSPIRATIONS = 20
IDEA_KEYS = ("id", "track", "pillar", "hook_type", "strategy", "hook")
EXPERIMENT_KEYS = ("id", "status", "hypothesis", "variable", "variants",
                   "target_per_variant", "ends_on")


def _cut(text: Optional[str], n: int) -> Optional[str]:
    return text if text is None or len(text) <= n else text[:n] + "…"


def _bible() -> Optional[str]:
    if not BIBLE_PATH.is_file():
        return None
    return _cut(BIBLE_PATH.read_text(encoding="utf-8"), BIBLE_CHARS)


def _rows(store: CampaignStore, sql: str, *args: Any) -> List[Dict[str, Any]]:
    with store._tx() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def creative_brief(store: CampaignStore, settings: InstagramMCPSettings,
                   now: datetime) -> Dict[str, Any]:
    """The brief for the owner-local day of `now` (see the module docstring)."""
    today = local_today(settings.timezone, now)
    bible = _bible()
    report = store.latest_daily_report()
    on_bench = bench(store, settings, now)
    since_hooks = (today - timedelta(days=settings.dedupe_days)).isoformat()
    mix = batch_mix(store, settings, today, now=now)  # first: the quotas read its humour share
    quotas = todays_quotas(store, settings, today, now)
    return {
        "bible": bible,
        "bible_note": None if bible else NO_BIBLE,
        "learnings": [{k: row[k] for k in ("id", "statement", "kind", "confidence", "origin",
                                           "scope")} | {"evidence_count": len(row["evidence"])}
                      for row in list_learnings(store, limit=40)],
        "feedback": get_feedback(store, limit=30),
        "change_requests": list_revision_requests(store)[:30],
        "last_daily_report": report and {"report_date": report["report_date"],
                                         "summary": _cut(report["summary"], REPORT_CHARS),
                                         # 083: ideas to try (also proposed rows below)
                                         "proposed_experiments":
                                             report["analysis"].get("experiments", [])},
        # 086: open experiments, then the newest proposals (open_experiment(proposed_id=))
        "experiments": [{k: e[k] for k in EXPERIMENT_KEYS}
                        for status in ("open", "proposed")
                        for e in store.list_experiments(status, limit=10)],
        # which open experiment variant each explore idea still to make today fills
        "explore_plan": explore_plan(
            store, quotas["limits"]["explore"] - quotas["counts"]["explore"]),
        "quotas": quotas,
        # Exploit ideas follow the mix; explore ideas (limits.explore) are free picks.
        "mix": with_counts(mix, quotas["limits"]["ideas"] - quotas["limits"]["explore"]),
        "today": [{k: i[k] for k in IDEA_KEYS}
                  for i in store.list_ideas(batch_date=today, limit=100)],
        "recent_hooks": [r["hook"] for r in _rows(
            store, "SELECT hook FROM ideas WHERE batch_date >= ? AND hook IS NOT NULL"
                   " AND hook != '' ORDER BY id DESC LIMIT 60", since_hooks)],
        # Reels the owner pasted with a note, not used or dismissed yet (step 051b).
        "inspirations": [{k: r[k] for k in ("id", "url", "note", "created_at")}
                         for r in store.list_inspirations("new", limit=INSPIRATIONS)],
        "bench": {"count": len(on_bench["assets"]), "supply_days": on_bench["supply_days"],
                  "hooks": [store.get_idea(a["idea_id"])["hook"]
                            for a in on_bench["assets"][:10]]},
    }
