"""Step 186: one heavy line, first in first out (src/studio/line.py), « start now » and the
timer; the render claim, the film start and the Planning page follow it. Step 187: remove,
hold, move up / down and the studio's pause switch."""

import asyncio
import sqlite3
import time
from contextlib import nullcontext, suppress
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src import store as store_mod
from src import worker
from src.agent import schedule
from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.store import MIGRATIONS, CampaignStore, to_iso, utcnow
from src.studio import alerts, housekeeping, line, planning, work_orders

from .conftest import LOCAL

UTC = timezone.utc
NOW = datetime(2026, 11, 17, 10, tzinfo=UTC)  # the fake clock


def cfg(**kw):
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                                database_path=":memory:",
                                **{"timezone": "Europe/Paris", "agent_schedule": "", **kw})


def _render(store, at, template="FactQuest"):
    idea = store.add_idea("motion", hook="Une vidéo", batch_date="2026-11-17")
    asset = store.add_asset(idea["id"], batch_date="2026-11-17",
                            recipe={"kind": "motion", "template": template, "props": {}})
    job = store.add_render_job(asset["id"], f"k{asset['id']}")
    with store._tx() as c:  # its arrival
        c.execute("UPDATE render_jobs SET created_at=? WHERE id=?", (to_iso(at), job["id"]))
    return job["id"]


def _film(store, monkeypatch, at):
    monkeypatch.setattr(work_orders, "utcnow", lambda: at)  # scheduled_at: its arrival
    return work_orders._insert_owner_order(store, "create", "Un film", "lemo:watercolor")["id"]


def _head(store, s, now=NOW):
    got = line.next_in_line(store, s, now)
    return got and (got["kind"], got["id"])


def _film_run(store, s, now=NOW):
    started = []
    schedule.film_run(store, s, now, start=lambda st, se, i: started.append(i),
                      check=lambda se: None)
    return started


def test_fifo_across_a_film_and_renders_in_both_arrival_orders(store, monkeypatch):
    s = cfg()
    film = _film(store, monkeypatch, NOW - timedelta(minutes=30))
    late = _render(store, NOW - timedelta(minutes=20))
    assert _head(store, s) == ("film", film)  # the film came first: no render before it
    early = _render(store, NOW - timedelta(minutes=40))
    assert _head(store, s) == ("render", early)  # this render came before the film
    assert _film_run(store, s) == []  # the film waits for it
    store.update_render_job(early, state="done")
    assert _film_run(store, s) == [film]  # renders still queued behind it don't block it
    assert [(i["kind"], i["id"]) for i in line.waiting(store)] == [("film", film),
                                                                   ("render", late)]


def test_a_film_that_cannot_start_does_not_block_the_renders(store, monkeypatch):
    s = cfg(lemo_films_per_day=1)
    _film(store, monkeypatch, NOW - timedelta(minutes=30))
    job = _render(store, NOW - timedelta(minutes=20))
    run = store.start_agent_run("daily-learn")  # an agent run (a film too) is running
    assert _head(store, s) == ("render", job)
    store.finish_agent_run(run["id"], "succeeded")
    assert _head(store, s)[0] == "film"
    with store._tx() as c:  # today's film is made
        c.execute("INSERT INTO agent_runs (playbook, status, started_at) VALUES"
                  " ('lemo-film', 'succeeded', ?)", (to_iso(NOW - timedelta(hours=1)),))
    assert _head(store, s) == ("render", job)


def test_start_now_jumps_the_line_and_the_latest_press_goes_first(store, monkeypatch):
    s = cfg()
    a = _render(store, NOW - timedelta(minutes=50))
    film = _film(store, monkeypatch, NOW - timedelta(minutes=40))
    c = _render(store, NOW - timedelta(minutes=30))
    line.start_now(store, "render", c)
    assert _head(store, s) == ("render", c)
    line.start_now(store, "film", film)
    assert [(i["kind"], i["id"]) for i in line.waiting(store)] == [
        ("film", film), ("render", c), ("render", a)]
    line.set_timer(store, "render", a, NOW + timedelta(hours=1))
    line.start_now(store, "render", a)  # « now » clears the timer
    assert _head(store, s) == ("render", a)
    assert store.get_render_job(a)["not_before"] is None


