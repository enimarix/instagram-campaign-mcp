"""
Styles as buttons (step 138): the one registry of the visual styles the owner launches work
in (one button per enabled style, plus « Auto (l'IA choisit) »).

- The styles are the templates' own: each template's `style` (motion/src/registry.ts STYLES,
  the cinematic engine's STYLE), listed by motion.list_templates(). A new style = its template
  step + one brand/styles.json entry, nothing else.
- brand/styles.json enriches them: label, a one-line French description, a preview still /
  clip (files under data/samples/; a missing file = no preview, never an error), the end-card
  style, the address (tu / vous) and `enabled`. An entry no template has is ignored; a style
  without an entry still shows, with its registry label.
- The owner's choices (Settings) live in worker_state[STATE_KEY] = {style: {enabled, share}}
  and win over the JSON's `enabled`. share: at most that part of a day's batch in the style
  (src/learning/quotas.py), None = no limit.
- The chosen style is stored on the work order (NULL = Auto) and on the idea; create_idea
  and render_motion refuse a template outside the idea's style (check_template).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import APP_HOME
from ..store import CampaignStore
from . import media

STYLES_PATH = APP_HOME / "brand" / "styles.json"
SAMPLES_DIR = APP_HOME / "data" / "samples"  # git-ignored, runtime only
STATE_KEY = "styles"
PREVIEWS = ("still", "clip")


def registry() -> Dict[str, Dict[str, Any]]:
    """{style: {label, templates}} in the registry's order (Node: motion.list_templates)."""
    from . import motion  # here: motion imports render, which pulls in most of the studio

    out: Dict[str, Dict[str, Any]] = {}
    for t in motion.list_templates():
        style = out.setdefault(t["style"], {"label": t.get("styleLabel") or t["style"],
                                            "templates": []})
        style["templates"].append(t["id"])
    return out


def _entries() -> Dict[str, Dict[str, Any]]:
    if not STYLES_PATH.is_file():
        return {}
    return json.loads(STYLES_PATH.read_text(encoding="utf-8")).get("styles", {})


def owner_choices(store: CampaignStore) -> Dict[str, Dict[str, Any]]:
    """The owner's Settings: {style: {enabled?, share?}} (no Node needed)."""
    return store.get_state(STATE_KEY) or {}


def _preview(entry: Dict[str, Any], kind: str) -> Optional[Path]:
    rel = (entry.get("preview") or {}).get(kind)
    if kind not in PREVIEWS or not rel:
        return None
    try:
        path = media.resolve(SAMPLES_DIR, rel)
    except ValueError:  # a bad path in the JSON: no preview
        return None
    return path if path.is_file() else None


def preview_file(style: str, kind: str) -> Optional[Path]:
    """The style's preview `kind` (still | clip) when the file exists, else None."""
    return _preview(_entries().get(style, {}), kind)


def list_styles(store: CampaignStore) -> List[Dict[str, Any]]:
    """Every style (enabled or not), registry order: {id, label, description, templates,
    end_card, address, enabled, share, preview: {still, clip} (URLs or None)}."""
    entries, own = _entries(), owner_choices(store)
    out = []
    for sid, reg in registry().items():
        e, mine = entries.get(sid, {}), own.get(sid, {})
        out.append({
            "id": sid, "label": e.get("label") or reg["label"],
            "description": e.get("description"), "templates": reg["templates"],
            "end_card": e.get("end_card"), "address": e.get("address"),
            "enabled": bool(mine.get("enabled", e.get("enabled", True))),
            "share": mine.get("share"),
            "preview": {k: f"/api/styles/{sid}/preview/{k}" if _preview(e, k) else None
                        for k in PREVIEWS},
        })
    return out


def get_style(store: CampaignStore, style: str) -> Dict[str, Any]:
    """One style; ValueError naming the known ones when there is no such style."""
    styles = {s["id"]: s for s in list_styles(store)}
    if style not in styles:
        raise ValueError(f"unknown style {style!r} (have {', '.join(styles)})")
    return styles[style]


def check_style(store: CampaignStore, style: Optional[str]) -> Optional[str]:
    """A style the owner may launch work in: None (Auto) or an enabled style."""
    if style is None:
        return None
    s = get_style(store, style)
    if not s["enabled"]:
        raise ValueError(f"style {style!r} ({s['label']}) is turned off in Settings")
    return style


def set_choice(store: CampaignStore, style: str, *, enabled: Optional[bool] = None,
               share: Any = ...) -> Dict[str, Any]:
    """The owner turns a style on / off, or sets its daily share (0 < share <= 1, None = no
    limit; leave it out to keep it). Returns the style."""
    get_style(store, style)
    if share is not ... and share is not None and not 0 < share <= 1:
        raise ValueError("share must be above 0 and at most 1 (or empty: no limit)")
    own = owner_choices(store)
    mine = dict(own.get(style, {}))
    if enabled is not None:
        mine["enabled"] = enabled
    if share is not ...:
        mine["share"] = share
    store.set_state(STATE_KEY, {**own, style: mine})
    return get_style(store, style)


def capabilities(store: CampaignStore) -> Optional[Dict[str, List[str]]]:
    """What the studio can make now (156): {enabled style: sorted templates}; None when the
    templates cannot be listed (no Node). A style or template here that was not before is
    new capability: it re-wakes the waiting videos (src/agent/schedule.py)."""
    from .motion import MotionError  # here: motion pulls in most of the studio

    try:
        return {s["id"]: sorted(s["templates"]) for s in list_styles(store) if s["enabled"]}
    except MotionError:
        return None


def owner_ban(store: CampaignStore, style: Optional[str],
              template: Optional[str] = None) -> Optional[str]:
    """Why the owner ruled this style or template out: an active owner `dont` learning
    scoped to it ({"tag": "style" | "template", "value": …}); None when none is."""
    from ..learning.evidence import predicate  # here: learning imports the studio

    for row in store.list_learnings(kind="dont", status="active", limit=100_000):
        if row["confidence"] != "owner":
            continue
        try:
            pred = predicate(row["scope"])
        except ValueError:  # a stored scope that no longer validates: not a rule
            continue
        if pred and pred in (("style", style), ("template", template)):
            return (f"the owner ruled out {pred[0]} {pred[1]!r} (learning {row['id']}:"
                    f" « {row['statement']} »): use another style")
    return None


def check_template(store: CampaignStore, idea: Dict[str, Any], template: str) -> str:
    """Before render_motion: the template must be in the idea's style, and neither may be
    ruled out by the owner (owner_ban). An idea without a style (Auto, older ideas) takes
    the template's, if that style is on; it is recorded on the idea. Returns the style;
    ValueError says what to use instead."""
    reg = registry()
    style = next((s for s, r in reg.items() if template in r["templates"]), None)
    if style is None:
        return idea.get("style")  # an unknown template: validate_props says so
    banned = owner_ban(store, style, template)
    if banned:
        raise ValueError(banned)
    want = idea.get("style")
    if want is None:
        check_style(store, style)
        store.set_idea_style(idea["id"], style)
        return style
    if want != style:
        templates = ", ".join(reg.get(want, {}).get("templates", [])) or "none listed"
        raise ValueError(f"idea {idea['id']} is in style {want!r}: template {template} is"
                         f" {style!r}; use one of {templates}")
    return style
