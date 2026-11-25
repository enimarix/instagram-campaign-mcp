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
from typing import Any, Callable, Dict, List, Optional, Set

from ..instagram_client import InstagramAPIError, InstagramClient, RateLimitExceeded
from ..store import CampaignStore, parse_dt, to_iso, utcnow
from .downloader import _same_post

STATUSES = ("new", "downloaded", "in_production", "posted", "skipped")
NOTE_MAX = 300
NOTE_WINDOW = timedelta(minutes=2)  # a text just after (or before) the share is its note
CONVERSATIONS = 50  # newest first; a pinned friend's new message moves theirs to the top
MESSAGES = 20  # Meta: details only for the 20 most recent messages
POLLED_KEY = "dm_picks_polled_at"  # worker_state: when the last full poll started
# worker_state {at, conversations}: a poll whose 20 messages all came after the last full
# poll (the worker was off): older shares may be lost, the owner should look at the DMs
GAP_KEY = "dm_picks_gap"
AGENT_KEYS = ("id", "status", "reel_url", "sender_username", "sender_note", "received_at",
              "skip_reason")
_USERNAME = re.compile(r"[a-z0-9._]{1,30}")
# a _select filter key: 1 = the pick is a work order
_ORDERED = "(id IN (SELECT pick_id FROM work_orders WHERE pick_id IS NOT NULL))"
OWN_MEDIA_PAGE = 100  # our newest media, asked at most once per poll
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
               limit: int = 100, *, newest: bool = False,
               ordered: Optional[bool] = None) -> List[Dict[str, Any]]:
    """Oldest first (picks are made in the order they came), or the newest first for the
    owner's list; all when status is None. ordered: only picks that are (True) or are not
    (False) a work order (136); None: both."""
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    order = "received_at DESC, id DESC" if newest else "received_at, id"
    return store._select("SELECT * FROM dm_picks", {"status": status, _ORDERED: ordered},
                         order, limit)


def agent_view(pick: Dict[str, Any]) -> Dict[str, Any]:
    """What the agent sees of a pick: no message ids, nothing else from the DM."""
    return {k: pick[k] for k in AGENT_KEYS}


def for_agent(store: CampaignStore, status: Optional[str] = "new",
              limit: int = 100) -> List[Dict[str, Any]]:
    """Picks that are not work orders: since 136 the agent makes every new pick as its
    order (work_orders.py), so only picks from before that would show here."""
    return [agent_view(p) for p in list_picks(store, status, limit, ordered=False)]


def mark_pick(store: CampaignStore, pick_id: int, status: str,
              reason: Optional[str] = None) -> Dict[str, Any]:
    """Move a pick; skipped needs a reason (kept), any other status clears it. Skipping a
    pick whose work order is still open skips the order (work_orders.skip_order, which
    skips the pick): the owner's « Écarter » stops the work."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    reason = (reason or "").strip()[:NOTE_MAX] or None
    if status == "skipped" and not reason:
        raise ValueError("say why the pick is skipped")
    if status == "skipped":
        with store._tx() as c:
            order = c.execute("SELECT id FROM work_orders WHERE pick_id=? AND status IN"
                              " ('needs_instruction','scheduled','in_production')",
                              (pick_id,)).fetchone()
        if order:
            from . import work_orders  # here: work_orders imports this module

            work_orders.skip_order(store, order[0], reason)
            return store._get("dm_picks", pick_id)
    return store._update("dm_picks", ("status", "skip_reason"), pick_id,
                         {"status": status, "skip_reason": reason if status == "skipped"
                          else None})


def mark_posted(store: CampaignStore, asset_id: int) -> int:
    """The asset was published: picks being made (downloaded, in_production) of its idea's
    source, or whose work order made its idea (an owner or inspired idea has no source),
    become posted. Returns how many moved."""
    with store._tx() as c:
        return c.execute(
            "UPDATE dm_picks SET status='posted', skip_reason=NULL, updated_at=?"
            " WHERE status IN ('downloaded','in_production') AND (source_id IN"
            " (SELECT i.source_id FROM assets a JOIN ideas i ON i.id = a.idea_id"
            " WHERE a.id = ?) OR id IN (SELECT w.pick_id FROM work_orders w JOIN assets a"
            " ON a.idea_id = w.idea_id WHERE a.id = ?))",
            (to_iso(utcnow()), asset_id, asset_id)).rowcount


# ---------------------------------------------------------------- polling
def _reel(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The first shared item that may be a Reel: {url, id}, or None."""
    for share in (msg.get("shares") or {}).get("data", []):
        url = share.get("link") or share.get("url")
        if (url and url.startswith("https://") and not _NOT_A_REEL.search(url)
                and share.get("type") not in ("post", "ig_post")):
            return {"url": url, "id": share.get("id")}
    return None


