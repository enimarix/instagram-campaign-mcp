"""Stock clip routes (thin doors onto src/studio/stock.py, step 064). Without
PEXELS_API_KEY: GET /api/stock says configured false (the website hides the search) and
the other routes answer 503 stock_not_configured."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ..store import CampaignStore
from ..studio import stock
from .assets import call, get_store

router = APIRouter(prefix="/api/stock")


def _call(fn, *args, **kwargs):
    try:
        return call(fn, *args, **kwargs)
    except stock.NotConfigured as e:
        return JSONResponse(status_code=503,
                            content={"error": "stock_not_configured", "message": str(e)})


@router.get("")
def status(request: Request):
    return {"configured": stock.configured(request.app.state.settings), "provider": "pexels"}


@router.get("/search")
def search(request: Request, q: str = Query(..., min_length=1, max_length=100),
           orientation: Literal["portrait", "landscape", "square"] = "portrait",
           min_duration: Optional[float] = Query(None, ge=0),
           max_duration: Optional[float] = Query(None, ge=0),
           per_page: int = Query(15, ge=1, le=80),
           store: CampaignStore = Depends(get_store)):
    return _call(stock.search, store, request.app.state.settings, q, orientation=orientation,
                 min_duration=min_duration, max_duration=max_duration, per_page=per_page)


class AddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_id: int


@router.post("/add")
def add(body: AddIn, request: Request, store: CampaignStore = Depends(get_store)):
    return _call(stock.add_clip, store, request.app.state.settings, body.result_id)
