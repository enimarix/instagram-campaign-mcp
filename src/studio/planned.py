"""
Claude's planned videos (step 188b): « Idées de Claude — à valider » on the Planning page.

The agent plans a video instead of queueing it (render_motion / render_remix with plan=True):
the asset is `planned`, with its full recipe (the voice still a `voice_todo`), caption and
description, and no render job, so nothing renders and no voice is made. The owner reviews
the card: edit() changes the voice, the music, the spoken lines, the caption and the
description, rebuilt through the same checks as at plan time; release() (« Valider ») checks
it all again and queues its render, arriving in the line now, ahead of it (« Lancer
maintenant ») or on a timer (« Minuteur »); remove() (« Retirer ») archives it. Only a
`planned` asset is taken. Its sources: the idea's citations.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..config import InstagramMCPSettings
from ..store import CampaignStore
from . import line, motion, remix, render
from .assets import checked_fields, transition

KeyPath = Tuple[Any, ...]  # keys / indices down the props to one text


def _planned(store: CampaignStore, asset_id: int) -> Dict[str, Any]:
    asset = store.get_asset(asset_id)
    if asset["status"] != "planned":
        raise ValueError(f"La vidéo {asset_id} n'est plus une idée à valider (statut"
                         f" {asset['status']}) : seule une idée de Claude en attente peut être"
                         " validée, modifiée ou retirée ici.")
    return asset


def _paths(template: str, props: Dict[str, Any]) -> List[Tuple[str, Optional[KeyPath]]]:
    """Each spoken line of the template (motion.SCRIPTS) and the props text it is, or None
    when the line joins several texts (PaperStory strips, Editorial lead + key...).
    ponytail: a line found by its text; two equal texts both point at the first."""
    leaves: Dict[str, KeyPath] = {}

    def walk(x: Any, path: KeyPath) -> None:
        if isinstance(x, str):
            leaves.setdefault(x, path)
        elif isinstance(x, dict):
            for k, v in x.items():
                if path or k != "voice":  # the voice-over's own lines are not the script
                    walk(v, (*path, k))
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, (*path, i))

    walk(props, ())
    script = motion.SCRIPTS.get(template)
    return [(text, leaves.get(text)) for text in (script(props) if script else [])]


def _set_lines(template: str, props: Dict[str, Any], lines: Sequence[str]) -> Dict[str, Any]:
    """Props with the owner's spoken lines (one per motion.SCRIPTS line, same order)."""
    have = _paths(template, props)
    if len(lines) != len(have):
        raise ValueError(f"envoie {len(have)} lignes, une par ligne dite (reçu {len(lines)})")
    props = copy.deepcopy(props)
    changed = False
    for n, ((old, path), new) in enumerate(zip(have, lines), 1):
        new = " ".join(str(new).split())
        if new == old:
            continue
        if not new:
            raise ValueError(f"la ligne {n} est vide")
        if path is None:
            raise ValueError(f"la ligne {n} réunit plusieurs textes du modèle : elle ne se"
                             " modifie pas ici")
        *up, last = path
        target = props
        for k in up:
            target = target[k]
        target[last] = new
        changed = True
    if changed:
        props.pop("voice", None)  # a voice made for the old lines would not say the new ones
    return props


