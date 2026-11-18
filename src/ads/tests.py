"""Paid A/B tests (step 094, AI-run since 126): propose, launch (the one place ads go
ACTIVE), cancel.

- `propose`: 2-4 variants {media_id, preset} that differ in ONE variable: `creative` =
  different posts with one preset; `audience` / `placement` = one post with presets that
  differ only in audience keys / only in placement keys. Every post is a published studio
  asset that may be advertised (rights, `can_advertise`) and that Meta does not call
  unboostable (`boost_eligibility_info`, e.g. copyrighted music). The budget it needs is
  `abtest.budget_needed` at the account's usual rates: spend × 1000 / impressions (CPM)
  and clicks / impressions (the CTR baseline) of its last 90 days of insights, else
  `ADS_DEFAULT_CPM` and DEFAULT_CTR. `underpowered` says whether the caps can fund it.
- `launch`: by the owner (Approve in the website, no password since 126) or the agent
  (`budget=None`: the need, capped by what the caps allow; never underpowered). Refuses
  (before any request) unless the test is proposed, every post is still advertisable,
  the budget covers the need (or the owner's `underpowered_ok`, stored and audited),
  fewer than `ads_max_running_tests` run and the caps (read fresh) allow the whole
  budget. Splits it equally per variant, creates each paused
  (`promote.create_paused_promotion`), then activates ad → ad set → campaign of every
  variant. On any failure: what was activated is paused again, the reservations of
  variants never activated are released, and the test is cancelled with the reason.
  ponytail: one campaign per variant with equal budgets, not a Meta ad_studies SPLIT_TEST
  (it needs a Business ID, not set before H6): audiences may overlap between variants.
- `cancel`: pauses the test's campaigns, ad sets and ads (a pause write: no spend).
  A running test keeps its reservations: 095 reconciles the spend Meta reports first.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from itertools import combinations
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import structlog

from ..config import InstagramMCPSettings
from ..instagram_client import InstagramAPIError, NotConfigured
from ..learning.analytics import scored_posts
from ..settings_overrides import refresh
from ..store import CampaignStore, to_iso, utcnow
from ..studio.media import media_url
from . import abtest
from .budget import _amount, audit, authorize_spend, open_authorizations, release
from .budget import status as budget_status
from .client import AdsClient
from .promote import (
    CENT,
    PRESET_LABELS,
    PRESETS,
    PromotionRefused,
    _advertisable_asset,
    create_paused_promotion,
)
from .writer import ACTIVE, PAUSED, AdsWriter, missing_settings

logger = structlog.get_logger(__name__)

TEST_FIELDS = ("hypothesis", "variable", "variants", "spec", "baseline_rate", "min_lift",
               "needed", "budget_total", "currency", "end_date", "status", "underpowered_ok",
               "reason", "proposed_by", "approved_at", "finished_at", "result")
PLACEMENT_KEYS = {"publisher_platforms", "instagram_positions"}
DEFAULT_CTR = 0.01  # ponytail: a low guess (larger sample) until the account has insights
MIN_IMPRESSIONS = 1000  # fewer: the account's own rates are noise, use the defaults
PAUSE_ORDER = {"campaign": 0, "adset": 1, "ad": 2}  # the campaign first stops everything
MAX_AGENT_PROPOSALS = 3  # agent proposals not launched yet, at once (096)
OPEN_RUNNING = ("approved", "running")  # count against ads_max_running_tests


class AdTestRefused(Exception):
    """Nothing was sent. code: invalid | rights | not_ours | not_published | not_boostable |
    status | underpowered | not_configured | cap | max_running."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class AdTestFailed(Exception):
    """Meta (or the guard) failed after requests went out; the test is cancelled."""


def _differ_only(a: str, b: str, variable: str) -> bool:
    """Presets a and b differ, and only in `variable` (audience or placement)."""
    changed = {k for k in {*PRESETS[a], *PRESETS[b]} if PRESETS[a].get(k) != PRESETS[b].get(k)}
    return bool(changed) and (changed <= PLACEMENT_KEYS if variable == "placement"
                              else changed.isdisjoint(PLACEMENT_KEYS))


def presets() -> List[Dict[str, Any]]:
    """Each preset with its plain label and the variables it can be compared on (a test of
    that variable may pair it with another preset)."""
    return [{"id": p, "label": PRESET_LABELS[p],
             "varies": [v for v in ("audience", "placement")
                        if any(_differ_only(p, q, v) for q in PRESETS)]}
            for p in PRESETS]


