"""Agent routes (thin doors onto src/agent/runs.py and schedule.py)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..agent import runs, schedule
from ..agent.runner import AgentError, AgentRunRefused
from ..store import utcnow

router = APIRouter(prefix="/api/agent")


class RunIn(BaseModel):
    playbook: str


@router.get("/playbooks")
def playbooks():
    return runs.list_playbooks()


@router.get("/schedule")
def agent_schedule(request: Request):
    return schedule.overview(request.app.state.store, request.app.state.settings, utcnow())


@router.get("/runs")
def list_runs(request: Request, limit: int = Query(50, ge=1, le=500)):
    return runs.list_runs(request.app.state.store, limit)


@router.get("/runs/{run_id}/log")
def log(request: Request, run_id: int):
    try:
        return runs.log_tail(request.app.state.store, request.app.state.settings, run_id)
    except KeyError:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    except PermissionError:
        return JSONResponse(status_code=403, content={"error": "log_outside_log_dir"})


@router.post("/runs")
def start(request: Request, body: RunIn):
    try:
        return runs.start_run(request.app.state.store, request.app.state.settings,
                              body.playbook)
    except AgentRunRefused as e:  # before AgentError: it is one
        return JSONResponse(status_code=409, content={"error": "already_running",
                                                      "message": str(e)})
    except AgentError as e:
        return JSONResponse(status_code=404, content={"error": "unknown_playbook",
                                                      "message": str(e)})
