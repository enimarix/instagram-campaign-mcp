"""Planning routes: what renders next and when, « start now », the timer, hold, move and
remove of a waiting render or film (remove: an owner order too), and the studio's pause
switch (thin doors onto src/studio/planning.py and src/studio/line.py)."""

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
Removable = Literal["render", "film", "order"]  # order: its work order's id


class TimerIn(BaseModel):
    at: Optional[datetime] = None  # UTC ISO; null clears the timer


class HoldIn(BaseModel):
    held: bool


class MoveIn(BaseModel):
    by: Literal[-1, 1]  # -1 up, 1 down


class PauseIn(BaseModel):
    paused: bool


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


@router.put("/planning/{kind}/{item_id}/hold")
def hold(kind: Kind, item_id: int, body: HoldIn, store: CampaignStore = Depends(get_store)):
    return call(line.hold, store, kind, item_id, body.held)


@router.post("/planning/{kind}/{item_id}/move")
def move(kind: Kind, item_id: int, body: MoveIn, store: CampaignStore = Depends(get_store)):
    return call(line.move, store, kind, item_id, body.by)


@router.post("/planning/{kind}/{item_id}/remove")
def remove(kind: Removable, item_id: int, store: CampaignStore = Depends(get_store)):
    return call(line.remove, store, kind, item_id)


@router.put("/planning/pause")
def pause(body: PauseIn, store: CampaignStore = Depends(get_store)):
    return call(line.pause, store, body.paused)
