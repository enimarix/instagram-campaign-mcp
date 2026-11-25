"""
Style requests (step 156): styles the agent asks the owner for, so a change request is
never parked. Two kinds:

- reference: a style seen in a Reel or a DM pick (`reference`: its link or notes) that no
  enabled style can make;
- invented: an original concept from imagination: name, look, palette, motion language,
  typography, sound, 3 example scenes and why it fits macroBody given what performs. The
  late-night run proposes at least one a week (for_agent's invent_due, INVENT_EVERY).

Each lists the waiting videos (`revision_requested` assets) and open work orders it would
unblock; those videos show « Nouveau style demandé : <name> » on their Inbox card.

A request that unblocks a work order starts accepted (the owner asked for that video, owner
2026-11-25) and the order waits for it (work_orders.held_by_style), never made in another
style. Lifecycle: proposed -> accepted | declined (the owner, Agent page; he may change his mind
until the build starts) -> building -> live (the lead's dev loop: an accepted request is a
style step, `ig-campaign style-requests list --status accepted`). Nothing here generates
code: a request is a brief for a human-led build. When the style goes live its template
joins the registry, and the registry change re-wakes every waiting video
(src/agent/schedule.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from ..store import CampaignStore, parse_iso, to_iso, utcnow
from . import feedback, work_orders

KINDS = ("reference", "invented")
STATUSES = ("proposed", "accepted", "declined", "building", "live")
OWNER_DECISIONS = ("accepted", "declined")
# status -> the statuses it may move to, and who moves it
OWNER_MOVES = {"proposed": OWNER_DECISIONS, "accepted": ("declined",),
               "declined": ("accepted",)}
LEAD_MOVES = {"accepted": ("building",), "building": ("live",)}
OPEN = ("proposed", "accepted", "building")  # a name asked again while one of these is open
CONCEPT = ("look", "palette", "motion", "typography", "sound")  # invented: all required
NAME_MAX, TEXT_MAX, REFERENCE_MAX, NOTE_MAX = 60, 400, 500, 300
SCENES = 3
INVENT_EVERY = timedelta(days=7)
MAX_ITEMS = 30
_FIELDS = ("kind", "name", "concept", "unblocks", "status", "owner_note", "decided_at")


def _text(value: Optional[str], name: str, limit: int, required: bool) -> Optional[str]:
    value = " ".join((value or "").split()) or None
    if required and not value:
        raise ValueError(f"{name} is required")
    if value and len(value) > limit:
        raise ValueError(f"{name} is at most {limit} characters")
    return value


def _check_unblocks(store: CampaignStore, asset_ids: Sequence[int],
                    order_ids: Sequence[int]) -> Dict[str, List[int]]:
    asset_ids, order_ids = list(dict.fromkeys(asset_ids)), list(dict.fromkeys(order_ids))
    for i in asset_ids:
        if store.get_asset(i)["status"] != "revision_requested":
            raise ValueError(f"video {i} is not waiting for changes (revision_requested)")
    for i in order_ids:
        if work_orders.get_order(store, i)["status"] not in work_orders.OPEN:
            raise ValueError(f"work order {i} is not open")
    return {"asset_ids": asset_ids, "order_ids": order_ids}


def request_style(store: CampaignStore, kind: str, name: str, why: str,
                  scenes: Sequence[str], *, look: Optional[str] = None,
                  palette: Optional[str] = None, motion: Optional[str] = None,
                  typography: Optional[str] = None, sound: Optional[str] = None,
                  reference: Optional[str] = None, unblocks_asset_ids: Sequence[int] = (),
                  unblocks_order_ids: Sequence[int] = ()) -> Dict[str, Any]:
    """The agent asks for a style (see the module doc) -> the request. ValueError names
    the problem: an unknown kind, a missing or too long field (an invented style needs
    every concept field, a reference one its reference), not exactly 3 scenes, a video
    not waiting or an order not open, or the same name already open. Every unblocked
    video gets the decision « Nouveau style demandé : <name> »."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    name = _text(name, "name", NAME_MAX, True)
    concept: Dict[str, Any] = {
        k: _text(v, k, TEXT_MAX, kind == "invented")
        for k, v in zip(CONCEPT, (look, palette, motion, typography, sound))}
    concept["why"] = _text(why, "why", TEXT_MAX, True)
    concept["reference"] = _text(reference, "reference", REFERENCE_MAX, kind == "reference")
    scenes = [_text(s, "a scene", TEXT_MAX, True) for s in scenes or ()]
    if len(scenes) != SCENES:
        raise ValueError(f"give exactly {SCENES} example scenes")
    concept["scenes"] = scenes
    unblocks = _check_unblocks(store, unblocks_asset_ids, unblocks_order_ids)
    with store._tx() as c:
        same = c.execute(f"SELECT id FROM style_requests WHERE lower(name) = lower(?) AND"
                         f" status IN ({','.join('?' * len(OPEN))})", (name, *OPEN)).fetchone()
    if same:
        raise ValueError(f"style request {same[0]} already asks for {name!r}: name that one"
                         " in your summary instead")
    # The owner's order asked for this video: the style built for it is already accepted
    # (it goes to the build list at once) and the order waits for it (owner 2026-11-25).
    decided = {"status": "accepted", "decided_at": to_iso(utcnow()),
               "owner_note": "pour ta commande"} if unblocks["order_ids"] else {}
    row = store._insert("style_requests", _FIELDS, {"kind": kind, "name": name,
                                                    "concept": concept, "unblocks": unblocks,
                                                    **decided})
    for asset_id in unblocks["asset_ids"]:
        feedback.set_decision(store, asset_id, "style_requested", concept["why"],
                              request_id=row["id"], name=name)
    return row


