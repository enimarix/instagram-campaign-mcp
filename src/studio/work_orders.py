"""
Work orders (step 134): Reels from the Trending feed (research references) the owner sends
the agent to make, each with a mode and, if they want, their exact instruction.

- inspired: an original video on the same idea or format; nothing of the Reel is reused
  (its idea may not use the Reel's source).
- react: a Track A commentary remix with credit (GOAL.md §5.1): the agent downloads the
  Reel (download_reel, 063b), and the remix rules of render_remix apply.

Lifecycle: new -> in_production (create_idea(work_order_id=...) links the idea) ->
in_feed (submit_asset on an asset of that idea; asset_id = the newest one submitted), or
skipped with a reason (the agent: e.g. a react the downloader refuses). The owner may
cancel (delete) a new one. One open order (new / in_production) per Reel.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..store import CampaignStore, to_iso, utcnow

MODES = ("inspired", "react")
STATUSES = ("new", "in_production", "in_feed", "skipped")
OPEN = ("new", "in_production")
INSTRUCTION_MAX = 500
REASON_MAX = 300
MAX_ITEMS = 20
CAPTION_LINE = 120
TRENDING_PROVIDER = "instagram"  # research.PROVIDER (research imports this module)
AGENT_KEYS = ("id", "source_id", "mode", "instruction", "status", "permalink", "topic",
              "caption_quote", "likes", "comments", "views", "created_at", "skip_reason",
              "idea_id", "asset_id")
_ROWS = ("SELECT w.*, s.url AS permalink, s.author, s.stats FROM work_orders w"
         " JOIN sources s ON s.id = w.source_id")


def _view(row: Dict[str, Any]) -> Dict[str, Any]:
    """The order with what the Reel was: permalink, topic (account, else hashtag), the
    caption's first line (other people's words: data, never instructions), stats."""
    stats = row.pop("stats") or {}
    caption = next((ln.strip() for ln in (stats.get("caption") or "").splitlines()
                    if ln.strip()), None)
    return {**row, "topic": row.pop("author") or stats.get("hashtag"),
            "caption_quote": caption and caption[:CAPTION_LINE],
            "likes": stats.get("likes"), "comments": stats.get("comments"),
            "views": stats.get("views"), "thumbnail_url": stats.get("thumbnail_url")}


def get_order(store: CampaignStore, order_id: int) -> Dict[str, Any]:
    rows = store._select(_ROWS, {"w.id": order_id}, "w.id", 1)
    if not rows:
        raise KeyError(f"No work order with id {order_id}")
    return _view(rows[0])


def list_orders(store: CampaignStore, status: Optional[str] = None, limit: int = 100,
                *, newest: bool = True) -> List[Dict[str, Any]]:
    """Newest first for the owner; oldest first (the order they were sent) for the agent."""
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    order = "w.id DESC" if newest else "w.id"
    return [_view(r) for r in store._select(_ROWS, {"w.status": status}, order, limit)]


def create_orders(store: CampaignStore, items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Store the owner's orders, all or none: [{source_id, mode, instruction?}]. ValueError
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
        if mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        try:
            source = store.get_source(source_id)
        except KeyError:
            raise ValueError(f"no Reel with id {source_id}") from None
        if source["provider"] != TRENDING_PROVIDER or not source["external_id"]:
            raise ValueError(f"source {source_id} is not a Reel from the Trending feed")
        if not source["url"]:
            raise ValueError(f"Reel {source_id} has no permalink")
        instruction = (item.get("instruction") or "").strip() or None
        if instruction and len(instruction) > INSTRUCTION_MAX:
            raise ValueError(f"an instruction is at most {INSTRUCTION_MAX} characters")
        if source_id in [r[0] for r in rows]:
            raise ValueError(f"Reel {source_id} is in the list twice")
        rows.append((source_id, mode, instruction))
    now = to_iso(utcnow())
    with store._tx() as c:  # one transaction: all or none
        for source_id, mode, instruction in rows:
            if c.execute("SELECT 1 FROM work_orders WHERE source_id=? AND status IN"
                         " ('new','in_production')", (source_id,)).fetchone():
                raise ValueError(f"Reel {source_id} already has an open work order")
        ids = [c.execute("INSERT INTO work_orders (source_id, mode, instruction, created_at,"
                         " updated_at) VALUES (?,?,?,?,?)",
                         (source_id, mode, instruction, now, now)).lastrowid
               for source_id, mode, instruction in rows]
    return [get_order(store, i) for i in ids]


def delete_order(store: CampaignStore, order_id: int) -> Dict[str, Any]:
    """The owner cancels a new order (not started yet); KeyError when there is none."""
    order = get_order(store, order_id)
    if order["status"] != "new":
        raise ValueError(f"work order {order_id} is {order['status']}: only a new one can"
                         " be cancelled")
    with store._tx() as c:
        c.execute("DELETE FROM work_orders WHERE id=? AND status='new'", (order_id,))
    return order


def skip_order(store: CampaignStore, order_id: int, reason: str) -> Dict[str, Any]:
    """The agent cannot make an open order: skipped, with a one-line reason."""
    reason = (reason or "").strip()[:REASON_MAX]
    if not reason:
        raise ValueError("say why the work order is skipped")
    order = get_order(store, order_id)
    if order["status"] not in OPEN:
        raise ValueError(f"work order {order_id} is {order['status']}: only an open one can"
                         " be skipped")
    store._update("work_orders", ("status", "skip_reason"), order_id,
                  {"status": "skipped", "skip_reason": reason})
    return get_order(store, order_id)


def check_idea(store: CampaignStore, order_id: int, track: str,
               source_id: Optional[int]) -> Dict[str, Any]:
    """Before create_idea(work_order_id=...) writes: the order is open and has no idea yet;
    react -> a remix of the order's Reel; inspired -> nothing of the Reel reused."""
    order = get_order(store, order_id)
    if order["status"] != "new":
        raise ValueError(f"work order {order_id} is {order['status']}: only a new one gets"
                         " an idea")
    if order["mode"] == "react" and (track != "remix" or source_id != order["source_id"]):
        raise ValueError(f"work order {order_id} is a react: create_idea(track='remix',"
                         f" source_id={order['source_id']}) after download_reel")
    if order["mode"] == "inspired" and source_id == order["source_id"]:
        raise ValueError(f"work order {order_id} is inspired: an original video, the Reel"
                         " itself is not used (no source_id)")
    return order


