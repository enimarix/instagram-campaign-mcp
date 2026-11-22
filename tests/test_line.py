"""Step 186: one heavy line, first in first out (src/studio/line.py), « start now » and the
timer; the render claim, the film start and the Planning page follow it."""

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
from src.studio import housekeeping, line, planning, work_orders

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
    monkeypatch.setattr(store_mod, "MIGRATIONS", MIGRATIONS[:-1])
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
