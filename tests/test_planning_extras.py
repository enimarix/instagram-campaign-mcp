"""Step 190: around the Planning chain: the 24 h strip, late running items, the supply
gauge, today's history and the delay warning (src/studio/planning.py)."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.store import to_iso
from src.studio import line, planning, work_orders

from .conftest import LOCAL
from .test_line import _film, _render
from .test_planning import NOW, _job, _run, cfg


def _video(store, status, verdict="none", template="FactQuest", **fields):
    idea = store.add_idea("motion", hook="Une vidéo", batch_date="2026-11-17")
    asset = store.add_asset(idea["id"], batch_date="2026-11-17",
                            recipe={"kind": "motion", "template": template, "props": {}})
    with store._tx() as c:
        c.execute("UPDATE assets SET status=?, verdict=? WHERE id=?", (status, verdict, asset["id"]))
    if fields:
        store.update_asset(asset["id"], **fields)
    return asset["id"]


def test_strip_blocks_from_the_etas_clipped_to_24_h_with_the_queued_posts(store):
    s = cfg(agent_schedule="daily-produce@03:00")
    _run(store, "daily-produce", NOW - timedelta(hours=7), minutes=20)  # ran tonight
    _job(store, "FactQuest", "running", progress=0.5, started_at=to_iso(NOW - timedelta(minutes=2)))
    _render(store, NOW - timedelta(minutes=5), "CinematicSkit")
    store.schedule("reel", {}, NOW + timedelta(hours=3))
    store.schedule("reel", {}, NOW + timedelta(hours=30))  # past the strip
    p = planning.build_planning(store, s, NOW)
    strip = p["strip"]
    assert strip["start"] == to_iso(NOW) and strip["end"] == to_iso(NOW + timedelta(hours=24))
    assert [(b["lane"], b["section"]) for b in strip["blocks"]] == [
        ("render", "running"), ("render", "next"), ("run", "planned")]
    assert strip["blocks"][0]["start"] == to_iso(NOW)  # started before now: clipped
    assert strip["blocks"][1]["start"] == strip["blocks"][0]["end"]  # chained
    assert strip["blocks"][2]["start"] == to_iso(NOW + timedelta(hours=16))  # 03:00 Paris
    assert strip["posts"] == [to_iso(NOW + timedelta(hours=3))]


def test_a_running_item_past_its_usual_time_is_late(store):
    s = cfg()
    _job(store, "FactQuest", "running", progress=0.9, started_at=to_iso(NOW - timedelta(minutes=5)))
    run = _run(store, "daily-learn", NOW - timedelta(minutes=10))  # usual: RUN_S, 15 min
    items = planning.build_planning(store, s, NOW)["items"]
    render, agent = [i for i in items if i["section"] == "running"]
    assert render["late_s"] == 300 - 24  # Remotion's usual 24 s
    assert agent["late_s"] is None and agent["ids"]["run_id"] == run
    items = planning.build_planning(store, s, NOW + timedelta(minutes=20))["items"]
    agent = next(i for i in items if i["kind"] == "agent_run")
    assert agent["late_s"] == 15 * 60
    p = planning.build_planning(store, s, NOW + timedelta(minutes=20))
    assert any(b["late"] for b in p["strip"]["blocks"])


def test_supply_counts_approved_and_bench_against_posts_per_day(store):
    s = cfg(max_posts_per_day=3)
    _video(store, "approved")
    _video(store, "scheduled")
    _video(store, "ready", "liked")
    _video(store, "ready", "liked", best_before="2026-11-16")  # stale: not counted
    _video(store, "ready")  # not liked: not on the bench
    _render(store, NOW - timedelta(minutes=5))  # the line will add it
    sup = planning.build_planning(store, s, NOW)["supply"]
    assert sup == {"approved": 2, "bench": 1, "per_day": 3, "days": 1.0, "until": "2026-11-18",
                   "low": False, "making": 1, "ideas": 0}
    with store._tx() as c:
        c.execute("UPDATE assets SET status='published' WHERE status='scheduled'")
    sup = planning.build_planning(store, s, NOW)["supply"]
    assert sup["days"] == 0.7 and sup["low"] and sup["until"] == "2026-11-17"


def test_history_lists_today_newest_first_and_only_failures_can_rerender(store, monkeypatch):
    s = cfg()
    yesterday = to_iso(NOW - timedelta(hours=12))  # 23:00 Paris the day before
    today = to_iso(NOW - timedelta(hours=1))
    _job(store, "FactQuest", "done", finished_at=yesterday)
    done = _job(store, "FactQuest", "done", finished_at=to_iso(NOW - timedelta(hours=3)))
    failed = _job(store, "FactQuest", "failed", failure="ffmpeg crashed", finished_at=today)
    with store._tx() as c:
        c.execute("UPDATE assets SET status='failed' WHERE id=?", (failed,))
    older = store.add_render_job(failed, "an older recipe")  # the same video failed before
    store.update_render_job(older["id"], state="failed", failure="boom",
                            finished_at=to_iso(NOW - timedelta(hours=2, minutes=30)))
    removed = _render(store, NOW - timedelta(hours=2))
    monkeypatch.setattr(line, "utcnow", lambda: NOW - timedelta(minutes=30))
    line.remove(store, "render", removed)
    dropped = _video(store, "ready", agent_decision={
        "kind": "dropped", "why": "image floue", "at": to_iso(NOW - timedelta(minutes=20))})
    order = _film(store, monkeypatch, NOW - timedelta(hours=4))
    made = _film(store, monkeypatch, NOW - timedelta(hours=4))  # the removed render's order
    for o in (order, made):
        work_orders.skip_order(store, o, line.REMOVED)
    with store._tx() as c:
        c.execute("UPDATE work_orders SET updated_at=? WHERE id IN (?, ?)",
                  (to_iso(NOW - timedelta(minutes=10)), order, made))
        c.execute("UPDATE work_orders SET idea_id = (SELECT a.idea_id FROM render_jobs j JOIN"
                  " assets a ON a.id = j.asset_id WHERE j.id = ?) WHERE id = ?", (removed, made))
    run = _run(store, "daily-produce", NOW - timedelta(hours=7), minutes=20)
    _run(store, "daily-learn", NOW - timedelta(hours=13), minutes=5)  # yesterday
    rows = planning.build_planning(store, s, NOW)["history"]
    assert [(r["kind"], r["asset_id"] or r["order_id"] or r["run_id"]) for r in rows] == [
        ("removed", order), ("dropped", dropped), ("removed", store.get_render_job(removed)[
            "asset_id"]), ("failed", failed), ("done", done), ("run", run)]  # one row per video
    by = {r["kind"]: r for r in rows}
    assert by["failed"]["reason"] == "ffmpeg crashed" and by["failed"]["recipe"]["kind"] == "motion"
    assert by["failed"]["tries"] == 2 and by["done"]["tries"] is None
    assert by["done"]["recipe"] is None and by["dropped"]["reason"] == "image floue"
    assert by["run"]["status"] == "succeeded" and by["run"]["title"] == "Run daily-produce"


def test_history_one_row_per_failed_video_each_can_be_relaunched(store):
    """Step 195: two videos that failed twice each are two rows, both with « Relancer »."""
    videos = []
    for n in range(2):
        first = _job(store, "FactQuest", "failed", failure="boom",
                     finished_at=to_iso(NOW - timedelta(hours=3, minutes=n)))
        again = store.add_render_job(first, f"again {n}")
        store.update_render_job(again["id"], state="failed", failure=f"crash {n}",
                                finished_at=to_iso(NOW - timedelta(hours=2, minutes=n)))
        with store._tx() as c:
            c.execute("UPDATE assets SET status='failed' WHERE id=?", (first,))
        videos.append(first)
    rows = planning.build_planning(store, cfg(), NOW)["history"]
    assert [(r["asset_id"], r["reason"], r["tries"], bool(r["recipe"])) for r in rows] == [
        (videos[0], "crash 0", 2, True), (videos[1], "crash 1", 2, True)]


def test_history_tries_count_the_relaunches_not_the_machine_retries(store):
    """Audit 200 #18: « Relancer » reuses the job's row (requeues); a requeue after the
    machine gave up (render.enqueue_render: count=False) is not the video's try."""
    video = _job(store, "FactQuest", "failed", failure="boom",
                 finished_at=to_iso(NOW - timedelta(hours=3)))
    job = store.list_render_jobs(asset_id=video)[0]["id"]
    for count in (True, True, False):  # two relaunches, one after a machine failure
        store.requeue_render_job(job, count=count)
        store.update_render_job(job, state="failed", failure="crash",
                                finished_at=to_iso(NOW - timedelta(hours=1)))
    [row] = planning.build_planning(store, cfg(), NOW)["history"]
    assert (row["asset_id"], row["tries"]) == (video, 3)


