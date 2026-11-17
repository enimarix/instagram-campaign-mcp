"""Clip intake routes (thin doors onto src/studio/sources.py, step 063): the clips with
their rights and attribution, the inbox files waiting for their rights, and the form that
turns one into a clip; POST /download fetches a public Reel for a reaction (063b)."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict

from ..store import CampaignStore, utcnow
from ..studio import downloader, sources
from .assets import call, get_store

router = APIRouter(prefix="/api/sources")


class IntakeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rights_basis: str
    rights_note: str
    audio_rights: Optional[Literal["covered", "not_covered", "no_audio"]] = None
    author: Optional[str] = None
    url: Optional[str] = None
    licence: Optional[str] = None


@router.get("")
def list_sources(role: Literal["clip", "reference"] = "clip",
                 limit: int = Query(100, ge=1, le=500),
                 store: CampaignStore = Depends(get_store)):
    return sources.list_clips(store, role, limit)


@router.get("/inbox")
def inbox(request: Request):
    return sources.scan_inbox(request.app.state.settings)


@router.post("/inbox/{name}")
def ingest_inbox_file(name: str, body: IntakeIn, request: Request,
                      store: CampaignStore = Depends(get_store)):
    provider = sources.LocalInboxProvider(store, request.app.state.settings)
    return call(lambda: sources.with_attribution(provider.ingest(name, **body.model_dump())))


class DownloadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: Optional[int] = None
    url: Optional[str] = None


@router.post("/download")
def download(body: DownloadIn, request: Request, store: CampaignStore = Depends(get_store)):
    """{status: downloaded | exists | refused | failed, source?, reason?} (blocking: the
    pause between downloads and the file transfer run in FastAPI's thread pool)."""
    target = body.source_id if body.source_id is not None else body.url or ""
    return call(downloader.download_reel, store, request.app.state.settings, target,
                now=utcnow())
