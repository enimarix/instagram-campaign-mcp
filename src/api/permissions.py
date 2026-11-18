"""/api/permissions: the permission tracker (thin doors onto src/studio/permissions.py, 065).

Nothing here sends a message: the draft is text the owner copies. Attach takes the raw file
as the request body (`POST /api/permissions/{id}/attach?name=<file name>`), like the reaction
reel upload, under max_clip_mb.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ..store import CampaignStore
from ..studio import permissions, reactions
from .assets import call, get_store

router = APIRouter(prefix="/api/permissions")


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: Optional[int] = None
    url: Optional[str] = None
    channel: Literal["dm", "email", "other"]
    note: Optional[str] = None
    creator: Optional[str] = None


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["granted", "denied"]
    proof_note: Optional[str] = None
    ads_allowed: bool = False


@router.get("")
def list_requests(status: Optional[Literal["requested", "granted", "denied"]] = None,
                  limit: int = Query(100, ge=1, le=500),
                  store: CampaignStore = Depends(get_store)):
    return permissions.list_requests(store, status, limit)


@router.get("/draft")
def draft(source_id: Optional[int] = None, url: Optional[str] = None,
          creator: Optional[str] = None, store: CampaignStore = Depends(get_store)):
    return call(permissions.draft, store, source_id if source_id is not None else url or "",
                creator)


@router.post("")
def ask(body: AskIn, store: CampaignStore = Depends(get_store)):
    target = body.source_id if body.source_id is not None else body.url or ""
    return call(permissions.request_permission, store, target, body.channel, body.note,
                creator=body.creator)


@router.post("/{request_id}/answer")
def answer(request_id: int, body: AnswerIn, store: CampaignStore = Depends(get_store)):
    return call(permissions.answer, store, request_id, body.status, body.proof_note,
                body.ads_allowed)


@router.post("/{request_id}/attach")
async def attach(request_id: int, request: Request, name: str = Query(..., max_length=200),
                 audio_rights: Optional[Literal["covered", "not_covered", "no_audio"]] = None,
                 store: CampaignStore = Depends(get_store)):
    length = request.headers.get("content-length")
    try:
        return await permissions.upload_granted_file(
            store, request.app.state.settings, request_id, request.stream(), name,
            int(length) if length else None, audio_rights=audio_rights)
    except KeyError:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    except reactions.UploadTooLarge as e:
        return JSONResponse(status_code=413, content={"error": "too_large", "message": str(e)})
    except ValueError as e:
        return JSONResponse(status_code=422, content={"error": "invalid", "message": str(e)})
