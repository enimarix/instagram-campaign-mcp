"""DM picks routes (thin doors onto studio/dm_picks.py, step 113): the pinned accounts the
owner edits, and the picks their DMs produced, with a skip button."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from ..store import CampaignStore
from ..studio import dm_picks
from .assets import call, get_store

router = APIRouter(prefix="/api")


class PinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    note: Optional[str] = None


class SkipIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


@router.get("/pinned-accounts")
def list_pinned(store: CampaignStore = Depends(get_store)):
    return dm_picks.list_pinned(store)


@router.post("/pinned-accounts")
def pin_account(body: PinIn, store: CampaignStore = Depends(get_store)):
    return call(dm_picks.pin_account, store, body.username, body.note)


@router.delete("/pinned-accounts/{account_id}", status_code=204)
def unpin_account(account_id: int, store: CampaignStore = Depends(get_store)):
    out = call(dm_picks.unpin_account, store, account_id)
    return out if isinstance(out, Response) else Response(status_code=204)


@router.get("/dm-picks")
def list_picks(status: Optional[Literal["new", "downloaded", "in_production", "posted",
                                       "skipped"]] = None,
               store: CampaignStore = Depends(get_store)):
    return dm_picks.list_picks(store, status)


@router.post("/dm-picks/{pick_id}/skip")
def skip_pick(pick_id: int, body: SkipIn, store: CampaignStore = Depends(get_store)):
    return call(dm_picks.mark_pick, store, pick_id, "skipped", body.reason)
