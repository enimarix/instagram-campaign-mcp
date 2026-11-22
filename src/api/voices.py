"""Voix page routes (thin doors onto studio/voices.py): the voice-over voices with their
samples, and the owner's on / off."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from ..store import CampaignStore
from ..studio import voices
from .assets import call, get_store

router = APIRouter(prefix="/api")


class VoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.get("/voices")
def list_voices(store: CampaignStore = Depends(get_store)):
    return call(voices.list_voices, store)


@router.get("/voices/{voice}/sample")
def sample(voice: str):
    path = voices.sample_file(voice)
    if path is None:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return FileResponse(path, media_type="audio/wav")


@router.patch("/voices/{voice}")
def set_voice(voice: str, body: VoiceIn, store: CampaignStore = Depends(get_store)):
    return call(voices.set_enabled, store, voice, body.enabled)