def test_a_timer_skips_without_blocking_then_expires(store, monkeypatch):
    s = cfg()
    film = _film(store, monkeypatch, NOW - timedelta(minutes=30))
    job = _render(store, NOW - timedelta(minutes=20))
    out = line.set_timer(store, "film", film, (NOW + timedelta(hours=2)).astimezone(
        timezone(timedelta(hours=1))))  # sent in any zone, stored UTC
    assert out["not_before"] == "2026-11-17T12:00:00+00:00"
    assert _head(store, s) == ("render", job)  # the film waits, the render behind it goes
    assert _film_run(store, s) == []
    later = NOW + timedelta(hours=2, seconds=1)
    assert _head(store, s, later) == ("film", film)  # its time came: back to its place
    line.set_timer(store, "film", film, None)
    assert _head(store, s) == ("film", film)
    with pytest.raises(ValueError, match="time zone"):
        line.set_timer(store, "film", film, datetime(2026, 11, 17, 12))


def test_refused_unless_waiting(store, monkeypatch):
    job = _render(store, NOW)
    store.update_render_job(job, state="running")
    with pytest.raises(ValueError, match="Ce rendu est en cours"):
        line.start_now(store, "render", job)
    store.update_render_job(job, state="done")
    with pytest.raises(ValueError, match="terminé"):
        line.set_timer(store, "render", job, NOW)
    film = _film(store, monkeypatch, NOW)
    work_orders.skip_order(store, film, "plus besoin")
    with pytest.raises(ValueError, match="statut skipped"):
        line.start_now(store, "film", film)
    with pytest.raises(KeyError):
        line.start_now(store, "render", 999)


def test_the_planning_lists_the_line_in_the_order_the_worker_takes_it(store, monkeypatch):
    s = cfg()
    film = _film(store, monkeypatch, NOW - timedelta(minutes=30))
    r1 = _render(store, NOW - timedelta(minutes=40))
    r2 = _render(store, NOW - timedelta(minutes=20))
    r3 = _render(store, NOW - timedelta(minutes=10))
    line.set_timer(store, "render", r2, NOW + timedelta(hours=5))
    line.start_now(store, "render", r3)

    items = [i for i in planning.build_planning(store, s, NOW)["items"]
             if i["kind"] in line.KINDS]
    shown = [(i["kind"], i["ids"].get("job_id") or i["ids"]["order_id"]) for i in items]
    assert shown == [("render", r3), ("render", r1), ("film", film), ("render", r2)]
    timer = items[-1]
    assert timer["waits_on"] == "timer" and timer["not_before"] == to_iso(NOW + timedelta(hours=5))
    assert timer["est_start"] == to_iso(NOW + timedelta(hours=5))  # not before its timer
    assert items[0]["waits_on"] is None and items[1]["waits_on"] == "gpu_busy"

    taken = []  # the worker's order: claim the head, or start the film, until none is left
    for _ in range(4):
        now = NOW + timedelta(hours=6)
        kind, item_id = _head(store, s, now)
        taken.append((kind, item_id))
        if kind == "render":
            store.update_render_job(item_id, state="done")
        else:
            assert _film_run(store, s, now) == [item_id]
            work_orders.skip_order(store, item_id, "fait")
    assert taken == shown


