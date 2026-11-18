"""Alerts for the website's bell: list and dismiss (thin doors onto src/studio/alerts.py)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..store import utcnow
from ..studio import alerts as alerts_service

router = APIRouter(prefix="/api/alerts")


@router.get("")
async def alerts(request: Request):
    state = request.app.state
    return await alerts_service.alerts(state.store, state.settings, utcnow(), state.client)


@router.post("/{alert_id}/dismiss")
def dismiss(alert_id: str, request: Request):
    return alerts_service.dismiss(request.app.state.store, alert_id, utcnow())
