"""Publishing worker routes: status and the pause switch (thin doors onto src/worker.py)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from .. import worker

router = APIRouter(prefix="/api/worker")


@router.get("/status")
def status(request: Request):
    return worker.status(request.app.state.store, request.app.state.settings)


@router.post("/pause")
def pause(request: Request):
    return worker.set_paused(request.app.state.store, request.app.state.settings, True)


@router.post("/resume")
def resume(request: Request):
    return worker.set_paused(request.app.state.store, request.app.state.settings, False)