def test_planned_ai_runs_start_after_the_chain(store, monkeypatch, tmp_path):
    d = tmp_path / "agent" / "playbooks"
    d.mkdir(parents=True)
    (d / "daily-produce.md").write_text("Run.\n")
    monkeypatch.setattr(schedule, "AGENT_DIR", tmp_path / "agent")
    s = cfg(agent_schedule="daily-produce@11:30")  # 10:30 UTC, half an hour from now
    for m in (3, 2, 1):  # three Blender renders: ~39 min of chain
        _render(store, NOW - timedelta(minutes=m), "CinematicSkit")
    later = _render(store, NOW)
    line.set_timer(store, "render", later, NOW + timedelta(hours=20))  # holds nothing back
    items = planning.build_planning(store, s, NOW)["items"]
    renders = [i for i in items if i["kind"] == "render"]
    run, = [i for i in items if i["section"] == "planned"]
    assert run["est_start"] == renders[2]["est_ready"] > to_iso(NOW + timedelta(minutes=30))
    assert renders[3]["waits_on"] == "timer"  # listed in its place, after the line


async def test_the_render_loop_claims_only_the_head_of_the_line(store, monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "keep_awake", nullcontext)
    monkeypatch.setattr(housekeeping, "disk_ok", lambda settings: True)
    film = _film(store, monkeypatch, utcnow() - timedelta(minutes=30))
    job = _render(store, utcnow() - timedelta(minutes=20))
    ran = []
    loop = asyncio.create_task(worker.render_loop(
        store, cfg(media_root=str(tmp_path)), run=lambda j: ran.append(j["id"]), interval=0.02))
    try:
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        assert ran == []  # the film came first
        line.start_now(store, "render", job)
        deadline = time.monotonic() + 5
        while not ran and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
    finally:
        loop.cancel()
        with suppress(asyncio.CancelledError):
            await loop
    assert ran == [job]
    assert work_orders.get_order(store, film)["status"] == "scheduled"


def test_a_crashed_render_keeps_its_place(store, monkeypatch):
    s = cfg()
    first = _render(store, NOW - timedelta(minutes=30))
    second = _render(store, NOW - timedelta(minutes=20))
    [claimed] = store.claim_render_jobs(1, NOW - timedelta(days=1), ids=[first])
    assert claimed["id"] == first and _head(store, s) == ("render", second)
    store.requeue_stale_render_jobs(utcnow() + timedelta(seconds=1))  # its heartbeat died
    assert _head(store, s) == ("render", first)
    assert store.claim_render_jobs(1, NOW, ids=[]) == []


