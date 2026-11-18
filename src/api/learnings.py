"""/api/learnings*: the owner's Learnings page (step 084), thin doors onto
src/learning/learnings.py and evidence.py. The actor is always the owner: owner edits win."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from ..learning import evidence, learnings
from ..store import CampaignStore, utcnow
from .assets import call, get_store

router = APIRouter(prefix="/api/learnings")


class Predicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    value: str


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str
    kind: str
    predicate: Optional[Predicate] = None


class RuleEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: Optional[str] = None
    kind: Optional[str] = None
    predicate: Optional[Predicate] = None  # sent as null: the rule loses its predicate


def _scope(p: Optional[Predicate]) -> dict:
    return p.model_dump() if p else {}


@router.get("")
def list_learnings(kind: Optional[str] = None, status: Optional[str] = None,
                   origin: Optional[str] = None, confidence: Optional[str] = None,
                   store: CampaignStore = Depends(get_store)):
    return call(learnings.learnings_page, store, kind=kind, status=status, origin=origin,
                confidence=confidence)


@router.post("")
def add_rule(body: RuleIn, store: CampaignStore = Depends(get_store)):
    return call(lambda: learnings.add_learning(
        store, body.statement, body.kind, "taste", scope=_scope(body.predicate),
        actor="owner")["learning"])


@router.post("/refresh")
def refresh(request: Request, store: CampaignStore = Depends(get_store)):
    return evidence.refresh_learnings(store, request.app.state.settings, utcnow())


@router.patch("/{learning_id}")
def edit(learning_id: int, body: RuleEdit, request: Request,
         store: CampaignStore = Depends(get_store)):
    scope = _scope(body.predicate) if "predicate" in body.model_fields_set else None
    return call(learnings.update_learning, store, learning_id, statement=body.statement,
                kind=body.kind, scope=scope, settings=request.app.state.settings,
                actor="owner")


def _set(store: CampaignStore, learning_id: int, **fields):
    return call(learnings.update_learning, store, learning_id, actor="owner", **fields)


@router.post("/{learning_id}/confirm")
def confirm(learning_id: int, store: CampaignStore = Depends(get_store)):
    return _set(store, learning_id, confidence="owner")


@router.post("/{learning_id}/retire")
def retire(learning_id: int, store: CampaignStore = Depends(get_store)):
    return _set(store, learning_id, status="retired")


@router.post("/{learning_id}/reactivate")
def reactivate(learning_id: int, store: CampaignStore = Depends(get_store)):
    return _set(store, learning_id, status="active")
