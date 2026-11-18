"""Promote an existing Instagram post as a paused ad (step 092).

`create_paused_promotion` refuses unless the post's asset may be advertised (rights,
GOAL.md §5.1), the ad settings are complete and the budget guard allows the budget; then
creates campaign → ad set → creative → ad on Meta, all PAUSED (src/ads/writer.py), and
records each in `ad_entities`. Meta holds the money limits too (§5.4): the ad set has a
lifetime budget and an end date, the campaign a spend cap.

- The lifetime budget is reserved once, by the ad set, and counts against the daily cap
  spread over its days (budget / days, rounded up to the cent, from today to end_date).
- The campaign's spend cap is the budget, raised to Meta's minimum (about 100 USD) when
  the budget is below it: the ad set's lifetime budget is then the binding limit.
- A failure halfway leaves what exists paused and recorded, releases the reservation (a
  paused ad set without an ad cannot spend; activation, 094, authorizes again) and says
  what exists.

Objective follows `ADS_OBJECTIVE` (default OUTCOME_AWARENESS: reach, billed on
impressions; H6/H9 decide). Audience and placement come from a named preset.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import ROUND_UP, Decimal
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
import structlog

from ..config import InstagramMCPSettings
from ..store import CampaignStore, utcnow
from ..studio.publish import _source
from ..studio.rights import can_advertise
from .budget import BudgetRefused, _amount, release
from .writer import PAUSED, AdsWriter, missing_settings

logger = structlog.get_logger(__name__)

ENTITY_FIELDS = ("kind", "meta_id", "parent_id", "test_id", "asset_id", "media_id", "status",
                 "lifetime_budget", "spend_cap", "end_time")
# Marketing API ODAX table: Awareness → REACH; Engagement on video → THRUPLAY.
OBJECTIVES: Dict[str, Dict[str, str]] = {
    "OUTCOME_AWARENESS": {"optimization_goal": "REACH", "billing_event": "IMPRESSIONS"},
    "OUTCOME_ENGAGEMENT": {"optimization_goal": "THRUPLAY", "billing_event": "IMPRESSIONS",
                           "destination_type": "ON_VIDEO"},
}
# ponytail: placeholder audiences until H9 names the market. advantage_audience must be
# explicit since v23.0 (0 = keep to the preset).
_IG = {"publisher_platforms": ["instagram"], "age_min": 18,
       "targeting_automation": {"advantage_audience": 0}}
PRESETS: Dict[str, Dict[str, Any]] = {
    "fr_reels": {**_IG, "geo_locations": {"countries": ["FR"]},
                 "instagram_positions": ["reels"]},
    "fr_feed_reels": {**_IG, "geo_locations": {"countries": ["FR"]},
                      "instagram_positions": ["stream", "reels"]},
    "francophone_reels": {**_IG, "geo_locations": {"countries": ["FR", "BE", "CH", "LU"]},
                          "instagram_positions": ["reels"]},
}
PRESET_LABELS = {"fr_reels": "France, Reels", "fr_feed_reels": "France, Feed and Reels",
                 "francophone_reels": "France, Belgium, Switzerland, Luxembourg, Reels"}
MIN_SPEND_CAP = Decimal(100)  # Meta: "a minimum value of $100 USD (or local equivalent)"
CENT = Decimal("0.01")


class PromotionRefused(Exception):
    """Nothing was sent. code: rights | not_ours | not_published | not_configured | invalid."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class PromotionFailed(Exception):
    """Meta (or the guard) failed halfway. `created`: the ad_entities rows that exist,
    all paused."""

    def __init__(self, message: str, created: List[Dict[str, Any]]):
        super().__init__(message)
        self.created = created


def _advertisable_asset(store: CampaignStore, media_id: str) -> Dict[str, Any]:
    label = store.get_label(media_id)
    if not label or label.get("asset_id") is None:
        raise PromotionRefused("not_ours", f"post {media_id} is not a studio asset")
    asset = store.get_asset(label["asset_id"])
    if asset["status"] != "published":  # the owner approved it, and it is on Instagram
        raise PromotionRefused("not_published", f"post {media_id}'s video is "
                               f"{asset['status']}, not published")
    decision = can_advertise(_source(store, store.get_idea(asset["idea_id"])))
    if not decision:
        raise PromotionRefused("rights", decision.reason)
    return asset