def test_migration_keeps_the_old_order_by_arrival(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    monkeypatch.setattr(store_mod, "MIGRATIONS", MIGRATIONS[:MIGRATIONS.index(store_mod.LINE_SCHEMA)])
    old = CampaignStore(path)
    jobs = [_render(old, NOW - timedelta(minutes=m)) for m in (40, 10)]
    film = _film(old, monkeypatch, NOW - timedelta(minutes=20))
    old.close()
    monkeypatch.setattr(store_mod, "MIGRATIONS", MIGRATIONS)
    new = CampaignStore(path)
    try:
        assert [(i["kind"], i["id"], i["pos"], i["not_before"]) for i in line.waiting(new)] == [
            ("render", jobs[0], 0, None), ("film", film, 0, None), ("render", jobs[1], 0, None)]
    finally:
        new.close()
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    con.close()


def test_routes_are_thin_doors(store, monkeypatch):
    film = _film(store, monkeypatch, NOW)
    job = _render(store, NOW)
    with TestClient(create_app(cfg(), store=store), base_url=LOCAL,
                    headers={"Origin": LOCAL}) as tc:
        assert tc.post(f"/api/planning/film/{film}/start-now").json()["line_pos"] == -1
        r = tc.put(f"/api/planning/render/{job}/timer", json={"at": "2026-11-17T12:00:00Z"})
        assert r.json()["not_before"] == "2026-11-17T12:00:00+00:00"
        assert tc.put(f"/api/planning/render/{job}/timer", json={"at": None}).json()[
            "not_before"] is None
        store.update_render_job(job, state="running")
        r = tc.post(f"/api/planning/render/{job}/start-now")
        assert r.status_code == 422 and "en cours" in r.json()["message"]
        assert tc.post("/api/planning/render/999/start-now").status_code == 404
        assert tc.post(f"/api/planning/idea/{job}/start-now").status_code == 422


def test_a_render_on_its_timer_holds_no_agent_run_back(store):
    job = _render(store, NOW)
    assert schedule.busy(store, now=NOW) == "renders are waiting"
    line.set_timer(store, "render", job, NOW + timedelta(hours=1))
    assert schedule.busy(store, now=NOW) is None  # the due playbooks and the light run go
    assert schedule.busy(store, now=NOW + timedelta(hours=2)) == "renders are waiting"


def test_renders_next_fills_free_slots_in_line_order_and_stops_at_a_film(store, monkeypatch):
    s = cfg()
    r1 = _render(store, NOW - timedelta(minutes=50))
    timed = _render(store, NOW - timedelta(minutes=45))
    film = _film(store, monkeypatch, NOW - timedelta(minutes=40))
    r3 = _render(store, NOW - timedelta(minutes=30))
    line.set_timer(store, "render", timed, NOW + timedelta(hours=1))
    assert line.renders_next(store, s, NOW, 3) == [r1]  # the film after it goes first
    run = store.start_agent_run("daily-learn")  # the film cannot start: skipped
    assert line.renders_next(store, s, NOW, 3) == [r1, r3]
    assert line.renders_next(store, s, NOW, 1) == [r1]
    store.finish_agent_run(run["id"], "succeeded")
    line.start_now(store, "film", film)
    assert line.renders_next(store, s, NOW, 3) == []


async def test_the_render_loop_fills_both_slots_in_one_tick_in_line_order(
        store, monkeypatch, tmp_path):
    import threading

    monkeypatch.setattr(worker, "keep_awake", nullcontext)
    monkeypatch.setattr(housekeeping, "disk_ok", lambda settings: True)
    r1 = _render(store, utcnow() - timedelta(minutes=30))
    r2 = _render(store, utcnow() - timedelta(minutes=20))
    r3 = _render(store, utcnow() - timedelta(minutes=10))
    line.start_now(store, "render", r3)  # the line: r3, r1, r2
    gate, ran = threading.Event(), []

    def run(job):
        ran.append(job["id"])
        gate.wait(5)

    s = cfg(media_root=str(tmp_path), render_concurrency=2)
    loop = asyncio.create_task(worker.render_loop(store, s, run=run, interval=30))
    try:  # the next claim is 30 s away: both slots fill in the first one
        deadline = time.monotonic() + 5
        while len(ran) < 2 and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        assert sorted(ran) == sorted([r3, r1])
        assert store.get_render_job(r2)["state"] == "queued"
    finally:
        gate.set()
        loop.cancel()
        with suppress(asyncio.CancelledError):
            await loop


# --- 187: the owner's controls ------------------------------------------------------------

def _line(store):
    return [(i["kind"], i["id"]) for i in line.waiting(store)]


def _order(store, monkeypatch, at, text="Une commande"):
    monkeypatch.setattr(work_orders, "utcnow", lambda: at)
    return work_orders._insert_owner_order(store, "create", text, None)["id"]


def test_remove_takes_a_render_out_for_good_and_the_others_keep_their_place(store, monkeypatch):
    s = cfg()
    a = _render(store, NOW - timedelta(minutes=50))
    b = _render(store, NOW - timedelta(minutes=40))
    film = _film(store, monkeypatch, NOW - timedelta(minutes=30))
    c = _render(store, NOW - timedelta(minutes=20))
    line.start_now(store, "render", c)
    before = {(i["kind"], i["id"]): (i["pos"], i["arrived"]) for i in line.waiting(store)}
    asset = store.get_render_job(b)["asset_id"]
    order = _order(store, monkeypatch, NOW)
    work_orders.start(store, order, store.get_idea(store.get_asset(asset)["idea_id"]))

    assert line.remove(store, "render", b) == {"kind": "render", "id": b, "removed": True}
    assert _line(store) == [("render", c), ("render", a), ("film", film)]
    assert all(before[(i["kind"], i["id"])] == (i["pos"], i["arrived"])
               for i in line.waiting(store))  # nobody else moved
    job = store.get_render_job(b)
    assert job["state"] == "failed" and job["failure"] == line.REMOVED
    assert store.get_asset(asset)["status"] == "archived"
    got = work_orders.get_order(store, order)  # the order it was made for goes too
    assert got["status"] == "skipped" and got["skip_reason"] == line.REMOVED
    assert line.renders_next(store, s, NOW, 5) == [c, a]  # the claim never takes it
    with pytest.raises(ValueError, match="a échoué"):
        line.remove(store, "render", b)


def test_remove_keeps_an_asset_that_has_another_live_job(store):
    job = _render(store, NOW)
    asset = store.get_render_job(job)["asset_id"]
    other = store.add_render_job(asset, "another-recipe")["id"]
    line.remove(store, "render", job)
    assert store.get_asset(asset)["status"] == "rendering"
    assert store.get_render_job(other)["state"] == "queued"


def test_remove_skips_a_film_or_an_order_and_refuses_what_runs(store, monkeypatch):
    film = _film(store, monkeypatch, NOW - timedelta(minutes=10))
    order = _order(store, monkeypatch, NOW)
    for kind, oid in (("film", film), ("order", order)):
        line.remove(store, kind, oid)
        got = work_orders.get_order(store, oid)
        assert got["status"] == "skipped" and got["skip_reason"] == line.REMOVED
    assert _line(store) == []
    with pytest.raises(ValueError, match="statut skipped"):
        line.remove(store, "order", order)
    job = _render(store, NOW)
    store.update_render_job(job, state="running")
    with pytest.raises(ValueError, match="est en cours"):
        line.remove(store, "render", job)
    store.update_render_job(job, state="done")
    with pytest.raises(ValueError, match="terminé"):
        line.remove(store, "render", job)
    with pytest.raises(KeyError):
        line.remove(store, "render", 999)
    with pytest.raises(ValueError, match="kind"):
        line.remove(store, "idea", job)


def test_hold_skips_without_blocking_until_released(store, monkeypatch):
    s = cfg()
    film = _film(store, monkeypatch, NOW - timedelta(minutes=30))
    job = _render(store, NOW - timedelta(minutes=20))
    line.hold(store, "film", film, True)
    assert _head(store, s) == ("render", job)  # the one behind it goes
    assert _head(store, s, NOW + timedelta(days=3650)) == ("render", job)  # no end
    assert _film_run(store, s) == []
    items = [i for i in planning.build_planning(store, s, NOW)["items"] if i["kind"] in line.KINDS]
    assert [i["kind"] for i in items] == ["render", "film"]
    assert items[1]["waits_on"] == "held" and items[1]["est_start"] is None
    assert items[1]["not_before"] is None
    store.update_render_job(job, state="running")
    assert schedule.busy(store, now=NOW) == "renders are waiting"  # the running one
    store.update_render_job(job, state="done")
    assert schedule.busy(store, now=NOW) is None  # a held film holds no agent run back
    line.hold(store, "film", film, False)
    assert _head(store, s) == ("film", film)
    assert work_orders.get_order(store, film)["not_before"] is None


def test_move_swaps_neighbours_old_rows_and_start_now_and_the_claim_follows(store, monkeypatch):
    s = cfg()
    a = _render(store, NOW - timedelta(minutes=50))  # old rows: no line_pos
    b = _render(store, NOW - timedelta(minutes=40))
    film = _film(store, monkeypatch, NOW - timedelta(minutes=30))
    c = _render(store, NOW - timedelta(minutes=20))
    line.start_now(store, "render", c)  # c, a, b, film
    line.move(store, "render", b, -1)
    assert _line(store) == [("render", c), ("render", b), ("render", a), ("film", film)]
    line.move(store, "render", b, -1)  # past the « start now » one
    assert _line(store) == [("render", b), ("render", c), ("render", a), ("film", film)]
    assert line.renders_next(store, s, NOW, 1) == [b]
    line.move(store, "film", film, -1)
    assert line.renders_next(store, s, NOW, 3) == [b, c]  # stops at the film
    late = _render(store, NOW)  # a new arrival still goes behind
    line.start_now(store, "render", a)  # and « start now » still goes first
    assert _line(store) == [("render", a), ("render", b), ("render", c), ("film", film),
                            ("render", late)]
    items = [i for i in planning.build_planning(store, s, NOW)["items"] if i["kind"] in line.KINDS]
    assert [(i["kind"], i["ids"].get("job_id") or i["ids"]["order_id"]) for i in items] == \
        _line(store)
    assert items[1]["why_here"] == "Placé par toi dans la file."
    with pytest.raises(ValueError, match="Déjà en tête"):
        line.move(store, "render", a, -1)
    with pytest.raises(ValueError, match="Déjà en bout"):
        line.move(store, "render", late, 1)
    line.hold(store, "render", c, True)
    line.move(store, "film", film, -1)  # the held one is passed over
    assert _line(store)[1:4] == [("film", film), ("render", c), ("render", b)]
    store.update_render_job(late, state="running")
    with pytest.raises(ValueError, match="est en cours"):
        line.move(store, "render", late, -1)


def test_place_drops_an_item_anywhere_held_ones_keep_their_place(store, monkeypatch):
    s = cfg()
    a = _render(store, NOW - timedelta(minutes=50))  # old rows: no line_pos
    b = _render(store, NOW - timedelta(minutes=40))
    film = _film(store, monkeypatch, NOW - timedelta(minutes=30))
    c = _render(store, NOW - timedelta(minutes=20))
    assert line.place(store, "render", c, 0)["index"] == 0  # to the front
    assert _line(store) == [("render", c), ("render", a), ("render", b), ("film", film)]
    line.place(store, "render", c, 3)  # to the end
    assert _line(store) == [("render", a), ("render", b), ("film", film), ("render", c)]
    line.hold(store, "render", b, True)
    line.place(store, "render", a, 1)  # past the held one: index counts the not held only
    assert _line(store) == [("render", b), ("film", film), ("render", a), ("render", c)]
    line.place(store, "render", c, 0)  # the head of the not held: the held one stays first
    assert _line(store) == [("render", b), ("render", c), ("film", film), ("render", a)]
    late = _render(store, NOW)  # a new arrival still goes behind
    assert _line(store)[-1] == ("render", late)
    items = [i for i in planning.build_planning(store, s, NOW)["items"] if i["kind"] in line.KINDS]
    assert [i["line_index"] for i in items] == [0, 1, 2, 3, None]  # the held one: listed last
    with pytest.raises(ValueError, match="between 0 and 3"):
        line.place(store, "render", c, 4)
    store.update_render_job(late, state="running")
    with pytest.raises(ValueError, match="est en cours"):
        line.place(store, "render", late, 0)
    with pytest.raises(KeyError):
        line.place(store, "film", 999, 0)


def test_pause_stops_the_film_and_the_runs_and_resumes(store, monkeypatch):
    s = cfg()
    monkeypatch.setattr(schedule, "preflight", lambda settings: None)
    film = _film(store, monkeypatch, NOW - timedelta(minutes=30))
    films, runs = [], []
    since = line.pause(store, True)["paused"]
    assert line.pause(store, True)["paused"] == since  # pressed again: the same pause
    assert schedule.catch_up(store, s, now=lambda: NOW,
                             start_film=lambda st, se, i: films.append(i)) == []
    monkeypatch.setattr(schedule, "due_runs", lambda *a: ["daily-produce"])
    assert schedule.run_due(store, s, run=lambda st, se, p: runs.append(p)) == []
    assert planning.build_planning(store, s, NOW)["paused"] == since
    assert films == runs == []
    assert line.pause(store, False) == {"paused": None}
    assert schedule.run_due(store, s, run=lambda st, se, p: runs.append(p) or p) == [
        "daily-produce"]
    monkeypatch.setattr(schedule, "due_runs", lambda *a: [])
    assert schedule.catch_up(store, s, now=lambda: NOW,
                             start_film=lambda st, se, i: films.append(i)) == [f"film {film}"]


async def test_the_render_loop_claims_nothing_while_paused(store, monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "keep_awake", nullcontext)
    monkeypatch.setattr(housekeeping, "disk_ok", lambda settings: True)
    job = _render(store, utcnow() - timedelta(minutes=20))
    line.pause(store, True)
    ran = []
    loop = asyncio.create_task(worker.render_loop(
        store, cfg(media_root=str(tmp_path)), run=lambda j: ran.append(j["id"]), interval=0.02))
    try:
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        assert ran == [] and store.get_render_job(job)["state"] == "queued"
        line.pause(store, False)  # the next tick takes it
        deadline = time.monotonic() + 5
        while not ran and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
    finally:
        loop.cancel()
        with suppress(asyncio.CancelledError):
            await loop
    assert ran == [job]


async def test_the_pause_shows_an_alert_on_every_page(store):
    s = cfg()
    assert not [a for a in await alerts.alerts(store, s, NOW) if a["kind"] == "studio_paused"]
    line.pause(store, True)
    [a] = [a for a in await alerts.alerts(store, s, NOW) if a["kind"] == "studio_paused"]
    assert a["title"] == "Studio en pause : rien ne démarre" and a["link"] == "/planning"


def test_the_control_routes_are_thin_doors(store, monkeypatch):
    film = _film(store, monkeypatch, NOW - timedelta(minutes=10))
    job = _render(store, NOW)
    order = _order(store, monkeypatch, NOW)
    with TestClient(create_app(cfg(), store=store), base_url=LOCAL,
                    headers={"Origin": LOCAL}) as tc:
        assert tc.post(f"/api/planning/render/{job}/move", json={"by": -1}).json()[
            "line_pos"] == 1
        assert tc.put(f"/api/planning/film/{film}/hold", json={"held": True}).json()["held"]
        assert tc.post(f"/api/planning/render/{job}/move", json={"by": 2}).status_code == 422
        r = tc.post(f"/api/planning/render/{job}/move", json={"by": -1})
        assert r.status_code == 422 and "Déjà en tête" in r.json()["message"]
        assert tc.post(f"/api/planning/order/{order}/remove").json()["removed"]
        assert tc.post(f"/api/planning/order/{order}/move", json={"by": 1}).status_code == 422
        assert tc.post(f"/api/planning/render/{job}/place", json={"index": 0}).json()[
            "index"] == 0
        r = tc.post(f"/api/planning/render/{job}/place", json={"index": 5})
        assert r.status_code == 422 and "between 0 and" in r.json()["message"]
        assert tc.post("/api/planning/render/999/place", json={"index": 0}).status_code == 404
        assert tc.post("/api/planning/render/999/remove").status_code == 404
        assert tc.put("/api/planning/pause", json={"paused": True}).json()["paused"]
        assert tc.get("/api/planning").json()["paused"]
        assert tc.put("/api/planning/pause", json={"paused": False}).json() == {"paused": None}


# --- step 192: audit fixes ------------------------------------------------------------------
def _film_render(store, monkeypatch):
    """A running film's own render: its Lemo order in_production, its job queued."""
    order = _film(store, monkeypatch, NOW - timedelta(minutes=60))
    idea = store.add_idea("motion", hook="Un film", style="lemo:watercolor",
                          batch_date="2026-11-17")
    work_orders.start(store, order, idea)
    asset = store.add_asset(idea["id"], batch_date="2026-11-17")
    return store.add_render_job(asset["id"], f"film{asset['id']}")["id"]


def test_a_films_own_render_refuses_hold_timer_and_remove(store, monkeypatch):
    other = _render(store, NOW - timedelta(minutes=30))
    job = _film_render(store, monkeypatch)
    assert line.film_renders(store) == [job]
    for act in (lambda: line.hold(store, "render", job, True),
                lambda: line.set_timer(store, "render", job, NOW + timedelta(hours=1)),
                lambda: line.remove(store, "render", job)):
        with pytest.raises(ValueError, match="film en cours"):
            act()
    assert store.get_render_job(job)["state"] == "queued"
    assert store.get_render_job(job)["not_before"] is None
    line.hold(store, "render", other, True)  # the others as before
    line.start_now(store, "render", job)  # what register_film does


async def test_the_pause_lets_a_running_films_own_render_through(store, monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "keep_awake", nullcontext)
    monkeypatch.setattr(housekeeping, "disk_ok", lambda settings: True)
    other = _render(store, utcnow() - timedelta(minutes=30))
    job = _film_render(store, monkeypatch)
    line.pause(store, True)
    ran = []
    loop = asyncio.create_task(worker.render_loop(
        store, cfg(media_root=str(tmp_path)), run=lambda j: ran.append(j["id"]), interval=0.02))
    try:
        deadline = time.monotonic() + 5
        while not ran and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.2)
    finally:
        loop.cancel()
        with suppress(asyncio.CancelledError):
            await loop
    assert ran == [job] and store.get_render_job(other)["state"] == "queued"


