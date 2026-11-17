"""Research routes (thin doors): the watchlist (the store's, step 051), the hashtags and
accounts research_trends looks up, for the owner to edit; GET /api/trends, the ranked
trend report (studio/research.py trend_report, step 052); /api/inspirations, the Reel
links the owner pastes with a note (store, step 051b)."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from ..store import CampaignStore
from ..studio import research
from .assets import call, get_store

router = APIRouter(prefix="/api")


class WatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["hashtag", "account"]
    value: str
    note: Optional[str] = None


@router.get("/watchlist")
def list_watchlist(store: CampaignStore = Depends(get_store)):
    return store.list_watchlist()


@router.post("/watchlist")
def add_watch(body: WatchIn, store: CampaignStore = Depends(get_store)):
    return call(store.add_watch, body.kind, body.value, body.note)


@router.delete("/watchlist/{watch_id}", status_code=204)
def remove_watch(watch_id: int, store: CampaignStore = Depends(get_store)):
    out = call(store.remove_watch, watch_id)  # the removed row, or a JSON error response
    return out if isinstance(out, Response) else Response(status_code=204)


class InspirationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    note: Optional[str] = None


class InspirationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["new", "used", "dismissed"]


@router.get("/inspirations")
def list_inspirations(status: Optional[Literal["new", "used", "dismissed"]] = None,
                      store: CampaignStore = Depends(get_store)):
    return store.list_inspirations(status)


@router.post("/inspirations")
def add_inspiration(body: InspirationIn, store: CampaignStore = Depends(get_store)):
    return call(store.add_inspiration, body.url, body.note)


@router.patch("/inspirations/{inspiration_id}")
def set_inspiration_status(inspiration_id: int, body: InspirationPatch,
                           store: CampaignStore = Depends(get_store)):
    return call(store.set_inspiration_status, inspiration_id, body.status)


@router.delete("/inspirations/{inspiration_id}", status_code=204)
def delete_inspiration(inspiration_id: int, store: CampaignStore = Depends(get_store)):
    out = call(store.delete_inspiration, inspiration_id)
    return out if isinstance(out, Response) else Response(status_code=204)


@router.get("/trends")
def trends(request: Request, days: int = Query(14, ge=1, le=365),
           limit: int = Query(30, ge=1, le=200),
           kind: Optional[Literal["account", "hashtag"]] = None,
           store: CampaignStore = Depends(get_store)):
    return research.trend_report(store, request.app.state.settings, days=days, limit=limit,
                                 kind=kind)
