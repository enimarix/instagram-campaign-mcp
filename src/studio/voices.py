"""
The voice-over voices the owner keeps on (Voix page, owner's casting 2026-11-22).

- brand/voices/voices.json is the one list (the voice service reads it too): each voice's
  label, description, styles, address, `enabled` default and `<id>.wav` (a designed voice's
  sample, a cloned voice's card) with `sample_text`, what that file says.
- The owner's on / off lives in worker_state[STATE_KEY] = {voice: bool} and wins over the
  JSON's `enabled`, like the styles (styles.py). At least one voice stays on.
- Only voices that are on reach a video: the agent's copy of voices.json lists them alone
  (agent_copy), render_motion / render_remix refuse another one for a new voice-over
  (check_voice), and the sitcom's characters speak in them (say_cast, by `gender`). No voice
  asked = the default voice if it is on, else the first one on. With ElevenLabs first (the
  Voix page's engine choice) the cards on are the cast and the local voices their relays
  (cast_voices), and any local pick still speaks ElevenLabs first (engine_plan).
- Step 204: ElevenLabs cards sit beside them, added by the owner from the Voice Library on the
  Voix page and kept in data/voices/elevenlabs.json (runtime data, with the engine choice:
  which engine speaks first and the ElevenLabs model). Each card names a local `fallback`
  voice: the two are a pair, so either engine can speak a video in the voice the AI picked
  (engine_plan).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import APP_HOME, InstagramMCPSettings
from ..store import CampaignStore
from . import elevenlabs

VOICES_DIR = APP_HOME / "brand" / "voices"
EL_PATH = APP_HOME / "data" / "voices" / "elevenlabs.json"
ENGINES = ("elevenlabs", "local")
DEFAULT_ENGINE = {"priority": "elevenlabs", "model": "eleven_v4"}
STATE_KEY = "voices"
# ponytail: one lock per process; the website (one process) is the only writer of the switches
_SWITCH = threading.Lock()


def _local() -> List[Dict[str, Any]]:
    path = VOICES_DIR / "voices.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("voices", [])


def _el() -> Dict[str, Any]:
    if not EL_PATH.is_file():
        return {}
    return json.loads(EL_PATH.read_text(encoding="utf-8"))


def _el_write(data: Dict[str, Any]) -> None:
    EL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = EL_PATH.with_name(f"{EL_PATH.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for wait in (0.05, 0.2, 0.5, None):  # Windows: refused while the worker is reading it
        try:
            os.replace(tmp, EL_PATH)
            return
        except PermissionError:
            if wait is None:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(wait)


def el_cards() -> List[Dict[str, Any]]:
    return [{**c, "engine": "elevenlabs"} for c in _el().get("voices", [])]


def el_card(voice: Optional[str]) -> Optional[Dict[str, Any]]:
    return next((c for c in el_cards() if c["id"] == voice), None)


def _entries() -> List[Dict[str, Any]]:
    """Every voice: voices.json's (the local engine), then the ElevenLabs cards."""
    return [{**e, "engine": "local"} for e in _local()] + el_cards()


def engine() -> Dict[str, str]:
    """The owner's engine choice: {priority: the engine that speaks first, model}."""
    saved = _el().get("engine", {})
    return {k: saved.get(k) or v for k, v in DEFAULT_ENGINE.items()}


def set_engine(priority: Optional[str] = None, model: Optional[str] = None) -> Dict[str, str]:
    if priority is not None and priority not in ENGINES:
        raise ValueError(f"priority must be one of {', '.join(ENGINES)}")
    if model is not None and not re.fullmatch(r"[a-z0-9_]{1,60}", model):
        raise ValueError(f"not an ElevenLabs model id: {model!r}")
    with _SWITCH:
        data = _el()
        data["engine"] = {**engine(), **{k: v for k, v in (("priority", priority),
                                                           ("model", model)) if v}}
        _el_write(data)
    return data["engine"]


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30]
    return f"el_{s or 'voix'}"


