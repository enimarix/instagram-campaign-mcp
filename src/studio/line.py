"""
The heavy line (step 186): renders and Lemo films wait in one line, first in, first out.

An item's place is its arrival (a render job's created_at, a film order's scheduled_at),
unless the owner pressed « start now »: line_pos < 0 puts it ahead of every waiting item
(the latest press first), never stopping the running one. A timer (not_before, UTC) skips
the item until then without blocking the ones behind it. next_in_line() is the one place
that decides the head: the render loop claims it when it is a render (renders_next: as many as it has free
slots, in line order, worker.render_loop),
the catch-up starts it when it is a film (schedule.film_run), and the Planning page lists
the line by calling head() again on a simulated clock (planning.build_planning).

Films are skipped (not blocking the renders behind them) while the film runner could not
take one: an agent run (a film included) is running, today's LEMO_FILMS_PER_DAY are made,
or the agent preflight failed less than ORDER_RETRY ago. Agent runs themselves are not in
the line: they stay gated as before (schedule.busy).

The owner's controls (187): move() swaps an item with its neighbour (the whole line then
gets line_pos 1..n, so new arrivals, NULL, still go behind it and « start now », < 0, ahead);
hold() is a timer with no end (not_before = HELD) until released; remove() takes a waiting
item out for good (the page's 5 s undo sends nothing before it ends, like the Inbox): a
render job fails with REMOVED and its asset is archived, an order is skipped with REMOVED.
pause() stops everything heavy from starting (worker_state PAUSE_KEY): the render loop
claims nothing, the catch-up and `agent run-due` start nothing; what runs finishes. A
running film's own render (film_renders: the film waits for it) is part of what runs: the
pause lets it through, and hold / timer / remove refuse it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import InstagramMCPSettings
from ..store import CampaignStore, parse_iso, to_iso, utcnow
from . import work_orders
from .assets import transition

KINDS = ("render", "film")
REMOVABLE = (*KINDS, "order")  # order: an owner order / change request for the light run
HELD = "9999-12-31T00:00:00+00:00"  # not_before of a held item: a timer with no end
REMOVED = "retiré du planning"
PAUSE_KEY = "studio_paused"  # worker_state: since when (UTC ISO), None = not paused
# Old rows have no line_pos (pos 0): they keep the order they had (oldest id / oldest
# scheduled first), behind « start now » (< 0) and the placed ones (move: 1..n). Ties
# between a render and a film queued the same second: renders first. A Lemo style is the
# case-sensitive prefix lemo.is_lemo tests (LIKE would ignore the case).
_LEMO = "substr(style, 1, 5) = 'lemo:'"
_WAITING = (
    "SELECT kind, id, COALESCE(line_pos, 0) AS pos, arrived, not_before FROM ("
    "SELECT 'render' AS kind, id, line_pos, created_at AS arrived, not_before"
    " FROM render_jobs WHERE state = 'queued'"
    " UNION ALL SELECT 'film', id, line_pos, COALESCE(scheduled_at, created_at), not_before"
    f" FROM work_orders WHERE status = 'scheduled' AND {_LEMO})"
    " ORDER BY line_pos IS NULL, line_pos, arrived, kind DESC, id")
_TABLE = {"render": ("render_jobs", "state = 'queued'"),
          "film": ("work_orders", f"status = 'scheduled' AND {_LEMO}")}
# A running film's own render (lemo.register_film; film._wait_render waits for it): its
# idea's Lemo order is in_production.
_FILM_RENDERS = ("SELECT j.id FROM render_jobs j JOIN assets a ON a.id = j.asset_id"
                 " JOIN work_orders w ON w.idea_id = a.idea_id WHERE j.state = 'queued'"
                 " AND w.status = 'in_production' AND substr(w.style, 1, 5) = 'lemo:'"
                 " ORDER BY j.id")
FILM_RENDER = ("Ce rendu est celui d'un film en cours, qui l'attend : il ne peut être ni mis"
               " en pause, ni minuté, ni retiré.")
_STATE = {"running": "est en cours", "done": "est terminé", "failed": "a échoué"}


def waiting(store: CampaignStore) -> List[Dict[str, Any]]:
    """Every waiting item, in line order: {kind render | film, id (job / order), pos,
    arrived, not_before}."""
    with store._tx() as c:
        return [dict(r) for r in c.execute(_WAITING)]


def film_renders(store: CampaignStore) -> List[int]:
    """The queued render jobs a running film waits for (module doc)."""
    with store._tx() as c:
        return [r[0] for r in c.execute(_FILM_RENDERS)]


def _not_film_render(store: CampaignStore, kind: str, item_id: int) -> None:
    if kind == "render" and item_id in film_renders(store):
        raise ValueError(FILM_RENDER)


def head(items: List[Dict[str, Any]], now: datetime, *, films: bool = True
         ) -> Optional[Dict[str, Any]]:
    """The first item whose timer is past (films only when `films`)."""
    return next((i for i in items if (films or i["kind"] != "film")
                 and not (i["not_before"] and parse_iso(i["not_before"]) > now)), None)


def films_ready(store: CampaignStore, settings: InstagramMCPSettings, now: datetime) -> bool:
    """Whether the film runner could take a film now (see module doc)."""
    from ..agent import film, schedule  # here: schedule imports this module

    failed = store.get_state("order_preflight_failed_at")
    return (not store.running_agent_runs(limit=1)
            and film.films_today(store, settings, now) < settings.lemo_films_per_day
            and not (failed and now - parse_iso(failed) < schedule.ORDER_RETRY))


def next_in_line(store: CampaignStore, settings: InstagramMCPSettings, now: datetime
                 ) -> Optional[Dict[str, Any]]:
    """The head of the line: what starts next once nothing heavy runs, or None."""
    return head(waiting(store), now, films=films_ready(store, settings, now))


def renders_next(store: CampaignStore, settings: InstagramMCPSettings, now: datetime,
                 n: int) -> List[int]:
    """The render loop's claim: up to `n` render job ids, in line order, head() after
    head(); stops at a film at the head (it goes first, the renders behind it wait)."""
    items, films, out = waiting(store), films_ready(store, settings, now), []
    while len(out) < n and (first := head(items, now, films=films)) and first["kind"] == "render":
        out.append(first["id"])
        items = items[items.index(first) + 1:]  # the ones skipped stay skipped at `now`
    return out


def _set(store: CampaignStore, kind: str, item_id: int, sets: str, args: tuple) -> None:
    """UPDATE the waiting item, or raise: KeyError (no such row), ValueError (it is not
    waiting any more)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    with store._tx() as c:
        if _update(c, kind, item_id, sets, args):
            return
    _refuse(store, kind, item_id)


