"""GET /api/experiments: experiments for a later Learnings page section (step 086), a thin
door onto src/learning/experiments.py."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..learning import experiments
from ..store import CampaignStore
from .assets import call, get_store

router = APIRouter(prefix="/api/experiments")


@router.get("")
def list_experiments(status: Optional[str] = None, limit: int = Query(50, ge=1, le=100),
                     store: CampaignStore = Depends(get_store)):
    return call(lambda: {"experiments": experiments.list_experiments(store, status, limit)})
