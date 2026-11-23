"""
Work orders: videos the owner sends the agent to make, each with a mode, a style and, if
they want, their exact instruction. Four origins:

- trend (134): Reels from the Trending feed (research references), sent from the app;
- dm (136): every Reel a pinned account sends the brand account by DM (dm_picks.py) is an
  order (pick_id) in mode `owner`; the DM's note is its instruction;
- create (138): « Créer une vidéo », a topic or instruction and nothing else (mode owner);
- change (138): « même vidéo, autre style » of one of our videos (from_asset_id, mode
  owner): the same video remade in another style.

style (138, src/studio/styles.py): the style button the owner pressed; None = Auto (the
agent picks). The idea made for the order is in that style (check_idea, create_idea).
A Lemo-Opuscar style (`lemo:<slug>`, 173, src/studio/lemo.py) is for owner-mode orders
only: the film runner (src/agent/film.py) makes those, never the agent (for_agent leaves
them out; set_blocked(films=True) is their own wait reason).

Modes:
- inspired: an original video on the same idea or format; nothing of the Reel is reused
  (its idea may not use the Reel's source).
- react: a Track A commentary remix with credit (GOAL.md §5.1): the agent downloads the
  Reel (download_reel, 063b), and the remix rules of render_remix apply.
- owner: follow the owner's free-text instruction (a reaction, an inspired video, a recut
  of our own Reel when own_reel, or analyse only); the playbooks say how.

Lifecycle: needs_instruction (a DM order without a note) -> scheduled (set_instruction;
an order with an instruction or a mode starts here) -> in_production
(create_idea(work_order_id=...) links the idea) -> in_feed (submit_asset on an asset of
that idea; asset_id = the newest one submitted) | analysed (analyse only: the agent's
analysis, no video) | skipped with a reason. The owner may cancel one not started.
A scheduled order starts the light run at once (src/agent/schedule.py order_run);
blocked_reason says why it still waits. One open order per Trending Reel; a DM Reel sent
twice is two orders. A DM order's pick follows it (in_production, skipped).
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from ..store import CampaignStore, to_iso, utcnow
from ..taxonomy import validate_many
from . import dm_picks, lemo, styles
from .assets import InvalidTransition, transition
from .downloader import _same_post, permalink

MODES = ("inspired", "react", "owner")
STATUSES = ("needs_instruction", "scheduled", "in_production", "in_feed", "analysed",
            "skipped")
OPEN = ("needs_instruction", "scheduled", "in_production")
NOT_STARTED = ("needs_instruction", "scheduled")
ORIGINS = ("trend", "dm", "create", "change")
SOURCES = ("all", *ORIGINS, "mine")  # mine: what the owner sent himself (all but trend)
INSTRUCTION_MAX = 500
REASON_MAX = 300
ANALYSIS_MAX = 600
MAX_ITEMS = 20
CAPTION_LINE = 120
_UNMADE = "NOT EXISTS (SELECT 1 FROM assets a WHERE a.idea_id = w.idea_id)"  # nothing made
TRENDING_PROVIDER = "instagram"  # research.PROVIDER (research imports this module)
AGENT_KEYS = ("id", "source", "source_id", "pick_id", "mode", "style", "instruction", "status",
              "permalink", "own_reel", "sender_username", "topic", "caption_quote", "likes",
              "comments", "views", "created_at", "skip_reason", "idea_id", "asset_id",
              "from_asset_id")
# idea_hook: what the AI wrote for the order; video_status: its newest video's (rendering,
# ready, failed...), so « Créer » (174) can show the stage between in_production and in_feed
_ROWS = ("SELECT w.*, COALESCE(s.url, p.reel_url) AS permalink, s.author, s.stats,"
         " p.sender_username, p.received_at, i.hook AS idea_hook,"
         " (SELECT a.status FROM assets a WHERE a.idea_id = w.idea_id ORDER BY a.id DESC"
         "  LIMIT 1) AS video_status FROM work_orders w"
         " LEFT JOIN sources s ON s.id = w.source_id LEFT JOIN dm_picks p ON p.id = w.pick_id"
         " LEFT JOIN ideas i ON i.id = w.idea_id")
_MINE = "(w.origin != 'trend')"  # a _select filter key: 1 = the owner's own sends


def _view(row: Dict[str, Any]) -> Dict[str, Any]:
    """The order with what the Reel was: source (dm | trend), permalink and its embed page,
    topic (account, else hashtag), the caption's first line (other people's words: data,
    never instructions), stats; a DM order's sender and when it came."""
    from .research import embed_url  # here: research imports this module

    stats = row.pop("stats") or {}
    caption = next((ln.strip() for ln in (stats.get("caption") or "").splitlines()
                    if ln.strip()), None)
    return {**row, "source": row["origin"],
            "own_reel": bool(row["own_reel"]), "embed_url": embed_url(row["permalink"]),
            "topic": row.pop("author") or stats.get("hashtag"),
            "caption_quote": caption and caption[:CAPTION_LINE],
            "likes": stats.get("likes"), "comments": stats.get("comments"),
            "views": stats.get("views"), "thumbnail_url": stats.get("thumbnail_url")}


