"""
The Planning page (step 185): what the studio makes next and when, read-only.

build_planning(store, settings, now) -> {now, items} lists one chain, in the order the
worker really takes the work today:

- running: the render in progress (render_jobs, one at a time) and the agent run going;
- next: the queued renders, oldest id first (the render loop's claim order), then what the
  worker's catch-up starts once nothing is busy, in schedule.CATCH_UP_ORDER: a due
  playbook, the oldest Lemo films (LEMO_FILMS_PER_DAY), the light run for the owner's
  orders and change requests (schedule.order_wait: grace, daily cap...) followed by each
  of their renders; then the orders that wait for the owner's instruction (no time);
- planned: the scheduled AI runs of the next 24 h as placeholders; the producing run says
  what it picks up first and how many places stay for Claude's own ideas.

Every time is an estimate (`estimated: true`): each item starts when the one before is
ready. A duration is the median of the recent real ones (render_jobs.render_ms per engine,
agent_runs per playbook), else the constants below (docs/DECISIONS.md).
ponytail: one render at a time (RENDER_CONCURRENCY=1 here); due_runs may close a crashed
run's row on the way, as the worker does every minute.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from statistics import median
from typing import Any, Dict, List, Optional

from ..agent import film, packet, schedule
from ..config import InstagramMCPSettings
from ..learning.learnings import list_revision_requests
from ..store import CampaignStore, parse_iso, to_iso
from . import cinematic, dm_picks, lemo, macro3d, sitcom, voices, work_orders

# Fallback seconds per engine (DECISIONS: Remotion ~0.4 min per 30 s video; the 8-shot
# Blender proof 13.1 min; Macro3D's first Blender plates 12-15 min). ponytail: ffmpeg's
# remix render is a guess.
ENGINE_S = {"remotion": 24.0, "blender": 786.0, "macro3d": 900.0, "ffmpeg": 60.0}
RUN_S = 15 * 60.0  # an agent run with no finished run to measure (guess)
HORIZON = timedelta(hours=24)
SAMPLES = 100  # recent finished jobs / runs the medians look at
TEMPLATE_ENGINES = {cinematic.TEMPLATE: "blender", sitcom.TEMPLATE: "blender",
                    macro3d.TEMPLATE: "macro3d"}
STYLE_ENGINES = {cinematic.STYLE: "blender", "sitcom": "blender", "macro3d": "macro3d"}
_JOBS = ("SELECT j.id, j.asset_id, j.state, j.progress, j.started_at, a.recipe, a.caption,"
         " i.hook, i.style, w.id AS order_id, w.origin, w.pick_id FROM render_jobs j"
         " JOIN assets a ON a.id = j.asset_id JOIN ideas i ON i.id = a.idea_id"
         " LEFT JOIN work_orders w ON w.id ="
         " (SELECT MAX(id) FROM work_orders WHERE idea_id = a.idea_id)"
         " WHERE j.state IN ('queued', 'running') ORDER BY j.state = 'queued', j.id")
_DONE = ("SELECT a.recipe, j.render_ms FROM render_jobs j JOIN assets a ON a.id = j.asset_id"
         " WHERE j.state = 'done' AND j.render_ms IS NOT NULL ORDER BY j.id DESC LIMIT ?")


def _engine(recipe: Any) -> str:
    recipe = json.loads(recipe) if isinstance(recipe, str) else (recipe or {})
    if recipe.get("kind") != "motion":
        return "ffmpeg"
    return TEMPLATE_ENGINES.get(recipe.get("template"), "remotion")


def style_engine(style: Optional[str]) -> str:
    if lemo.is_lemo(style):
        return "film"
    return STYLE_ENGINES.get(style or "", "remotion")


def _render_s(store: CampaignStore) -> Dict[str, float]:
    """Seconds per engine: the median of the recent real renders, else ENGINE_S."""
    with store._tx() as c:
        rows = c.execute(_DONE, (SAMPLES,)).fetchall()
    seen: Dict[str, List[float]] = {}
    for r in rows:
        seen.setdefault(_engine(r["recipe"]), []).append(r["render_ms"] / 1000)
    return {**ENGINE_S, **{e: median(v) for e, v in seen.items()}}


def _run_s(store: CampaignStore, playbook: str, fallback: float = RUN_S) -> float:
    took = [(parse_iso(r["finished_at"]) - parse_iso(r["started_at"])).total_seconds()
            for r in store.list_agent_runs(playbook, limit=SAMPLES // 10)
            if r["status"] == "succeeded" and r["finished_at"]]
    return median(took) if took else fallback


def _item(section: str, kind: str, title: str, start: Optional[datetime],
          duration: Optional[float], why: str, *, waits_on: Optional[str] = None,
          source: Optional[str] = None, style: Optional[str] = None,
          engine: Optional[str] = None, voice: Optional[str] = None,
          **ids: Optional[int]) -> Dict[str, Any]:
    timed = start is not None and duration is not None
    return {"section": section, "kind": kind, "title": title, "source": source,
            "ids": {k: v for k, v in ids.items() if v is not None},
            "style": style, "engine": engine, "voice": voice,
            "est_start": to_iso(start) if start else None,
            "est_duration_s": round(duration) if duration is not None else None,
            "est_ready": to_iso(start + timedelta(seconds=duration)) if timed else None,
            "estimated": True, "why_here": why, "waits_on": waits_on,
            "stage": None, "progress": None}


def _ready(item: Dict[str, Any]) -> Optional[datetime]:
    return parse_iso(item["est_ready"]) if item["est_ready"] else None


def _midnight(settings: InstagramMCPSettings, at: datetime) -> datetime:
    """The next owner-local midnight after `at` (when the daily caps reset)."""
    local = schedule._local(settings, at)
    return datetime.combine(local.date() + timedelta(days=1), time(), tzinfo=local.tzinfo)


def _title(*texts: Optional[str]) -> str:
    text = next((t for t in texts if t and t.strip()), "")
    return " ".join(text.split())[:120]


def _running(store: CampaignStore, settings: InstagramMCPSettings, now: datetime,
             jobs: List[Dict[str, Any]], render_s: Dict[str, float]) -> List[Dict[str, Any]]:
    out = []
    for j in (j for j in jobs if j["state"] == "running"):
        engine = _engine(j["recipe"])
        start = parse_iso(j["started_at"]) if j["started_at"] else now
        took = (now - start).total_seconds()
        p = j["progress"] or 0.0
        # past 5 %: what is left at the pace so far; before, the engine's usual time
        left = took * (1 - p) / p if p > 0.05 else max(0.0, render_s[engine] - took)
        item = _item("running", "render", _title(j["hook"], j["caption"], f"Vidéo {j['asset_id']}"),
                     start, took + left, "Le rendu en cours : un seul à la fois.",
                     source=j["origin"] or "agent", style=j["style"], engine=engine,
                     asset_id=j["asset_id"], order_id=j["order_id"], pick_id=j["pick_id"])
        out.append({**item, "stage": "rendu", "progress": p})
    for r in store.running_agent_runs():
        start = parse_iso(r["started_at"])
        if r["playbook"] == film.PLAYBOOK:
            order = next((o for o in work_orders.list_orders(store, "in_production")
                          if lemo.is_lemo(o["style"])), None)
            took = max(_run_s(store, film.PLAYBOOK, settings.lemo_film_max_min * 60),
                       (now - start).total_seconds())
            item = _item("running", "film", _title(order and order["instruction"], "Film Lemo"),
                         start, took, "Le film Lemo en fabrication : un à la fois.",
                         source=order and order["source"], style=order and order["style"],
                         engine="film", run_id=r["id"], order_id=order and order["id"])
        else:
            light = r["playbook"] == schedule.ORDER_PLAYBOOK
            took = max(_run_s(store, r["playbook"]), (now - start).total_seconds())
            item = _item("running", "order_run" if light else "agent_run",
                         f"Run {r['playbook']}", start, took,
                         "Le run de l'IA en cours : rien d'autre ne démarre avant sa fin.",
                         source="agent", run_id=r["id"])
        out.append({**item, "stage": "en cours"})
    return out


def build_planning(store: CampaignStore, settings: InstagramMCPSettings, now: datetime
                   ) -> Dict[str, Any]:
    """{now, items}: the chain (see module doc). Item: section running | next | planned,
    kind render | film | order_run | agent_run | work_order | change_request, title,
    source, ids {order_id, asset_id, pick_id, run_id}, style, engine, voice, est_start,
    est_duration_s, est_ready (ISO, None when it waits on the owner), estimated, why_here,
    waits_on (gpu_busy | agent_running | order_grace | daily_cap | preflight | next_ai_run
    | needs_instruction | None), stage and progress (running items), picks_up (the
    producing run's placeholder)."""
    with store._tx() as c:
        jobs = [dict(r) for r in c.execute(_JOBS)]
    render_s = _render_s(store)
    voice = voices.default_voice(store)  # what a new video gets when the AI picks none
    items = _running(store, settings, now, jobs, render_s)
    cursor = max([now, *filter(None, map(_ready, items))])
    agent_busy = any(i["kind"] != "render" for i in items)

    def add(item: Dict[str, Any]) -> None:
        nonlocal cursor
        items.append(item)
        cursor = _ready(item) or cursor

    for n, j in enumerate(j for j in jobs if j["state"] == "queued"):
        engine = _engine(j["recipe"])
        ahead = n > 0 or any(i["kind"] == "render" for i in items)
        add(_item("next", "render", _title(j["hook"], j["caption"], f"Vidéo {j['asset_id']}"),
                  cursor, render_s[engine],
                  "File des rendus : le plus ancien d'abord, un à la fois.",
                  waits_on="gpu_busy" if ahead else None, source=j["origin"] or "agent",
                  style=j["style"], engine=engine, asset_id=j["asset_id"],
                  order_id=j["order_id"], pick_id=j["pick_id"]))
    busy = "gpu_busy" if jobs else "agent_running" if agent_busy else None

    def playbook() -> None:
        for name in schedule.due_runs(store, settings, now):
            add(_item("next", "agent_run", f"Run {name}", cursor, _run_s(store, name),
                      "Run prévu pas encore lancé : il passe dès que rien ne tourne.",
                      waits_on=busy, source="agent"))

    def films() -> None:
        nonlocal cursor
        took = _run_s(store, film.PLAYBOOK, settings.lemo_film_max_min * 60)
        done = film.films_today(store, settings, now)
        for o in (o for o in work_orders.list_orders(store, "scheduled", newest=False)
                  if lemo.is_lemo(o["style"])):
            waits = busy
            if done >= settings.lemo_films_per_day:  # the next day's films
                cursor, done, waits = _midnight(settings, cursor), 0, "daily_cap"
            done += 1
            add(_item("next", "film", _title(o["instruction"], f"Film {o['id']}"), cursor, took,
                      "Film Lemo : le plus ancien d'abord, après les runs prévus.",
                      waits_on=waits, source=o["source"], style=o["style"], engine="film",
                      order_id=o["id"], pick_id=o["pick_id"]))

    def orders() -> None:
        nonlocal cursor
        seen = store.get_state(schedule.CAPABILITIES_KEY) or {}
        gained = parse_iso(seen["gained_at"]) if seen.get("gained_at") else None
        why, newest = schedule.order_wait(store, settings, now, gained)
        if why == "nothing":
            return
        waits = why or busy
        if why == "seen":  # this run had them: they wait for the next run that reads them
            nxt = [r["next_at"] for r in schedule.next_runs(settings, now)
                   if r["playbook"] in schedule.ORDER_READERS]
            cursor, waits = max(cursor, min(nxt)) if nxt else cursor, "next_ai_run"
        else:
            if why == "order_grace":
                cursor = max(cursor, newest + timedelta(
                    minutes=settings.order_run_debounce_minutes))
            elif why == "daily_cap":
                cursor = max(cursor, _midnight(settings, now))
            add(_item("next", "order_run", f"Run {schedule.ORDER_PLAYBOOK}", cursor,
                      _run_s(store, schedule.ORDER_PLAYBOOK),
                      "Tes commandes et demandes de changement lancent le run léger.",
                      waits_on=waits, source="agent"))
        why_here = "L'IA l'écrit dans ce run, puis son rendu suit celui d'avant."
        for o in work_orders.for_agent(store, "scheduled"):
            engine = style_engine(o["style"])
            add(_item("next", "change_request" if o["source"] == "change" else "work_order",
                      _title(o["instruction"], f"Commande {o['id']}"), cursor,
                      render_s[engine], why_here, waits_on=waits, source=o["source"],
                      style=o["style"], engine=engine, voice=voice, order_id=o["id"],
                      pick_id=o["pick_id"], asset_id=o["from_asset_id"]))
        for r in list_revision_requests(store):
            a = r["asset"]
            engine = _engine(store.get_asset(a["id"])["recipe"])
            add(_item("next", "change_request", _title(a.get("hook"), f"Vidéo {a['id']}"),
                      cursor, render_s[engine], why_here, waits_on=waits, source="change",
                      engine=engine, asset_id=a["id"]))

    steps = {"playbook": playbook, "film": films, "orders": orders}
    for step in schedule.CATCH_UP_ORDER:
        steps[step]()

    for o in work_orders.list_orders(store, "needs_instruction", newest=False):
        items.append(_item("next", "work_order", _title(o["caption_quote"], f"Commande {o['id']}"),
                           None, None, "Attend ta consigne : rien ne part sans elle.",
                           waits_on="needs_instruction", source=o["source"], style=o["style"],
                           order_id=o["id"], pick_id=o["pick_id"]))

    planned_at: Optional[datetime] = None
    for r in sorted(schedule.next_runs(settings, now), key=lambda r: r["next_at"]):
        if r["next_at"] - now > HORIZON:
            continue
        start = max(filter(None, (r["next_at"], planned_at)))
        item = _item("planned", "agent_run", f"Run {r['playbook']}", start,
                     _run_s(store, r["playbook"]), f"Prévu chaque jour à {r['time']}."
                     if not r["weekly"] else f"Prévu chaque semaine ({r['time']}).",
                     source="schedule")
        if packet.RUNS.get(r["playbook"], ("custom",))[0] == "produce":
            n = {"orders": len(work_orders.for_agent(store, "scheduled")),
                 "change_requests": len(list_revision_requests(store)),
                 "dm_picks": len(dm_picks.for_agent(store, "new"))}
            item["picks_up"] = {**n, "ideas_left": max(0, settings.batch_size - sum(n.values()))}
        items.append(item)
        planned_at = _ready(item)
    return {"now": to_iso(now), "items": items}