def test_a_re_render_of_the_same_recipe_is_a_new_arrival(store):
    from src.studio import render
    from src.studio.assets import transition

    job = _render(store, NOW - timedelta(days=4))
    asset = store.get_render_job(job)["asset_id"]
    store.update_render_job(job, state="failed")
    with store._tx() as c:  # an old « start now » and a hold it kept
        c.execute("UPDATE render_jobs SET line_pos=-5, not_before=? WHERE id=?",
                  (line.HELD, job))
    with store._tx() as c:
        c.execute("UPDATE assets SET status='failed' WHERE id=?", (asset,))
    transition(store, asset, "rendering", actor="agent")
    later = _render(store, NOW - timedelta(days=1))
    again = render.enqueue_render(store, asset, key=f"k{asset}")
    assert again["id"] == job and again["state"] == "queued" and again["requeues"] == 1
    assert again["line_pos"] is None and again["not_before"] is None
    assert again["created_at"] > to_iso(NOW)
    assert _line(store) == [("render", later), ("render", job)]


def test_a_crashed_render_keeps_its_place_after_a_move(store):
    s = cfg()
    a, b, c = (_render(store, NOW - timedelta(minutes=m)) for m in (30, 20, 10))
    store.claim_render_jobs(1, NOW - timedelta(days=1), ids=[a])
    line.move(store, "render", c, -1)  # b and c placed: 1, 2
    assert _line(store) == [("render", c), ("render", b)]
    store.requeue_stale_render_jobs(utcnow() + timedelta(seconds=1))  # its heartbeat died
    assert _line(store) == [("render", a), ("render", c), ("render", b)]
    assert _head(store, s) == ("render", a)


def test_two_start_now_at_once_get_distinct_places(tmp_path):
    import threading

    path = str(tmp_path / "line.db")
    first = CampaignStore(path)
    jobs = [_render(first, NOW - timedelta(minutes=m)) for m in range(40)]
    second = CampaignStore(path)
    go, got = threading.Barrier(2), []

    def press(store, mine):
        go.wait()
        got.extend(line.start_now(store, "render", j)["line_pos"] for j in mine)

    try:
        threads = [threading.Thread(target=press, args=(st, jobs[n::2]))
                   for n, st in enumerate((first, second))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        first.close()
        second.close()
    assert len(got) == len(jobs) == len(set(got))


def test_a_lemo_style_is_case_sensitive(store, monkeypatch):
    film = _film(store, monkeypatch, NOW)
    with store._tx() as c:
        c.execute("UPDATE work_orders SET style='LEMO:watercolor' WHERE id=?", (film,))
    assert _line(store) == []  # lemo.is_lemo says no: not a film