def get_order(store: CampaignStore, order_id: int) -> Dict[str, Any]:
    rows = store._select(_ROWS, {"w.id": order_id}, "w.id", 1)
    if not rows:
        raise KeyError(f"No work order with id {order_id}")
    return _view(rows[0])


def list_orders(store: CampaignStore, status: Optional[str] = None, limit: int = 100,
                *, newest: bool = True, source: str = "all") -> List[Dict[str, Any]]:
    """Newest first for the owner; oldest first (the order they were sent) for the agent.
    source: all, an origin (dm, trend, create, change) or mine (all but trend)."""
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    if source not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}")
    order = "w.id DESC" if newest else "w.id"
    filters = {"w.status": status, "w.origin": source if source in ORIGINS else None,
               _MINE: 1 if source == "mine" else None}
    return [_view(r) for r in store._select(_ROWS, filters, order, limit)]


def _style(store: CampaignStore, style: Optional[str], mode: str) -> Optional[str]:
    """A style an order may ask for: None (Auto), an enabled studio style, or a style of the
    Lemo-Opuscar library for an owner-mode order (ValueError otherwise)."""
    if not lemo.is_lemo(style):
        return styles.check_style(store, style)
    if mode != "owner":
        raise ValueError(f"a Lemo-Opuscar style ({style}) is for your own orders only, not"
                         f" mode {mode}")
    return lemo.check_style(style)


def _instruction(text: Optional[str]) -> Optional[str]:
    text = (text or "").strip() or None
    if text and len(text) > INSTRUCTION_MAX:
        raise ValueError(f"an instruction is at most {INSTRUCTION_MAX} characters")
    return text


