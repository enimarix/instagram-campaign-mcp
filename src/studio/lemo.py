"""
Lemo-Opuscar films (step 173): an order in one of the library's ~100 styles becomes a video.

A style id is `lemo:<slug>`, a selectable Lemo entry of step 172's catalog
(style_catalog.lemo_styles: a folder `<LEMO_LIBRARY>/styles/<slug>/`, not one that needs an
image generator). Unlike our templates, a Lemo film
is written as code by a Claude Code session (src/agent/film.py) from the film brief made
here (agent/playbooks/lemo-film.md filled in per order). It delivers `film/final.mp4` and
`film/post.json` in its workspace; register_film() copies the film into the media folder
and queues it like any edit (an ffmpeg recipe: normalised to our output spec, loudness
-14 LUFS), so the studio's normal QC decides whether it reaches the Inbox.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional

from ..config import InstagramMCPSettings, get_settings
from ..store import CampaignStore
from . import line, media, style_catalog
from .assets import DESCRIPTION_CHARS
from .render import enqueue_render

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "agent" / "playbooks" / "lemo-film.md"
GPU_RUN = REPO / "src" / "studio" / "gpu_run.py"
PREFIX = style_catalog.LEMO_PREFIX
FILM_DIR = "film"  # the film's project folder inside its workspace
VOICE_TAKES = "voice_takes.json"  # the voice door's takes, in the workspace (film_voice.py)
DEFAULT_TTS = "http://127.0.0.1:8766/tts"
HOOK_CHARS = 200
SCRIPT_CHARS = 8000
# Normalise to our spec (1080x1920, 30 fps, H.264 + AAC) and loudness; a film is already
# vertical, so the crop cuts nothing.
RECIPE = {"version": 1, "ops": [{"op": "fit_vertical", "mode": "crop"}]}


def is_lemo(style: Optional[str]) -> bool:
    return bool(style) and style.startswith(PREFIX)


def style_info(style: str, settings: Optional[InstagramMCPSettings] = None
               ) -> Dict[str, Any]:
    """{id, slug, label, line} of a selectable `lemo:<slug>` style of the catalog;
    ValueError when there is no such style or it cannot be made here."""
    entries = style_catalog.lemo_styles(settings or get_settings()) if is_lemo(style) else []
    entry = next((e for e in entries if e["id"] == style), None)
    if entry is None:
        raise ValueError(f"unknown Lemo-Opuscar style {style!r}")
    if not entry["selectable"]:
        raise ValueError(f"{entry['label']} ({style}): {entry['why_not']}")
    return {"id": style, "slug": style[len(PREFIX):], "label": entry["label"],
            "line": entry["essence"] or ""}


def check_style(style: str) -> str:
    style_info(style)
    return style


def film_brief(settings: InstagramMCPSettings, order: Dict[str, Any], style: Dict[str, Any],
               from_video: Optional[Dict[str, Any]] = None,
               tts_url: Optional[str] = None) -> str:
    """The film's BRIEF.md: the template (minus its comments) with this order filled in.
    Placeholders are `$name`; the owner's words are data inside it. tts_url: the film
    runner's voice door (agent/film_voice.py, 207), else the local voice service."""
    remake = ""
    if from_video:
        remake = ("This order remakes one of our videos in this style: keep its topic, "
                  "message and facts.\n"
                  f"- Its hook: {from_video.get('hook') or '-'}\n"
                  f"- Its script: {from_video.get('script') or '-'}\n")
    text = re.sub(r"<!--.*?-->\n*", "", TEMPLATE.read_text(encoding="utf-8"), flags=re.S)
    return Template(text).safe_substitute(
        order_id=order["id"], style_id=style["id"], slug=style["slug"],
        style_label=style["label"], style_line=style["line"],
        instruction=order.get("instruction") or "(none: pick a useful macroBody topic)",
        remake=remake, film_dir=FILM_DIR,
        library=Path(settings.lemo_library).expanduser().as_posix(),
        gpu_run=f'"{Path(sys.executable).as_posix()}" "{GPU_RUN.as_posix()}" --',
        tts_url=tts_url or settings.tts_http_url or DEFAULT_TTS)