def _variants(variable: str, variants: Any) -> List[Dict[str, str]]:
    if not isinstance(variants, list) or not 2 <= len(variants) <= 4:
        raise AdTestRefused("invalid", "a test has 2 to 4 variants")
    out = []
    for v in variants:
        media, preset = (v or {}).get("media_id"), (v or {}).get("preset")
        if not (isinstance(media, str) and media.isascii() and media.isdigit()
                and preset in PRESETS):
            raise AdTestRefused("invalid", f"each variant needs a media_id and a preset "
                                f"(one of {sorted(PRESETS)})")
        out.append({"media_id": media, "preset": preset})
    medias = {v["media_id"] for v in out}
    presets = [v["preset"] for v in out]
    if variable == "creative":
        ok = len(medias) == len(out) and len(set(presets)) == 1
    else:
        ok = len(medias) == 1 and len(set(presets)) == len(out)
        ok = ok and all(_differ_only(a, b, variable) for a, b in combinations(presets, 2))
    if not ok:
        raise AdTestRefused("invalid", f"variants must differ in {variable} only: "
                            "creative = different posts, one preset; audience / placement"
                            " = one post, presets that differ only in that")
    return out


async def usual_rates(client: AdsClient, settings: InstagramMCPSettings) -> Dict[str, Any]:
    """CPM, CPC and CTR of the account's last 90 days, else the defaults."""
    try:
        rows = await client.get_insights(date_preset="last_90d")
    except NotConfigured:  # no ad account yet (H6)
        rows = []
    imp = sum(int(r.get("impressions") or 0) for r in rows)
    clicks = sum(int(r.get("clicks") or 0) for r in rows)
    spend = sum((Decimal(str(r.get("spend") or 0)) for r in rows), Decimal(0))
    if imp < MIN_IMPRESSIONS or spend <= 0:
        return {"cpm": float(settings.ads_default_cpm), "cpc": None, "ctr": DEFAULT_CTR,
                "source": "default"}
    return {"cpm": float(spend * 1000 / imp), "cpc": float(spend / clicks) if clicks else None,
            "ctr": clicks / imp if clicks else DEFAULT_CTR, "source": "insights"}


async def propose(
    store: CampaignStore,
    settings: InstagramMCPSettings,
    *,
    hypothesis: str,
    variable: str,
    variants: Any,
    min_lift: float = 0.2,
    primary_metric: str = "ctr",
    baseline_rate: Optional[float] = None,
    proposed_by: str = "owner",
    client: Optional[AdsClient] = None,
) -> Dict[str, Any]:
    """Store a proposed test. Returns it with `underpowered` (None or why) and `summary`."""
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        raise AdTestRefused("invalid", "a hypothesis is required")
    if variable not in abtest.VARIABLES:
        raise AdTestRefused("invalid", f"variable must be one of {abtest.VARIABLES}")
    if proposed_by not in ("owner", "agent"):
        raise AdTestRefused("invalid", "proposed_by is owner or agent")
    if proposed_by == "agent":  # ponytail: count then insert, one agent run at a time
        with store._tx() as c:
            waiting = c.execute("SELECT COUNT(*) FROM ad_tests WHERE proposed_by='agent'"
                                " AND status='proposed'").fetchone()[0]
        if waiting >= MAX_AGENT_PROPOSALS:
            raise AdTestRefused("cap", f"{waiting} agent proposals already wait for the "
                                "owner (MAX_AGENT_PROPOSALS): propose again once they decide")
    rows = _variants(variable, variants)
    for v in rows:
        try:
            _advertisable_asset(store, v["media_id"])
        except PromotionRefused as e:
            raise AdTestRefused(e.code, e.message) from None
    own = client is None
    client = client or AdsClient(settings, store=store)
    try:
        for media in dict.fromkeys(v["media_id"] for v in rows):
            info = await client.boost_eligibility(media)
            if info.get("eligible_to_boost") is False:
                why = {k: v for k, v in info.items() if k != "eligible_to_boost"}
                raise AdTestRefused("not_boostable", f"Meta says post {media} cannot be "
                                    f"promoted: {why or 'no reason given'}")
        rates = await usual_rates(client, settings)
    finally:
        if own:
            await client.close()
    try:
        spec = abtest.TestSpec(variable, variants=len(rows), primary_metric=primary_metric,
                               min_days=settings.ads_test_days)
        baseline = baseline_rate if baseline_rate is not None else (
            rates["ctr"] if primary_metric == "ctr" else None)
        if baseline is None:
            raise ValueError(f"give baseline_rate for {primary_metric}")
        spec = replace(spec, min_sample=abtest.sample_size(
            baseline, min_lift, spec.alpha, spec.power, comparisons=spec.comparisons))
        needed = abtest.budget_needed(spec, baseline, min_lift, cpm=rates["cpm"],
                                      cpc=rates["cpc"])
    except ValueError as e:
        raise AdTestRefused("invalid", str(e)) from None
    test = store._insert("ad_tests", TEST_FIELDS, {
        "hypothesis": hypothesis.strip(), "variable": variable, "variants": rows,
        "spec": asdict(spec), "baseline_rate": baseline, "min_lift": min_lift,
        "needed": {**needed, **rates}, "currency": settings.ads_currency,
        "proposed_by": proposed_by})
    audit(store, "propose", actor=proposed_by, test_id=test["id"], needed=needed["total"])
    return _shown(store, settings, test)