def create_orders(store: CampaignStore, items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Store the owner's Trending orders, all or none, scheduled at once:
    [{source_id, mode (inspired | react), instruction?, style? (None: Auto)}]. ValueError
    names the first problem: an empty list, an unknown source, one research did not find
    (not in the Trending feed) or with no permalink, a bad mode, an instruction too long,
    a style unknown or turned off, a Reel twice or one with an open order already."""
    if not items:
        raise ValueError("pick at least one Reel")
    if len(items) > MAX_ITEMS:
        raise ValueError(f"at most {MAX_ITEMS} Reels at once")
    rows = []
    for item in items:
        source_id, mode = item.get("source_id"), item.get("mode")
        if mode not in ("inspired", "react"):
            raise ValueError("mode must be one of inspired, react")
        try:
            source = store.get_source(source_id)
        except KeyError:
            raise ValueError(f"no Reel with id {source_id}") from None
        if source["provider"] != TRENDING_PROVIDER or not source["external_id"]:
            raise ValueError(f"source {source_id} is not a Reel from the Trending feed")
        if not source["url"]:
            raise ValueError(f"Reel {source_id} has no permalink")
        instruction = _instruction(item.get("instruction"))
        style = _style(store, item.get("style"), mode)
        if source_id in [r[0] for r in rows]:
            raise ValueError(f"Reel {source_id} is in the list twice")
        rows.append((source_id, mode, instruction, style))
    now = to_iso(utcnow())
    with store._tx() as c:  # one transaction: all or none
        for source_id, *_ in rows:
            if c.execute("SELECT 1 FROM work_orders WHERE source_id=? AND origin='trend'"
                         " AND status IN ('needs_instruction','scheduled','in_production')",
                         (source_id,)).fetchone():
                raise ValueError(f"Reel {source_id} already has an open work order")
        ids = [c.execute("INSERT INTO work_orders (origin, source_id, mode, instruction, style,"
                         " scheduled_at, created_at, updated_at)"
                         " VALUES ('trend',?,?,?,?,?,?,?)", (*row, now, now, now)).lastrowid
               for row in rows]
    return [get_order(store, i) for i in ids]


def add_for_pick(c: Any, pick_id: int, note: Optional[str], own_reel: bool, now: str) -> None:
    """In the poll's transaction (connection c): a new DM pick's order, mode owner; its
    note is the instruction and schedules it, no note waits for one (needs_instruction)."""
    c.execute("INSERT INTO work_orders (origin, pick_id, mode, instruction, own_reel, status,"
              " scheduled_at, created_at, updated_at) VALUES ('dm',?,'owner',?,?,?,?,?,?)",
              (pick_id, note, int(own_reel), "scheduled" if note else "needs_instruction",
               now if note else None, now, now))


def late_note(c: Any, pick_id: int, note: str, now: str) -> None:
    """In the poll's transaction: a note found on a later poll for a pick stored without
    one. Only while its order still waits for an instruction (needs_instruction): the pick
    gets the note and the order is scheduled as add_for_pick would have done. An existing
    note, an owner's instruction or an order that moved on is never touched."""
    if not c.execute("UPDATE dm_picks SET sender_note=?, updated_at=? WHERE id=?"
                     " AND sender_note IS NULL AND id IN (SELECT pick_id FROM work_orders"
                     " WHERE status='needs_instruction' AND instruction IS NULL)",
                     (note, now, pick_id)).rowcount:
        return
    c.execute("UPDATE work_orders SET instruction=?, status='scheduled', scheduled_at=?,"
              " updated_at=? WHERE pick_id=? AND status='needs_instruction'"
              " AND instruction IS NULL", (note, now, now, pick_id))


def set_instruction(store: CampaignStore, order_id: int, instruction: str,
                    mode: Optional[str] = None, style: Any = ...) -> Dict[str, Any]:
    """The owner writes (or rewrites) an order's instruction, and its mode and style if
    given (style None: Auto), while it is needs_instruction or scheduled: the order is
    scheduled (now). InvalidTransition once the agent started it; KeyError when there is
    none."""
    text = _instruction(instruction)
    if not text:
        raise ValueError("write the instruction")
    if mode is not None and mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    order = get_order(store, order_id)
    if style is ...:  # kept; a Lemo style still needs mode owner
        style = order["style"]
        if lemo.is_lemo(style):
            _style(store, style, mode or order["mode"])
    else:
        style = _style(store, style, mode or order["mode"])
    now = to_iso(utcnow())
    with store._tx() as c:
        moved = c.execute(
            "UPDATE work_orders SET instruction=?, mode=COALESCE(?, mode), style=?,"
            " status='scheduled', scheduled_at=?, blocked_reason=NULL, updated_at=? WHERE id=?"
            " AND status IN ('needs_instruction','scheduled')",
            (text, mode, style, now, now, order_id)).rowcount
    if not moved:
        raise InvalidTransition(f"work order {order_id} is {order['status']}: the instruction"
                                " can only change before the agent starts it")
    return get_order(store, order_id)


def _insert_owner_order(store: CampaignStore, origin: str, instruction: str,
                        style: Optional[str], from_asset_id: Optional[int] = None
                        ) -> Dict[str, Any]:
    now = to_iso(utcnow())
    with store._tx() as c:
        order_id = c.execute(
            "INSERT INTO work_orders (origin, from_asset_id, mode, instruction, style,"
            " scheduled_at, created_at, updated_at) VALUES (?,?,'owner',?,?,?,?,?)",
            (origin, from_asset_id, instruction, style, now, now, now)).lastrowid
    return get_order(store, order_id)


def create_video(store: CampaignStore, instruction: str,
                 style: Optional[str] = None) -> Dict[str, Any]:
    """« Créer une vidéo »: a topic or instruction in the owner's words and a style (None:
    Auto), scheduled at once (mode owner)."""
    text = _instruction(instruction)
    if not text:
        raise ValueError("write the topic or the instruction")
    return _insert_owner_order(store, "create", text, _style(store, style, "owner"))


def restyle(store: CampaignStore, asset_id: int, style: Optional[str],
            note: Optional[str] = None, reasons: Sequence[str] = (), *,
            retire: bool = False) -> Dict[str, Any]:
    """« Même vidéo, autre style »: an order to remake our video `asset_id` (same topic,
    script and message) in `style` (None: another one the agent picks), with the owner's
    optional note and reason codes (they go in the instruction). ValueError when the video
    is already in that style; KeyError when there is no such video.
    `retire` (the owner's Inbox, 181): the note and reasons are also saved as a comment on
    the video (the agent learns from it), and a `ready` video leaves the Inbox (archived:
    the remake replaces it)."""
    asset = store.get_asset(asset_id)
    current = store.get_idea(asset["idea_id"])["style"]
    style = _style(store, style, "owner")
    if style is not None and style == current:
        raise ValueError(f"video {asset_id} is already in style {style!r}: pick another one")
    if style is None:
        other = f" que {current}" if current else ""
        how = f"dans un autre style{other}, au choix de l'IA"
    else:
        label = (lemo.style_info(style) if lemo.is_lemo(style)
                 else styles.get_style(store, style))["label"]
        how = f"en style « {label} » ({style})"
    text = (f"Même vidéo, autre style : refais la vidéo {asset_id} (même sujet, même script,"
            f" même message) {how}.")
    note = (note or "").strip()
    reasons = validate_many("feedback_reasons", reasons)  # before anything is written
    extra = " ".join(x for x in (
        f"Raisons : {', '.join(reasons)}." if reasons else "",
        f"Et aussi : {note}" if note else "") if x)
    order = _insert_owner_order(store, "change", _instruction(f"{text} {extra}" if extra else text),
                                style, asset_id)
    if retire:
        if note or reasons:
            store.add_feedback(asset_id, text=note or None, reason_codes=reasons)
        if asset["status"] == "ready":
            with contextlib.suppress(InvalidTransition):  # moved meanwhile: it stays
                transition(store, asset_id, "archived", actor="owner")
    return order


def refilm(store: CampaignStore, asset_id: int, why: str) -> Dict[str, Any]:
    """202: a Lemo film the owner sent back, remade in its own style (the agent's
    decide_revision remade): a film has no template to re-render, so this is a change order
    the film runner makes, `why` (what to change) in its instruction. ValueError when the
    video is not a Lemo film."""
    style = store.get_idea(store.get_asset(asset_id)["idea_id"])["style"]
    if not lemo.is_lemo(style):
        raise ValueError(f"video {asset_id} is not a Lemo film: re-render it with"
                         " render_motion(asset_id=...)")
    text = (f"Même film, refait : refais la vidéo {asset_id} (même sujet, même message) dans"
            f" son style « {lemo.style_info(style)['label']} » ({style}), en changeant ce que"
            f" le propriétaire a demandé : {' '.join(why.split())}")
    return _insert_owner_order(store, "change", text[:INSTRUCTION_MAX], style, asset_id)


def drop_unmade(store: CampaignStore, order_id: int, reason: str) -> bool:
    """202: an open order with nothing made yet (no video of its idea) is skipped with
    `reason` (a newer decision on its video replaced it); True when it was."""
    with store._tx() as c:
        hit = c.execute(f"SELECT 1 FROM work_orders w WHERE w.id=? AND w.status IN"
                        f" ('needs_instruction','scheduled','in_production') AND {_UNMADE}",
                        (order_id,)).fetchone()
    if hit:
        skip_order(store, order_id, reason)
    return bool(hit)


def recover(store: CampaignStore, stale_before: datetime) -> Dict[str, List[int]]:
    """202: orders a dead agent run left in_production with nothing made (no video of their
    idea, untouched since `stale_before`, the agent's time cap ago) -> {rescheduled,
    skipped}. Back to scheduled with the idea unlinked, so the next run makes them; a
    change order whose video got another decision since (sent back or archived meanwhile)
    is skipped: that decision replaced it. Lemo orders are the film runner's
    (film.close_orphans). ponytail: "another decision" = the video's latest agent_decision
    names another order; an owner's change order (no agent decision) comes back."""
    with store._tx() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT w.* FROM work_orders w WHERE w.status='in_production' AND w.updated_at < ?"
            f" AND COALESCE(w.style, '') NOT LIKE ? AND {_UNMADE}",
            (to_iso(stale_before), lemo.PREFIX + "%"))]
    out: Dict[str, List[int]] = {"rescheduled": [], "skipped": []}
    for o in rows:
        asset = store.get_asset(o["from_asset_id"]) if o["from_asset_id"] else None
        decided = (asset or {}).get("agent_decision") or {}
        if o["origin"] == "change" and decided and decided.get("order_id") != o["id"]:
            skip_order(store, o["id"], f"remplacée : la vidéo {asset['id']} a eu une autre"
                       " décision depuis (le run qui l'avait commencée s'est arrêté)")
            out["skipped"].append(o["id"])
            continue
        store._update("work_orders", ("status", "idea_id", "blocked_reason"), o["id"],
                      {"status": "scheduled", "idea_id": None, "blocked_reason": None})
        out["rescheduled"].append(o["id"])
    return out


