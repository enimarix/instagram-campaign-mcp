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
  asked = the default voice if it is on, else the first one on.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import APP_HOME
from ..store import CampaignStore

VOICES_DIR = APP_HOME / "brand" / "voices"
STATE_KEY = "voices"
# ponytail: one lock per process; the website (one process) is the only writer of the switches
_SWITCH = threading.Lock()


def _entries() -> List[Dict[str, Any]]:
    path = VOICES_DIR / "voices.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("voices", [])


def recipe(voice: Optional[str]) -> Optional[Dict[str, Any]]:
    """A designed voice's recipe from voices.json (None: a cloned or unknown voice)."""
    return next((e.get("recipe") for e in _entries() if e["id"] == voice), None)


def owner_choices(store: CampaignStore) -> Dict[str, bool]:
    return store.get_state(STATE_KEY) or {}


def list_voices(store: CampaignStore) -> List[Dict[str, Any]]:
    """Every voice, voices.json order: {id, label, description, use_for, styles, address, default,
    designed, enabled, sample_text, sample (URL or None)}."""
    own = owner_choices(store)
    return [{
        "id": e["id"], "label": e.get("label") or e["id"], "description": e.get("description"),
        "use_for": e.get("use_for"),
        "styles": e.get("styles", []), "address": e.get("address", []),
        "default": bool(e.get("default")), "designed": "recipe" in e,
        "enabled": bool(own.get(e["id"], e.get("enabled", True))),
        "sample_text": e.get("sample_text") or e.get("card_text"),
        "sample": f"/api/voices/{e['id']}/sample" if (VOICES_DIR / f"{e['id']}.wav").is_file()
        else None,
    } for e in _entries()]


def sample_file(voice: str) -> Optional[Path]:
    """The voice's sample wav, None for an unknown voice or a missing file."""
    if voice not in {e["id"] for e in _entries()}:
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
    return {**voices[voice], "enabled": enabled}


def enabled_voices(store: CampaignStore) -> List[Dict[str, Any]]:
    return [v for v in list_voices(store) if v["enabled"]]


def default_voice(store: CampaignStore) -> Optional[str]:
    """The JSON's default voice if it is on, else the first voice on (None: no voices)."""
    on = enabled_voices(store)
    return next((v["id"] for v in on if v["default"]), on[0]["id"] if on else None)


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
    """The sitcom's character voices among the voices on: {gender: (first, other)}, the
    gender's own voices first, then the other gender's (sitcom.say_voice takes `other` when
    the narrator already has `first`); voices without a `gender` come after the gender's own.
    None when no voice is on."""
    on = [e for e in _entries() if e["id"] in {v["id"] for v in enabled_voices(store)}]
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
    check_voice(None) gives. Recipes stay out (the agent picks a voice, never makes one)."""
    on = {v["id"] for v in enabled_voices(store)}
    if not on:
        return
    default = default_voice(store)
    voices = [{**{k: v for k, v in e.items() if k not in ("recipe", "enabled")},
               "default": e["id"] == default} for e in _entries() if e["id"] in on]
    dest.write_text(json.dumps({"voices": voices}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
