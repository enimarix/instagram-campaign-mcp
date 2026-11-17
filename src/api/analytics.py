"""GET /api/analytics/*: thin doors onto src/learning/analytics.py, breakdowns.py, funnel.py
and campaign.py (A/B)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from .. import campaign as campaign_service
from ..learning import analytics, breakdowns
from ..learning import funnel as funnel_service
from ..store import CampaignStore
from .assets import call, get_store

router = APIRouter(prefix="/api/analytics")


@router.get("/account")
def account(request: Request, days: int = Query(30, ge=1, le=3660),
            store: CampaignStore = Depends(get_store)):
    return analytics.recent_account_series(store, request.app.state.settings, days)


@router.get("/posts")
def posts(request: Request, limit: int = Query(50, ge=1, le=500),
          offset: int = Query(0, ge=0), sort: str = "-posted_at",
          type: Optional[str] = None, verdict: Optional[str] = None,
          tagged: Optional[bool] = None, store: CampaignStore = Depends(get_store)):
    return call(analytics.posts_table, store, request.app.state.settings, limit=limit,
                offset=offset, sort=sort, post_type=type, verdict=verdict, tagged=tagged)


@router.get("/posts/{media_id}")
def post(request: Request, media_id: str, store: CampaignStore = Depends(get_store)):
    return call(analytics.post_detail, store, request.app.state.settings, media_id)


@router.get("/breakdown")
def breakdown(request: Request, tag: str, type: str = "REELS",
              days: int = Query(90, ge=1, le=3660), store: CampaignStore = Depends(get_store)):
    return call(breakdowns.tag_breakdown, store, request.app.state.settings,
                tag=tag, post_type=type, days=days)


@router.get("/campaigns")
def campaigns(store: CampaignStore = Depends(get_store)):
    return campaign_service.campaigns(store)


@router.get("/ab")
def ab(request: Request, campaign: str = Query(..., min_length=1),
       store: CampaignStore = Depends(get_store)):
    return campaign_service.variants(store, request.app.state.settings, campaign)


@router.get("/funnel")
def funnel(request: Request, days: int = Query(30, ge=1, le=3660), group_by: str = "day",
           store: CampaignStore = Depends(get_store)):
    return call(funnel_service.funnel, store, request.app.state.settings,
                days=days, group_by=group_by)


@router.get("/taste")
def taste(request: Request, days: int = Query(30, ge=1, le=3660),
          store: CampaignStore = Depends(get_store)):
    return funnel_service.taste(store, request.app.state.settings, days=days)