def add_el_card(*, el_voice_id: str, label: str, fallback: str, gender: Optional[str] = None,
                use_for: Optional[str] = None, description: Optional[str] = None,
                language: Optional[str] = None, accent: Optional[str] = None,
                preview_url: Optional[str] = None,
                address: Optional[List[str]] = None) -> Dict[str, Any]:
    """Add an ElevenLabs card (its voice already in the account); returns it, on. ValueError
    for a fallback that is not a local voice, an empty name or a bad gender."""
    local = {e["id"]: e for e in _local()}
    if fallback not in local:
        raise ValueError(f"the fallback must be a local voice ({', '.join(local)})")
    label = " ".join((label or "").split())[:60]
    if not label:
        raise ValueError("a card needs a name")
    if gender not in (None, "male", "female", "neutral"):
        raise ValueError("gender: male, female or neutral")
    if address and not set(address) <= {"tu", "vous"}:
        raise ValueError("address: tu and / or vous")
    styles = sorted({s for e in local.values() for s in e.get("styles", [])})
    with _SWITCH:
        data = _el()
        cards = data.get("voices", [])
        taken = set(local) | {c["id"] for c in cards}
        base = cid = _slug(label)
        n = 2
        while cid in taken:
            cid, n = f"{base}_{n}", n + 1
        card = {"id": cid, "label": label, "el_voice_id": el_voice_id,
                "description": (description or "")[:400], "use_for": (use_for or "")[:400],
                "gender": gender or local[fallback].get("gender"), "language": language,
                "accent": accent, "preview_url": preview_url, "fallback": fallback,
                "address": address or local[fallback].get("address", ["tu", "vous"]),
                "styles": styles, "enabled": True}
        data["voices"] = cards + [card]
        _el_write(data)
    return {**card, "engine": "elevenlabs"}


def remove_el_card(store: CampaignStore, voice: str) -> Dict[str, Any]:
    """Remove an ElevenLabs card (never a local voice). KeyError: no such card; ValueError:
    it is the last voice on."""
    with _SWITCH:
        data = _el()
        cards = data.get("voices", [])
        if voice not in {c["id"] for c in cards}:
            raise KeyError(voice)
        own = owner_choices(store)
        on = [e["id"] for e in _entries() if own.get(e["id"], e.get("enabled", True))]
        if on == [voice]:
            raise ValueError("at least one voice must stay on")
        data["voices"] = [c for c in cards if c["id"] != voice]
        _el_write(data)
        # a card added later under the same id starts on, like any new card
        store.set_state(STATE_KEY, {k: v for k, v in own.items() if k != voice})
    return {"id": voice, "removed": True}


def engine_plan(voice: Optional[str]) -> List[Tuple[str, Optional[str]]]:
    """[(engine, voice id)] in the order to try: the owner's priority engine first, each in
    the voice of the pair the picked voice belongs to (an ElevenLabs card and its `fallback`;
    a local voice and the first card on that falls back to it). With ElevenLabs first, a
    local voice with no card of its own (or no voice) speaks in the first card on of its
    gender: the owner's engine choice wins over an old or default local pick. A voice still
    with no pair: its own engine only; a card id no longer listed: the default local voice.
    A card the owner turned off is never a twin; a local relay voice the owner turned off
    still speaks for its card, as a backup only."""
    card = el_card(voice)
    first = engine()["priority"]
    if card:
        pair = {"elevenlabs": card["id"], "local": card.get("fallback")}
    else:
        if voice is not None and voice.startswith("el_"):
            voice = None  # a card removed since the video was queued: the default local voice
        # a twin the owner turned off never speaks (set_enabled keeps `enabled` on the card)
        on = [c for c in el_cards() if c.get("enabled", True)]
        twin = next((c["id"] for c in on if voice is not None and c.get("fallback") == voice),
                    None)
        if twin is None and first == "elevenlabs":
            gender = next((e.get("gender") for e in _local() if e["id"] == voice), None)
            twin = next((c["id"] for c in on if gender is None or c.get("gender") == gender),
                        None)
        pair = {"local": voice, "elevenlabs": twin}
    order = (first, "local" if first == "elevenlabs" else "elevenlabs")
    return [(e, pair[e]) for e in order if pair[e] is not None or (e == "local" and not card)]


def speaker(voice: Optional[str]) -> Optional[str]:
    """The voice that speaks `voice`'s lines first (engine_plan): a local pick and its card
    are one speaker, so a sitcom character never gets the narrator's voice under a new id."""
    plan = engine_plan(voice)
    return (plan[0][1] if plan else None) or voice


