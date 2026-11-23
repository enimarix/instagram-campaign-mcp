"""
Review inbox REST routes (GOAL.md §3.2): thin doors onto src/studio/assets.py.

The actor is always the owner: the website is the owner's door (the password guards
it); the agent never uses REST.
"""

from __future__ import annotations

from typing import Any, Callable, List, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict

from ..store import CampaignStore, utcnow
from ..studio import assets, checks, planned, remix, scheduling
from ..studio.assets import InvalidTransition
from ..studio.media import media_url
from ..studio.publish import QueueRefused, release_publish_check

OWNER = "owner"

router = APIRouter(prefix="/api/assets")


def get_store(request: Request) -> CampaignStore:
    return request.app.state.store


def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return call(lambda: with_urls(fn(*args, **kwargs)))


def call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a service call; translate its errors to the API's JSON errors."""
    try:
        return fn(*args, **kwargs)
    except KeyError:  # the store's "no <row> with id"
        return JSONResponse(status_code=404, content={"error": "not_found"})
    except InvalidTransition as e:
        return JSONResponse(status_code=409,
                            content={"error": "invalid_transition", "message": str(e)})
    except QueueRefused as e:  # before ValueError: it is one
        return JSONResponse(status_code=409, content={"error": e.code, "message": str(e)})
    except ValueError as e:
        return JSONResponse(status_code=422, content={"error": "invalid", "message": str(e)})


def with_urls(asset: dict) -> dict:
    """The asset plus file_url / preview_url / poster_url / thumbnail_url (None: no file)."""
    return {**asset, **{f"{k}_url": media_url(asset.get(f"{k}_path"))
                        for k in ("file", "preview", "poster", "thumbnail")}}


class VerdictIn(BaseModel):
    verdict: str


Trial = Optional[Literal["MANUAL", "SS_PERFORMANCE"]]  # a trial Reel's graduation (088)


class ScheduleIn(BaseModel):
    publish_at: AwareDatetime  # with an offset: a naive time would be guessed
    confirmed: bool = False
    trial: Trial = None


class ApproveIn(BaseModel):
    confirmed: bool = False  # the owner's per-video confirmation a commentary clip needs
    trial: Trial = None


class TranscriptIn(BaseModel):
    texts: List[str]  # the corrected text of each line GET /reaction lists, in order


class AssetEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caption: Optional[str] = None
    best_before: Optional[str] = None
    description: Optional[str] = None


@router.get("")
def list_assets(request: Request, batch_date: Optional[str] = None,
                status: Optional[str] = None, verdict: Optional[str] = None,
                track: Optional[str] = None, limit: int = Query(100, ge=1, le=500),
                store: CampaignStore = Depends(get_store)):
    # awaiting_check (188c): the Inbox leaves a video out until its check submits it
    rows = store.list_assets(batch_date=batch_date, status=status, verdict=verdict,
                             track=track, limit=limit)
    return [with_urls(a) for a in checks.flag(store, request.app.state.settings, rows,
                                              utcnow())]


@router.get("/{asset_id}")
def get_asset(asset_id: int, store: CampaignStore = Depends(get_store)):
    return _call(store.get_asset, asset_id)


@router.patch("/{asset_id}")
def edit_asset(asset_id: int, body: AssetEdit, store: CampaignStore = Depends(get_store)):
    return _call(assets.edit_asset, store, asset_id, **body.model_dump(exclude_unset=True))


@router.post("/{asset_id}/verdict")
def set_verdict(asset_id: int, body: VerdictIn, store: CampaignStore = Depends(get_store)):
    return _call(assets.set_verdict, store, asset_id, body.verdict)


@router.post("/{asset_id}/approve")
def approve(asset_id: int, store: CampaignStore = Depends(get_store)):
    # Approve only opens the door to publishing; scheduling is the next, explicit step.
    return _call(assets.transition, store, asset_id, "approved", actor=OWNER)


@router.post("/{asset_id}/approve-and-queue")
def approve_and_queue(asset_id: int, body: ApproveIn, request: Request,
                      store: CampaignStore = Depends(get_store)):
    # The feed's one-tap Approve: approved and queued into the next free slot (or approved
    # only when the planner's week is full: `slot` null).
    def run():
        out = scheduling.approve_and_queue(store, request.app.state.settings, asset_id,
                                           utcnow(), body.confirmed, body.trial)
        return {**out, "asset": with_urls(out["asset"])}
    return call(run)


@router.post("/{asset_id}/unapprove")
def unapprove(asset_id: int, store: CampaignStore = Depends(get_store)):
    return _call(scheduling.unapprove, store, asset_id)


@router.get("/{asset_id}/proposed-slot")
def proposed_slot(asset_id: int, request: Request, store: CampaignStore = Depends(get_store)):
    return call(scheduling.propose_slot, store, request.app.state.settings, asset_id, utcnow())


@router.get("/{asset_id}/slot")
def slot(asset_id: int, request: Request, store: CampaignStore = Depends(get_store)):
    return call(scheduling.slot, store, request.app.state.settings, asset_id)


@router.post("/{asset_id}/schedule")
def schedule(asset_id: int, body: ScheduleIn, request: Request,
             store: CampaignStore = Depends(get_store)):
    def run():
        out = scheduling.schedule_asset(store, request.app.state.settings, asset_id,
                                        body.publish_at, body.confirmed, body.trial)
        return {**out, "asset": with_urls(out["asset"])}
    return call(run)


@router.post("/{asset_id}/unschedule")
def unschedule(asset_id: int, store: CampaignStore = Depends(get_store)):
    return _call(scheduling.unschedule, store, asset_id)


@router.post("/{asset_id}/archive")
def archive(asset_id: int, store: CampaignStore = Depends(get_store)):
    return _call(planned.archive, store, asset_id)


@router.post("/{asset_id}/release")
def release(asset_id: int, store: CampaignStore = Depends(get_store)):
    # The owner checked Instagram: the post is not there (publish_check -> approved).
    return _call(release_publish_check, store, asset_id)


# Reaction remixes (072): the reel piece used, the next piece, the clip's speech.
@router.get("/{asset_id}/reaction")
def reaction(asset_id: int, store: CampaignStore = Depends(get_store)):
    return call(remix.reaction_info, store, asset_id)


def _rendered(out: dict) -> dict:
    return {**out, "asset": with_urls(out["asset"])}


@router.post("/{asset_id}/next-piece")
def next_piece(asset_id: int, request: Request, store: CampaignStore = Depends(get_store)):
    return call(lambda: _rendered(remix.use_next_piece(store, request.app.state.settings,
                                                       asset_id)))


@router.post("/{asset_id}/transcript")
def fix_transcript(asset_id: int, body: TranscriptIn, request: Request,
                   store: CampaignStore = Depends(get_store)):
    # Saves the corrected lines on the clip, then re-renders with captions rebuilt from them.
    return call(lambda: _rendered(remix.fix_transcript(store, request.app.state.settings,
                                                       asset_id, body.texts)))
