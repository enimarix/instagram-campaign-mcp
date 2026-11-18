"""Marketing API writes (step 092): the only POSTs in src/ads.

Every method is `@spends` and calls `authorize_spend()` before its request:
- the ad set reserves its lifetime budget (spread over its days for the daily cap) and
  releases it when Meta refuses;
- the campaign, the creative and the ad cannot spend by themselves, so they only run the
  guard's checks (`check_only`): the kill switch and the caps still stop them.

Nothing is ever created ACTIVE: `_paused()` puts `status=PAUSED` last in every campaign, ad
set and ad body, and no method takes a status. (A creative has no delivery status: its
enum is ACTIVE/IN_PROCESS/WITH_ISSUES/DELETED and is not a creation parameter.)
Activation is 094, behind the owner's approval.

Money goes to Meta as int64 in the currency's smallest unit (cents); spend_cap is the
campaign's, lifetime_budget + end_time the ad set's (Marketing API v25.0 reference).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..config import InstagramMCPSettings
from ..store import CampaignStore
from .budget import authorize_spend, release, spends
from .client import AdsClient

PAUSED = "PAUSED"


def _paused(body: Dict[str, Any]) -> Dict[str, Any]:
    return {**body, "status": PAUSED}


def _id(out: Dict[str, Any]) -> str:
    if not isinstance(out.get("id"), str):
        raise ValueError("Meta returned no id for the new object")
    return out["id"]


def minor_units(amount: Decimal) -> int:
    """Account-currency amount → Meta's int64 in cents.
    ponytail: assumes 2 decimals (EUR, USD, GBP); Meta's offset-1 currencies (JPY, KRW, …)
    need a table if H9 picks one."""
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise ValueError(f"{amount} has more than 2 decimals")
    return int(cents)


def missing_settings(settings: InstagramMCPSettings) -> List[str]:
    """Settings a paused promotion needs, unset ones. The EU (Digital Services Act) fields
    are required for every ad set we create: the owner is in the EU."""
    need = ("instagram_access_token", "instagram_business_account_id", "meta_ad_account_id",
            "meta_page_id", "ads_dsa_beneficiary", "ads_dsa_payor")
    return [n.upper() for n in need if not (getattr(settings, n) or "").strip()]


class AdsWriter(AdsClient):
    """Creates paused campaigns, ad sets, creatives and ads. Needs the store (ledger)."""

    def __init__(
        self,
        settings: InstagramMCPSettings,
        http_client: Optional[httpx.AsyncClient] = None,
        *,
        store: CampaignStore,
    ):
        super().__init__(settings, http_client, store)
        self.ledger = store

    @spends
    async def create_campaign(
        self, name: str, *, objective: str, spend_cap: Decimal, planned: Decimal,
        daily_amount: Optional[Decimal] = None, daily_until: Optional[date] = None,
        test_id: Optional[int] = None,
    ) -> str:
        """`planned`: what its ad sets will reserve, checked (not reserved) here so a cap
        refuses before any request."""
        body = _paused({
            "name": name, "objective": objective, "special_ad_categories": [],
            "spend_cap": minor_units(spend_cap), "is_adset_budget_sharing_enabled": False,
        })
        authorize_spend(self.ledger, self.settings, planned, test_id=test_id,
                        daily_amount=daily_amount, daily_until=daily_until,
                        reason=f"campaign {name}", check_only=True)
        self._check_throttle()
        return _id(await self._make_request("POST", f"{self.ad_account}/campaigns", data=body))

    @spends
    async def create_ad_set(
        self, name: str, *, campaign_id: str, budget: Decimal, end_time: datetime,
        daily_amount: Decimal, daily_until: date, targeting: Dict[str, Any],
        optimization_goal: str, billing_event: str, destination_type: Optional[str] = None,
        test_id: Optional[int] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Returns (meta id, ledger authorization). The authorization holds the lifetime
        budget, under the campaign's id (pausing it stops the spend)."""
        s = self.settings
        body = {
            "name": name, "campaign_id": campaign_id,
            "lifetime_budget": minor_units(budget), "end_time": int(end_time.timestamp()),
            "billing_event": billing_event, "optimization_goal": optimization_goal,
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP", "targeting": targeting,
            "dsa_beneficiary": s.ads_dsa_beneficiary, "dsa_payor": s.ads_dsa_payor,
        }
        if destination_type:
            body["destination_type"] = destination_type
        auth = authorize_spend(self.ledger, s, budget, test_id=test_id,
                               ad_entity_id=campaign_id, daily_amount=daily_amount,
                               daily_until=daily_until, reason=f"ad set {name}")
        try:
            self._check_throttle()
            out = await self._make_request("POST", f"{self.ad_account}/adsets",
                                           data=_paused(body))
            return _id(out), auth
        except BaseException:
            release(self.ledger, auth["id"], reason=f"ad set {name} not created")
            raise

    @spends
    async def create_creative(self, name: str, *, media_id: str) -> str:
        """A creative from an existing Instagram post (`source_instagram_media_id`)."""
        s = self.settings
        authorize_spend(self.ledger, s, 0, reason=f"creative {name}", check_only=True)
        self._check_throttle()
        return _id(await self._make_request("POST", f"{self.ad_account}/adcreatives", data={
            "name": name, "object_id": s.meta_page_id,
            "instagram_user_id": s.instagram_business_account_id,
            "source_instagram_media_id": media_id,
        }))

    @spends
    async def create_ad(self, name: str, *, adset_id: str, creative_id: str) -> str:
        authorize_spend(self.ledger, self.settings, 0, reason=f"ad {name}", check_only=True)
        self._check_throttle()
        return _id(await self._make_request("POST", f"{self.ad_account}/ads", data=_paused({
            "name": name, "adset_id": adset_id, "creative": {"creative_id": creative_id},
        })))
