"""
The ElevenLabs API (step 204), thin and synchronous: speech with character timings, the
account's credits, the models, the account's voices, the shared Voice Library and adding a
library voice to the account. Docs read 2026-11-24 (elevenlabs.io/docs/api-reference):
auth header `xi-api-key`; POST /v1/text-to-speech/{voice_id}/with-timestamps answers
{audio_base64, alignment: {characters, character_start_times_seconds,
character_end_times_seconds}}; GET /v1/user/subscription (character_count, character_limit,
next_character_count_reset_unix); GET /v1/models; GET /v2/voices (next_page_token);
GET /v1/shared-voices (page); POST /v1/voices/add/{public_owner_id}/{voice_id} {new_name}.
Error bodies are not documented in pages we could read: every non-2xx is an ElevenLabsError
with its status. docs/developers/resources/errors (read 2026-11-25): 429 is a rate or
concurrency limit (« implement exponential backoff »), 500 / 503 a passing server fault; no
Retry-After is documented (kept when sent). The studio retries those (tts.py), then falls back
to the local voice.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any, Dict, List, Optional

import httpx

from ..config import InstagramMCPSettings

OUTPUT_FORMAT = "mp3_44100_128"
LIBRARY_FILTERS = ("search", "language", "accent", "gender", "age", "sort")
LIST_FILTERS = ("use_cases", "descriptives")
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")  # ids go into URL paths: never anything else


def _id(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"not an ElevenLabs id: {value!r}")
    return value


class ElevenLabsError(RuntimeError):
    """A failed call: `status` the HTTP status (None: no answer), `retry_after` the answer's
    Retry-After seconds when it sent one. Never carries the key."""

    def __init__(self, message: str, status: Optional[int] = None,
                 retry_after: Optional[float] = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def configured(settings: InstagramMCPSettings) -> bool:
    return bool(settings.elevenlabs_api_key and settings.elevenlabs_api_key.get_secret_value())


def _detail(resp: httpx.Response) -> str:
    """The error's own words when the body has them (`detail.message` / `detail.status`)."""
    try:
        d = resp.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    if isinstance(d, dict):
        return str(d.get("message") or d.get("status") or "")[:200]
    return str(d or "")[:200]


def _call(settings: InstagramMCPSettings, method: str, path: str, *,
          client: Optional[httpx.Client] = None, **kw: Any) -> Any:
    if not configured(settings):
        raise ElevenLabsError("ELEVENLABS_API_KEY is not set")
    headers = {"xi-api-key": settings.elevenlabs_api_key.get_secret_value()}
    http = client or httpx.Client()
    try:
        resp = http.request(method, settings.elevenlabs_url.rstrip("/") + path, headers=headers,
                            timeout=settings.elevenlabs_timeout_s, **kw)
    except httpx.HTTPError as e:
        raise ElevenLabsError(f"ElevenLabs did not answer ({type(e).__name__})") from None
    finally:
        if client is None:
            http.close()
    if resp.status_code >= 400:
        why = _detail(resp)
        after = resp.headers.get("retry-after", "")
        raise ElevenLabsError(f"ElevenLabs answered HTTP {resp.status_code}"
                              + (f": {why}" if why else ""), resp.status_code,
                              float(after) if after.isdigit() else None)
    try:
        return resp.json()
    except ValueError:
        raise ElevenLabsError("ElevenLabs answered something that is not JSON") from None


def speech(settings: InstagramMCPSettings, voice_id: str, text: str, model_id: str, *,
           client: Optional[httpx.Client] = None):
    """(mp3 bytes, alignment dict or None). No language_code: ElevenLabs takes the script's
    language from the text (a voice's own label is not the script's language)."""
    body: Dict[str, Any] = {"text": text, "model_id": model_id}
    data = _call(settings, "POST", f"/v1/text-to-speech/{_id(voice_id)}/with-timestamps",
                 params={"output_format": OUTPUT_FORMAT}, json=body, client=client)
    try:
        audio = base64.b64decode(data["audio_base64"], validate=True)
    except (KeyError, TypeError, binascii.Error):
        raise ElevenLabsError("ElevenLabs returned no audio") from None
    return audio, data.get("alignment")


