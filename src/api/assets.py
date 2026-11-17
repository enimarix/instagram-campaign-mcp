"""
Review inbox REST routes (GOAL.md §3.2): thin doors onto src/studio/assets.py.

The actor is always the owner: the website is the owner's door (the password guards
it); the agent never uses REST.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ..store import CampaignStore
from ..studio import assets
from ..studio.assets import InvalidTransition
from ..studio.media import media_url

OWNER = "owner"

router = APIRouter(prefix="/api/assets")


def get_store(request: Request) -> CampaignStore:
    return request.app.state.store


def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return call(lambda: _with_urls(fn(*args, **kwargs)))


def call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a service call; translate its errors to the API's JSON errors."""
    try:
        return fn(*args, **kwargs)
    except KeyError:  # the store's "no <row> with id"
        return JSONResponse(status_code=404, content={"error": "not_found"})
    except InvalidTransition as e:
        return JSONResponse(status_code=409,
                            content={"error": "invalid_transition", "message": str(e)})
    except ValueError as e:
        return JSONResponse(status_code=422, content={"error": "invalid", "message": str(e)})


def _with_urls(asset: dict) -> dict:
    """The asset plus file_url / preview_url / thumbnail_url (None when there is no file)."""
    return {**asset, **{f"{k}_url": media_url(asset.get(f"{k}_path"))
                        for k in ("file", "preview", "thumbnail")}}


class VerdictIn(BaseModel):
    verdict: str


class AssetEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caption: Optional[str] = None
    best_before: Optional[str] = None


@router.get("")
def list_assets(batch_date: Optional[str] = None, status: Optional[str] = None,
                verdict: Optional[str] = None, track: Optional[str] = None,
                limit: int = Query(100, ge=1, le=500),
                store: CampaignStore = Depends(get_store)):
    return [_with_urls(a) for a in store.list_assets(
        batch_date=batch_date, status=status, verdict=verdict, track=track, limit=limit)]


@router.get("/{asset_id}")
def get_asset(asset_id: int, store: CampaignStore = Depends(get_store)):
    return _call(store.get_asset, asset_id)


@router.patch("/{asset_id}")
def edit_asset(asset_id: int, body: AssetEdit, store: CampaignStore = Depends(get_store)):
    return _call(assets.edit_asset, store, asset_id, **body.model_dump(exclude_unset=True))


@router.post("/{asset_id}/verdict")
def set_verdict(asset_id: int, body: VerdictIn, store: CampaignStore = Depends(get_store)):
    return _call(assets.set_verdict, store, asset_id, body.verdict)


@router.post("/{asset_id}/approve")
def approve(asset_id: int, store: CampaignStore = Depends(get_store)):
    # Approve only opens the door to publishing; slots are planned elsewhere (019/023).
    return _call(assets.transition, store, asset_id, "approved", actor=OWNER)


@router.post("/{asset_id}/unapprove")
def unapprove(asset_id: int, store: CampaignStore = Depends(get_store)):
    return _call(assets.transition, store, asset_id, "ready", actor=OWNER)


@router.post("/{asset_id}/archive")
def archive(asset_id: int, store: CampaignStore = Depends(get_store)):
    return _call(assets.transition, store, asset_id, "archived", actor=OWNER)
