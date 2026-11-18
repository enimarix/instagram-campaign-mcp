"""Settings page routes: disk usage (thin door onto src/studio/storage.py) and the
owner-editable settings (124, src/settings_overrides.py). Raising a money cap asks the
website password again (auth.reauth_error)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import settings_overrides as overrides
from ..studio import storage as storage_service
from .auth import reauth_error

router = APIRouter(prefix="/api")


@router.get("/storage")
def storage(request: Request):
    settings = request.app.state.settings
    return storage_service.storage(settings.media_root, settings.database_path,
                                   last_backup=request.app.state.store.get_state("last_backup"))


class SettingsPatch(BaseModel):
    values: Dict[str, Any] = {}
    reset: List[str] = []  # back to the .env value
    password: Optional[str] = None  # needed when a money cap rises


@router.get("/settings")
def get_settings(request: Request):
    return overrides.editable(request.app.state.store, request.app.state.settings)


@router.patch("/settings")
def patch_settings(request: Request, body: SettingsPatch):
    s = request.app.state
    try:
        try:
            return overrides.update(s.store, s.settings, body.values, body.reset)
        except overrides.PasswordNeeded:
            refused = reauth_error(s.auth, body.password)
            if refused:
                return JSONResponse(status_code=refused[0], content=refused[1])
            return overrides.update(s.store, s.settings, body.values, body.reset,
                                    confirmed=True)
    except overrides.SettingsInvalid as e:
        return JSONResponse(status_code=422, content={"error": "invalid", "message": e.message,
                                                      "field": e.field})