def _update(c: Any, kind: str, item_id: int, sets: str, args: tuple) -> int:
    table, still = _TABLE[kind]
    return c.execute(f"UPDATE {table} SET {sets}, updated_at = ? WHERE id = ? AND {still}",
                     (*args, to_iso(utcnow()), item_id)).rowcount


def _refuse(store: CampaignStore, kind: str, item_id: int) -> None:
    """Raise why the item is not waiting: KeyError (no such row), else ValueError."""
    table = _TABLE[kind][0]
    with store._tx() as c:
        row = c.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(f"No {table.removesuffix('s')} with id {item_id}")
    if kind == "render":
        raise ValueError(f"Ce rendu {_STATE.get(row['state'], row['state'])} : seul un rendu"
                         " en attente peut être changé.")
    raise ValueError(f"Cette commande n'attend pas dans la file des films (statut"
                     f" {row['status']}) : seul un film en attente peut être changé.")


def start_now(store: CampaignStore, kind: str, item_id: int) -> Dict[str, Any]:
    """« Lancer maintenant »: the item goes ahead of every waiting one (its timer is
    cleared); the running item is never stopped."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    with store.immediate() as c:  # read-then-write: two presses never get the same place
        first = c.execute("SELECT MIN(p) FROM (SELECT MIN(line_pos) AS p FROM render_jobs"
                          " UNION ALL SELECT MIN(line_pos) FROM work_orders)").fetchone()[0]
        pos = min(first or 0, 0) - 1
        done = _update(c, kind, item_id, "line_pos = ?, not_before = NULL", (pos,))
    if not done:
        _refuse(store, kind, item_id)
    return {"kind": kind, "id": item_id, "line_pos": pos}


def set_timer(store: CampaignStore, kind: str, item_id: int, at: Optional[datetime]
              ) -> Dict[str, Any]:
    """« Minuteur »: the item is skipped until `at` (stored UTC); None clears the timer."""
    if at is not None and at.tzinfo is None:
        raise ValueError("the timer needs a time zone (send it as UTC ISO)")
    nb = to_iso(at) if at else None
    if nb:
        _not_film_render(store, kind, item_id)
    _set(store, kind, item_id, "not_before = ?", (nb,))
    return {"kind": kind, "id": item_id, "not_before": nb}


def hold(store: CampaignStore, kind: str, item_id: int, held: bool) -> Dict[str, Any]:
    """« Mettre en pause » / « Reprendre »: a held item is skipped like a timer with no
    end (it blocks nothing behind it); releasing it clears its timer too."""
    if held:
        _not_film_render(store, kind, item_id)
    _set(store, kind, item_id, "not_before = ?", (HELD if held else None,))
    return {"kind": kind, "id": item_id, "held": held}


def move(store: CampaignStore, kind: str, item_id: int, by: int) -> Dict[str, Any]:
    """« Monter » (by -1) / « Descendre » (+1): swap the item with its neighbour in the
    line (held ones are passed over), then write the whole line's order as line_pos 1..n."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if by not in (-1, 1):
        raise ValueError("by must be -1 (up) or 1 (down)")
    with store.immediate() as c:  # read-then-write: a start-now meanwhile is never lost
        items = [dict(r) for r in c.execute(_WAITING)]
        me = next((n for n, i in enumerate(items) if (i["kind"], i["id"]) == (kind, item_id)),
                  None)
        to = -1 if me is None else me + by
        while 0 <= to < len(items) and items[to]["not_before"] == HELD:
            to += by
        if me is not None and 0 <= to < len(items):
            items[me], items[to] = items[to], items[me]
            for pos, i in enumerate(items, 1):
                _update(c, i["kind"], i["id"], "line_pos = ?", (pos,))
    if me is None:
        _refuse(store, kind, item_id)
    if not 0 <= to < len(items):
        raise ValueError("Déjà en tête de la file." if by < 0 else "Déjà en bout de file.")
    return {"kind": kind, "id": item_id, "line_pos": to + 1}


