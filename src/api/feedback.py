"""
Owner comments REST routes (GOAL.md §3.2): thin doors onto src/studio/feedback.py,
plus the taxonomy the website's reason chips need. The actor is always the owner.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .. import taxonomy
from ..store import CampaignStore
from ..studio import feedback
from .assets import _with_urls, call, get_store

router = APIRouter(prefix="/api")


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Optional[str] = None
    reason_codes: List[str] = []
    video_time_s: Optional[float] = Field(None, ge=0)
    wants_changes: bool = False


class CommentEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Optional[str] = None
    reason_codes: List[str] = []  # defaults unused: only the keys sent are applied
    video_time_s: Optional[float] = Field(None, ge=0)
    wants_changes: bool = False


def _out(result: dict) -> dict:
    return {**result, "asset": _with_urls(result["asset"])}


@router.get("/assets/{asset_id}/feedback")
def list_feedback(asset_id: int, store: CampaignStore = Depends(get_store)):
    return call(feedback.list_comments, store, asset_id)


@router.post("/assets/{asset_id}/feedback")
def add_feedback(asset_id: int, body: CommentIn, store: CampaignStore = Depends(get_store)):
    return call(lambda: _out(feedback.add_comment(store, asset_id, **body.model_dump())))


@router.patch("/feedback/{feedback_id}")
def edit_feedback(feedback_id: int, body: CommentEdit,
                  store: CampaignStore = Depends(get_store)):
    fields = body.model_dump(exclude_unset=True)
    return call(lambda: _out(feedback.edit_comment(store, feedback_id, **fields)))


@router.delete("/feedback/{feedback_id}", status_code=204)
def delete_feedback(feedback_id: int, store: CampaignStore = Depends(get_store)):
    return call(feedback.delete_comment, store, feedback_id) or Response(status_code=204)


@router.get("/taxonomy")
def get_taxonomy():
    """Every vocabulary in brand/taxonomy.json: {kind: {values: [{id, label, ...}]}}."""
    return taxonomy.load_taxonomy()
