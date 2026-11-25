"""
Owner comments on an asset (GOAL.md §3.2): reason chips, a pinned video moment,
"ask for changes".

A comment that wants changes moves a `ready` asset to `revision_requested` (owner).
On any other status the comment is still saved, the asset stays where it is and the
result says why. Nothing here ever schedules or publishes.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from ..store import CampaignStore, to_iso, utcnow
from . import lemo, styles, work_orders
from .assets import InvalidTransition, transition


def _check_time(asset: Dict[str, Any], video_time_s: Optional[float]) -> None:
    if video_time_s is None:
        return
    if video_time_s < 0:
        raise ValueError(f"video_time_s must be >= 0, not {video_time_s}")
    duration = asset.get("duration")
    if duration is not None and video_time_s > duration:
        raise ValueError(f"video_time_s {video_time_s} is past the video's end ({duration} s)")


def _ask_for_changes(store: CampaignStore, asset: Dict[str, Any]) -> Dict[str, Any]:
    """Move a ready asset to revision_requested; never fails the comment."""
    if asset["status"] != "ready":
        return {"asset": asset, "moved": False,
                "reason": f"asset is {asset['status']}; only a ready asset can be sent back"
                          " for changes"}
    try:
        asset = transition(store, asset["id"], "revision_requested", actor="owner")
    except InvalidTransition as e:  # status changed meanwhile
        return {"asset": store.get_asset(asset["id"]), "moved": False, "reason": str(e)}
    return {"asset": asset, "moved": True, "reason": None}


def add_comment(
    store: CampaignStore,
    asset_id: int,
    *,
    text: Optional[str] = None,
    reason_codes: Sequence[str] = (),
    video_time_s: Optional[float] = None,
    wants_changes: bool = False,
) -> Dict[str, Any]:
    """Save a comment -> {feedback, asset, moved, reason}. KeyError: no such asset."""
    asset = store.get_asset(asset_id)
    _check_time(asset, video_time_s)
    feedback = store.add_feedback(asset_id, text=text, reason_codes=reason_codes,
                                  video_time_s=video_time_s, wants_changes=wants_changes)
    if not wants_changes:
        return {"feedback": feedback, "asset": asset, "moved": False, "reason": None}
    return {"feedback": feedback, **_ask_for_changes(store, asset)}


def decline(
    store: CampaignStore,
    asset_id: int,
    *,
    reason_codes: Sequence[str] = (),
    text: Optional[str] = None,
) -> Dict[str, Any]:
    """The feed's Decline: verdict disliked, archived, and the motive saved as a comment
    -> the asset. Every decline has a motive (step 133): reason codes or text, so the agent
    learns from it. Ordered so a refusal leaves the asset unchanged: the status and the
    motive are checked first, the archive move (a compare-and-set) comes before the
    verdict. KeyError: no such asset; InvalidTransition: the asset is not ready;
    ValueError: no motive, or an unknown reason code."""
    asset = store.get_asset(asset_id)
    if asset["status"] != "ready":
        raise InvalidTransition(f"asset {asset_id} is {asset['status']}; only a ready asset"
                                " can be declined")
    if not (text and text.strip()) and not reason_codes:
        raise ValueError("a decline needs a motive: pick a reason or say why")
    # validates before the move; a lost race leaves only the comment
    store.add_feedback(asset_id, text=text and text.strip(), reason_codes=reason_codes)
    transition(store, asset_id, "archived", actor="owner")
    return store.update_asset(asset_id, verdict="disliked")


def edit_comment(store: CampaignStore, feedback_id: int, **fields: Any) -> Dict[str, Any]:
    """Edit a comment -> {feedback, asset, moved, reason}.

    Setting wants_changes=True follows add_comment's rule. Turning it off never moves
    the asset back: a revision once asked for stays asked for.
    """
    asset = store.get_asset(store.get_feedback(feedback_id)["asset_id"])
    if "video_time_s" in fields:
        _check_time(asset, fields["video_time_s"])
    feedback = store.update_feedback(feedback_id, **fields)
    if not fields.get("wants_changes"):
        return {"feedback": feedback, "asset": asset, "moved": False, "reason": None}
    return {"feedback": feedback, **_ask_for_changes(store, asset)}


# --- the agent's decision on a video sent back (156) -------------------------------------
# Never silence: every revision the agent reads gets one, shown on the Inbox.
DECISIONS = ("remade", "restyled", "style_requested", "waiting")
AGENT_DECISIONS = ("remade", "restyled", "waiting")  # style_requested: request_style sets it
WHY_MAX = 300


def set_decision(store: CampaignStore, asset_id: int, kind: str, why: Optional[str], *,
                 style: Optional[str] = None, order_id: Optional[int] = None,
                 request_id: Optional[int] = None, name: Optional[str] = None
                 ) -> Dict[str, Any]:
    """Store the agent's latest decision on a `revision_requested` video -> the asset.
    text is what its Inbox card says: « Refaite en <style> », « Nouveau style demandé :
    <name> » or « En attente : <why> »."""
    asset = store.get_asset(asset_id)
    if asset["status"] != "revision_requested":
        raise ValueError(f"video {asset_id} is {asset['status']}: a decision is only for a"
                         " video sent back for changes")
    if kind not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    why = " ".join((why or "").split())[:WHY_MAX] or None
    if not why:
        raise ValueError("say why in one line")
    label = None
    if style:
        try:
            label = (lemo.style_info(style) if lemo.is_lemo(style)
                     else styles.get_style(store, style))["label"]
        except (ValueError, RuntimeError):  # unknown, or no Node (MotionError): the id
            label = style
    text = {"remade": f"Refaite en {label}" if label else "Refaite",
            "restyled": f"Refaite en {label}",
            "style_requested": f"Nouveau style demandé : {name}",
            "waiting": f"En attente : {why}"}[kind]
    decision = {"kind": kind, "text": text, "why": why, "style": style,
                "order_id": order_id, "request_id": request_id, "at": to_iso(utcnow())}
    return store.update_asset(asset_id, agent_decision=decision)


# ponytail: a keyword match on the owner's words (French or English); a phrasing it misses
# reaches the film's brief verbatim, where the film says it can't carry the track.
_IG_MUSIC = re.compile(r"\b(insta(gram)?|ig)\b.*\b(musi\w*|audio|sound|track|song|chanson)"
                       r"|\b(musi\w*|audio|sound|track|song|chanson)\b.*\b(insta(gram)?|ig)\b",
                       re.I | re.S)


def _check_remake(store: CampaignStore, asset: Dict[str, Any], decision: str,
                  style: Optional[str]) -> None:
    """A remake (remade, restyled) in `style` must be one the owner can get: ValueError when
    he asked for Instagram music and the style is a Lemo film (no film path takes a track).
    A style he ruled out never gets here: decide_revision swaps it first (swap_banned)."""
    if not style:
        if decision == "restyled":
            raise ValueError("restyled needs the style to remake it in")
        return
    if lemo.is_lemo(style) and any(
            fb["wants_changes"] and _IG_MUSIC.search(fb["text"] or "")
            for fb in store.list_feedback(asset_id=asset["id"], limit=1000)):
        raise ValueError(f"the owner asks for Instagram music and a Lemo film ({style}) cannot"
                         " take an Instagram track: decide restyled in a template style that"
                         " can (fetch_music, then render_motion(music_audio_id=...); not the"
                         " Blender ones), and say in why that this is for the music")


def decide_revision(store: CampaignStore, asset_id: int, decision: str, why: str,
                    style: Optional[str] = None) -> Dict[str, Any]:
    """The agent's decision on a video the owner sent back -> {asset, order}:
    - remade: re-rendered in its own style (render_motion(asset_id=...)) as asked; a Lemo
      film (no template) gets a film order in its own style instead (order, 202): the film
      runner remakes it with `why` (what to change), the old video is archived once the
      new one is in the Inbox;
    - restyled: the note cannot be met in its style: remade in `style` (an enabled one,
      not its own) through a « même vidéo, autre style » work order (order; make it with
      create_idea(work_order_id=...); in a Lemo style the film runner makes it, 203); once
      that video is submitted the old one is archived;
    - waiting: it waits, and `why` says for what (a render pending). A missing style is not
      waiting: request_style.
    The order of an earlier decision with nothing made yet is skipped (202). A remake in a
    style (or, remade, a template) the owner ruled out becomes restyled in its best
    alternative (styles.swap_banned); one in a Lemo style is refused when he asked for
    Instagram music (_check_remake).
    ValueError names the problem; KeyError: no such video."""
    if decision not in AGENT_DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(AGENT_DECISIONS)}"
                         " (a new style: request_style)")
    asset = store.get_asset(asset_id)
    if asset["status"] != "revision_requested":
        raise ValueError(f"video {asset_id} is {asset['status']}: only a video sent back for"
                         " changes gets a decision")
    order = None
    before = (asset.get("agent_decision") or {}).get("order_id")
    if decision == "remade":
        style = store.get_idea(asset["idea_id"])["style"]
    if decision != "waiting" and style:  # a style (or template) the owner ruled out: its
        template = (asset.get("recipe") or {}).get("template") if decision == "remade" else None
        swapped, note = styles.swap_banned(store, style, template)  # best alternative
        if note:
            decision, style, why = "restyled", swapped, f"{note}. {why}"[:WHY_MAX]
    if decision != "waiting":
        _check_remake(store, asset, decision, style)
    if decision == "restyled":
        order = work_orders.restyle(store, asset_id, style, why)
    elif decision == "remade" and lemo.is_lemo(style):
        # 202: a film has no template: the film runner remakes it
        order = work_orders.refilm(store, asset_id, why)
    asset = set_decision(store, asset_id, decision, why, style=style,
                         order_id=order and order["id"])
    if before and before != (order and order["id"]):  # 202: never two remakes of one video
        work_orders.drop_unmade(store, before, f"remplacée : nouvelle décision sur la vidéo"
                                f" {asset_id} ({decision})")
    return {"asset": asset, "order": order}


def list_comments(store: CampaignStore, asset_id: int) -> List[Dict[str, Any]]:
    """Oldest first. KeyError: no such asset."""
    store.get_asset(asset_id)
    return store.list_feedback(asset_id=asset_id, limit=1000)


def delete_comment(store: CampaignStore, feedback_id: int) -> None:
    """Delete a comment. Never changes the asset's status."""
    store.delete_feedback(feedback_id)
