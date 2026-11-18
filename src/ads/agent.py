"""The agent's side of ads (096; AI-run since 126): it proposes, launches and stops A/B
tests and reads results.

Money moves only through the guard: `launch` goes through `tests.launch` (the caps read
fresh, the kill switch, `ads_max_running_tests`, never underpowered, the budget picked
from the need), `stop` through `tests.cancel` (a pause). Nothing here reaches unkill,
the settings, the writer or `authorize_spend` directly: tests/test_ads_agent.py walks
the calls from every agent tool to prove it. Every action is audited `actor = "agent"`.
Until ads are set up (H6) each answers {"error": "ads_not_configured", "message"}.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..config import InstagramMCPSettings
from ..store import CampaignStore
from . import sync, tests
from .budget import BudgetRefused
from .writer import missing_settings

OPEN = ("proposed", "approved", "running")
MAX_HYPOTHESIS = 500


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


async def _refused(work: Any) -> Dict[str, Any]:
    try:
        return await work
    except (tests.AdTestRefused, BudgetRefused) as e:
        raise ValueError(f"{e.code}: {e.message}") from None
    except tests.AdTestFailed as e:  # Meta failed after requests went out
        raise ValueError(f"failed: {e}") from None


async def launch(store: CampaignStore, settings: InstagramMCPSettings,
                 test_id: int) -> Dict[str, Any]:
    """Launch one of the agent's proposed tests within the caps (the owner's proposals
    wait for the owner). ValueError '<code>: <why>' when refused."""
    refused = not_configured(settings)
    if refused:
        return refused
    if store._get("ad_tests", test_id)["proposed_by"] != "agent":
        raise ValueError(f"owner_test: test {test_id} was proposed by the owner, who "
                         "launches it")
    return await _refused(tests.launch(store, settings, test_id, actor="agent"))


async def stop(store: CampaignStore, settings: InstagramMCPSettings, test_id: int,
               reason: str) -> Dict[str, Any]:
    """Pause a test's ads and cancel it. ValueError '<code>: <why>' when refused."""
    if not (reason or "").strip() or len(reason) > MAX_HYPOTHESIS:
        raise ValueError(f"invalid: a reason of 1 to {MAX_HYPOTHESIS} characters is needed")
    return not_configured(settings) or await _refused(tests.cancel(
        store, settings, test_id, reason=f"stopped by the AI: {reason.strip()}",
        actor="agent"))


async def propose(store: CampaignStore, settings: InstagramMCPSettings, *, hypothesis: str,
                  variable: str, variants: Any, min_lift: float = 0.2,
                  primary_metric: str = "ctr") -> Dict[str, Any]:
    """A proposed test, `proposed_by` agent. ValueError '<code>: <why>' when refused."""
    refused = not_configured(settings)
    if refused:
        return refused
    if len(hypothesis or "") > MAX_HYPOTHESIS:  # the website's limit (api/ads.py)
        raise ValueError(f"invalid: a hypothesis has at most {MAX_HYPOTHESIS} characters")
    return await _refused(tests.propose(
        store, settings, hypothesis=hypothesis, variable=variable, variants=variants,
        min_lift=min_lift, primary_metric=primary_metric, proposed_by="agent"))


def _brief(test: Dict[str, Any]) -> Dict[str, Any]:
    ev = (test.get("result") or {}).get("evaluation") or {}
    return {**{k: test[k] for k in ("id", "status", "hypothesis", "variable", "variants",
                                    "proposed_by", "launched_by", "min_lift", "reason",
                                    "finished_at", "underpowered")},
            "primary_metric": test["spec"]["primary_metric"],
            "evaluation": {k: ev.get(k) for k in ("status", "winner", "lift", "p_values",
                                                  "variants")}}


def _learned(store: CampaignStore) -> set:
    return {str(e.get("test_id")) for row in store.list_learnings(origin="ads", limit=100_000)
            for e in row["evidence"] if isinstance(e, dict)}


def work_packet(store: CampaignStore, settings: InstagramMCPSettings) -> Tuple[Any, int]:
    """The `ads` section of a work packet and its count: eligible winners (only while the
    agent may still propose), open tests, how many more may run now (`launches_left`;
    the agent's waiting proposals count only while it is above 0), and finished tests no
    ads learning cites yet (evidence `test_id`). Not configured: count 0, so the run is
    skipped."""
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
    launches = max(settings.ads_max_running_tests
                   - sum(t["status"] in tests.OPEN_RUNNING for t in rows), 0)
    return {"configured": True, "proposals_left": room, "winners": found,
            "launches_left": launches,
            "open_tests": [_brief(t) for t in rows if t["status"] in OPEN],
            "to_learn": to_learn}, len(to_learn) + len(found) + (waiting if launches else 0)