def _text(msg: Dict[str, Any]) -> str:
    return (msg.get("message") or "").strip()


def _neighbour(msgs: List[Dict[str, Any]], i: int, step: int) -> Optional[int]:
    """The index of the sender's own message right after (step 1) or before (-1) msgs[i]."""
    sender, j = (msgs[i].get("from") or {}).get("id"), i + step
    while 0 <= j < len(msgs) and (msgs[j].get("from") or {}).get("id") != sender:
        j += step
    return j if 0 <= j < len(msgs) else None


def _beside(msgs: List[Dict[str, Any]], i: int, step: int) -> Optional[int]:
    """The sender's neighbour of msgs[i] when it is a text (not a Reel) within NOTE_WINDOW
    of it, else None. Being the sender's very next one, no other share of theirs sits
    between."""
    j = _neighbour(msgs, i, step)
    if j is None or _reel(msgs[j]) or not _text(msgs[j]):
        return None
    apart = abs(parse_dt(msgs[j]["created_time"]) - parse_dt(msgs[i]["created_time"]))
    return j if apart <= NOTE_WINDOW else None


def _note_at(msgs: List[Dict[str, Any]], i: int) -> Optional[int]:
    """Where the note of the share msgs[i] (no text of its own) is: the sender's text right
    after it, else the one right before it (the owner may type first, then share) unless
    that text is already the note of the share before it."""
    after = _beside(msgs, i, 1)
    if after is not None:
        return after
    before = _beside(msgs, i, -1)
    if before is None:
        return None
    prev = _neighbour(msgs, before, -1)
    taken = (prev is not None and _reel(msgs[prev]) and not _text(msgs[prev])
             and _beside(msgs, prev, 1) == before)
    return None if taken else before


def _note(msgs: List[Dict[str, Any]], i: int) -> Optional[str]:
    """The share's own text, else the sender's text just after it, else just before it
    (_note_at). msgs: oldest first."""
    text = _text(msgs[i])
    if not text and (j := _note_at(msgs, i)) is not None:
        text = _text(msgs[j])
    return text[:NOTE_MAX] or None


