"""Planning routes: what renders next and when, « start now » and the timer of a waiting
render or film (thin doors onto src/studio/planning.py and src/studio/line.py)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..store import CampaignStore, utcnow
from ..studio import line, planning
from .assets import call, get_store

router = APIRouter(prefix="/api")
Kind = Literal["render", "film"]  # id: the render job's, the film's work order's


class TimerIn(BaseModel):
    at: Optional[datetime] = None  # UTC ISO; null clears the timer


@router.get("/planning")
def get_planning(request: Request):
    return planning.build_planning(request.app.state.store, request.app.state.settings,
                                   utcnow())


@router.post("/planning/{kind}/{item_id}/start-now")
def start_now(kind: Kind, item_id: int, store: CampaignStore = Depends(get_store)):
    return call(line.start_now, store, kind, item_id)


@router.put("/planning/{kind}/{item_id}/timer")
def set_timer(kind: Kind, item_id: int, body: TimerIn,
              store: CampaignStore = Depends(get_store)):
    return call(line.set_timer, store, kind, item_id, body.at)
