"""
Lemo-Opuscar films (step 173): an order in one of the library's ~100 styles becomes a video.

A style id is `lemo:<slug>`, the slug of a folder `<LEMO_LIBRARY>/styles/<slug>/` with a
style.json (step 172's catalog lists them for the owner). Unlike our templates, a Lemo film
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
from . import media
from .assets import DESCRIPTION_CHARS
from .render import enqueue_render

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "agent" / "playbooks" / "lemo-film.md"
GPU_RUN = REPO / "src" / "studio" / "gpu_run.py"
PREFIX = "lemo:"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FILM_DIR = "film"  # the film's project folder inside its workspace
DEFAULT_TTS = "http://127.0.0.1:8766/tts"
HOOK_CHARS = 200
# Normalise to our spec (1080x1920, 30 fps, H.264 + AAC) and loudness; a film is already
# vertical, so the crop cuts nothing.
RECIPE = {"version": 1, "ops": [{"op": "fit_vertical", "mode": "crop"}]}


def is_lemo(style: Optional[str]) -> bool:
    return bool(style) and style.startswith(PREFIX)


def style_info(style: str, library: Optional[str] = None) -> Dict[str, Any]:
    """{id, slug, label, line} of a `lemo:<slug>` style; ValueError when the library has no
    such style (or the id is not a Lemo one)."""
    slug = style[len(PREFIX):] if is_lemo(style) else ""
    lib = Path(library or get_settings().lemo_library).expanduser()
    path = lib / "styles" / slug / "style.json"
    if not SLUG.match(slug) or not path.is_file():
        raise ValueError(f"unknown Lemo-Opuscar style {style!r} (no {path})")
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        meta = {}
    return {"id": style, "slug": slug, "label": meta.get("en") or slug,
            "line": meta.get("line") or ""}


def check_style(style: str) -> str:
    style_info(style)
    return style


def film_brief(settings: InstagramMCPSettings, order: Dict[str, Any], style: Dict[str, Any],
               from_video: Optional[Dict[str, Any]] = None) -> str:
    """The film's BRIEF.md: the template (minus its comments) with this order filled in.
    Placeholders are `$name`; the owner's words are data inside it."""
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
        tts_url=settings.tts_http_url or DEFAULT_TTS)


def _post(film: Path) -> Dict[str, Any]:
    """The film's post.json ({hook, script, caption, description, sources}); {} when it is
    missing or not a JSON object (the order's instruction stands in)."""
    try:
        data = json.loads((film / "post.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


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


def register_film(store: CampaignStore, settings: InstagramMCPSettings,
                  order: Dict[str, Any], idea: Dict[str, Any], workspace: Path
                  ) -> Dict[str, Any]:
    """The delivered film becomes an asset of the order's idea, queued for render + QC.
    Returns {asset, job}; ValueError when the film delivered no final.mp4."""
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
    script = _text(post.get("script"), 8000)
    with store._tx() as c:  # the idea was made at the film's start from the instruction
        c.execute("UPDATE ideas SET hook=?, script=COALESCE(?, script), citations=? WHERE id=?",
                  (hook, script, json.dumps(_citations(post.get("sources"))), idea["id"]))
    asset = store.add_asset(
        idea["id"], batch_date=idea["batch_date"],
        recipe={"kind": "ffmpeg", "recipe": RECIPE, "inputs": {"source": rel}},
        caption=_text(post.get("caption"), 2200) or hook,
        description=_text(post.get("description"), DESCRIPTION_CHARS)
        or f"Un film Lemo-Opuscar ({idea['style']}) : {hook}"[:DESCRIPTION_CHARS])
    return {"asset": asset, "job": enqueue_render(store, asset["id"])}