def _match(pinned: List[Dict[str, Any]], who: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name, uid = (who.get("username") or "").lower(), who.get("id")
    return next((p for p in pinned if p["username"] == name
                 or (uid and p["ig_user_id"] == uid)), None)


async def _own_reel(client: InstagramClient, store: CampaignStore, url: str,
                   budget_left: Callable[[], bool], cache: Dict[str, Set[str]]) -> bool:
    """The Reel is one of ours: its permalink is one we published (scheduled_posts, insight
    snapshots) or among our OWN_MEDIA_PAGE newest media (one Graph call per poll, when the
    budget allows). Not a permalink, or not found: someone else's."""
    try:
        post = set(_same_post(url))
    except ValueError:
        return False
    if "ours" not in cache:
        with store._tx() as c:
            links = [r[0] for r in c.execute(
                "SELECT permalink FROM scheduled_posts WHERE permalink IS NOT NULL UNION"
                " SELECT permalink FROM insight_snapshots WHERE permalink IS NOT NULL")]
        if budget_left():
            try:
                links += [m.get("permalink") for m in
                          (await client.get_media_posts(limit=OWN_MEDIA_PAGE))["posts"]]
            except RateLimitExceeded:
                raise
            except InstagramAPIError:
                pass  # e.g. no permission: only what we published here counts
        cache["ours"] = {p.rstrip("/") + "/" for p in links if p}
    return bool(post & cache["ours"])


async def poll_dm_picks(client: Optional[InstagramClient], store: CampaignStore, *,
                        budget_left: Callable[[], bool]) -> Dict[str, Any]:
    """Record a pick for every Reel a pinned account shared in the brand account's recent
    DMs (idempotent per message id), each with its work order (136: scheduled at once when
    the DM has a note, else waiting for the owner's instruction; own_reel when the Reel is
    ours). A pick stored without a note gets it on a later poll while its order still
    waits (141). Returns {conversations, picks, stopped}; stopped: null, "request_budget" or
    "rate_limited". No client (setup mode) or no pins: no call."""
    from . import work_orders  # here: work_orders imports this module

    pinned = list_pinned(store)
    own: Dict[str, Set[str]] = {}
    if client is None or not pinned:
        return {"skipped": "not configured" if client is None else "no pinned accounts"}
    out: Dict[str, Any] = {"conversations": 0, "picks": 0, "stopped": None}
    last, started = store.get_state(POLLED_KEY), to_iso(utcnow())
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
            # The API lists the newest first, and created_time is to the second: reversed
            # then a stable sort, a share and its text sent in the same second keep their
            # real order (141).
            msgs = sorted(reversed(await client.get_conversation_messages(
                conv["id"], limit=MESSAGES)), key=lambda m: parse_dt(m["created_time"]))
            # all 20 came after the last full poll: older ones since then are out of reach
            if (last and len(msgs) >= MESSAGES
                    and parse_dt(msgs[0]["created_time"]) > parse_dt(last)):
                out["maybe_missed"] = out.get("maybe_missed", 0) + 1
            for i, msg in enumerate(msgs):
                p, reel = _match(pinned, msg.get("from") or {}), _reel(msg)
                if not p or not reel or not msg.get("id"):
                    continue
                with store._tx() as c:
                    known = c.execute("SELECT id FROM dm_picks WHERE message_id=?",
                                      (msg["id"],)).fetchone()
                if known:  # its note may have come after an earlier poll stored it
                    if note := _note(msgs, i):
                        with store._tx() as c:
                            work_orders.late_note(c, known[0], note, to_iso(utcnow()))
                    continue
                own_reel = await _own_reel(client, store, reel["url"], budget_left, own)
                note, now = _note(msgs, i), to_iso(utcnow())
                with store._tx() as c:
                    cur = c.execute(
                        "INSERT INTO dm_picks (message_id, pinned_account_id, sender_username,"
                        " reel_url, reel_media_id, sender_note, received_at, created_at,"
                        " updated_at) VALUES (?,?,?,?,?,?,?,?,?)"
                        " ON CONFLICT(message_id) DO NOTHING",
                        (msg["id"], p["id"], p["username"], reel["url"], reel["id"],
                         note, to_iso(parse_dt(msg["created_time"])), now, now))
                    if cur.rowcount:  # another poll may have stored it meanwhile
                        work_orders.add_for_pick(c, cur.lastrowid, note, own_reel, now)
                    out["picks"] += cur.rowcount
    except RateLimitExceeded:
        out["stopped"] = "rate_limited"
    if out.get("maybe_missed"):  # for alerts to show (studio/alerts.py reads worker_state)
        store.set_state(GAP_KEY, {"at": started, "conversations": out["maybe_missed"]})
    if out["stopped"] is None:
        store.set_state(POLLED_KEY, started)
    return out
