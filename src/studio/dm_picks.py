"""
DM picks (step 113, GOAL.md §3.1 Track A step 1): the owner pins Instagram accounts (their
own, trusted friends); every Reel such an account sends the brand account by DM becomes a
pick, the strongest positive signal for Track A (113b downloads and produces it).

poll_dm_picks() reads the brand account's recent conversations through the Page (Messenger
Platform for Instagram: Page token, instagram_manage_messages). Only conversations with a
pinned participant are opened, and in them only messages FROM a pinned account that share
something are kept. Nothing else from the DMs is stored, and nothing is ever sent.

What Meta's docs say (2026-11): shares are read through `shares{link,name,id}`; details come
only for the 20 newest messages of a conversation; Requests-folder conversations idle for 30
days are not returned; the Conversations API allows 2 calls/s per account. A share whose
kind cannot be told (the API returns a URL, usually a CDN one) is taken: a non-video pick
is skipped with its reason at download (113b).
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional

from ..instagram_client import InstagramClient, RateLimitExceeded
from ..store import CampaignStore, parse_dt, to_iso, utcnow

STATUSES = ("new", "downloaded", "in_production", "posted", "skipped")
NOTE_MAX = 300
NOTE_WINDOW = timedelta(minutes=2)  # a text right after the share is its note
CONVERSATIONS = 50  # newest first; a pinned friend's new message moves theirs to the top
MESSAGES = 20  # Meta: details only for the 20 most recent messages
AGENT_KEYS = ("id", "status", "reel_url", "sender_username", "sender_note", "received_at",
              "skip_reason")
_USERNAME = re.compile(r"[a-z0-9._]{1,30}")
# A shared feed post or a picture: never a Reel.
_NOT_A_REEL = re.compile(r"https://(?:www\.)?instagram\.com/p/"
                         r"|[.](?:jpe?g|png|webp|heic)(?:[?#]|$)", re.IGNORECASE)


# ---------------------------------------------------------------- pinned accounts
def normalise(username: str) -> str:
    """`@Name ` -> `name`; ValueError when it is not an Instagram username."""
    value = (username or "").strip().lstrip("@").lower()
    if not _USERNAME.fullmatch(value):
        raise ValueError(f"not an Instagram username: {username!r}")
    return value


def pin_account(store: CampaignStore, username: str,
                note: Optional[str] = None) -> Dict[str, Any]:
    """Pin an account; pinning it again returns it, with the note replaced when given."""
    username, note = normalise(username), (note or "").strip() or None
    with store._tx() as c:
        c.execute("INSERT INTO pinned_accounts (username, note, created_at) VALUES (?,?,?)"
                  " ON CONFLICT(username) DO UPDATE SET note=COALESCE(excluded.note, note)",
                  (username, note, to_iso(utcnow())))
        return dict(c.execute("SELECT * FROM pinned_accounts WHERE username=?",
                              (username,)).fetchone())


def unpin_account(store: CampaignStore, account_id: int) -> Dict[str, Any]:
    """Unpin and return the row (its picks stay); KeyError when there is none."""
    row = store._get("pinned_accounts", account_id)
    with store._tx() as c:
        c.execute("DELETE FROM pinned_accounts WHERE id=?", (account_id,))
    return row


def list_pinned(store: CampaignStore) -> List[Dict[str, Any]]:
    return store._select("SELECT * FROM pinned_accounts", {}, "username", 10_000)


# ---------------------------------------------------------------- picks
def list_picks(store: CampaignStore, status: Optional[str] = "new",
               limit: int = 100, *, newest: bool = False) -> List[Dict[str, Any]]:
    """Oldest first (picks are made in the order they came), or the newest first for the
    owner's list; all when status is None."""
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    order = "received_at DESC, id DESC" if newest else "received_at, id"
    return store._select("SELECT * FROM dm_picks", {"status": status}, order, limit)


def agent_view(pick: Dict[str, Any]) -> Dict[str, Any]:
    """What the agent sees of a pick: no message ids, nothing else from the DM."""
    return {k: pick[k] for k in AGENT_KEYS}


def for_agent(store: CampaignStore, status: Optional[str] = "new",
              limit: int = 100) -> List[Dict[str, Any]]:
    return [agent_view(p) for p in list_picks(store, status, limit)]


