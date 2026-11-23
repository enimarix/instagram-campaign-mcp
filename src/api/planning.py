"""Planning routes: what renders next and when, « start now », the timer, hold, move, place
(drag and drop, 195) and remove of a waiting render or film (remove: an owner order too),
the studio's pause switch, the delay preview (190), Claude's planned videos: release,
edit, remove, and « Lancer » one card or many (196) (thin doors onto
src/studio/planning.py, src/studio/line.py and src/studio/planned.py)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional, Union

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from ..store import CampaignStore, utcnow
from ..studio import line, planned, planning
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


class PlaceIn(BaseModel):
    index: int  # among the other waiting items not held: 0 the head (line.place)


class PauseIn(BaseModel):
    paused: bool


class ReleaseIn(BaseModel):
    now: bool = False  # « Lancer maintenant »
    at: Optional[datetime] = None  # « Minuteur », UTC ISO


class IdeaEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voice: Optional[str] = None
    music: Optional[str] = None  # a bed (music-...), none, or an Instagram track's audio_id
    lines: Optional[List[str]] = None  # the spoken lines, in the card's order
    caption: Optional[str] = None
    description: Optional[str] = None


class PreviewIn(BaseModel):
    action: Literal["start_now", "move", "release"]
    kind: Literal["render", "film", "idea"]  # idea: release, id its video
    id: int
    by: Literal[-1, 0, 1] = 0  # move: -1 up, 1 down


class LaunchItem(BaseModel):
    kind: str  # render | film | claude_idea | work_order | change_request | agent_run
    id: Union[int, str]  # the job's, the order's, the video's; agent_run: the playbook


class LaunchIn(BaseModel):
    items: List[LaunchItem]  # in on-screen order


@router.get("/planning")
def get_planning(request: Request):
    return planning.build_planning(request.app.state.store, request.app.state.settings,
                                   utcnow())


@router.post("/planning/preview")
def preview(body: PreviewIn, request: Request, store: CampaignStore = Depends(get_store)):
    return call(planning.preview, store, request.app.state.settings, utcnow(), body.action,
                body.kind, body.id, body.by)


@router.post("/planning/launch")
def launch(body: LaunchIn, request: Request, store: CampaignStore = Depends(get_store)):
    return call(planning.launch, store, request.app.state.settings,
                [i.model_dump() for i in body.items], utcnow())


@router.post("/planning/launch/preview")
def preview_launch(body: LaunchIn, request: Request, store: CampaignStore = Depends(get_store)):
    return call(planning.preview_launch, store, request.app.state.settings, utcnow(),
                [i.model_dump() for i in body.items])


# Before the line's routes: /planning/{kind}/{item_id}/remove would take /idea/... first.
@router.post("/planning/idea/{asset_id}/release")
def release_idea(asset_id: int, request: Request, body: ReleaseIn,
                 store: CampaignStore = Depends(get_store)):
    return call(planned.release, store, request.app.state.settings, asset_id, now=body.now,
                at=body.at)


@router.patch("/planning/idea/{asset_id}")
def edit_idea(asset_id: int, body: IdeaEdit, request: Request,
              store: CampaignStore = Depends(get_store)):
    return call(planned.edit, store, request.app.state.settings, asset_id,
                **body.model_dump(exclude_none=True))


@router.post("/planning/idea/{asset_id}/remove")
def remove_idea(asset_id: int, store: CampaignStore = Depends(get_store)):
    return call(planned.remove, store, asset_id)


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


@router.post("/planning/{kind}/{item_id}/place")
def place(kind: Kind, item_id: int, body: PlaceIn, store: CampaignStore = Depends(get_store)):
    return call(line.place, store, kind, item_id, body.index)


@router.post("/planning/{kind}/{item_id}/remove")
def remove(kind: Removable, item_id: int, store: CampaignStore = Depends(get_store)):
    return call(line.remove, store, kind, item_id)


@router.put("/planning/pause")
def pause(body: PauseIn, store: CampaignStore = Depends(get_store)):
    return call(line.pause, store, body.paused)

