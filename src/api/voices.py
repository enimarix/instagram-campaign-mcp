"""Voix page routes (thin doors onto studio/voices.py and studio/elevenlabs.py): the
voice-over voices with their samples, the owner's on / off, and (step 204) the engines:
which speaks first, the ElevenLabs model and credits, the Voice Library search and the
ElevenLabs cards."""

from __future__ import annotations

from typing import Any, Callable, List, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..store import CampaignStore
from ..studio import elevenlabs, voices
from .assets import call, get_store

router = APIRouter(prefix="/api")


class VoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class EngineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: Optional[Literal["elevenlabs", "local"]] = None
    model: Optional[str] = Field(None, max_length=60)


class CardIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voice_id: str = Field(max_length=80)
    public_owner_id: Optional[str] = Field(None, max_length=80)  # a library voice
    label: str = Field(max_length=60)
    fallback: str = Field(max_length=60)
    gender: Optional[Literal["male", "female", "neutral"]] = None
    use_for: Optional[str] = Field(None, max_length=400)
    description: Optional[str] = Field(None, max_length=400)
    language: Optional[str] = Field(None, max_length=10)
    accent: Optional[str] = Field(None, max_length=40)
    preview_url: Optional[str] = Field(None, max_length=500)
    address: Optional[List[Literal["tu", "vous"]]] = None


def _el(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """call() with ElevenLabs' own failures as 502 (the page says what ElevenLabs said)."""
    try:
        return call(fn, *args, **kwargs)
    except elevenlabs.ElevenLabsError as e:
        return JSONResponse(status_code=502, content={"error": "elevenlabs", "message": str(e)})


@router.get("/voices")
def list_voices(store: CampaignStore = Depends(get_store)):
    return call(voices.list_voices, store)


@router.get("/voices/engine")
def engine(request: Request):
    return call(voices.engine_status, request.app.state.settings)


@router.patch("/voices/engine")
def set_engine(body: EngineIn):
    return call(voices.set_engine, body.priority, body.model)


@router.get("/voices/elevenlabs/models")
def models(request: Request):
    return _el(elevenlabs.models, request.app.state.settings)


@router.get("/voices/elevenlabs/search")
def search(request: Request, source: Literal["library", "account"] = "library",
           page: Optional[str] = Query(None, max_length=200),
           search: Optional[str] = Query(None, max_length=100),
           language: Optional[str] = Query(None, max_length=10),
           accent: Optional[str] = Query(None, max_length=40),
           gender: Optional[str] = Query(None, max_length=10),
           age: Optional[str] = Query(None, max_length=20),
           sort: Optional[str] = Query(None, max_length=40),
           use_cases: Optional[List[str]] = Query(None),
           descriptives: Optional[List[str]] = Query(None)):
    return _el(elevenlabs.search_voices, request.app.state.settings, source=source, page=page,
               search=search, language=language, accent=accent, gender=gender, age=age,
               sort=sort, use_cases=use_cases, descriptives=descriptives)


@router.post("/voices/elevenlabs")
def add_card(body: CardIn, request: Request):
    return _el(voices.add_from_elevenlabs, request.app.state.settings,
               **body.model_dump(exclude_none=True))


@router.get("/voices/{voice}/sample")
def sample(voice: str):
    path = voices.sample_file(voice)
    if path is None:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return FileResponse(path, media_type="audio/wav")


@router.patch("/voices/{voice}")
def set_voice(voice: str, body: VoiceIn, store: CampaignStore = Depends(get_store)):
    return call(voices.set_enabled, store, voice, body.enabled)


@router.delete("/voices/{voice}")
def remove_card(voice: str, store: CampaignStore = Depends(get_store)):
    return call(voices.remove_el_card, store, voice)
