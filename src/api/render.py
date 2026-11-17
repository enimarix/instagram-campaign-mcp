"""Render routes: re-render with an edited recipe, render queue progress (thin doors onto
src/studio/render.py)."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from ..store import CampaignStore
from ..studio import render
from .assets import OWNER, call, get_store, with_urls

router = APIRouter(prefix="/api")


class RerenderIn(BaseModel):
    recipe: Dict[str, Any]


@router.post("/assets/{asset_id}/rerender")
def rerender(asset_id: int, body: RerenderIn, request: Request,
             store: CampaignStore = Depends(get_store)):
    def run():
        out = render.rerender(store, request.app.state.settings.media_root, asset_id,
                              body.recipe, actor=OWNER)
        return {**out, "asset": with_urls(out["asset"])}
    return call(run)


@router.get("/render-jobs")
def render_jobs(state: Optional[Literal["queued", "running", "done", "failed"]] = None,
                asset_id: Optional[int] = None, limit: int = Query(100, ge=1, le=500),
                store: CampaignStore = Depends(get_store)):
    return store.list_render_jobs(state=state, asset_id=asset_id, limit=limit)