def _post(film: Path) -> Dict[str, Any]:
    """The film's post.json ({hook, script, caption, description, sources}); {} when it is
    missing or not a JSON object (the order's instruction stands in)."""
    try:
        data = json.loads((film / "post.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _notes(film: Path) -> Optional[str]:
    try:
        return _text((film / "NOTES.md").read_text(encoding="utf-8"), SCRIPT_CHARS)
    except OSError:
        return None


def _text(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value.strip()[:limit] or None


def _citations(sources: Any) -> List[Dict[str, str]]:
    """The sources with an http(s) URL, as idea citations [{url, title}]."""
    out = []
    for s in sources if isinstance(sources, list) else ():
        url = s.get("url") if isinstance(s, dict) else None
        if isinstance(url, str) and re.match(r"^https?://[^\s/]+", url):
            out.append({"url": url, "title": str(s.get("title") or url)[:200]})
    return out


def _voiced_by(workspace: Path) -> Optional[Dict[str, Any]]:
    """What spoke the film (motion.voiced_by's shape) from the voice door's takes: engine
    elevenlabs only if every take was, the last take's voice, the first fallback reason. None
    when the film spoke through no door take."""
    try:
        takes = json.loads((workspace / VOICE_TAKES).read_text(encoding="utf-8"))
        engines = {t["engine"] for t in takes}
        reasons = [t["fallback"] for t in takes if t.get("fallback")]
        voice = takes[-1].get("voice")
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        return None
    return {"engine": "elevenlabs" if engines == {"elevenlabs"} else "http", "voice": voice,
            "fallback": reasons[0] if reasons else None}


def register_film(store: CampaignStore, settings: InstagramMCPSettings,
                  order: Dict[str, Any], idea: Dict[str, Any], workspace: Path
                  ) -> Dict[str, Any]:
    """The delivered film becomes an asset of the order's idea, queued for render + QC at
    the front of the heavy line (186), with what spoke it (_voiced_by: the asset's badge and
    the tts_fallback alert, as render.voice_first does for our videos).
    ponytail: QC never runs voice_above_bed on a film: the film mixes its own takes and keeps
    no voice stem (listen.voice_track finds none). Needs the film to deliver its voice track
    (e.g. film/voice.wav, as a recipe input) for that check.
    Returns {asset, job}; ValueError when the film delivered no final.mp4."""
    from .production import default_best_before  # here: production imports work_orders

    film = workspace / FILM_DIR
    final = film / "final.mp4"
    if not final.is_file() or not final.stat().st_size:
        raise ValueError(f"the film delivered no {FILM_DIR}/final.mp4")
    post = _post(film)
    rel = f"films/{order['id']}/final.mp4"
    dest = media.resolve(settings.media_root, rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(final, dest)
    hook = _text(post.get("hook"), HOOK_CHARS) or idea["hook"]
    # never empty: a script marks the video AI-made for Instagram's label (publish.py)
    script = _text(post.get("script"), SCRIPT_CHARS) or _notes(film) or hook
    with store._tx() as c:  # the idea was made at the film's start from the instruction
        c.execute("UPDATE ideas SET hook=?, script=?, citations=? WHERE id=?",
                  (hook, script, json.dumps(_citations(post.get("sources"))), idea["id"]))
    env = {"kind": "ffmpeg", "recipe": RECIPE, "inputs": {"source": rel}}
    by = _voiced_by(workspace)
    if by:
        env["voiced_by"] = by
    asset = store.add_asset(
        idea["id"], batch_date=idea["batch_date"], recipe=env,
        caption=_text(post.get("caption"), 2200) or hook,
        description=_text(post.get("description"), DESCRIPTION_CHARS)
        or f"Un film Lemo-Opuscar ({idea['style']}) : {hook}"[:DESCRIPTION_CHARS],
        best_before=default_best_before(store, settings, {"idea_id": idea["id"]}))
    if by and by["fallback"]:  # the owner hears of a fallback, as for our videos (204)
        from ..store import utcnow
        from . import alerts  # alerts imports the worker, which imports us

        alerts.raise_alert(store, "tts_fallback", None, "warn",
                           "ElevenLabs n'a pas parlé : la voix locale a pris le relais"
                           if by["engine"] == "http"
                           else "La voix locale a échoué : ElevenLabs a pris le relais",
                           f"Vidéo {asset['id']} : {by['fallback']}", "/voices", utcnow(),
                           renew=True)
    job = enqueue_render(store, asset["id"])
    try:  # the film waits for this render (film._wait_render): it goes first in the line
        line.start_now(store, "render", job["id"])
    except ValueError:  # the render loop took it already
        pass
    return {"asset": asset, "job": job}