def _ahead(store, s):
    return planning.build_planning(store, s, NOW)["items"]


def test_preview_says_what_a_start_now_or_a_move_pushes_back_and_changes_nothing(
        store, monkeypatch):
    s = cfg()
    a = _render(store, NOW - timedelta(minutes=50))
    b = _render(store, NOW - timedelta(minutes=40), "CinematicSkit")  # Blender: 786 s
    c = _render(store, NOW - timedelta(minutes=30), "CinematicSkit")
    before = _ahead(store, s)
    got = planning.preview(store, s, NOW, "start_now", "render", c)
    assert [(p["kind"], p["by_s"]) for p in got["pushed"]] == [("render", 786), ("render", 786)]
    assert _ahead(store, s) == before  # the real line is untouched
    assert planning.preview(store, s, NOW, "move", "render", b, 1)["pushed"] == [
        {"kind": "render", "title": "Une vidéo", "by_s": 786}]  # b itself, behind c
    assert planning.preview(store, s, NOW, "move", "render", b, -1)["pushed"] == [
        {"kind": "render", "title": "Une vidéo", "by_s": 786}]  # a, behind b
    with pytest.raises(ValueError, match="Déjà en tête"):
        planning.preview(store, s, NOW, "move", "render", a, -1)
    with pytest.raises(KeyError):
        planning.preview(store, s, NOW, "start_now", "render", 999)
    with pytest.raises(ValueError, match="action"):
        planning.preview(store, s, NOW, "remove", "render", a)


def test_preview_of_releasing_an_idea_with_start_now(store, monkeypatch):
    s = cfg()
    monkeypatch.setattr(planning.planned, "cards", lambda store: [])  # its card: 188b's tests
    _render(store, NOW - timedelta(minutes=50))
    idea = _video(store, "planned", template="CinematicSkit")
    got = planning.preview(store, s, NOW, "release", "idea", idea)
    assert got == {"pushed": [{"kind": "render", "title": "Une vidéo", "by_s": 786}]}
    assert store.get_asset(idea)["status"] == "planned"


def test_preview_route(store):
    _render(store, NOW - timedelta(minutes=50))
    b = _render(store, NOW - timedelta(minutes=40), "CinematicSkit")
    with TestClient(create_app(cfg(), store=store), base_url=LOCAL) as client:
        got = client.post("/api/planning/preview", json={"action": "start_now", "kind": "render",
                                                         "id": b})
        assert got.status_code == 200 and len(got.json()["pushed"]) == 1
        assert client.post("/api/planning/preview", json={
            "action": "start_now", "kind": "render", "id": 999}).status_code == 404
        p = client.get("/api/planning").json()
        assert {"strip", "supply", "history"} <= set(p)
