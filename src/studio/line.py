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
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import InstagramMCPSettings
from ..store import CampaignStore, parse_iso, to_iso, utcnow

KINDS = ("render", "film")
# Old rows have no line_pos (NULL = 0): they keep the order they had (oldest id / oldest
# scheduled first). Ties between a render and a film queued the same second: renders first.
_WAITING = (
    "SELECT 'render' AS kind, id, COALESCE(line_pos, 0) AS pos, created_at AS arrived,"
    " not_before FROM render_jobs WHERE state = 'queued'"
    " UNION ALL SELECT 'film', id, COALESCE(line_pos, 0), COALESCE(scheduled_at, created_at),"
    " not_before FROM work_orders WHERE status = 'scheduled' AND style LIKE 'lemo:%'"
    " ORDER BY pos, arrived, kind DESC, id")
_TABLE = {"render": ("render_jobs", "state = 'queued'"),
          "film": ("work_orders", "status = 'scheduled' AND style LIKE 'lemo:%'")}
_STATE = {"running": "est en cours", "done": "est terminé", "failed": "a échoué"}


def waiting(store: CampaignStore) -> List[Dict[str, Any]]:
    """Every waiting item, in line order: {kind render | film, id (job / order), pos,
    arrived, not_before}."""
    with store._tx() as c:
        return [dict(r) for r in c.execute(_WAITING)]


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
    while len(out) < n and (first := head(items, now, films=films)) and             first["kind"] == "render":
        out.append(first["id"])
        items = items[items.index(first) + 1:]  # the ones skipped stay skipped at `now`
    return out


def _set(store: CampaignStore, kind: str, item_id: int, sets: str, args: tuple) -> None:
    """UPDATE the waiting item, or raise: KeyError (no such row), ValueError (it is not
    waiting any more)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    table, still = _TABLE[kind]
    with store._tx() as c:
        if c.execute(f"UPDATE {table} SET {sets}, updated_at = ? WHERE id = ? AND {still}",
                     (*args, to_iso(utcnow()), item_id)).rowcount:
            return
        row = c.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(f"No {table.removesuffix('s')} with id {item_id}")
    if kind == "render":
        raise ValueError(f"Ce rendu {_STATE.get(row['state'], row['state'])} : seul un rendu"
                         " en attente peut être lancé ou minuté.")
    raise ValueError(f"Cette commande n'attend pas dans la file des films (statut"
                     f" {row['status']}) : seul un film en attente peut être lancé ou minuté.")


def start_now(store: CampaignStore, kind: str, item_id: int) -> Dict[str, Any]:
    """« Lancer maintenant »: the item goes ahead of every waiting one (its timer is
    cleared); the running item is never stopped."""
    with store._tx() as c:
        first = c.execute("SELECT MIN(p) FROM (SELECT MIN(line_pos) AS p FROM render_jobs"
                          " UNION ALL SELECT MIN(line_pos) FROM work_orders)").fetchone()[0]
    pos = min(first or 0, 0) - 1
    _set(store, kind, item_id, "line_pos = ?, not_before = NULL", (pos,))
    return {"kind": kind, "id": item_id, "line_pos": pos}


def set_timer(store: CampaignStore, kind: str, item_id: int, at: Optional[datetime]
              ) -> Dict[str, Any]:
    """« Minuteur »: the item is skipped until `at` (stored UTC); None clears the timer."""
    if at is not None and at.tzinfo is None:
        raise ValueError("the timer needs a time zone (send it as UTC ISO)")
    nb = to_iso(at) if at else None
    _set(store, kind, item_id, "not_before = ?", (nb,))
    return {"kind": kind, "id": item_id, "not_before": nb}
