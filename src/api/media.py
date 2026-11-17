"""
GET /api/media/<path>: asset files for the website, with HTTP Range (the player seeks).

Behind the session like every /api route. `studio.media.resolve` keeps every request inside
the media root; FileResponse answers Range with 206 + Content-Range.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from ..studio.media import resolve

# Explicit: mimetypes depends on the OS (Windows registry) and older Pythons lack webp.
MEDIA_TYPES = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".png": "image/png", ".webp": "image/webp"}

router = APIRouter(prefix="/api/media")


@router.get("/{rel:path}")
def media(rel: str, request: Request):
    try:
        path = resolve(request.app.state.media_root, rel)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "bad_path"})
    if not path.is_file():
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return FileResponse(path, media_type=MEDIA_TYPES.get(path.suffix.lower()))