def mark_pick(store: CampaignStore, pick_id: int, status: str,
              reason: Optional[str] = None) -> Dict[str, Any]:
    """Move a pick; skipped needs a reason (kept), any other status clears it."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    reason = (reason or "").strip()[:NOTE_MAX] or None
    if status == "skipped" and not reason:
        raise ValueError("say why the pick is skipped")
    return store._update("dm_picks", ("status", "skip_reason"), pick_id,
                         {"status": status, "skip_reason": reason if status == "skipped"
                          else None})


def mark_posted(store: CampaignStore, asset_id: int) -> int:
    """The asset was published: picks of its idea's source that are being made (downloaded,
    in_production) become posted. Returns how many moved."""
    with store._tx() as c:
        return c.execute(
            "UPDATE dm_picks SET status='posted', skip_reason=NULL, updated_at=?"
            " WHERE status IN ('downloaded','in_production') AND source_id IN"
            " (SELECT i.source_id FROM assets a JOIN ideas i ON i.id = a.idea_id"
            " WHERE a.id = ?)", (to_iso(utcnow()), asset_id)).rowcount


# ---------------------------------------------------------------- polling
def _reel(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The first shared item that may be a Reel: {url, id}, or None."""
    for share in (msg.get("shares") or {}).get("data", []):
        url = share.get("link") or share.get("url")
        if (url and url.startswith("https://") and not _NOT_A_REEL.search(url)
                and share.get("type") not in ("post", "ig_post")):
            return {"url": url, "id": share.get("id")}
    return None


def _note(msgs: List[Dict[str, Any]], i: int) -> Optional[str]:
    """The share's own text, else the sender's next text message within NOTE_WINDOW."""
    msg, sender = msgs[i], msgs[i]["from"].get("id")
    text = (msg.get("message") or "").strip()
    if not text:
        until = parse_dt(msg["created_time"]) + NOTE_WINDOW
        nxt = next((m for m in msgs[i + 1:] if (m.get("from") or {}).get("id") == sender),
                   None)
        if nxt and not _reel(nxt) and parse_dt(nxt["created_time"]) <= until:
            text = (nxt.get("message") or "").strip()
    return text[:NOTE_MAX] or None


def _match(pinned: List[Dict[str, Any]], who: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name, uid = (who.get("username") or "").lower(), who.get("id")
    return next((p for p in pinned if p["username"] == name
                 or (uid and p["ig_user_id"] == uid)), None)


async def poll_dm_picks(client: Optional[InstagramClient], store: CampaignStore, *,
                        budget_left: Callable[[], bool]) -> Dict[str, Any]:
    """Record a pick for every Reel a pinned account shared in the brand account's recent
    DMs (idempotent per message id). Returns {conversations, picks, stopped}; stopped: null,
    "request_budget" or "rate_limited". No client (setup mode) or no pins: no call."""
    pinned = list_pinned(store)
    if client is None or not pinned:
        return {"skipped": "not configured" if client is None else "no pinned accounts"}
    out: Dict[str, Any] = {"conversations": 0, "picks": 0, "stopped": None}
    try:
        if not budget_left():
            out["stopped"] = "request_budget"
            return out
        for conv in await client.get_conversations(limit=CONVERSATIONS):
            people = [(p, who) for who in (conv.get("participants") or {}).get("data", [])
                      if (p := _match(pinned, who))]
            if not people:
                continue  # never opened: not a pinned account's conversation
            for p, who in people:
                if not p["ig_user_id"] and who.get("id"):
                    with store._tx() as c:
                        c.execute("UPDATE pinned_accounts SET ig_user_id=? WHERE id=?",
                                  (who["id"], p["id"]))
                    p["ig_user_id"] = who["id"]
            if not budget_left():
                out["stopped"] = "request_budget"
                break
            out["conversations"] += 1
            msgs = sorted(await client.get_conversation_messages(conv["id"], limit=MESSAGES),
                          key=lambda m: parse_dt(m["created_time"]))
            for i, msg in enumerate(msgs):
                p, reel = _match(pinned, msg.get("from") or {}), _reel(msg)
                if not p or not reel or not msg.get("id"):
                    continue
                now = to_iso(utcnow())
                with store._tx() as c:
                    out["picks"] += c.execute(
                        "INSERT INTO dm_picks (message_id, pinned_account_id, sender_username,"
                        " reel_url, reel_media_id, sender_note, received_at, created_at,"
                        " updated_at) VALUES (?,?,?,?,?,?,?,?,?)"
                        " ON CONFLICT(message_id) DO NOTHING",
                        (msg["id"], p["id"], p["username"], reel["url"], reel["id"],
                         _note(msgs, i), to_iso(parse_dt(msg["created_time"])), now, now)
                    ).rowcount
    except RateLimitExceeded:
        out["stopped"] = "rate_limited"
    return out
