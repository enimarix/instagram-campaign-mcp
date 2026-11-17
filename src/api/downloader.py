"""GET /api/downloader/status: the Reel downloader service for Settings (thin door onto
src/studio/downloader_service.py)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..studio import downloader_service

router = APIRouter(prefix="/api/downloader")


@router.get("/status")
def status(request: Request):
    return downloader_service.status(request.app.state.store, request.app.state.settings)