def engine_status(settings: InstagramMCPSettings) -> Dict[str, Any]:
    """The Voix page's engine panel: {priority, model, local (the local service is set up),
    elevenlabs: {configured, credits ({used, limit, left, resets_at, tier}) or None, error}}."""
    el: Dict[str, Any] = {"configured": elevenlabs.configured(settings), "credits": None,
                          "error": None}
    if el["configured"]:
        try:
            el["credits"] = elevenlabs.credits(settings)
        except elevenlabs.ElevenLabsError as e:
            el["error"] = str(e)
    return {**engine(), "local": settings.tts_provider == "http", "elevenlabs": el}


def add_from_elevenlabs(settings: InstagramMCPSettings, *, voice_id: str,
                        public_owner_id: Optional[str] = None, **card: Any) -> Dict[str, Any]:
    """Add an ElevenLabs voice as a card: a library voice (`public_owner_id`) is first added
    to the account (one of its voice slots), then the card is kept (add_el_card)."""
    if card.get("fallback") not in {e["id"] for e in _local()}:  # before spending a slot
        raise ValueError("the fallback must be a local voice")
    if public_owner_id:
        try:
            voice_id = elevenlabs.add_shared(settings, public_owner_id, voice_id,
                                             card.get("label") or voice_id)
        except elevenlabs.ElevenLabsError as e:
            # already in the account (added before, its card removed since): it speaks
            # under its library id; anything else is ElevenLabs' refusal, said as is
            owned = (_in_account(settings, voice_id, card.get("label"))
                     if e.status in (400, 409, 422) else None)
            if owned is None:
                raise
            voice_id = owned
    return add_el_card(el_voice_id=voice_id, **card)


def _in_account(settings: InstagramMCPSettings, voice_id: str,
                name: Optional[str]) -> Optional[str]:
    """The account's id of a library voice already added (same id, or added under `name`);
    None when it is not there. ponytail: the first 100 account voices only."""
    try:
        found = elevenlabs.search_voices(settings, source="account", page_size=100)
    except elevenlabs.ElevenLabsError:
        return None
    return next((v["voice_id"] for v in found["voices"]
                 if v["voice_id"] == voice_id or (name and v["name"] == name)), None)


def recipe(voice: Optional[str]) -> Optional[Dict[str, Any]]:
    """A designed voice's recipe from voices.json (None: a cloned or unknown voice)."""
    return next((e.get("recipe") for e in _local() if e["id"] == voice), None)


def owner_choices(store: CampaignStore) -> Dict[str, bool]:
    return store.get_state(STATE_KEY) or {}


def list_voices(store: CampaignStore) -> List[Dict[str, Any]]:
    """Every voice, voices.json order then the ElevenLabs cards: {id, label, engine,
    description, use_for, styles, address, default, designed, enabled, sample_text, sample
    (URL or None), gender, fallback (a card's local voice), language, accent}."""
    own = owner_choices(store)
    return [{
        "id": e["id"], "label": e.get("label") or e["id"], "description": e.get("description"),
        "use_for": e.get("use_for"),
        "styles": e.get("styles", []), "address": e.get("address", []),
        "default": bool(e.get("default")), "designed": "recipe" in e,
        "enabled": bool(own.get(e["id"], e.get("enabled", True))),
        "sample_text": e.get("sample_text") or e.get("card_text"),
        "sample": e.get("preview_url") if e["engine"] == "elevenlabs"
        else f"/api/voices/{e['id']}/sample" if (VOICES_DIR / f"{e['id']}.wav").is_file()
        else None,
        "engine": e["engine"], "gender": e.get("gender"), "fallback": e.get("fallback"),
        "language": e.get("language"), "accent": e.get("accent"),
    } for e in _entries()]


def sample_file(voice: str) -> Optional[Path]:
    """The voice's sample wav, None for an unknown voice or a missing file."""
    if voice not in {e["id"] for e in _local()}:
        return None  # only listed ids: never a path built from the request
    path = VOICES_DIR / f"{voice}.wav"
    return path if path.is_file() else None


