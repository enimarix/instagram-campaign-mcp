"""Settings page routes: disk usage (thin door onto src/studio/storage.py)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..studio import storage as storage_service

router = APIRouter(prefix="/api")


@router.get("/storage")
def storage(request: Request):
    settings = request.app.state.settings
    return storage_service.storage(settings.media_root, settings.database_path,
                                   last_backup=request.app.state.store.get_state("last_backup"))