def remade_idea(store: CampaignStore, order: Dict[str, Any]) -> Optional[int]:
    """The idea of the video a change order remakes (its hook may come back), else None."""
    if not order.get("from_asset_id"):
        return None
    return store.get_asset(order["from_asset_id"])["idea_id"]


def delete_order(store: CampaignStore, order_id: int) -> Dict[str, Any]:
    """The owner cancels an order not started yet (needs_instruction or scheduled; a DM
    order's pick stays); KeyError when there is none."""
    order = get_order(store, order_id)
    if order["status"] not in NOT_STARTED:
        raise ValueError(f"work order {order_id} is {order['status']}: only one not started"
                         " can be cancelled")
    with store._tx() as c:
        c.execute("DELETE FROM work_orders WHERE id=? AND status IN"
                  " ('needs_instruction','scheduled')", (order_id,))
    return order


def skip_order(store: CampaignStore, order_id: int, reason: str) -> Dict[str, Any]:
    """The agent cannot make an open order: skipped, with a one-line reason (a DM order's
    pick too, unless it was posted)."""
    reason = (reason or "").strip()[:REASON_MAX]
    if not reason:
        raise ValueError("say why the work order is skipped")
    order = get_order(store, order_id)
    if order["status"] not in OPEN:
        raise ValueError(f"work order {order_id} is {order['status']}: only an open one can"
                         " be skipped")
    store._update("work_orders", ("status", "skip_reason", "blocked_reason"), order_id,
                  {"status": "skipped", "skip_reason": reason, "blocked_reason": None})
    if order["pick_id"] and store._get("dm_picks", order["pick_id"])["status"] != "posted":
        dm_picks.mark_pick(store, order["pick_id"], "skipped", reason)
    return get_order(store, order_id)


