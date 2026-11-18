"""Ads budget routes (step 091): thin doors onto src/ads/budget.py.

No MCP tool reaches these: the agent never touches money. Unkill asks the website
password again (auth.reauth_error), like budget approval will (094).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..ads import budget
from .auth import reauth_error

router = APIRouter(prefix="/api/ads")


class KillBody(BaseModel):
    reason: str = Field("kill switch", min_length=1, max_length=200)


class UnkillBody(BaseModel):
    password: str


def _status(request: Request) -> dict:
    return budget.status(request.app.state.store, request.app.state.settings)


@router.get("/budget")
def get_budget(request: Request):
    return _status(request)


@router.post("/kill")
def kill(request: Request, body: Optional[KillBody] = None):
    budget.kill(request.app.state.store, (body or KillBody()).reason)
    return _status(request)


@router.post("/unkill")
def unkill(request: Request, body: UnkillBody):
    refused = reauth_error(request.app.state.auth, body.password)
    if refused:
        return JSONResponse(status_code=refused[0], content=refused[1])
    budget.unkill(request.app.state.store)
    return _status(request)