def remove(store: CampaignStore, kind: str, item_id: int) -> Dict[str, Any]:
    """« Retirer »: a waiting render job fails with REMOVED (the claim never takes it) and
    its asset is archived unless another job of it is queued or running (the order in
    production for its idea is then skipped, unless another video of it lives); a waiting
    film (kind film) or an owner order / change request still waiting for the light run (kind
    order) is skipped with REMOVED. Running or done, or a running film's own render: refused."""
    if kind not in REMOVABLE:
        raise ValueError(f"kind must be one of {', '.join(REMOVABLE)}")
    if kind != "render":
        status = work_orders.get_order(store, item_id)["status"]
        if status != "scheduled":
            raise ValueError(f"Cette commande ne peut plus être retirée (statut {status}) :"
                             " seule une commande en attente peut l'être.")
        work_orders.skip_order(store, item_id, REMOVED)
        return {"kind": kind, "id": item_id, "removed": True}
    _not_film_render(store, kind, item_id)
    now = to_iso(utcnow())
    with store._tx() as c:
        done = c.execute("UPDATE render_jobs SET state = 'failed', failure = ?, finished_at = ?,"
                         " updated_at = ? WHERE id = ? AND state = 'queued'",
                         (REMOVED, now, now, item_id)).rowcount
    if not done:
        _refuse(store, kind, item_id)
    asset_id = store.get_render_job(item_id)["asset_id"]
    with store._tx() as c:
        live = c.execute("SELECT 1 FROM render_jobs WHERE asset_id = ? AND state IN"
                         " ('queued', 'running')", (asset_id,)).fetchone()
    if live or store.get_asset(asset_id)["status"] != "rendering":
        return {"kind": kind, "id": item_id, "removed": True}
    skip_orders(store, transition(store, asset_id, "archived", actor="owner")["idea_id"])
    return {"kind": kind, "id": item_id, "removed": True}


def skip_orders(store: CampaignStore, idea_id: int) -> None:
    """A removed video's idea: the order in production for it is skipped with REMOVED,
    unless another video of it lives (remove; planned.remove, 188b)."""
    with store._tx() as c:
        orders = [r[0] for r in c.execute(
            "SELECT id FROM work_orders WHERE idea_id = ? AND status = 'in_production'"
            " AND NOT EXISTS (SELECT 1 FROM assets WHERE idea_id = ? AND status NOT IN"
            " ('archived', 'failed'))", (idea_id, idea_id))]
    for order_id in orders:
        work_orders.skip_order(store, order_id, REMOVED)


def paused(store: CampaignStore) -> Optional[str]:
    """Since when the owner paused the studio (UTC ISO), else None."""
    return store.get_state(PAUSE_KEY)


def pause(store: CampaignStore, on: bool) -> Dict[str, Any]:
    """« Tout mettre en pause »: nothing heavy starts until it is off (see module doc)."""
    since = (paused(store) or to_iso(utcnow())) if on else None
    store.set_state(PAUSE_KEY, since)
    return {"paused": since}