def analyse(store: CampaignStore, order_id: int, source_id: int, why: str) -> Dict[str, Any]:
    """Analyse only, no video: a scheduled order's Reel, downloaded (source_id) with its
    timeline written by set_clip_timeline (110's format), and why it worked (at most
    ANALYSIS_MAX characters). The order is analysed, with {why, summary, timeline}."""
    why = " ".join((why or "").split())
    if not why or len(why) > ANALYSIS_MAX:
        raise ValueError(f"why must be 1-{ANALYSIS_MAX} characters")
    order = get_order(store, order_id)
    if order["status"] != "scheduled":
        raise ValueError(f"work order {order_id} is {order['status']}: only a scheduled one"
                         " can be analysed")
    source = store.get_source(source_id)
    if source_id != order["source_id"] and not _same_reel(source["url"], order["permalink"]):
        raise ValueError(f"source {source_id} is not the Reel of work order {order_id}")
    stats = source.get("stats") or {}
    if not stats.get("timeline"):
        raise ValueError(f"no timeline on source {source_id}: get_clip_frames, then"
                         " set_clip_timeline first")
    store._update("work_orders", ("status", "source_id", "analysis", "blocked_reason"),
                  order_id, {"status": "analysed", "source_id": source_id,
                             "blocked_reason": None,
                             "analysis": {"why": why, "summary": stats.get("summary"),
                                          "timeline": stats["timeline"]}})
    return get_order(store, order_id)


def _same_reel(url: Optional[str], other: Optional[str]) -> bool:
    try:
        return permalink(url or "") in _same_post(other or "")
    except ValueError:  # not a Reel permalink (e.g. a CDN link): never the same
        return False


def check_idea(store: CampaignStore, order_id: int, track: str,
               source_id: Optional[int], style: Optional[str] = None) -> Dict[str, Any]:
    """Before create_idea(work_order_id=...) writes: the order is scheduled and has no idea
    yet; react -> a remix of the order's Reel; inspired -> nothing of the Reel reused;
    owner -> the agent reads the instruction (the idea's own checks still apply); an order
    with a style -> the idea is in that style."""
    order = get_order(store, order_id)
    if order["status"] != "scheduled":
        raise ValueError(f"work order {order_id} is {order['status']}: only a scheduled one"
                         " gets an idea")
    if order["style"] and style and style != order["style"]:
        raise ValueError(f"work order {order_id} asks for style {order['style']!r}, not"
                         f" {style!r}: create_idea(style={order['style']!r}) and a template"
                         " of that style")
    reel = order["source_id"]  # a DM order's Reel: the source download_reel made of it
    if reel is None and source_id is not None and _same_reel(
            store.get_source(source_id)["url"], order["permalink"]):
        reel = source_id
    if order["mode"] == "react" and (track != "remix" or reel is None or source_id != reel):
        raise ValueError(f"work order {order_id} is a react: create_idea(track='remix',"
                         f" source_id={reel or '<the source download_reel made of it>'})"
                         " after download_reel")
    if order["mode"] == "inspired" and reel is not None and source_id == reel:
        raise ValueError(f"work order {order_id} is inspired: an original video, the Reel"
                         " itself is not used (no source_id)")
    return order


