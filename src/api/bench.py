"""GET /api/bench: liked videos waiting to be approved (thin door onto
src/studio/scheduling.py bench())."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..store import CampaignStore, utcnow
from ..studio import scheduling
from .assets import get_store, with_urls

router = APIRouter(prefix="/api")


@router.get("/bench")
def bench(request: Request, store: CampaignStore = Depends(get_store)):
    out = scheduling.bench(store, request.app.state.settings, utcnow())
    return {**out, "assets": [with_urls(a) for a in out["assets"]]}
