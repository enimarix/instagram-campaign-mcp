"""
The Planning page (step 185): what the studio makes next and when.

build_planning(store, settings, now) -> {now, items} lists one chain, in the order the
worker really takes the work today:

- running: the render in progress (render_jobs, one at a time) and the agent run going;
- next: in schedule.CATCH_UP_ORDER, the heavy line (studio/line.py, 186: queued renders
  and Lemo films, first in first out, « start now » first, a timer skipping without
  blocking: line.head() again on a simulated clock, LEMO_FILMS_PER_DAY moving the next
  day's films past midnight), then a due playbook, the light run for the owner's orders
  and change requests (schedule.order_wait: grace, daily cap...) followed by each of their
  renders, the check run of finished renders (schedule.check_wait, 188c; a waiting light
  run is listed after it); then the orders that wait for the owner's instruction (no time);
- planned: the scheduled AI runs of the next 24 h as placeholders, none before the AI's
  runs ahead are done; the producing run says what it picks up first and how many places stay
  for Claude's own ideas.
- ideas: Claude's planned videos waiting for the owner (src/studio/planned.py, 188b):
  outside the chain, no time until released.

« Lancer » (196): launch() takes one card or a selection: renders, films and Claude's ideas
to the head of the line, the owner's orders / change requests and the AI's runs as launch
requests catch_up starts first (schedule.request_launch). The chain times a launched run as
the next thing on the AI track once no render waits, before the films and the other runs, and
hides that playbook's placeholder later the same day (200). A film is an AI run there too: one
due before the other runs could start goes first (200).

Around the chain (190): the 24 h strip of its ETAs and the queued posts (strip), the
supply gauge (supply), today's history (history), and the delay warning before a move or
« start now » (preview: the real call on a copy of the database).

Every time is an estimate (`estimated: true`) on two tracks (194), as the worker does: the
heavy line starts behind the running render only (a film also waits for the running AI
run); the AI's runs start behind the running run once the line is idle, each by catch_up's
rules, and one waiting for its own time (a grace, the daily cap, the next run, the check's
re-check) holds nothing after it. A duration is the median of the recent real ones
(render_jobs.render_ms per engine, agent_runs per playbook), else the constants below
(docs/DECISIONS.md).
ponytail: one render at a time (RENDER_CONCURRENCY=1 here); due_runs may close a crashed
run's row on the way, as the worker does every minute.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, time, timedelta
from functools import cache
from statistics import median
from typing import Any, Callable, Dict, List, Optional

from ..agent import film, packet, schedule
from ..config import InstagramMCPSettings
from ..learning.learnings import list_revision_requests
from ..store import CampaignStore, parse_dt, parse_iso, to_iso
from . import (
    checks,
    cinematic,
    lemo,
    line,
    macro3d,
    planned,
    render,
    scheduling,
    sitcom,
    voices,
    work_orders,
)
from .assets import transition

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
# The AI's jobs in the owner's words (UI-015; web/src/pages/load.ts PLAYBOOKS holds the same).
PLAYBOOK_LABELS = {"daily-learn": "Analyse de la nuit", "daily-produce": "Vidéos du jour",
                   schedule.ORDER_PLAYBOOK: "Tes changements", checks.PLAYBOOK: "Vérifier les rendus",
                   "weekly-ads": "Pubs de la semaine"}


def run_title(playbook: str) -> str:
    """A run card's title; an unknown playbook keeps its file name."""
    return PLAYBOOK_LABELS.get(playbook, playbook)