def start(store: CampaignStore, order_id: int, idea: Dict[str, Any]) -> None:
    """The idea made for the order exists: in_production (a DM order's pick too)."""
    order = get_order(store, order_id)
    fields: Dict[str, Any] = {"status": "in_production", "idea_id": idea["id"],
                              "blocked_reason": None}
    if order["source_id"] is None and idea.get("source_id") is not None:
        fields["source_id"] = idea["source_id"]
    store._update("work_orders", tuple(fields), order_id, fields)
    if order["pick_id"]:
        dm_picks.mark_pick(store, order["pick_id"], "in_production")


def mark_in_feed(store: CampaignStore, asset: Dict[str, Any]) -> None:
    """submit_asset on an asset whose idea was made for an order: the order is in_feed,
    linked to this (newest submitted) asset. Nothing when the idea has no order. A change
    order's old video still sent back for changes is archived: its remake in another
    style is in the feed now (156, like a new version of the same style)."""
    with store._tx() as c:
        c.execute("UPDATE work_orders SET status='in_feed', asset_id=?, updated_at=?"
                  " WHERE idea_id=? AND status IN ('in_production','in_feed')",
                  (asset["id"], to_iso(utcnow()), asset["idea_id"]))
        old = [r[0] for r in c.execute(
            "SELECT a.id FROM work_orders w JOIN assets a ON a.id = w.from_asset_id"
            " WHERE w.idea_id=? AND w.origin='change' AND a.status='revision_requested'",
            (asset["idea_id"],))]
    for asset_id in old:
        try:
            transition(store, asset_id, "archived", actor="system")
        except InvalidTransition:  # the owner moved it meanwhile
            pass


def open_by_source(store: CampaignStore, source_ids: Sequence[int]) -> Dict[int, Dict]:
    """{source_id: {id, mode, instruction, status}} of the open Trending orders of these
    Reels."""
    if not source_ids:
        return {}
    with store._tx() as c:
        rows = c.execute(
            "SELECT id, source_id, mode, instruction, status, style FROM work_orders"
            " WHERE origin='trend' AND status IN ('needs_instruction','scheduled',"
            f"'in_production') AND source_id IN ({','.join('?' * len(source_ids))})",
            list(source_ids)).fetchall()
    return {r["source_id"]: {k: r[k] for k in ("id", "mode", "instruction", "status", "style")}
            for r in rows}


def for_agent(store: CampaignStore, status: Optional[str] = "scheduled",
              limit: int = 50) -> List[Dict[str, Any]]:
    """What the agent sees of the orders (status None: all), oldest first. A change order
    carries from_video: the idea of the video to remake (its hook, script, template).
    Lemo-Opuscar orders are left out: the film runner makes them (173)."""
    out = []
    for o in list_orders(store, status, limit, newest=False):
        if lemo.is_lemo(o["style"]):
            continue
        row = {k: o[k] for k in AGENT_KEYS}
        if o["from_asset_id"]:
            asset = store.get_asset(o["from_asset_id"])
            idea = store.get_idea(asset["idea_id"])
            row["from_video"] = {**{k: idea[k] for k in ("id", "track", "pillar", "hook",
                                                          "hook_type", "script", "style")},
                                 "template": (asset["recipe"] or {}).get("template")}
        out.append(row)
    return out


def set_blocked(store: CampaignStore, reason: Optional[str], *, films: bool = False) -> int:
    """Why the scheduled orders still wait (None: they don't): the agent's, or with films
    the Lemo-Opuscar ones (the film runner's); returns how many changed."""
    which = "LIKE" if films else "NOT LIKE"
    with store._tx() as c:
        return c.execute("UPDATE work_orders SET blocked_reason=?, updated_at=?"
                         " WHERE status='scheduled' AND blocked_reason IS NOT ?"
                         f" AND COALESCE(style, '') {which} ?",
                         (reason, to_iso(utcnow()), reason, lemo.PREFIX + "%")).rowcount