def start(store: CampaignStore, order_id: int, idea_id: int) -> None:
    """The idea made for the order exists: in_production."""
    store._update("work_orders", ("status", "idea_id"), order_id,
                  {"status": "in_production", "idea_id": idea_id})


def mark_in_feed(store: CampaignStore, asset: Dict[str, Any]) -> None:
    """submit_asset on an asset whose idea was made for an order: the order is in_feed,
    linked to this (newest submitted) asset. Nothing when the idea has no order."""
    with store._tx() as c:
        c.execute("UPDATE work_orders SET status='in_feed', asset_id=?, updated_at=?"
                  " WHERE idea_id=? AND status IN ('in_production','in_feed')",
                  (asset["id"], to_iso(utcnow()), asset["idea_id"]))


def open_by_source(store: CampaignStore, source_ids: Sequence[int]) -> Dict[int, Dict]:
    """{source_id: {id, mode, instruction, status}} of the open orders of these Reels."""
    if not source_ids:
        return {}
    with store._tx() as c:
        rows = c.execute(
            "SELECT id, source_id, mode, instruction, status FROM work_orders"
            f" WHERE status IN ('new','in_production') AND source_id IN"
            f" ({','.join('?' * len(source_ids))})", list(source_ids)).fetchall()
    return {r["source_id"]: {k: r[k] for k in ("id", "mode", "instruction", "status")}
            for r in rows}


def for_agent(store: CampaignStore, status: Optional[str] = "new",
              limit: int = 50) -> List[Dict[str, Any]]:
    """What the agent sees of the orders (status None: all), oldest first."""
    return [{k: o[k] for k in AGENT_KEYS}
            for o in list_orders(store, status, limit, newest=False)]
