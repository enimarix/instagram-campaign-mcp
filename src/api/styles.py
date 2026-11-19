"""Style routes (thin doors, step 138): the style buttons (studio/styles.py), their preview
files, the owner's Settings per style, and the two launch points that are not a Reel:
« Créer une vidéo » and « même vidéo, autre style » (studio/work_orders.py); the styles
the agent asks for and the owner's « Construire » / « Non » (studio/style_requests.py,
156)."""

from __future__ import annotations

from typing import Any, Callable, Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..store import CampaignStore
from ..studio import style_requests, styles, work_orders
from ..studio.motion import MotionError
from .assets import call, get_store

router = APIRouter(prefix="/api")


def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """call(), plus 503 when the templates cannot be listed (Node or motion/ missing)."""
    try:
        return call(fn, *args, **kwargs)
    except MotionError as e:
        return JSONResponse(status_code=503, content={"error": "styles_unavailable",
                                                      "message": str(e)})


class StyleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: Optional[bool] = None
    share: Optional[float] = None  # None (sent): no limit; left out: unchanged


class CreateVideoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(max_length=work_orders.INSTRUCTION_MAX)
    style: Optional[str] = None  # None: Auto


class RestyleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: Optional[str] = None  # None: another style the agent picks
    note: Optional[str] = None


class StyleRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accepted", "declined"]  # « Construire » / « Non »
    note: Optional[str] = Field(None, max_length=style_requests.NOTE_MAX)


@router.get("/styles")
def list_styles(store: CampaignStore = Depends(get_store)):
    return _call(styles.list_styles, store)


@router.get("/styles/{style}/preview/{kind}")
def preview(style: str, kind: Literal["still", "clip"]):
    path = styles.preview_file(style, kind)
    if path is None:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return FileResponse(path)


@router.patch("/styles/{style}")
def set_style(style: str, body: StyleIn, store: CampaignStore = Depends(get_store)):
    return _call(styles.set_choice, store, style, **body.model_dump(exclude_unset=True))


@router.post("/work-orders")
def create_video(body: CreateVideoIn, store: CampaignStore = Depends(get_store)):
    return _call(work_orders.create_video, store, body.instruction, body.style)


@router.post("/assets/{asset_id}/restyle")
def restyle(asset_id: int, body: RestyleIn, store: CampaignStore = Depends(get_store)):
    return _call(work_orders.restyle, store, asset_id, body.style, body.note)


@router.get("/style-requests")
def list_style_requests(status: Optional[str] = None, limit: int = Query(100, ge=1, le=500),
                        store: CampaignStore = Depends(get_store)):
    return call(style_requests.list_requests, store, status, limit)


@router.patch("/style-requests/{request_id}")
def decide_style_request(request_id: int, body: StyleRequestIn,
                         store: CampaignStore = Depends(get_store)):
    return call(style_requests.decide, store, request_id, body.decision, body.note)