def credits(settings: InstagramMCPSettings, *, client: Optional[httpx.Client] = None
            ) -> Dict[str, Any]:
    """{used, limit, left, resets_at (unix or None), tier}."""
    s = _call(settings, "GET", "/v1/user/subscription", client=client)
    used, limit = int(s.get("character_count") or 0), int(s.get("character_limit") or 0)
    return {"used": used, "limit": limit, "left": max(limit - used, 0),
            "resets_at": s.get("next_character_count_reset_unix"), "tier": s.get("tier")}


def models(settings: InstagramMCPSettings, *, client: Optional[httpx.Client] = None
           ) -> List[Dict[str, Any]]:
    """The text-to-speech models: {id, name, description, languages: [codes], cost}."""
    return [{"id": m["model_id"], "name": m.get("name") or m["model_id"],
             "description": m.get("description") or "",
             "languages": [lang.get("language_id") for lang in m.get("languages") or []],
             "cost": (m.get("model_rates") or {}).get("character_cost_multiplier")}
            for m in _call(settings, "GET", "/v1/models", client=client)
            if m.get("can_do_text_to_speech")]


def _voice(v: Dict[str, Any], library: bool) -> Dict[str, Any]:
    labels = v if library else (v.get("labels") or {})
    return {"voice_id": v["voice_id"], "public_owner_id": v.get("public_owner_id"),
            "name": v.get("name") or v["voice_id"], "description": v.get("description") or "",
            "gender": labels.get("gender"), "age": labels.get("age"),
            "accent": labels.get("accent"), "language": labels.get("language"),
            "use_case": labels.get("use_case"), "descriptive": labels.get("descriptive"),
            "category": v.get("category"), "preview_url": v.get("preview_url"),
            "free_users_allowed": v.get("free_users_allowed", True)}


def search_voices(settings: InstagramMCPSettings, *, source: str = "library",
                  page: Optional[str] = None, page_size: int = 24,
                  client: Optional[httpx.Client] = None, **filters: Any) -> Dict[str, Any]:
    """One page of voices: `source` library (the shared Voice Library) or account (voices the
    account already has). Filters: search, language, accent, gender, age, sort, use_cases,
    descriptives (lists). {voices, next: the next page's `page` or None, total}."""
    params: Dict[str, Any] = {"page_size": page_size}
    if source == "library":
        params.update({k: filters[k] for k in LIBRARY_FILTERS if filters.get(k)})
        params.update({k: filters[k] for k in LIST_FILTERS if filters.get(k)})
        params["page"] = int(page or 0)
        data = _call(settings, "GET", "/v1/shared-voices", params=params, client=client)
        nxt = str(params["page"] + 1) if data.get("has_more") else None
        return {"voices": [_voice(v, True) for v in data.get("voices", [])], "next": nxt,
                "total": data.get("total_count")}
    if source != "account":
        raise ValueError("source must be library or account")
    params.update({k: filters[k] for k in ("search", "language", "accent", "gender", "age")
                   if filters.get(k)})
    if page:
        params["next_page_token"] = page
    data = _call(settings, "GET", "/v2/voices", params=params, client=client)
    return {"voices": [_voice(v, False) for v in data.get("voices", [])],
            "next": data.get("next_page_token") if data.get("has_more") else None,
            "total": data.get("total_count")}


def add_shared(settings: InstagramMCPSettings, public_owner_id: str, voice_id: str,
               name: str, *, client: Optional[httpx.Client] = None) -> str:
    """Add a library voice to the account (one voice slot); returns the account's voice_id."""
    data = _call(settings, "POST", f"/v1/voices/add/{_id(public_owner_id)}/{_id(voice_id)}",
                 json={"new_name": name}, client=client)
    return data.get("voice_id") or voice_id