def get_request(store: CampaignStore, request_id: int) -> Dict[str, Any]:
    return store._get("style_requests", request_id)


def list_requests(store: CampaignStore, status: Optional[str] = None,
                  limit: int = 100) -> List[Dict[str, Any]]:
    """Newest first."""
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    return store._select("SELECT * FROM style_requests", {"status": status}, "id DESC",
                         limit)


def _move(store: CampaignStore, request_id: int, status: str, moves: Dict[str, Sequence[str]],
          **fields: Any) -> Dict[str, Any]:
    row = get_request(store, request_id)
    if status not in moves.get(row["status"], ()):
        raise ValueError(f"style request {request_id} is {row['status']}: it cannot become"
                         f" {status}")
    with store._tx() as c:  # compare-and-set: a concurrent move wins, this one refuses
        sets = ", ".join(f"{k}=?" for k in ("status", *fields))
        moved = c.execute(f"UPDATE style_requests SET {sets}, updated_at=? WHERE id=? AND"
                          " status=?", (status, *fields.values(), to_iso(utcnow()),
                                        request_id, row["status"])).rowcount
    if not moved:
        raise ValueError(f"style request {request_id} changed meanwhile: reload it")
    return get_request(store, request_id)


def decide(store: CampaignStore, request_id: int, decision: str,
           note: Optional[str] = None) -> Dict[str, Any]:
    """The owner: « Construire » (accepted) or « Non » (declined), with an optional note
    for the agent and the lead. KeyError: no such request."""
    if decision not in OWNER_DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(OWNER_DECISIONS)}")
    return _move(store, request_id, decision, OWNER_MOVES,
                 owner_note=_text(note, "note", NOTE_MAX, False),
                 decided_at=to_iso(utcnow()))


def mark(store: CampaignStore, request_id: int, status: str) -> Dict[str, Any]:
    """The lead's dev loop: accepted -> building (the style step started) -> live (merged,
    the style is in the registry)."""
    return _move(store, request_id, status, LEAD_MOVES)


def for_agent(store: CampaignStore, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The packet's view: {invent_due (no invented request in the last INVENT_EVERY),
    last_invented_at, requests (newest MAX_ITEMS: id, kind, name, status, owner_note,
    concept)}."""
    now = now or utcnow()
    with store._tx() as c:
        last = c.execute("SELECT MAX(created_at) FROM style_requests WHERE kind='invented'"
                         ).fetchone()[0]
    rows = list_requests(store, limit=MAX_ITEMS)
    return {"invent_due": last is None or now - parse_iso(last) >= INVENT_EVERY,
            "last_invented_at": last,
            "requests": [{k: r[k] for k in ("id", "kind", "name", "status", "owner_note",
                                            "concept")} for r in rows]}
