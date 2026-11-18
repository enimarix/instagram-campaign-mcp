"""The agent's side of ads (step 096): it proposes A/B tests and reads results, nothing more.

Every function here reads, or stores a proposal (`proposed_by = "agent"`, at most
tests.MAX_AGENT_PROPOSALS waiting) that only the owner can approve, in the website, with
the password. None reaches approve, cancel, activate, the kill switch, the caps or the
writer: tests/test_ads_agent.py walks the calls from every agent tool to prove it.
Until ads are set up (H6) each answers {"error": "ads_not_configured", "message"}.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..config import InstagramMCPSettings
from ..store import CampaignStore
from . import sync, tests
from .writer import missing_settings

OPEN = ("proposed", "approved", "running")


def not_configured(settings: InstagramMCPSettings) -> Optional[Dict[str, str]]:
    missing = missing_settings(settings)
    return {"error": "ads_not_configured", "message": "ads are not set up yet (owner step "
            f"H6): {', '.join(missing)} missing in .env"} if missing else None


def winners(store: CampaignStore, settings: InstagramMCPSettings) -> Dict[str, Any]:
    return not_configured(settings) or {"winners": tests.eligible_winners(store, settings)}


def list_tests(store: CampaignStore, settings: InstagramMCPSettings,
               status: Optional[str] = None) -> Dict[str, Any]:
    return not_configured(settings) or {"tests": tests.list_tests(store, settings,
                                                                  status=status)}


def results(store: CampaignStore, settings: InstagramMCPSettings,
            test_id: int) -> Dict[str, Any]:
    return not_configured(settings) or sync.results(store, settings, test_id)


async def propose(store: CampaignStore, settings: InstagramMCPSettings, *, hypothesis: str,
                  variable: str, variants: Any, min_lift: float = 0.2,
                  primary_metric: str = "ctr") -> Dict[str, Any]:
    """A proposed test, `proposed_by` agent. ValueError '<code>: <why>' when refused."""
    refused = not_configured(settings)
    if refused:
        return refused
    try:
        return await tests.propose(store, settings, hypothesis=hypothesis, variable=variable,
                                   variants=variants, min_lift=min_lift,
                                   primary_metric=primary_metric, proposed_by="agent")
    except tests.AdTestRefused as e:
        raise ValueError(f"{e.code}: {e.message}") from None


def _brief(test: Dict[str, Any]) -> Dict[str, Any]:
    ev = (test.get("result") or {}).get("evaluation") or {}
    return {**{k: test[k] for k in ("id", "status", "hypothesis", "variable", "variants",
                                    "proposed_by", "min_lift", "reason", "finished_at")},
            "primary_metric": test["spec"]["primary_metric"],
            "evaluation": {k: ev.get(k) for k in ("status", "winner", "lift", "p_values",
                                                  "variants")}}


def _learned(store: CampaignStore) -> set:
    return {str(e.get("test_id")) for row in store.list_learnings(origin="ads", limit=100_000)
            for e in row["evidence"] if isinstance(e, dict)}


def work_packet(store: CampaignStore, settings: InstagramMCPSettings) -> Tuple[Any, int]:
    """The `ads` section of a work packet and its count: eligible winners (only while the
    agent may still propose), open tests, and finished tests no ads learning cites yet
    (evidence `test_id`). Not configured: count 0, so the run is skipped."""
    refused = not_configured(settings)
    if refused:
        return {"configured": False, "message": refused["message"]}, 0
    rows = tests.list_tests(store, settings, limit=100)
    waiting = sum(t["status"] == "proposed" and t["proposed_by"] == "agent" for t in rows)
    room = max(tests.MAX_AGENT_PROPOSALS - waiting, 0)
    learned = _learned(store)
    found: List[Dict[str, Any]] = tests.eligible_winners(store, settings) if room else []
    to_learn = [_brief(t) for t in rows
                if t["status"] == "finished" and str(t["id"]) not in learned]
    return {"configured": True, "proposals_left": room, "winners": found,
            "open_tests": [_brief(t) for t in rows if t["status"] in OPEN],
            "to_learn": to_learn}, len(to_learn) + len(found)