def _motion_env(store: CampaignStore, settings: InstagramMCPSettings, asset: Dict[str, Any],
                voice: Optional[str] = None, music: Optional[str] = None,
                lines: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """A planned motion recipe rebuilt through motion_recipe (props, style, voice on, track)."""
    env = asset["recipe"]
    todo = env.get("voice_todo") or {}
    props, track = env["props"], todo.get("music_audio_id")
    if music is not None:  # digits: an Instagram track (fetch_music); else the template's bed
        if music.isdigit():
            track = music
        else:
            props, track = {**props, "music": music}, None
    if lines is not None:
        props = _set_lines(env["template"], props, lines)
    return motion.motion_recipe(store, settings, store.get_idea(asset["idea_id"]),
                                env["template"], props, voice or todo.get("voice"), track,
                                plan=True)


def _remix_changes(voice: Optional[str], music: Optional[str],
                   lines: Optional[Sequence[str]]) -> Dict[str, Any]:
    changes: Dict[str, Any] = {}
    if voice is not None:
        changes["voice"] = voice
    if music is not None:
        changes["music"] = None if music == "none" else music
    if lines is not None:  # a remix says one text: the voice-over script
        if len(lines) != 1:
            raise ValueError(f"un remix a une seule ligne dite, son texte (reçu {len(lines)})")
        changes["script"] = " ".join(str(lines[0]).split()) or None
    return changes


def edit(store: CampaignStore, settings: InstagramMCPSettings, asset_id: int, *,
         voice: Optional[str] = None, music: Optional[str] = None,
         lines: Optional[Sequence[str]] = None, caption: Optional[str] = None,
         description: Optional[str] = None) -> Dict[str, Any]:
    """The owner's changes to a planned video (None: unchanged): voice (a voice on), music
    (a bed `music-...` or `none`, or a fetched Instagram track's audio_id: motion only), the
    spoken lines (cards()' script, in order), caption, description. Everything is checked
    before anything is saved; ValueError names the problem. Returns the asset."""
    asset = _planned(store, asset_id)
    fields = checked_fields("planned", **{k: x for k, x in (
        ("caption", caption), ("description", description)) if x is not None})
    if (voice, music, lines) != (None, None, None):
        fields["recipe"] = (_motion_env(store, settings, asset, voice, music, lines)
                            if asset["recipe"]["kind"] == "motion" else
                            remix.replan(store, settings, asset,
                                         **_remix_changes(voice, music, lines)))
    return store.update_asset(asset_id, **fields) if fields else asset


def release(store: CampaignStore, settings: InstagramMCPSettings, asset_id: int, *,
            now: bool = False, at: Optional[datetime] = None) -> Dict[str, Any]:
    """« Valider »: the planned video, checked again as at plan time (a remix: its rights,
    then its reaction piece), goes to `rendering` and its render joins the line, arriving
    now; `now`: « Lancer maintenant » (line.start_now), `at` (UTC): « Minuteur »
    (line.set_timer). Returns {asset, job}."""
    if now and at is not None:
        raise ValueError("choisis « Lancer maintenant » ou un minuteur, pas les deux")
    if at is not None and at.tzinfo is None:
        raise ValueError("the timer needs a time zone (send it as UTC ISO)")
    asset = _planned(store, asset_id)
    if asset["recipe"]["kind"] == "motion":
        store.update_asset(asset_id, recipe=_motion_env(store, settings, asset))
    else:
        remix.attach_piece(store, settings, asset_id, remix.replan(store, settings, asset))
    transition(store, asset_id, "rendering", actor="owner")
    job = render.enqueue_render(store, asset_id)
    if now:
        line.start_now(store, "render", job["id"])
    elif at is not None:
        line.set_timer(store, "render", job["id"], at)
    return {"asset": store.get_asset(asset_id), "job": store.get_render_job(job["id"])}


def remove(store: CampaignStore, asset_id: int) -> Dict[str, Any]:
    """« Retirer »: the planned video is archived (the page's 5 s undo sends nothing before
    it ends), and the order it was made for skipped unless another video of it lives."""
    asset = _planned(store, asset_id)
    transition(store, asset_id, "archived", actor="owner")
    line.skip_orders(store, asset["idea_id"])
    return {"asset_id": asset_id, "removed": True}


def cards(store: CampaignStore) -> List[Dict[str, Any]]:
    """The planned videos, newest batch first and oldest first inside it: {asset_id, batch_date,
    hook, style, recipe, kind motion | remix, template, script [{text, editable}], voice,
    music (a bed, or an Instagram track's audio_id), caption, description, sources (the
    idea's citations), music_options (our beds and none; a template takes some of them)}.
    `recipe` is for the Planning page's engine (build_planning drops it)."""
    rows = store._select("SELECT a.*, i.hook, i.style, i.citations FROM assets a"
                         " JOIN ideas i ON i.id = a.idea_id", {"a.status": "planned"},
                         "a.batch_date DESC, a.id", 500)
    beds = [*sorted(p.stem for p in remix.MUSIC_DIR.glob("music-*.wav")), "none"]
    out = []
    for r in rows:
        env = r["recipe"]
        todo = env.get("voice_todo") or {}
        if env["kind"] == "motion":
            script = [{"text": t, "editable": p is not None}
                      for t, p in _paths(env["template"], env["props"])]
            tune = todo.get("music_audio_id") or env["props"].get("music")
        else:
            script = [{"text": todo["script"], "editable": True}] if todo.get("script") else []
            tune = remix.remix_params(env)["music"] or "none"
        out.append({"asset_id": r["id"], "batch_date": r["batch_date"], "hook": r["hook"],
                    "style": r["style"], "recipe": env,
                    "kind": "motion" if env["kind"] == "motion" else "remix",
                    "template": env.get("template"), "script": script,
                    "voice": todo.get("voice"), "music": tune, "caption": r["caption"],
                    "description": r["description"], "sources": r["citations"] or [],
                    "music_options": beds})
    return out
