"""
Style catalog (step 172): every style the owner can look at in one list, with favourites.

Two families:
- `studio`: the studio's own styles (styles.list_styles: Remotion / Blender templates, step
  138). Selectable when enabled in Settings.
- `lemo`: the Lemo-Opuscar library (settings.lemo_library, ~100 code-rendered film styles).
  Ids are `lemo:<slug>`. Each `styles/<slug>/STYLE.md` gives the name (title line
  `# <Name> — Style Prompt`) and the essence (first sentence of the first `> ` quote);
  the library's own `style.json` gives the category, the uses (tags) and `needs`: a style
  that needs `image-generation` (✦ in the library) is shown but not selectable.
  Parses are cached by file mtime.

Previews of Lemo styles are fetched once by `ig-campaign styles fetch-previews` (never at
request time): the gallery site's 960 px poster card (~60 KB each, lighter than the
library's `setup.sh demo`, which checks out a whole demo source) and, opt-in, the web
cut of the demo film when small enough. They live in PREVIEWS_DIR/<slug>/ and are served
by GET /api/style-catalog/{id}/preview/{kind}. Posters and films are CC BY 4.0: every
Lemo entry carries the credit line.

Favourites: worker_state[FAVOURITES_KEY] = [id, ...]; favourites come first in the list.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..config import APP_HOME, InstagramMCPSettings
from ..store import CampaignStore
from . import styles

PREVIEWS_DIR = APP_HOME / "data" / "style-previews" / "lemo"  # git-ignored, runtime only
FAVOURITES_KEY = "style_favourites"
LEMO_PREFIX = "lemo:"
GALLERY = "https://lemomo-ai.github.io/lemo-opuscar"
FILMS = "https://lemomo-ai.github.io/lemo-opuscar-films"
CLIP_MAX_MB = 20
PREVIEW_FILES = {"poster": ("poster.webp", "image/webp"), "clip": ("clip.mp4", "video/mp4")}
CREDIT = {
    "text": "Lemo-Opuscar by Lemomo (LemoLab)",
    "url": "https://github.com/lemomo-ai/lemo-opuscar",
    "licence": "CC BY 4.0",
    "licence_url": "https://creativecommons.org/licenses/by/4.0/",
}
NEEDS_IMAGE_GEN = "Demande un générateur d'images externe (✦) : pas encore possible au studio"
DISABLED = "Désactivé dans Réglages"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_TITLE = re.compile(r"^#\s+(.+?)\s+[—-]+\s+Style Prompt\s*$")


# --- Lemo library -----------------------------------------------------------------------
def library(settings: InstagramMCPSettings) -> Path:
    return Path(settings.lemo_library).expanduser()


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


@lru_cache(maxsize=512)
def _parse(folder: str, md_mtime: int, json_mtime: int) -> Optional[Dict[str, Any]]:
    """One style folder -> its catalog fields (cached by the two files' mtimes)."""
    d = Path(folder)
    try:
        lines = (d / "STYLE.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    meta: Dict[str, Any] = {}
    if json_mtime:
        try:
            meta = json.loads((d / "style.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            meta = {}
    title = next((m.group(1) for m in map(_TITLE.match, lines[:3]) if m), None)
    quote = next((ln[2:].strip() for ln in lines if ln.startswith("> ")), "")
    essence = re.split(r"(?<=[.!?])\s", quote, maxsplit=1)[0] or None
    return {"label": title or meta.get("en") or d.name, "essence": essence,
            "category": meta.get("category_en"), "tags": list(meta.get("uses") or []),
            "needs": list(meta.get("needs") or [])}


def lemo_styles(settings: InstagramMCPSettings) -> List[Dict[str, Any]]:
    """The library's styles as catalog entries (no favourite yet); [] when it is missing."""
    root = library(settings) / "styles"
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or not _SLUG.match(d.name):  # skips _template
            continue
        p = _parse(str(d), _mtime(d / "STYLE.md"), _mtime(d / "style.json"))
        if p is None:
            continue
        sid = LEMO_PREFIX + d.name
        image_gen = "image-generation" in p["needs"]
        out.append({
            "id": sid, "family": "lemo", "label": p["label"], "essence": p["essence"],
            "category": p["category"], "tags": p["tags"],
            "preview": {k: (f"/api/style-catalog/{sid}/preview/{k}"
                            if preview_file(sid, k) else None) for k in PREVIEW_FILES},
            "selectable": not image_gen, "why_not": NEEDS_IMAGE_GEN if image_gen else None,
            "credit": CREDIT,
        })
    out.sort(key=lambda e: (e["category"] or "~", e["label"].lower()))
    return out


def _studio_styles(store: CampaignStore) -> List[Dict[str, Any]]:
    return [{
        "id": s["id"], "family": "studio", "label": s["label"], "essence": s["description"],
        "category": None, "tags": [],
        "preview": {"poster": s["preview"]["still"], "clip": s["preview"]["clip"]},
        "selectable": s["enabled"], "why_not": None if s["enabled"] else DISABLED,
        "credit": None,
    } for s in styles.list_styles(store)]


# --- catalog ----------------------------------------------------------------------------
def favourites(store: CampaignStore) -> List[str]:
    return list(store.get_state(FAVOURITES_KEY) or [])


def catalog(store: CampaignStore, settings: InstagramMCPSettings, *,
            family: Optional[str] = None, q: Optional[str] = None,
            favourites_only: bool = False) -> List[Dict[str, Any]]:
    """Every style: {id, family studio|lemo, label, essence, category, tags, preview {poster,
    clip} (URLs or None), favourite, selectable, why_not, credit}. Favourites first, then
    studio, then Lemo by category. family / q (words in the name, essence, category, tags)
    / favourites_only narrow it."""
    if family not in (None, "studio", "lemo"):
        raise ValueError("family must be studio or lemo")
    entries = ((_studio_styles(store) if family != "lemo" else [])
               + (lemo_styles(settings) if family != "studio" else []))
    favs = set(favourites(store))
    words = (q or "").lower().split()
    out = []
    for e in entries:
        e["favourite"] = e["id"] in favs
        hay = " ".join([e["id"], e["label"], e["essence"] or "", e["category"] or "",
                        *e["tags"]]).lower()
        if (favourites_only and not e["favourite"]) or not all(w in hay for w in words):
            continue
        out.append(e)
    out.sort(key=lambda e: not e["favourite"])  # stable: keeps the order within each part
    return out


def get_entry(store: CampaignStore, settings: InstagramMCPSettings,
              style_id: str) -> Dict[str, Any]:
    """One entry; ValueError when there is no such style."""
    lemo = style_id.startswith(LEMO_PREFIX)
    found = next((e for e in catalog(store, settings, family="lemo" if lemo else "studio")
                  if e["id"] == style_id), None)
    if found is None:
        raise ValueError(f"unknown style {style_id!r}")
    return found


def set_favourite(store: CampaignStore, settings: InstagramMCPSettings, style_id: str,
                  favourite: bool) -> Dict[str, Any]:
    """The owner stars / unstars a style. Returns its entry."""
    get_entry(store, settings, style_id)
    favs = [f for f in favourites(store) if f != style_id]
    if favourite:
        favs.append(style_id)
    store.set_state(FAVOURITES_KEY, favs)
    return get_entry(store, settings, style_id)


# --- previews ---------------------------------------------------------------------------
def preview_file(style_id: str, kind: str) -> Optional[Path]:
    """A Lemo style's fetched preview (poster | clip), or None."""
    slug = style_id[len(LEMO_PREFIX):] if style_id.startswith(LEMO_PREFIX) else ""
    if kind not in PREVIEW_FILES or not _SLUG.match(slug):
        return None
    path = PREVIEWS_DIR / slug / PREVIEW_FILES[kind][0]
    return path if path.is_file() else None


def media_type(kind: str) -> str:
    return PREVIEW_FILES[kind][1]


def _download(client: httpx.Client, url: str, dest: Path, max_bytes: int) -> Tuple[bool, str]:
    """GET url into dest (atomic). (True, '') or (False, why)."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with client.stream("GET", url) as r:
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}"
            if int(r.headers.get("content-length") or 0) > max_bytes:
                return False, f"bigger than {max_bytes // 2**20} MB"
            dest.parent.mkdir(parents=True, exist_ok=True)
            size = 0
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(f"bigger than {max_bytes // 2**20} MB")
                    f.write(chunk)
        tmp.replace(dest)
        return True, ""
    except (httpx.HTTPError, OSError, ValueError) as e:
        tmp.unlink(missing_ok=True)
        return False, str(e) or type(e).__name__


def fetch_previews(settings: InstagramMCPSettings, *, slugs: Optional[List[str]] = None,
                   clips: bool = False, force: bool = False,
                   client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Fetch the posters (and with clips=True the demo films up to CLIP_MAX_MB) of the
    library's styles (or only `slugs`) from the gallery site. Files already there are kept
    unless force. Returns {fetched, kept, failed: [{id, kind, error}]}."""
    known = [e["id"][len(LEMO_PREFIX):] for e in lemo_styles(settings)]
    wanted = known if not slugs else [s.removeprefix(LEMO_PREFIX) for s in slugs]
    unknown = sorted(set(wanted) - set(known))
    if unknown:
        raise ValueError(f"not in the library: {', '.join(unknown)}")
    jobs = [("poster", f"{GALLERY}/media/thumb/{{}}-960.webp", 5 * 2**20)]
    if clips:
        jobs.append(("clip", f"{FILMS}/{{}}.mp4", CLIP_MAX_MB * 2**20))
    result: Dict[str, Any] = {"fetched": 0, "kept": 0, "failed": []}
    own = client is None
    client = client or httpx.Client(timeout=60, follow_redirects=True)
    try:
        for slug in wanted:
            for kind, url, cap in jobs:
                dest = PREVIEWS_DIR / slug / PREVIEW_FILES[kind][0]
                if dest.is_file() and not force:
                    result["kept"] += 1
                    continue
                ok, why = _download(client, url.format(slug), dest, cap)
                if ok:
                    result["fetched"] += 1
                else:
                    result["failed"].append({"id": LEMO_PREFIX + slug, "kind": kind,
                                             "error": why})
    finally:
        if own:
            client.close()
    return result