async def create_paused_promotion(
    store: CampaignStore,
    settings: InstagramMCPSettings,
    media_id: str,
    *,
    preset: str,
    budget: Any,
    end_date: date,
    test_id: Optional[int] = None,
    now: Optional[datetime] = None,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Returns {campaign, adset, creative, ad: ad_entities rows, authorization_id}.
    Raises PromotionRefused / BudgetRefused before any request, PromotionFailed after."""
    if preset not in PRESETS:
        raise PromotionRefused("invalid", f"unknown preset {preset!r}; one of {sorted(PRESETS)}")
    try:
        amount = _amount(budget)
    except BudgetRefused as e:
        raise PromotionRefused("invalid", e.message) from None
    if amount != amount.quantize(CENT):
        raise PromotionRefused("invalid", "budget has more than 2 decimals")
    zone = ZoneInfo(settings.timezone)
    today = (now or utcnow()).astimezone(zone).date()
    if isinstance(end_date, datetime) or not isinstance(end_date, date) or end_date <= today:
        raise PromotionRefused("invalid", "end_date must be a date after today")
    missing = missing_settings(settings)
    if missing:
        raise PromotionRefused("not_configured", f"set {', '.join(missing)} in .env")
    asset = _advertisable_asset(store, media_id)

    daily = (amount / ((end_date - today).days + 1)).quantize(CENT, rounding=ROUND_UP)
    end_time = datetime.combine(end_date, time(23, 59, 59), tzinfo=zone)
    spend_cap = max(amount, MIN_SPEND_CAP)
    name = f"studio {media_id} {today.isoformat()}"
    goal = OBJECTIVES[settings.ads_objective]
    created: List[Dict[str, Any]] = []
    auth: Optional[Dict[str, Any]] = None

    def record(kind: str, meta_id: str, parent: Optional[Dict[str, Any]], **kw: Any):
        row = store._insert("ad_entities", ENTITY_FIELDS, {
            "kind": kind, "meta_id": meta_id, "parent_id": parent and parent["id"],
            "test_id": test_id, "asset_id": asset["id"], "media_id": media_id,
            "status": PAUSED, **kw})
        created.append(row)
        return row

    step = "campaign"
    async with AdsWriter(settings, http_client, store=store) as w:
        try:
            campaign = record("campaign", await w.create_campaign(
                name, objective=settings.ads_objective, spend_cap=spend_cap, planned=amount,
                daily_amount=daily, daily_until=end_date, test_id=test_id),
                None, spend_cap=str(spend_cap))
            step = "ad set"
            adset_id, auth = await w.create_ad_set(
                name, campaign_id=campaign["meta_id"], budget=amount, end_time=end_time,
                daily_amount=daily, daily_until=end_date, targeting=PRESETS[preset],
                test_id=test_id, **goal)
            adset = record("adset", adset_id, campaign, lifetime_budget=str(amount),
                           end_time=end_time.isoformat())
            step = "creative"
            creative = record("creative", await w.create_creative(name, media_id=media_id),
                              adset)
            step = "ad"
            ad = record("ad", await w.create_ad(name, adset_id=adset_id,
                                                creative_id=creative["meta_id"]), adset)
        except Exception as e:
            if isinstance(e, BudgetRefused) and not created:
                raise  # refused before any request

            raise _failed(store, step, auth, created, e) from e
    logger.info("ad_promotion_created", media_id=media_id, campaign=campaign["meta_id"],
                ad=ad["meta_id"], budget=str(amount))
    return {"campaign": campaign, "adset": adset, "creative": creative, "ad": ad,
            "authorization_id": auth["id"]}


def _failed(store: CampaignStore, step: str, auth: Optional[Dict[str, Any]],
            created: List[Dict[str, Any]], error: Exception) -> PromotionFailed:
    if auth is not None:
        release(store, auth["id"], reason=f"promotion failed at the {step}")
    exists = ", ".join(f"{r['kind']} {r['meta_id']}" for r in created) or "nothing"
    logger.warning("ad_promotion_failed", step=step, created=exists)
    return PromotionFailed(f"creating the {step} failed ({error}); "
                           f"on Meta, paused: {exists}", created)
