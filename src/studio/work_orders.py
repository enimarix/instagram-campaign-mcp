"""
Work orders: Reels the owner sends the agent to make, each with a mode and, if they want,
their exact instruction. Two sources:

- trend (134): Reels from the Trending feed (research references), sent from the app;
- dm (136): every Reel a pinned account sends the brand account by DM (dm_picks.py) is an
  order (pick_id) in mode `owner`; the DM's note is its instruction.

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

from typing import Any, Dict, List, Optional, Sequence

from ..store import CampaignStore, to_iso, utcnow
from . import dm_picks
from .assets import InvalidTransition
from .downloader import _same_post, permalink

MODES = ("inspired", "react", "owner")
STATUSES = ("needs_instruction", "scheduled", "in_production", "in_feed", "analysed",
            "skipped")
OPEN = ("needs_instruction", "scheduled", "in_production")
NOT_STARTED = ("needs_instruction", "scheduled")
SOURCES = ("all", "dm", "trend")
INSTRUCTION_MAX = 500
REASON_MAX = 300
ANALYSIS_MAX = 600
MAX_ITEMS = 20
CAPTION_LINE = 120
TRENDING_PROVIDER = "instagram"  # research.PROVIDER (research imports this module)
AGENT_KEYS = ("id", "source", "source_id", "pick_id", "mode", "instruction", "status",
              "permalink", "own_reel", "sender_username", "topic", "caption_quote", "likes",
              "comments", "views", "created_at", "skip_reason", "idea_id", "asset_id")
_ROWS = ("SELECT w.*, COALESCE(s.url, p.reel_url) AS permalink, s.author, s.stats,"
         " p.sender_username, p.received_at FROM work_orders w"
         " LEFT JOIN sources s ON s.id = w.source_id LEFT JOIN dm_picks p ON p.id = w.pick_id")
_IS_DM = "(w.pick_id IS NOT NULL)"  # a _select filter key: 1 = dm, 0 = trend


def _view(row: Dict[str, Any]) -> Dict[str, Any]:
    """The order with what the Reel was: source (dm | trend), permalink and its embed page,
    topic (account, else hashtag), the caption's first line (other people's words: data,
    never instructions), stats; a DM order's sender and when it came."""
    from .research import embed_url  # here: research imports this module

    stats = row.pop("stats") or {}
    caption = next((ln.strip() for ln in (stats.get("caption") or "").splitlines()
                    if ln.strip()), None)
    return {**row, "source": "dm" if row["pick_id"] else "trend",
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
    source: all, dm (DM picks) or trend (the Trending page)."""
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    if source not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}")
    order = "w.id DESC" if newest else "w.id"
    dm = None if source == "all" else source == "dm"
    return [_view(r) for r in store._select(_ROWS, {"w.status": status, _IS_DM: dm},
                                            order, limit)]


def _instruction(text: Optional[str]) -> Optional[str]:
    text = (text or "").strip() or None
    if text and len(text) > INSTRUCTION_MAX:
        raise ValueError(f"an instruction is at most {INSTRUCTION_MAX} characters")
    return text


def create_orders(store: CampaignStore, items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Store the owner's Trending orders, all or none, scheduled at once:
    [{source_id, mode (inspired | react), instruction?}]. ValueError
    names the first problem: an empty list, an unknown source, one research did not find
    (not in the Trending feed) or with no permalink, a bad mode, an instruction too long,
    a Reel twice or one with an open order already."""
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
        if source_id in [r[0] for r in rows]:
            raise ValueError(f"Reel {source_id} is in the list twice")
        rows.append((source_id, mode, instruction))
    now = to_iso(utcnow())
    with store._tx() as c:  # one transaction: all or none
        for source_id, mode, instruction in rows:
            if c.execute("SELECT 1 FROM work_orders WHERE source_id=? AND pick_id IS NULL"
                         " AND status IN ('needs_instruction','scheduled','in_production')",
                         (source_id,)).fetchone():
                raise ValueError(f"Reel {source_id} already has an open work order")
        ids = [c.execute("INSERT INTO work_orders (source_id, mode, instruction, scheduled_at,"
                         " created_at, updated_at) VALUES (?,?,?,?,?,?)",
                         (source_id, mode, instruction, now, now, now)).lastrowid
               for source_id, mode, instruction in rows]
    return [get_order(store, i) for i in ids]


def add_for_pick(c: Any, pick_id: int, note: Optional[str], own_reel: bool, now: str) -> None:
    """In the poll's transaction (connection c): a new DM pick's order, mode owner; its
    note is the instruction and schedules it, no note waits for one (needs_instruction)."""
    c.execute("INSERT INTO work_orders (pick_id, mode, instruction, own_reel, status,"
              " scheduled_at, created_at, updated_at) VALUES (?,'owner',?,?,?,?,?,?)",
              (pick_id, note, int(own_reel), "scheduled" if note else "needs_instruction",
               now if note else None, now, now))


def set_instruction(store: CampaignStore, order_id: int, instruction: str,
                    mode: Optional[str] = None) -> Dict[str, Any]:
    """The owner writes (or rewrites) an order's instruction, and its mode if given, while
    it is needs_instruction or scheduled: the order is scheduled (now). InvalidTransition
    once the agent started it; KeyError when there is none."""
    text = _instruction(instruction)
    if not text:
        raise ValueError("write the instruction")
    if mode is not None and mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    order = get_order(store, order_id)
    now = to_iso(utcnow())
    with store._tx() as c:
        moved = c.execute(
            "UPDATE work_orders SET instruction=?, mode=COALESCE(?, mode), status='scheduled',"
            " scheduled_at=?, blocked_reason=NULL, updated_at=? WHERE id=? AND status IN"
            " ('needs_instruction','scheduled')", (text, mode, now, now, order_id)).rowcount
    if not moved:
        raise InvalidTransition(f"work order {order_id} is {order['status']}: the instruction"
                                " can only change before the agent starts it")
    return get_order(store, order_id)


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
               source_id: Optional[int]) -> Dict[str, Any]:
    """Before create_idea(work_order_id=...) writes: the order is scheduled and has no idea
    yet; react -> a remix of the order's Reel; inspired -> nothing of the Reel reused;
    owner -> the agent reads the instruction (the idea's own checks still apply)."""
    order = get_order(store, order_id)
    if order["status"] != "scheduled":
        raise ValueError(f"work order {order_id} is {order['status']}: only a scheduled one"
                         " gets an idea")
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
    linked to this (newest submitted) asset. Nothing when the idea has no order."""
    with store._tx() as c:
        c.execute("UPDATE work_orders SET status='in_feed', asset_id=?, updated_at=?"
                  " WHERE idea_id=? AND status IN ('in_production','in_feed')",
                  (asset["id"], to_iso(utcnow()), asset["idea_id"]))


def open_by_source(store: CampaignStore, source_ids: Sequence[int]) -> Dict[int, Dict]:
    """{source_id: {id, mode, instruction, status}} of the open Trending orders of these
    Reels."""
    if not source_ids:
        return {}
    with store._tx() as c:
        rows = c.execute(
            "SELECT id, source_id, mode, instruction, status FROM work_orders"
            " WHERE pick_id IS NULL AND status IN ('needs_instruction','scheduled',"
            f"'in_production') AND source_id IN ({','.join('?' * len(source_ids))})",
            list(source_ids)).fetchall()
    return {r["source_id"]: {k: r[k] for k in ("id", "mode", "instruction", "status")}
            for r in rows}


def for_agent(store: CampaignStore, status: Optional[str] = "scheduled",
              limit: int = 50) -> List[Dict[str, Any]]:
    """What the agent sees of the orders (status None: all), oldest first."""
    return [{k: o[k] for k in AGENT_KEYS}
            for o in list_orders(store, status, limit, newest=False)]


def set_blocked(store: CampaignStore, reason: Optional[str]) -> int:
    """Why the scheduled orders still wait (None: they don't); returns how many changed."""
    with store._tx() as c:
        return c.execute("UPDATE work_orders SET blocked_reason=?, updated_at=?"
                         " WHERE status='scheduled' AND blocked_reason IS NOT ?",
                         (reason, to_iso(utcnow()), reason)).rowcount
