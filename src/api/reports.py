"""GET /api/reports*: the daily report page (step 085), thin doors onto
src/learning/report.py."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..learning import report
from ..store import CampaignStore
from .assets import call, get_store

router = APIRouter(prefix="/api/reports")


@router.get("")
def archive(limit: int = Query(60, ge=1, le=report.ARCHIVE_MAX),
            store: CampaignStore = Depends(get_store)):
    return report.report_archive(store, limit)


@router.get("/latest")
def latest(store: CampaignStore = Depends(get_store)):
    return call(report.report_page, store)


@router.get("/{report_date}")
def by_date(report_date: str, store: CampaignStore = Depends(get_store)):
    return call(report.report_page, store, report_date)
