"""Planning route: what renders next and when (thin door onto src/studio/planning.py)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..store import utcnow
from ..studio import planning

router = APIRouter(prefix="/api")


@router.get("/planning")
def get_planning(request: Request):
    return planning.build_planning(request.app.state.store, request.app.state.settings,
                                   utcnow())
