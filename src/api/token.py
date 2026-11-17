"""GET /api/token: access-token expiry for the Settings page and banner (thin door onto
src/studio/token.py; the token itself is never returned)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..studio import token as token_service

router = APIRouter(prefix="/api")


@router.get("/token")
async def token(request: Request):
    return await token_service.token_status(request.app.state.client, request.app.state.settings)
