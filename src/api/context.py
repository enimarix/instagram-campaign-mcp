"""GET /api/assets/{id}/context: a thin door onto src/studio/context.py."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..store import CampaignStore
from ..studio.context import asset_context
from .assets import call, get_store

router = APIRouter(prefix="/api/assets")


@router.get("/{asset_id}/context")
def get_context(asset_id: int, store: CampaignStore = Depends(get_store)):
    return call(asset_context, store, asset_id)
