"""Research routes (thin doors): the watchlist (the store's, step 051), the hashtags and
accounts research_trends looks up, for the owner to edit; GET /api/trends, the ranked
trend report (studio/research.py trend_report, step 052); /api/inspirations, the Reel
links the owner pastes with a note (store, step 051b); /api/research/*, the Trending page
(step 134): refresh, feed, reactions, suggested topics (studio/research.py) and work
orders (studio/work_orders.py); /api/work-orders: every work order, Trending and DM
(136), and the owner's instruction."""

from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from ..store import CampaignStore, utcnow
from ..studio import research, work_orders
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


# --- Trending page (134) ---------------------------------------------------------------
class ReactionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reaction: Literal["like", "dislike", "none"]


class WorkOrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: int
    mode: Literal["inspired", "react"]
    instruction: Optional[str] = None


class WorkOrdersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: List[WorkOrderItem] = Field(min_length=1)


@router.post("/research/refresh")
async def refresh(request: Request):
    state = request.app.state
    if state.client is None:
        return JSONResponse(status_code=503, content={"error": "instagram_not_configured"})
    try:
        return await research.refresh(state.client, state.store, now=utcnow())
    except research.RefreshRunning as e:
        return JSONResponse(status_code=409, content={"error": "already_running",
                                                      "message": str(e)})


@router.get("/research/feed")
def feed(request: Request, topic: Optional[str] = None,
         limit: int = Query(50, ge=1, le=research.FEED_MAX), include_old: bool = False,
         store: CampaignStore = Depends(get_store)):
    return research.trending_feed(
        store, topic=topic, limit=limit, include_old=include_old,
        max_age_days=request.app.state.settings.trending_max_age_days)


@router.get("/research/suggested-topics")
def suggested_topics(store: CampaignStore = Depends(get_store)):
    return research.suggested_topics(store, utcnow())


@router.post("/research/feed/{source_id}/reaction")
def set_reaction(source_id: int, body: ReactionIn, store: CampaignStore = Depends(get_store)):
    return call(research.set_reaction, store, source_id, body.reaction)


@router.post("/research/work-orders")
def create_work_orders(body: WorkOrdersIn, store: CampaignStore = Depends(get_store)):
    return call(work_orders.create_orders, store, [i.model_dump() for i in body.items])


WorkOrderStatus = Literal["needs_instruction", "scheduled", "in_production", "in_feed",
                          "analysed", "skipped"]


class InstructionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str
    mode: Optional[Literal["inspired", "react", "owner"]] = None


@router.get("/research/work-orders")
def list_work_orders(status: Optional[WorkOrderStatus] = None,
                     store: CampaignStore = Depends(get_store)):
    return work_orders.list_orders(store, status, source="trend")


@router.get("/work-orders")
def list_all_work_orders(source: Literal["all", "dm", "trend"] = "all",
                         status: Optional[WorkOrderStatus] = None,
                         limit: int = Query(100, ge=1, le=500),
                         store: CampaignStore = Depends(get_store)):
    return work_orders.list_orders(store, status, limit, source=source)


@router.patch("/work-orders/{order_id}")
def set_instruction(order_id: int, body: InstructionIn,
                    store: CampaignStore = Depends(get_store)):
    return call(work_orders.set_instruction, store, order_id, body.instruction, body.mode)


@router.delete("/research/work-orders/{order_id}", status_code=204)
def delete_work_order(order_id: int, store: CampaignStore = Depends(get_store)):
    out = call(work_orders.delete_order, store, order_id)
    return out if isinstance(out, Response) else Response(status_code=204)