def set_enabled(store: CampaignStore, voice: str, enabled: bool) -> Dict[str, Any]:
    """The owner turns a voice on / off; returns it. ValueError for an unknown voice or for
    turning off the last voice on (a video always needs one)."""
    with _SWITCH:  # read, check, write as one: two quick taps never lose one or turn all off
        voices = {v["id"]: v for v in list_voices(store)}
        if voice not in voices:
            raise ValueError(f"unknown voice {voice!r} (have {', '.join(voices)})")
        if not enabled and [v for v in voices.values() if v["enabled"]] == [voices[voice]]:
            raise ValueError("at least one voice must stay on")
        store.set_state(STATE_KEY, {**owner_choices(store), voice: enabled})
        if voices[voice]["engine"] == "elevenlabs":  # engine_plan reads it without a store
            data = _el()
            data["voices"] = [{**c, "enabled": enabled} if c["id"] == voice else c
                              for c in data.get("voices", [])]
            _el_write(data)
    return {**voices[voice], "enabled": enabled}


def enabled_voices(store: CampaignStore) -> List[Dict[str, Any]]:
    return [v for v in list_voices(store) if v["enabled"]]


def cast_voices(store: CampaignStore) -> List[Dict[str, Any]]:
    """The voices a new voice-over is cast from: the voices on; with ElevenLabs first and a
    card on, the cards on only (each local voice is then a card's relay, never a pick)."""
    on = enabled_voices(store)
    cards = [v for v in on if v["engine"] == "elevenlabs"]
    return cards if cards and engine()["priority"] == "elevenlabs" else on


def default_voice(store: CampaignStore) -> Optional[str]:
    """The JSON's default voice if it is on and cast (cast_voices), else its card, else the
    first cast voice of its gender, else the first cast voice (None: no voices)."""
    on = cast_voices(store)
    if not on:
        return None
    marked = next((v for v in enabled_voices(store) if v["default"]), None)
    if marked is None:
        return on[0]["id"]
    return next((v["id"] for v in on if v["id"] == marked["id"]),
                next((v["id"] for v in on if v["fallback"] == marked["id"]),
                     next((v["id"] for v in on if v["gender"] == marked["gender"]),
                          on[0]["id"])))


def check_voice(store: CampaignStore, voice: Optional[str]) -> Optional[str]:
    """The voice a video gets: `voice` when it is on (ValueError naming the voices on
    otherwise), the default voice when None."""
    if voice is None:
        return default_voice(store)
    if not _entries():  # no list: nothing to check against
        return voice
    on = [v["id"] for v in enabled_voices(store)]
    if voice not in on:
        raise ValueError(f"voice {voice!r} is not available (turned off or unknown); "
                         f"voices on: {', '.join(on)}")
    return voice


def say_cast(store: CampaignStore) -> Optional[Dict[str, Tuple[str, str]]]:
    """The sitcom's character voices among the cast voices (cast_voices): {gender: (first, other)}, the
    gender's own voices first, then the other gender's (sitcom.say_voice takes `other` when
    the narrator already has `first`); voices without a `gender` come after the gender's own.
    None when no voice is on."""
    on = [e for e in _entries() if e["id"] in {v["id"] for v in cast_voices(store)}]
    if not on:
        return None
    by = {g: [e["id"] for e in on if e.get("gender") == g] for g in ("male", "female")}
    rest = [e["id"] for e in on if e.get("gender") not in by]  # no gender: after both
    cast = {}
    for g, o in (("male", "female"), ("female", "male")):
        pool = by[g] + rest + by[o]
        cast[g] = (pool[0], pool[1] if len(pool) > 1 else pool[0])
    return cast


def agent_copy(store: CampaignStore, dest: Path) -> None:
    """Write the agent's voices.json: the voices on only, the default moved to the voice
    check_voice(None) gives. Recipes stay out (the agent picks a voice, never makes one).
    A Lemo film gets the same (207: it speaks through the film runner's voice door). The
    voices listed are the cast ones (cast_voices): the ElevenLabs cards when it speaks first."""
    on = {v["id"] for v in cast_voices(store)}
    if not on:
        return
    default = default_voice(store)
    if default not in on:
        default = next(e["id"] for e in _entries() if e["id"] in on)
    hidden = ("recipe", "enabled", "el_voice_id", "preview_url", "fallback")
    voices = [{**{k: v for k, v in e.items() if k not in hidden},
               "default": e["id"] == default} for e in _entries() if e["id"] in on]
    dest.write_text(json.dumps({"voices": voices}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