_JOBS = ("SELECT j.id, j.asset_id, j.state, j.progress, j.started_at, j.failure, a.recipe,"
         " a.caption,"
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


def _style_engine(style: Optional[str]) -> str:
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
          not_before: Optional[str] = None, playbook: Optional[str] = None,
          **ids: Optional[int]) -> Dict[str, Any]:
    timed = start is not None and duration is not None
    return {"section": section, "kind": kind, "title": title, "source": source,
            "ids": {k: v for k, v in ids.items() if v is not None}, "playbook": playbook,
            "style": style, "engine": engine, "voice": voice,
            "est_start": to_iso(start) if start else None,
            "est_duration_s": round(duration) if duration is not None else None,
            "est_ready": to_iso(start + timedelta(seconds=duration)) if timed else None,
            "estimated": True, "why_here": why, "waits_on": waits_on,
            "not_before": not_before,
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


def _late(start: datetime, usual_s: float, now: datetime) -> Optional[int]:
    """Seconds a running item is past its usual time (start + the median duration), else
    None. Its est_ready never is (it moves with the pace, never before now)."""
    late = (now - start).total_seconds() - usual_s
    return round(late) if late >= 60 else None


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
        out.append({**item, "stage": "rendu", "progress": p,
                    "late_s": _late(start, render_s[engine], now)})
    for r in store.running_agent_runs():
        start = parse_iso(r["started_at"])
        if r["playbook"] == film.PLAYBOOK:
            order = next((o for o in work_orders.list_orders(store, "in_production")
                          if lemo.is_lemo(o["style"])), None)
            usual = _run_s(store, film.PLAYBOOK, settings.lemo_film_max_min * 60)
            took = max(usual, (now - start).total_seconds())
            item = _item("running", "film", _title(order and order["instruction"], "Film Lemo"),
                         start, took, "Le film Lemo en fabrication : un à la fois.",
                         source=order and order["source"], style=order and order["style"],
                         engine="film", run_id=r["id"], order_id=order and order["id"])
        else:
            kind = {schedule.ORDER_PLAYBOOK: "order_run",
                    checks.PLAYBOOK: "check_run"}.get(r["playbook"], "agent_run")
            usual = _run_s(store, r["playbook"])
            took = max(usual, (now - start).total_seconds())
            item = _item("running", kind,
                         run_title(r['playbook']), start, took,
                         "Le run de l'IA en cours : rien d'autre ne démarre avant sa fin.",
                         source="agent", playbook=r["playbook"], run_id=r["id"])
        out.append({**item, "stage": "en cours", "late_s": _late(start, usual, now)})
    return out


def build_planning(store: CampaignStore, settings: InstagramMCPSettings, now: datetime
                   ) -> Dict[str, Any]:
    """{now, items, paused, strip, supply, history}: the chain (see chain()); paused: since
    when the studio is paused (line.pause), else None; strip, supply, history (190): see
    those functions."""
    items = chain(store, settings, now)
    return {"now": to_iso(now), "items": items, "paused": line.paused(store),
            "strip": strip(store, now, items), "supply": supply(store, settings, now, items),
            "history": history(store, settings, now)}


def chain(store: CampaignStore, settings: InstagramMCPSettings, now: datetime
          ) -> List[Dict[str, Any]]:
    """The chain (see module doc). Item: section running | next | planned | ideas, kind
    render | film | order_run | check_run | agent_run | work_order | change_request | claude_idea, title,
    source, ids {order_id, asset_id, pick_id, run_id, job_id}, style, engine, voice,
    est_start, est_duration_s, est_ready (ISO, None when it waits on the owner), estimated,
    why_here, waits_on (gpu_busy | agent_running | timer | machine (197: a render waiting
    to retry after a machine failure) | held | order_grace | check_grace |
    recheck | daily_cap | preflight | next_ai_run | needs_instruction | None), not_before (a
    waiting render's or film's timer, UTC ISO), stage and progress (running items), late_s
    (a running item past its usual time, 190; else None), picks_up (the producing run's
    placeholder), idea (a claude_idea's card: planned.cards, section ideas), line_index (a
    waiting render's or film's place among the line's items not held, for line.place; held:
    None), playbook (an AI run's), launch_requested (196: the owner launched it, it waits for
    the machine)."""
    with store._tx() as c:
        jobs = [dict(r) for r in c.execute(_JOBS)]
    render_s = _render_s(store)
    voice = voices.default_voice(store)  # what a new video gets when the AI picks none
    items = _running(store, settings, now, jobs, render_s)
    # Two tracks (194). The heavy line waits only for the running render: the render loop
    # never waits for an AI run (line.renders_next), a film does (line.films_ready). The AI's
    # runs wait for the running run and for the line to be idle (schedule.busy); one that
    # waits for its own time (a grace, the daily cap, a later run) moves nothing after it.
    gpu = max([now, *(_ready(i) for i in items if i["kind"] == "render")])
    agent = max([now, *(_ready(i) for i in items if i["kind"] != "render")])
    agent_busy = any(i["kind"] != "render" for i in items)

    def add(item: Dict[str, Any]) -> datetime:
        """Append a timed item; returns when it is ready."""
        items.append(item)
        return _ready(item)

    busy: Optional[str] = None
    todo = schedule.launch_requests(store)  # 196: the runs the owner launched, oldest first
    launched = {r["playbook"] for r in todo}
    listed: set = set()  # the orders and change requests a light run lists already

    def launches(at: datetime) -> None:
        """The runs the owner launched (200): catch_up starts them before anything else once
        no render waits and no run runs (busy), so from `at` they are the next thing on the AI
        track, past the grace, the daily cap or their scheduled time."""
        nonlocal agent
        first = len(items)
        while todo:
            req = todo.pop(0)
            name = req["playbook"]
            kind = {schedule.ORDER_PLAYBOOK: "order_run",
                    checks.PLAYBOOK: "check_run"}.get(name, "agent_run")
            waits = ("agent_running" if agent > max(at, now) else "gpu_busy" if at > now
                     else None)
            agent = add(_item("next", kind, run_title(name), max(agent, at),
                              _run_s(store, name, RUN_S / 3 if kind == "check_run" else RUN_S),
                              "Lancé par toi : il passe avant les autres runs de l'IA, dès que"
                              " la machine est libre.", waits_on=waits, source="agent",
                              playbook=name))
            if kind == "order_run":
                agent = requests(agent, waits, "L'IA l'écrit dans ce run lancé par toi, puis"
                                 " son rendu suit celui d'avant.", req["only"])
        for i in items[first:]:
            i["launch_requested"] = True

    def heavy() -> None:
        nonlocal gpu, agent, busy
        rows = {("render", j["id"]): j for j in jobs if j["state"] == "queued"}
        rows.update({("film", o["id"]): o for o in work_orders.list_orders(
            store, "scheduled", newest=False) if lemo.is_lemo(o["style"])})
        pending = [i for i in line.waiting(store) if (i["kind"], i["id"]) in rows]
        held = [i for i in pending if i["not_before"] == line.HELD]  # listed after, no time
        pending = [i for i in pending if i not in held]
        # the drag and drop's index (line.place, 195): the place among the not held
        index = {(i["kind"], i["id"]): n for n, i in enumerate(pending)}
        took = _run_s(store, film.PLAYBOOK, settings.lemo_film_max_min * 60)
        quota = left = film.films_left(store, settings, now)  # inf: no limit
        reset, films_n, idle_at, n = _midnight(settings, now), 0, None, len(items)
        ahead = any(i["kind"] == "render" for i in items)  # a running film holds no render
        films: List[Dict[str, Any]] = []  # the films' cards, in line order

        def card(i: Dict[str, Any], start: Optional[datetime], waits: Optional[str],
                 why: str) -> Dict[str, Any]:
            key = (i["kind"], i["id"])
            r, nb = rows[key], i["not_before"]
            nb = None if nb == line.HELD else nb
            if i["kind"] == "render":
                engine = _engine(r["recipe"])
                item = _item("next", "render", _title(r["hook"], r["caption"],
                                                      f"Vidéo {r['asset_id']}"),
                             start, render_s[engine], why, waits_on=waits, not_before=nb,
                             source=r["origin"] or "agent", style=r["style"], engine=engine,
                             asset_id=r["asset_id"], order_id=r["order_id"],
                             pick_id=r["pick_id"], job_id=r["id"])
            else:
                item = _item("next", "film", _title(r["instruction"], f"Film {r['id']}"),
                             start, took, why, waits_on=waits, not_before=nb,
                             source=r["source"], style=r["style"], engine="film",
                             order_id=r["id"], pick_id=r["pick_id"])
            return {**item, "line_index": index.get(key)}

        while pending:
            if gpu >= reset:  # the caps reset at owner-local midnight
                left, reset = film.films_per_day(settings), _midnight(settings, gpu)
            if todo and not line.head([p for p in pending if p["kind"] == "render"], gpu):
                launches(gpu)  # no render waits: the owner's launches go before the films
            # a film waits for the running AI run (line.films_ready), the renders don't
            i = line.head(pending, gpu, films=left > 0 and gpu >= agent)
            if i is None:  # each one waits on its timer, the films on tomorrow or the run
                if idle_at is None:  # the line is idle: the agent runs can go (busy)
                    idle_at, n = gpu, len(items)
                gpu = min([t for t in (parse_iso(p["not_before"]) for p in pending
                                       if p["not_before"]) if t > gpu]
                          + ([reset] if left <= 0 else []) + ([agent] if agent > gpu else []))
                continue
            pending.remove(i)
            nb = i["not_before"]
            timer = bool(nb) and parse_iso(nb) > now
            machine = timer and i["kind"] == "render" and bool(
                render.machine_retries(rows[(i["kind"], i["id"])]))
            capped = i["kind"] == "film" and films_n >= quota
            waits = ("machine" if machine else "timer" if timer else "daily_cap" if capped else
                     "agent_running" if agent_busy and i["kind"] == "film" and gpu <= agent else
                     "gpu_busy" if ahead else None)
            why = ("La machine n'a pas pu faire la voix ou le rendu (RAM, GPU ou service de"
                   " voix) : nouvel essai automatique, sans compter contre la vidéo."
                   if machine else
                   "Lancé maintenant : il passe devant la file." if i["pos"] < 0 else
                   "Minuteur : il attend son heure sans bloquer la file." if timer else
                   "Placé par toi dans la file." if i["pos"] > 0 else
                   "File unique des rendus et des films : le premier arrivé passe d'abord,"
                   " un à la fois.")
            if i["kind"] == "film":
                films_n, left = films_n + 1, left - 1
                films.append(card(i, gpu, waits, why))
                gpu = add(films[-1])
            else:
                gpu = add(card(i, gpu, waits, why))
            ahead = True
        launches(gpu)
        # what waits on a timer holds no agent run back
        chain = items if idle_at is None else items[:n]
        agent = max(agent, gpu if idle_at is None else idle_at)
        for f in films:  # 200: a film is an AI run for catch_up (busy), which starts it before
            if parse_iso(f["est_start"]) <= agent:  # the others: one due by then goes first
                agent = max(agent, _ready(f))
        busy = ("gpu_busy" if any(i["kind"] == "render" for i in chain) else
                "agent_running" if chain or agent > now else None)
        items.extend(card(i, None, "held", "En pause : il attend que tu le reprennes, sans"
                          " bloquer la file.") for i in held)

    def playbook() -> None:
        nonlocal agent
        for name in schedule.due_runs(store, settings, now):
            if name in launched:  # listed with the launches
                continue
            agent = add(_item("next", "agent_run", run_title(name), agent, _run_s(store, name),
                              "Run prévu pas encore lancé : il passe dès que rien ne tourne.",
                              waits_on=busy, source="agent", playbook=name))

    def requests(at: datetime, waits: Optional[str], why_here: str,
                 only: Optional[Dict[str, List[int]]] = None) -> datetime:
        """The owner's orders and change requests the light run writes (only: those of a
        launch on a selection, 196), rendered one after the other from `at`, each listed
        once; returns when the last is ready."""
        for o in work_orders.for_agent(store, "scheduled"):
            if ("order", o["id"]) in listed or only and o["id"] not in only["order_ids"]:
                continue
            listed.add(("order", o["id"]))
            engine = _style_engine(o["style"])
            at = add(_item("next", "change_request" if o["source"] == "change" else "work_order",
                           _title(o["instruction"], f"Commande {o['id']}"), at,
                           render_s[engine], why_here, waits_on=waits, source=o["source"],
                           style=o["style"], engine=engine, voice=voice, order_id=o["id"],
                           pick_id=o["pick_id"], asset_id=o["from_asset_id"]))
        for r in list_revision_requests(store):
            a = r["asset"]
            if ("asset", a["id"]) in listed or only and a["id"] not in only["asset_ids"]:
                continue
            listed.add(("asset", a["id"]))
            engine = _engine(store.get_asset(a["id"])["recipe"])
            at = add(_item("next", "change_request", _title(a.get("hook"), f"Vidéo {a['id']}"),
                           at, render_s[engine], why_here, waits_on=waits, source="change",
                           engine=engine, asset_id=a["id"]))
        return at

    later: List[Callable[[], datetime]] = []  # a waiting order run: after the check run

    def orders() -> None:
        nonlocal agent
        if schedule.ORDER_PLAYBOOK in launched and not (
                any(("order", o["id"]) not in listed
                    for o in work_orders.for_agent(store, "scheduled"))
                or any(("asset", r["asset"]["id"]) not in listed
                       for r in list_revision_requests(store))):
            return  # the launched light run lists them all
        seen = store.get_state(schedule.CAPABILITIES_KEY) or {}
        gained = parse_iso(seen["gained_at"]) if seen.get("gained_at") else None
        why, newest = schedule.order_wait(store, settings, now, gained)
        if why == "nothing":
            return
        if why == "seen":  # this run had them: the next run that reads them writes them
            nxt = [r["next_at"] for r in schedule.next_runs(settings, now)
                   if r["playbook"] in schedule.ORDER_READERS]
            requests(max(agent, min(nxt)) if nxt else agent, "next_ai_run",
                     "Le dernier run l'a vue et l'a laissée : elle attend le prochain run prévu.")
            return
        at = (newest + timedelta(minutes=settings.order_run_debounce_minutes)
              if why == "order_grace" else _midnight(settings, now) if why == "daily_cap"
              else None)

        def run() -> datetime:
            ready = add(_item("next", "order_run", run_title(schedule.ORDER_PLAYBOOK),
                              max(agent, at) if at else agent,
                              _run_s(store, schedule.ORDER_PLAYBOOK),
                              "Tes commandes et demandes de changement lancent le run léger.",
                              waits_on=why or busy, source="agent",
                              playbook=schedule.ORDER_PLAYBOOK))
            return requests(ready, why or busy,
                            "L'IA l'écrit dans ce run, puis son rendu suit celui d'avant.")

        if at is None:  # it starts now: the check run waits for it and its renders (busy)
            agent = run()
        else:
            later.append(run)

    def check() -> None:  # 188c: the finished renders' check, once the line is idle
        nonlocal agent
        if checks.PLAYBOOK in launched:  # listed with the launches
            return
        why, newest = schedule.check_wait(store, settings, now)
        if why == "nothing":
            return
        midnight, at = _midnight(settings, now), None
        if why == "check_grace":
            at = newest + timedelta(minutes=settings.check_run_debounce_minutes)
        elif why == "daily_cap":
            at = midnight
        elif why == "seen":  # 193: what the last check left is offered again later
            last = schedule.check_started_at(store)
            if not last:
                return
            at = last + timedelta(hours=settings.check_recheck_hours)
            if at < midnight and schedule._runs_today(
                    store, settings, now, "check")[1] >= settings.max_check_runs_per_day:
                at = midnight
            why = "recheck"
        ready = add(_item("next", "check_run", run_title(checks.PLAYBOOK),
                          max(agent, at) if at else agent,
                          _run_s(store, checks.PLAYBOOK, RUN_S / 3),
                          "Les rendus finis sont vérifiés (images, contrôle) puis envoyés dans"
                          " ta boîte, ou refaits.", waits_on=why or busy, source="agent",
                          playbook=checks.PLAYBOOK))
        if at is None:
            agent = ready

    steps = {"film": heavy, "playbook": playbook, "orders": orders, "checks": check}
    for step in schedule.CATCH_UP_ORDER:
        steps[step]()
    # ponytail: a waiting order run and a waiting check run may overlap on the strip (the
    # catch-up runs them one after the other); neither moves the planned runs.
    for run in later:
        run()

    for o in work_orders.list_orders(store, "needs_instruction", newest=False):
        items.append(_item("next", "work_order", _title(o["caption_quote"], f"Commande {o['id']}"),
                           None, None, "Attend ta consigne : rien ne part sans elle.",
                           waits_on="needs_instruction", source=o["source"], style=o["style"],
                           order_id=o["id"], pick_id=o["pick_id"]))

    planned_at: Optional[datetime] = None
    local = schedule._local(settings, now)
    day_start = to_iso(local.replace(hour=0, minute=0, second=0, microsecond=0))
    for r in sorted(schedule.next_runs(settings, now), key=lambda r: r["next_at"]):
        if r["next_at"] - now > HORIZON:
            continue
        if r["next_at"].date() == local.date() and (r["playbook"] in launched or any(
                x["started_at"] >= day_start for x in store.list_agent_runs(r["playbook"],
                                                                             limit=1))):
            continue  # it starts (or started) today: due_runs skips today's time (200)
        start = max(filter(None, (r["next_at"], planned_at, agent)))  # after the AI's runs
        item = _item("planned", "agent_run", run_title(r['playbook']), start,
                     _run_s(store, r["playbook"]), f"Prévu chaque jour à {r['time']}."
                     if not r["weekly"] else f"Prévu chaque semaine ({r['time']}).",
                     source="schedule", playbook=r["playbook"])
        if packet.RUNS.get(r["playbook"], ("custom",))[0] == "produce":
            item["picks_up"] = planned.ideas_left(store, settings)
        items.append(item)
        planned_at = _ready(item)
    for card in planned.cards(store):  # Claude's ideas: not in the line, no time (188b)
        env = card.pop("recipe")
        items.append({**_item("ideas", "claude_idea", _title(card["hook"], card["caption"],
                                                             f"Vidéo {card['asset_id']}"),
                              None, None, "Idée de Claude : rien ne se rend ni ne se dit sans"
                              " ton « Valider ».", source="agent", style=card["style"],
                              engine=_engine(env), voice=card["voice"],
                              asset_id=card["asset_id"]), "idea": card})
    for i in items:
        i.setdefault("launch_requested", False)
    return items


LANES = {"render": "render", "work_order": "render", "change_request": "render",
         "film": "film"}  # else run (the AI's runs)
MAKES = ("render", "film", "work_order", "change_request")  # each ends as a video


def strip(store: CampaignStore, now: datetime, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The 24 h strip (190): {start, end (UTC ISO, now → now + HORIZON), blocks [{lane render
    | film | run, kind, title, section, start, end (clipped to the strip), late}], posts
    [publish_at of the queued posts in the strip]}, from the chain's ETAs."""
    end = now + HORIZON
    blocks = []
    for i in items:
        start, ready = (parse_iso(i["est_start"]) if i["est_start"] else None), _ready(i)
        if start is None or ready is None or ready <= now or start >= end:
            continue
        blocks.append({"lane": LANES.get(i["kind"], "run"), "kind": i["kind"],
                       "title": i["title"], "section": i["section"],
                       "start": to_iso(max(start, now)), "end": to_iso(min(ready, end)),
                       "late": bool(i.get("late_s"))})
    queued = (parse_dt(r["publish_at"]) for r in store.queue_times(since=now)
              if r["status"] == "pending")
    return {"start": to_iso(now), "end": to_iso(end), "blocks": blocks,
            "posts": sorted(to_iso(at) for at in queued if now <= at <= end)}


def supply(store: CampaignStore, settings: InstagramMCPSettings, now: datetime,
           items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The supply gauge (190): {approved (approved or queued), bench (scheduling.bench_assets),
    per_day (MAX_POSTS_PER_DAY), days, until (owner-local date the reserve lasts to), low
    (under a day), making (videos the line will add once done), ideas (Claude's cards)}."""
    with store._tx() as c:
        approved = c.execute("SELECT COUNT(*) FROM assets WHERE status IN"
                             " ('approved', 'scheduled')").fetchone()[0]
    bench = len(scheduling.bench_assets(store, settings, now))
    days = (approved + bench) / settings.max_posts_per_day
    today = schedule._local(settings, now).date()
    return {"approved": approved, "bench": bench, "per_day": settings.max_posts_per_day,
            "days": round(days, 1), "until": (today + timedelta(days=int(days))).isoformat(),
            "low": days < 1,
            "making": sum(i["section"] in ("running", "next") and i["kind"] in MAKES
                          and i["est_ready"] is not None for i in items),
            "ideas": sum(i["section"] == "ideas" for i in items)}


_DAY_JOBS = ("SELECT j.id, j.asset_id, j.state, j.failure, j.finished_at, j.requeues,"
             " a.status AS asset_status, a.recipe, a.caption, i.hook FROM render_jobs j"
             " JOIN assets a ON a.id = j.asset_id JOIN ideas i ON i.id = a.idea_id"
             " WHERE j.state IN ('done', 'failed') AND j.finished_at >= ?"
             " ORDER BY j.finished_at DESC, j.id DESC")
_DAY_DROPS = ("SELECT a.id, a.caption, a.agent_decision, i.hook FROM assets a"
              " JOIN ideas i ON i.id = a.idea_id"
              " WHERE json_extract(a.agent_decision, '$.kind') = 'dropped'"
              " AND json_extract(a.agent_decision, '$.at') >= ? ORDER BY a.id")
# Not the order of a removed render's video (line.skip_orders): that render is listed.
_DAY_ORDERS = ("SELECT w.id, w.instruction, w.updated_at FROM work_orders w"
               " WHERE w.status = 'skipped' AND w.skip_reason = ? AND w.updated_at >= ?"
               " AND NOT EXISTS (SELECT 1 FROM render_jobs j JOIN assets a ON a.id = j.asset_id"
               " WHERE a.idea_id = w.idea_id AND j.failure = ?) ORDER BY w.id")


def history(store: CampaignStore, settings: InstagramMCPSettings, now: datetime
            ) -> List[Dict[str, Any]]:
    """Today's history (190, since owner-local midnight), newest first: [{kind done | failed
    | removed | dropped | run, at, title, asset_id, order_id, run_id, reason (failed,
    dropped), status (run), recipe (a failed render whose video can be rendered again with
    it: POST /api/assets/{id}/rerender; else None; a dropped one too: the re-render revives
    it, checks.revive), tries (failed: how many times the video was rendered, its jobs that
    failed today and their requeues; a machine retry is not a try, render.machine_wait)}]. A
    video's failures are one row (195): its newest, with its reason."""
    local = schedule._local(settings, now)
    since = to_iso(local.replace(hour=0, minute=0, second=0, microsecond=0))

    def row(kind: str, at: str, title: str, **extra: Any) -> Dict[str, Any]:
        return {"kind": kind, "at": at, "title": title, "asset_id": None, "order_id": None,
                "run_id": None, "reason": None, "status": None, "recipe": None, "tries": None,
                **extra}

    out = []
    with store._tx() as c:
        jobs = c.execute(_DAY_JOBS, (since,)).fetchall()
        drops = c.execute(_DAY_DROPS, (since,)).fetchall()
        orders = c.execute(_DAY_ORDERS, (line.REMOVED, since, line.REMOVED)).fetchall()
    kinds = [("done" if j["state"] == "done" else
              "removed" if j["failure"] == line.REMOVED else "failed") for j in jobs]
    tries: Counter = Counter()
    for j, kind in zip(jobs, kinds):
        if kind == "failed":  # a relaunch reuses the job's row (store.requeue_render_job)
            tries[j["asset_id"]] += 1 + j["requeues"]
    shown = set()
    for j, kind in zip(jobs, kinds):
        failed = kind == "failed"
        if failed:  # one row per video: its newest failure
            if j["asset_id"] in shown:
                continue
            shown.add(j["asset_id"])
        retry = failed and j["asset_status"] == "failed"
        out.append(row(kind, j["finished_at"],
                       _title(j["hook"], j["caption"], f"Vidéo {j['asset_id']}"),
                       asset_id=j["asset_id"], reason=_title(j["failure"]) if failed else None,
                       recipe=json.loads(j["recipe"]) if retry else None,
                       tries=tries[j["asset_id"]] if failed else None))
    for a in drops:
        why = json.loads(a["agent_decision"])
        out.append(row("dropped", why["at"], _title(a["hook"], a["caption"], f"Vidéo {a['id']}"),
                       asset_id=a["id"], reason=why.get("why")))
    out.extend(row("removed", o["updated_at"], _title(o["instruction"], f"Commande {o['id']}"),
                   order_id=o["id"]) for o in orders)
    # ponytail: the last 50 runs; more than 50 runs a day is not a real case.
    out.extend(row("run", r["started_at"], run_title(r['playbook']), run_id=r["id"],
                   status=r["status"])
               for r in store.list_agent_runs(limit=50) if r["started_at"] >= since)
    return sorted(out, key=lambda r: r["at"], reverse=True)


PREVIEWS = ("start_now", "move", "release")


def _key(item: Dict[str, Any]) -> tuple:
    return item["section"], item["kind"], item["title"], tuple(sorted(item["ids"].items()))


def _release_now(store: CampaignStore, asset_id: int) -> None:
    """planned.release(now=True) minus its checks, for a preview: they change no time."""
    transition(store, asset_id, "rendering", actor="owner")
    line.start_now(store, "render", render.enqueue_render(store, asset_id)["id"])


def preview(store: CampaignStore, settings: InstagramMCPSettings, now: datetime,
            action: str, kind: str, item_id: int, by: int = 0) -> Dict[str, Any]:
    """The delay warning (190): what « Lancer maintenant » (start_now), « Monter » /
    « Descendre » (move, by -1 / 1) or releasing Claude's idea with start now (release, kind
    idea, item_id its video) would push back: the real calls run on a copy of the database,
    the chain built again. {pushed: [{kind, title, by_s}]} in chain order; the real call's
    errors (KeyError, ValueError)."""
    if action not in PREVIEWS:
        raise ValueError(f"action must be one of {', '.join(PREVIEWS)}")

    def change(copy: CampaignStore) -> None:
        if action == "start_now":
            line.start_now(copy, kind, item_id)
        elif action == "move":
            line.move(copy, kind, item_id, by)
        else:
            _release_now(copy, item_id)

    return _pushed(store, settings, now, change)


def preview_launch(store: CampaignStore, settings: InstagramMCPSettings, now: datetime,
                   items: List[Dict[str, Any]], bulk: bool = False) -> Dict[str, Any]:
    """The delay warning before « Lancer la sélection » / « Tout lancer » (196): what the
    selection's renders, films and Claude's ideas going to the head of the line push back
    (on preview's copy; refused ones and, with bulk, the ones launch() leaves are left out,
    the AI runs move nothing ahead). {pushed}."""
    waits = _waits(store, now) if bulk else {}

    def change(copy: CampaignStore) -> None:
        for i in reversed(items):  # as launch(): the selection keeps its order at the front
            if (i["kind"], i["id"]) in waits:
                continue
            try:
                if i["kind"] in line.KINDS:
                    line.start_now(copy, i["kind"], i["id"])
                elif i["kind"] == "claude_idea":
                    planned._planned(copy, i["id"])
                    _release_now(copy, i["id"])
            except (KeyError, ValueError):
                continue

    return _pushed(store, settings, now, change)


def _pushed(store: CampaignStore, settings: InstagramMCPSettings, now: datetime,
            change: Callable[[CampaignStore], Any]) -> Dict[str, Any]:
    """{pushed: [{kind, title, by_s}]}: the items made ready a minute or more later once
    `change` is applied to a copy of the database, in chain order."""
    # ponytail: copies the whole database (2 MB today: milliseconds); a SAVEPOINT on a
    # dedicated connection if it grows past what a click can wait for.
    copy = CampaignStore(":memory:")
    try:
        with store._tx() as c:
            c.backup(copy._conn)
        change(copy)
        after = {_key(i): _ready(i) for i in chain(copy, settings, now) if i["est_ready"]}
    finally:
        copy.close()
    pushed = []
    for i in chain(store, settings, now):
        moved = after.get(_key(i))
        by_s = (moved - _ready(i)).total_seconds() if moved and i["est_ready"] else 0
        if by_s >= 60:
            pushed.append({"kind": i["kind"], "title": i["title"], "by_s": round(by_s)})
    return {"pushed": pushed}


HEAVY = (*line.KINDS, "claude_idea")  # to the head of the line
ORDERS = ("work_order", "change_request")  # the light run, on the selection
LAUNCHES = (*HEAVY, *ORDERS, "agent_run")


def _waits(store: CampaignStore, now: datetime) -> Dict[tuple, str]:
    """{(kind, id): held | timer | machine}: the line's items a bulk launch leaves where they
    are (200): held, on a timer, or waiting to retry after a machine failure."""
    out = {}
    for i in line.waiting(store):
        nb = i["not_before"]
        if not nb or parse_iso(nb) <= now:
            continue
        out[(i["kind"], i["id"])] = (
            "held" if nb == line.HELD else
            "machine" if i["kind"] == "render" and render.machine_retries(
                store.get_render_job(i["id"])) else "timer")
    return out


def _order_ids(store: CampaignStore, kind: str, item_id: int, sent_back: Callable[[], set]
                ) -> Dict[str, List[int]]:
    """The waiting order (work_order: its id) or change request (its video's id, among
    sent_back()) for the light run, or the refusal: KeyError, ValueError."""
    if kind == "work_order":
        o = work_orders.get_order(store, item_id)
        if o["status"] == "needs_instruction":
            raise ValueError("Cette commande attend ta consigne : rien ne part sans elle.")
        if o["status"] != "scheduled" or lemo.is_lemo(o["style"]):
            raise ValueError(f"Cette commande n'attend pas le run léger (statut {o['status']}) :"
                             " seule une commande en attente peut être lancée.")
        return {"order_ids": [item_id], "asset_ids": []}
    if item_id not in sent_back():
        status = store.get_asset(item_id)["status"]
        raise ValueError(f"La vidéo {item_id} n'attend pas de changement (statut {status}, ou sa"
                         " nouvelle version est déjà en rendu).")
    return {"order_ids": [], "asset_ids": [item_id]}


def _playbook(store: CampaignStore, name: Any) -> str:
    """A playbook the owner may launch, or the refusal (AgentError, ValueError)."""
    from ..agent.runner import _playbook_file

    name = _playbook_file(str(name), schedule.AGENT_DIR).stem
    if store.running_agent_run(name):
        raise ValueError(f"Le run {name} est déjà en cours.")
    return name


def launch(store: CampaignStore, settings: InstagramMCPSettings, items: List[Dict[str, Any]],
           now: datetime, bulk: bool = False) -> Dict[str, Any]:
    """« Lancer maintenant » on one card or many, « Lancer la sélection », « Tout lancer »
    (196). items [{kind, id}] in on-screen order: render (its job), film (its order) and
    claude_idea (its video: planned.release now=True) go to the head of the line in that
    order (line.start_now); work_order (its order) and change_request (its video, one the AI
    left « en attente » included) ask for the light run on those only, agent_run (id: the
    playbook) for that run: schedule.request_launch, started by catch_up as soon as nothing
    else runs, past the grace, the « seen » rule and the daily cap. Running, done or unknown:
    refused with the reason. bulk (« Tout lancer », « Lancer la sélection », 200): a held render
    or film, one on a timer or waiting for the machine stays where it is (one card's « Lancer
    maintenant » overrides those). {front: [{kind, id}], requested: [{kind, id}], refused:
    [{kind, id, message}], left: [{kind, id, why held | timer | machine}] (on-screen order),
    busy (schedule.busy: why the requests wait, else None), paused (line.paused)}."""
    from ..agent.runner import AgentError
    from .motion import MotionError

    front, requested, refused, left = [], [], [], []
    waits = _waits(store, now) if bulk else {}
    sent_back = cache(lambda: {r["asset"]["id"] for r in list_revision_requests(store)})

    orders: Dict[str, List[int]] = {"order_ids": [], "asset_ids": []}
    playbooks: List[str] = []
    for i in reversed(items):  # each start_now goes ahead of all: the first ends at the head
        kind, item_id = i["kind"], i["id"]
        if (kind, item_id) in waits:
            left.append({"kind": kind, "id": item_id, "why": waits[(kind, item_id)]})
            continue
        try:
            if kind not in LAUNCHES:
                raise ValueError(f"« {kind} » ne se lance pas.")
            if kind == "agent_run":
                playbooks.append(_playbook(store, item_id))
            elif not isinstance(item_id, int):
                raise ValueError(f"id {item_id!r} : un nombre est attendu.")
            elif kind == "claude_idea":
                planned.release(store, settings, item_id, now=True)
            elif kind in HEAVY:
                line.start_now(store, kind, item_id)
            else:
                for k, ids in _order_ids(store, kind, item_id, sent_back).items():
                    orders[k] += ids
        except KeyError:
            refused.append({"kind": kind, "id": item_id, "message": "Introuvable."})
            continue
        except (ValueError, AgentError, MotionError) as e:
            refused.append({"kind": kind, "id": item_id, "message": str(e)})
            continue
        (front if kind in HEAVY else requested).append({"kind": kind, "id": item_id})
    if orders["order_ids"] or orders["asset_ids"]:
        schedule.request_launch(store, schedule.ORDER_PLAYBOOK, now, **orders)
    for name in playbooks:
        schedule.request_launch(store, name, now)
    return {"front": front[::-1], "requested": requested[::-1], "refused": refused[::-1],
            "left": left[::-1], "busy": schedule.busy(store, now=now) if requested else None,
            "paused": line.paused(store)}
