"""Calendar routes (GOAL.md §3.3): thin doors onto src/studio/calendar.py. Actor: owner."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime, BaseModel

from ..store import CampaignStore
from ..studio import calendar
from ..studio.publish import cancel_post
from .assets import call, get_store, with_urls

router = APIRouter(prefix="/api")


class RescheduleIn(BaseModel):
    publish_at: AwareDatetime  # with an offset: a naive time would be guessed


class ReplanIn(BaseModel):
    confirmed: bool = False


@router.get("/calendar")
def get_calendar(request: Request, start: date = Query(alias="from"),
                 end: date = Query(alias="to"), store: CampaignStore = Depends(get_store)):
    def run():
        out = calendar.calendar(store, request.app.state.settings, start, end)
        return {**out, "publish_check": [with_urls(a) for a in out["publish_check"]]}
    return call(run)


@router.post("/posts/{post_id}/reschedule")
def reschedule(post_id: int, body: RescheduleIn, store: CampaignStore = Depends(get_store)):
    return call(calendar.reschedule, store, post_id, body.publish_at)


@router.post("/posts/{post_id}/cancel")
def cancel(post_id: int, store: CampaignStore = Depends(get_store)):
    return call(cancel_post, store, post_id)


@router.post("/posts/{post_id}/replan")
def replan(post_id: int, request: Request, body: Optional[ReplanIn] = None,
           store: CampaignStore = Depends(get_store)):
    return call(calendar.replan, store, request.app.state.settings, post_id,
                confirmed=bool(body and body.confirmed))
