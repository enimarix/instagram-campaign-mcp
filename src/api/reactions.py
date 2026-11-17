"""/api/reactions: the reaction reel (thin doors onto src/studio/reactions.py).

Upload: the raw file is the request body (`POST /api/reactions/upload?name=<file name>`),
streamed to disk chunk by chunk; no multipart form, so an hour of video is never spooled
twice or held in memory.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from ..store import CampaignStore
from ..studio import reactions
from .assets import call, get_store

router = APIRouter(prefix="/api/reactions")


@router.get("")
def list_reels(store: CampaignStore = Depends(get_store)):
    return reactions.list_reels(store)


@router.post("/upload")
async def upload(request: Request, name: str = Query(..., max_length=200),
                 store: CampaignStore = Depends(get_store)):
    length = request.headers.get("content-length")
    try:
        return await reactions.upload_reel(store, request.app.state.settings, request.stream(),
                                           name, int(length) if length else None)
    except reactions.UploadTooLarge as e:
        return JSONResponse(status_code=413, content={"error": "too_large", "message": str(e)})
    except ValueError as e:
        return JSONResponse(status_code=422, content={"error": "invalid", "message": str(e)})


@router.post("/{reel_id}/activate")
def activate(reel_id: int, store: CampaignStore = Depends(get_store)):
    return call(reactions.activate, store, reel_id)


@router.post("/{reel_id}/reset")
def reset(reel_id: int, store: CampaignStore = Depends(get_store)):
    return call(reactions.reset_cursor, store, reel_id)
