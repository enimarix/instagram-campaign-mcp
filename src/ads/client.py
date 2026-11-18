"""Meta Marketing API client, read only (step 090).

Lists ad accounts, campaigns, ad sets, ads and insights. It has no method that writes:
creating ads is step 092, behind the budget guard (091). Requests go through
GraphClient (src/instagram_client.py): the same token (it needs `ads_read`), sent in the
Authorization header, the same request budget and the same error mapping.

On top of Meta's rate-limit error codes, the usage headers are read on every response:
when Meta says the account is throttled, later calls fail fast with RateLimitExceeded
until the stated time has passed, instead of hammering a blocked account.
"""

from __future__ import annotations

import json
import math
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional

import httpx
import structlog

from ..config import PLACEHOLDERS, InstagramMCPSettings, get_settings
from ..instagram_client import GraphClient, NotConfigured, RateLimitExceeded
from ..store import CampaignStore

logger = structlog.get_logger(__name__)

ADS_NOT_CONFIGURED_MSG = (
    "ads_not_configured: set INSTAGRAM_ACCESS_TOKEN (with ads_read) and META_AD_ACCOUNT_ID "
    "in .env (owner step H6)"
)
# Fields per object, Marketing API reference v25.0. Money fields are strings in the
# account currency's smallest unit (e.g. cents).
ACCOUNT_FIELDS = ("id,account_id,name,account_status,disable_reason,currency,timezone_name,"
                  "spend_cap,amount_spent")
CAMPAIGN_FIELDS = ("id,name,objective,status,effective_status,daily_budget,lifetime_budget,"
                   "budget_remaining,spend_cap,start_time,stop_time")
ADSET_FIELDS = ("id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,"
                "budget_remaining,start_time,end_time,optimization_goal,billing_event")
AD_FIELDS = ("id,name,campaign_id,adset_id,status,effective_status,ad_review_feedback,"
             "issues_info,creative{id}")
INSIGHT_FIELDS = ("date_start,date_stop,spend,impressions,reach,frequency,clicks,ctr,cpm,cpc,"
                  "actions,cost_per_action_type")
DATE_PRESETS = frozenset({
    "today", "yesterday", "this_month", "last_month", "this_quarter", "maximum",
    "data_maximum", "last_3d", "last_7d", "last_14d", "last_28d", "last_30d", "last_90d",
    "last_week_mon_sun", "last_week_sun_sat", "last_quarter", "last_year",
    "this_week_mon_today", "this_week_sun_today", "this_year",
})
LEVELS = frozenset({"account", "campaign", "adset", "ad"})
PAGE_SIZE = 100
MAX_PAGES = 20  # ponytail: hard stop at 2000 rows; one ad account of this studio is far below


def usage_wait_s(headers: httpx.Headers) -> float:
    """Seconds Meta's usage headers say to stay away (0 = fine)."""
    wait = 0.0
    try:
        buc = json.loads(headers.get("x-business-use-case-usage") or "{}")
        for entries in buc.values():
            for e in entries:
                wait = max(wait, float(e.get("estimated_time_to_regain_access") or 0) * 60)
        acc = json.loads(headers.get("x-ad-account-usage") or "{}")
        if float(acc.get("acc_id_util_pct") or 0) >= 100:
            wait = max(wait, float(acc.get("reset_time_duration") or 0), 60.0)
    except (ValueError, TypeError, AttributeError):
        logger.warning("ads_usage_header_unreadable")
    return wait


class AdsClient(GraphClient):
    """Read-only Marketing API client. Raises NotConfigured until H6 gives a token."""

    def __init__(
        self,
        settings: Optional[InstagramMCPSettings] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        store: Optional[CampaignStore] = None,
    ):
        settings = settings or get_settings()
        token = settings.instagram_access_token
        if not token or token in PLACEHOLDERS:
            raise NotConfigured(ADS_NOT_CONFIGURED_MSG)
        super().__init__(settings, http_client, store)
        self._blocked_until = 0.0  # time.monotonic()

    @property
    def ad_account(self) -> str:
        """`act_<id>` of the configured ad account."""
        if not self.settings.meta_ad_account_id:
            raise NotConfigured(ADS_NOT_CONFIGURED_MSG)
        return f"act_{self.settings.meta_ad_account_id}"

    def _on_response(self, response: httpx.Response) -> None:
        wait = usage_wait_s(response.headers)
        if wait:
            self._blocked_until = max(self._blocked_until, time.monotonic() + wait)
            logger.warning("ads_throttled", wait_s=wait)

    async def _get(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        left = self._blocked_until - time.monotonic()
        if left > 0:
            raise RateLimitExceeded(
                f"Marketing API usage limit reached; retry in {math.ceil(left / 60)} min"
            )
        return await self._make_request("GET", endpoint, params=params)

    async def _list(self, endpoint: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Every row of a cursor-paged edge. Follows `after` (not `paging.next`, whose URL
        can carry the token)."""
        params = {"limit": PAGE_SIZE, **params}
        rows: List[Dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            data = await self._get(endpoint, params)
            rows.extend(data.get("data", []))
            after = data.get("paging", {}).get("cursors", {}).get("after")
            if not after or not data.get("paging", {}).get("next"):
                return rows
            params = {**params, "after": after}
        logger.warning("ads_paging_cut", endpoint=endpoint, rows=len(rows))
        return rows

    async def list_ad_accounts(self) -> List[Dict[str, Any]]:
        """Ad accounts the token can see (works before META_AD_ACCOUNT_ID is set)."""
        return await self._list("me/adaccounts", {"fields": ACCOUNT_FIELDS})

    async def list_campaigns(self) -> List[Dict[str, Any]]:
        return await self._list(f"{self.ad_account}/campaigns", {"fields": CAMPAIGN_FIELDS})

    async def list_ad_sets(self) -> List[Dict[str, Any]]:
        return await self._list(f"{self.ad_account}/adsets", {"fields": ADSET_FIELDS})

    async def list_ads(self) -> List[Dict[str, Any]]:
        return await self._list(f"{self.ad_account}/ads", {"fields": AD_FIELDS})

    async def get_insights(
        self,
        object_id: Optional[str] = None,
        *,
        date_preset: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        level: Optional[str] = None,
        fields: str = INSIGHT_FIELDS,
    ) -> List[Dict[str, Any]]:
        """Insights rows of a campaign / ad set / ad id (default: the ad account).
        Either `date_preset` or `since` + `until` (YYYY-MM-DD, both days included);
        neither = Meta's default (last_30d)."""
        if object_id is not None and not re.fullmatch(r"(act_)?\d+", object_id):
            raise ValueError(f"not an ad object id: {object_id!r}")
        params: Dict[str, Any] = {"fields": fields}
        if since or until:
            if date_preset or not (since and until):
                raise ValueError("give since and until together, without date_preset")
            if date.fromisoformat(since) > date.fromisoformat(until):
                raise ValueError("since is after until")
            params["time_range"] = json.dumps({"since": since, "until": until})
        elif date_preset:
            if date_preset not in DATE_PRESETS:
                raise ValueError(f"unknown date_preset {date_preset!r}")
            params["date_preset"] = date_preset
        if level:
            if level not in LEVELS:
                raise ValueError(f"unknown level {level!r}")
            params["level"] = level
        return await self._list(f"{object_id or self.ad_account}/insights", params)