def _affordable(store: CampaignStore, settings: InstagramMCPSettings, days: int) -> Decimal:
    st = budget_status(store, settings)
    return min(settings.ads_test_cap, Decimal(st["lifetime"]["remaining"]),
               Decimal(st["daily"]["remaining"]) * days)


def _shown(store: CampaignStore, settings: InstagramMCPSettings,
           test: Dict[str, Any]) -> Dict[str, Any]:
    """The test plus `underpowered` (can the caps fund the need?) and a plain `summary`."""
    spec, need = abtest.TestSpec(**test["spec"]), test["needed"]
    short = None
    if test["status"] == "proposed":
        short = abtest.underpowered(spec, float(_affordable(store, settings, spec.min_days)),
                                    test["baseline_rate"], test["min_lift"], cpm=need["cpm"],
                                    cpc=need["cpc"])
        short = short and f"the caps allow less than the test needs: {short}"
    return {**test, "underpowered": short, "summary": (
        f"To see a {test['min_lift']:.0%} lift you need about {need['total']:.2f} "
        f"{test['currency']} over {spec.min_days} days")}


def list_tests(store: CampaignStore, settings: InstagramMCPSettings, *,
               status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Newest first; `launched_by` owner | agent (the audit's launch row), else None."""
    with store._tx() as c:
        by = dict(c.execute("SELECT test_id, actor FROM ads_audit WHERE action='approve'"
                            " AND test_id IS NOT NULL").fetchall())
    return [{**_shown(store, settings, t), "launched_by": by.get(t["id"])}
            for t in store._select("SELECT * FROM ad_tests", {"status": status}, "id DESC",
                                   limit)]


def eligible_winners(store: CampaignStore, settings: InstagramMCPSettings) -> List[Dict]:
    """Matured Reels scored `winner` whose studio asset may be advertised, newest first."""
    out = []
    for snap, s in scored_posts(store, settings):
        if s.get("verdict") != "winner" or s["group"] != "REELS":
            continue
        try:
            asset = _advertisable_asset(store, snap["media_id"])
        except PromotionRefused:
            continue
        out.append({"media_id": snap["media_id"], "permalink": snap["permalink"],
                    "posted_at": snap["posted_at"], "caption": (snap["caption"] or "")[:120],
                    "asset_id": asset["id"],
                    "thumbnail_url": media_url(asset.get("thumbnail_path")),
                    "engagement_index": s.get("engagement_index"),
                    "reach_index": s.get("reach_index")})
    return out


def _entities(store: CampaignStore, test_id: int) -> List[Dict[str, Any]]:
    rows = store._select("SELECT * FROM ad_entities", {"test_id": test_id}, "id", 1000)
    return sorted((r for r in rows if r["kind"] in PAUSE_ORDER),
                  key=lambda r: PAUSE_ORDER[r["kind"]])


def _mark(store: CampaignStore, entity: Dict[str, Any], status: str) -> None:
    store._update("ad_entities", ("status",), entity["id"], {"status": status})


async def _pause_active(store: CampaignStore, settings: InstagramMCPSettings,
                        test_id: int) -> List[str]:
    """Pause the test's objects not recorded PAUSED; returns the ids that failed."""
    todo = [r for r in _entities(store, test_id) if r["status"] != PAUSED]
    failed = []
    if todo:
        async with AdsWriter(settings, store=store) as w:
            for r in todo:
                try:
                    await w.pause(r["meta_id"])
                    _mark(store, r, PAUSED)
                except Exception:  # keep pausing the others
                    logger.exception("ad_pause_failed", meta_id=r["meta_id"])
                    failed.append(r["meta_id"])
    return failed


def _running(c) -> int:
    return c.execute(f"SELECT COUNT(*) FROM ad_tests WHERE status IN {OPEN_RUNNING}"
                     ).fetchone()[0]


def _set_status(store: CampaignStore, test_id: int, new: str, *, expect: tuple,
                max_running: Optional[int] = None, **fields: Any) -> Dict[str, Any]:
    """Compare-and-set the status; AdTestRefused('status') when it is not in `expect`,
    ('max_running') when `max_running` tests already run (counted in the same
    transaction, so two launches never both pass the limit)."""
    sets = {"status": new, "updated_at": to_iso(utcnow()), **fields}
    with store.immediate() as c:
        if max_running is not None and _running(c) >= max_running:
            raise AdTestRefused("max_running", f"{max_running} tests already run (the "
                                "most at once, set in the website): wait for one to end")
        cur = c.execute(
            f"UPDATE ad_tests SET {', '.join(f'{k}=?' for k in sets)} WHERE id=? AND status"
            f" IN ({','.join('?' * len(expect))})", [*sets.values(), test_id, *expect])
    if cur.rowcount != 1:
        test = store._get("ad_tests", test_id)  # KeyError when missing
        raise AdTestRefused("status", f"test {test_id} is {test['status']}")
    return store._get("ad_tests", test_id)


def _agent_budget(store: CampaignStore, settings: InstagramMCPSettings,
                  test: Dict[str, Any]) -> Decimal:
    """The agent's budget: the test's need (rounded up to whole cents per variant), capped
    by what the caps allow over its days; ZERO when they allow nothing."""
    n = len(test["variants"])
    want = (Decimal(str(test["needed"]["total"])) / n).quantize(CENT, rounding=ROUND_UP) * n
    room = _affordable(store, settings, test["spec"]["min_days"])
    return min(want, (room / n).quantize(CENT, rounding=ROUND_DOWN) * n)


async def launch(
    store: CampaignStore,
    settings: InstagramMCPSettings,
    test_id: int,
    budget: Any = None,
    *,
    actor: str,
    underpowered_ok: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Create the variants paused, then activate them. `actor` owner (the website's
    Approve) or agent (`budget` None: picked by `_agent_budget`; never underpowered).
    Raises AdTestRefused / BudgetRefused before any request, AdTestFailed after (the test
    is then cancelled)."""
    if actor not in ("owner", "agent"):
        raise AdTestRefused("invalid", "actor is owner or agent")
    if actor == "agent" and (budget is not None or underpowered_ok):
        raise AdTestRefused("invalid", "the agent's budget comes from the need and the caps")
    test = store._get("ad_tests", test_id)
    if test["status"] != "proposed":
        raise AdTestRefused("status", f"test {test_id} is {test['status']}, not proposed")
    refresh(store, settings)  # the caps, limits and ids the owner set a moment ago count
    missing = missing_settings(settings)
    if missing:
        raise AdTestRefused("not_configured", f"set {', '.join(missing)}")
    for media in dict.fromkeys(v["media_id"] for v in test["variants"]):
        try:  # rights or status may have changed since the proposal
            _advertisable_asset(store, media)
        except PromotionRefused as e:
            raise AdTestRefused(e.code, e.message) from None
    if budget is None:
        budget = _agent_budget(store, settings, test)
        if budget <= 0:
            raise AdTestRefused("underpowered", "the caps leave nothing to spend on this "
                                "test now: wait, or propose a smaller one")
    amount = _amount(budget)
    variants, spec, need = test["variants"], abtest.TestSpec(**test["spec"]), test["needed"]
    per = (amount / len(variants)).quantize(CENT, rounding=ROUND_DOWN)
    total = per * len(variants)
    short = abtest.underpowered(spec, float(total), test["baseline_rate"], test["min_lift"],
                                cpm=need["cpm"], cpc=need["cpc"])
    if short and not underpowered_ok:
        raise AdTestRefused("underpowered", f"{short}; " + (
            "propose a larger lift or wait for room under the caps" if actor == "agent"
            else "tick 'run underpowered anyway' to run it regardless"))
    now = now or utcnow()
    today = now.astimezone(ZoneInfo(settings.timezone)).date()
    end_date = today + timedelta(days=max(spec.min_days - 1, 1))
    days = (end_date - today).days + 1
    daily = (per / days).quantize(CENT, rounding=ROUND_UP) * len(variants)
    authorize_spend(store, settings, total, test_id=test_id, daily_amount=daily,
                    daily_until=end_date, reason=f"test {test_id} launch", check_only=True,
                    now=now)
    _set_status(store, test_id, "approved", expect=("proposed",),
                max_running=settings.ads_max_running_tests, budget_total=str(total),
                end_date=end_date.isoformat(), approved_at=to_iso(now),
                underpowered_ok=int(bool(short)))
    audit(store, "approve", actor=actor, test_id=test_id, budget=str(total),
          per_variant=str(per), end_date=end_date.isoformat(), underpowered=short)

    created: List[Dict[str, Any]] = []
    live: set = set()  # authorizations with something activated
    try:
        for v in variants:
            created.append(await create_paused_promotion(
                store, settings, v["media_id"], preset=v["preset"], budget=per,
                end_date=end_date, test_id=test_id, now=now))
        async with AdsWriter(settings, store=store) as w:
            for p in created:
                if store._get("ad_tests", test_id)["status"] != "approved":
                    raise AdTestRefused("status", "the test was cancelled during the launch")
                for kind in ("ad", "adset", "campaign"):
                    try:
                        await w.activate(p[kind]["meta_id"], test_id=test_id,
                                         authorization_id=p["authorization_id"])
                    except InstagramAPIError as e:
                        if getattr(e, "network", False):  # Meta may have acted: pause it
                            _mark(store, p[kind], ACTIVE)
                            live.add(p["authorization_id"])
                        raise
                    _mark(store, p[kind], ACTIVE)
                    live.add(p["authorization_id"])
                audit(store, "activate", actor=actor, test_id=test_id,
                      media_id=p["ad"]["media_id"],
                      campaign=p["campaign"]["meta_id"], adset=p["adset"]["meta_id"],
                      ad=p["ad"]["meta_id"])
    except Exception as e:
        failed = await _pause_active(store, settings, test_id)
        for auth_id in open_authorizations(store, test_id):
            if auth_id not in live:
                release(store, auth_id, reason=f"test {test_id} launch failed")
        reason = f"launch failed: {getattr(e, 'message', None) or e}"
        _set_status(store, test_id, "cancelled", expect=("approved", "cancelled"),
                    reason=reason, finished_at=to_iso(utcnow()))
        audit(store, "cancel", actor=actor, test_id=test_id, reason=reason,
              pause_failed=failed)
        logger.warning("ad_test_launch_failed", test_id=test_id, pause_failed=failed)
        raise AdTestFailed(reason + (f"; could not pause {failed}: press the kill switch"
                                     if failed else "; everything is paused")) from e
    logger.info("ad_test_running", test_id=test_id, budget=str(total), actor=actor)
    return {**_set_status(store, test_id, "running", expect=("approved",)), "entities":
            _entities(store, test_id)}


async def cancel(store: CampaignStore, settings: InstagramMCPSettings, test_id: int, *,
                 reason: str = "cancelled by the owner", actor: str = "owner") -> Dict:
    """Pause the test's ads and mark it cancelled. Releases its reservations unless it was
    running (095 reconciles the reported spend first)."""
    test = store._get("ad_tests", test_id)
    if test["status"] not in ("proposed", "approved", "running"):
        raise AdTestRefused("status", f"test {test_id} is {test['status']}")
    failed = await _pause_active(store, settings, test_id)
    if failed:
        audit(store, "cancel_failed", actor=actor, test_id=test_id, pause_failed=failed)
        raise AdTestFailed(f"could not pause {failed}: retry, or press the kill switch")
    if test["status"] != "running":
        for auth_id in open_authorizations(store, test_id):
            release(store, auth_id, reason=f"test {test_id} cancelled")
    out = _set_status(store, test_id, "cancelled", expect=(test["status"],), reason=reason,
                      finished_at=to_iso(utcnow()))
    audit(store, "cancel", actor=actor, test_id=test_id, reason=reason)
    return out
