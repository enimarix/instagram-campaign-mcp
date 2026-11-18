"""Ads routes: budget and kill switch (091), A/B tests and the audit log (094), a test's
results (095). Thin doors onto src/ads/budget.py, src/ads/tests.py and src/ads/sync.py.

The agent launches and stops tests through its own MCP tools (126); the owner's Approve
here launches a proposed test too, without a password (the caps and the kill switch are
the money safety). Unkill asks the website password again (auth.reauth_error).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Awaitable, List, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..ads import budget, sync, tests
from ..ads.budget import BudgetRefused
from ..instagram_client import NotConfigured
from .auth import reauth_error

router = APIRouter(prefix="/api/ads")


class KillBody(BaseModel):
    reason: str = Field("kill switch", min_length=1, max_length=200)


class UnkillBody(BaseModel):
    password: str


def _status(request: Request) -> dict:
    st = budget.status(request.app.state.store, request.app.state.settings)
    return {**st, "near_cap": sync.near_caps(st)}


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


class VariantIn(BaseModel):
    media_id: str = Field(min_length=1, max_length=40)
    preset: str


class ProposeBody(BaseModel):
    hypothesis: str = Field(min_length=1, max_length=500)
    variable: str
    variants: List[VariantIn]
    min_lift: float = Field(0.2, gt=0, le=5)
    primary_metric: str = "ctr"
    baseline_rate: Optional[float] = Field(None, gt=0, lt=1)


class ApproveBody(BaseModel):
    budget: Decimal
    underpowered_ok: bool = False


async def _call(work: Awaitable[Any]) -> Any:
    try:
        return await work
    except KeyError:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    except (tests.AdTestRefused, BudgetRefused) as e:
        return JSONResponse(status_code=409, content={"error": e.code, "message": e.message})
    except tests.AdTestFailed as e:
        return JSONResponse(status_code=502, content={"error": "failed", "message": str(e)})
    except NotConfigured as e:
        return JSONResponse(status_code=503,
                            content={"error": "ads_not_configured", "message": str(e)})


@router.get("/tests")
def list_tests(request: Request, status: Optional[str] = None):
    s = request.app.state
    return {"tests": tests.list_tests(s.store, s.settings, status=status)}


@router.get("/tests/{test_id}")
def get_test(request: Request, test_id: int):
    s = request.app.state
    try:
        return sync.results(s.store, s.settings, test_id)
    except KeyError:
        return JSONResponse(status_code=404, content={"error": "not_found"})


@router.get("/winners")
def winners(request: Request):
    s = request.app.state
    return {"winners": tests.eligible_winners(s.store, s.settings)}


@router.get("/presets")
def presets(request: Request):
    return {"presets": tests.presets(request.app.state.settings)}


@router.post("/tests")
async def propose(request: Request, body: ProposeBody):
    s = request.app.state
    return await _call(tests.propose(s.store, s.settings, **body.model_dump()))


@router.post("/tests/{test_id}/approve")
async def approve(request: Request, test_id: int, body: ApproveBody):
    s = request.app.state
    return await _call(tests.launch(s.store, s.settings, test_id, body.budget, actor="owner",
                                    underpowered_ok=body.underpowered_ok))


@router.post("/tests/{test_id}/cancel")
async def cancel(request: Request, test_id: int):
    s = request.app.state
    return await _call(tests.cancel(s.store, s.settings, test_id))


@router.get("/audit")
def audit_log(request: Request, limit: int = Query(50, ge=1, le=200),
              offset: int = Query(0, ge=0)):
    return budget.audit_log(request.app.state.store, limit=limit, offset=offset)
