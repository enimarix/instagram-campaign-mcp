"""Step 185: the read-only Planning chain (src/studio/planning.py, GET /api/planning)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.agent import runs, schedule
from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.store import parse_iso, to_iso
from src.studio import planning, work_orders

from .conftest import LOCAL

UTC = timezone.utc
NOW = datetime(2026, 11, 17, 10, tzinfo=UTC)  # 11:00 in Paris
MIDNIGHT = datetime(2026, 11, 17, 23, tzinfo=UTC)  # the next Paris midnight


@pytest.fixture
def agent_dir(tmp_path, monkeypatch):
    d = tmp_path / "agent"
    (d / "playbooks").mkdir(parents=True)
    for name in ("daily-learn", "daily-produce", "daily-revise"):
        (d / "playbooks" / f"{name}.md").write_text("Run.\n")
    monkeypatch.setattr(schedule, "AGENT_DIR", d)
    monkeypatch.setattr(runs, "AGENT_DIR", d)
    return d


def cfg(**kw):
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                                database_path=":memory:",
                                **{"timezone": "Europe/Paris", "agent_schedule": "", **kw})


def _order(store, monkeypatch, text, style=None, minutes_ago=10):
    monkeypatch.setattr(work_orders, "utcnow", lambda: NOW - timedelta(minutes=minutes_ago))
    return work_orders._insert_owner_order(store, "create", text, style)["id"]


def _job(store, template, state, created_at=None, **fields):
    idea = store.add_idea("motion", hook=f"Idée {template}", batch_date="2026-11-17")
    recipe = {"kind": "motion", "template": template, "props": {}}
    asset = store.add_asset(idea["id"], batch_date="2026-11-17", recipe=recipe)
    job = store.add_render_job(asset["id"], f"k{asset['id']}")
    store.update_render_job(job["id"], state=state, **fields)
    if created_at:  # the line's arrival
        with store._tx() as c:
            c.execute("UPDATE render_jobs SET created_at=? WHERE id=?", (created_at, job["id"]))
    return asset["id"]


def _run(store, playbook, started, minutes=None):
    run = store.start_agent_run(playbook)
    if minutes is not None:
        store.finish_agent_run(run["id"], "succeeded")
    with store._tx() as c:
        c.execute("UPDATE agent_runs SET started_at=?, finished_at=? WHERE id=?",
                  (to_iso(started), minutes is not None and to_iso(
                      started + timedelta(minutes=minutes)) or None, run["id"]))
    return run["id"]


def _timed(items):
    return [i for i in items if i["est_start"]]


def test_chain_follows_the_worker_order_and_each_start_is_the_last_ready(
        store, agent_dir, monkeypatch):
    s = cfg(agent_schedule="daily-learn@10:00,daily-produce@03:00")
    _run(store, "daily-produce", NOW - timedelta(hours=7), minutes=20)  # ran tonight
    _job(store, "CinematicSkit", "done", render_ms=600_000)  # a real Blender render: 600 s
    running = _job(store, "FactQuest", "running", progress=0.5,
                   started_at=to_iso(NOW - timedelta(seconds=60)))
    queued = _job(store, "CinematicSkit", "queued", created_at=to_iso(NOW - timedelta(hours=1)))
    film = _order(store, monkeypatch, "Un film", "lemo:watercolor")
    mine = _order(store, monkeypatch, "Pourquoi on a faim le soir")
    with store._tx() as c:  # a DM'd Reel without a note waits for the owner
        c.execute("INSERT INTO dm_picks (message_id, sender_username, reel_url, received_at,"
                  " created_at, updated_at) VALUES ('m1', 'x', 'https://www.instagram.com/"
                  "reel/A/', ?, ?, ?)", (to_iso(NOW),) * 3)
        work_orders.add_for_pick(c, 1, None, False, to_iso(NOW))

    items = planning.build_planning(store, s, NOW)["items"]
    got = [(i["section"], i["kind"], i["ids"].get("asset_id") or i["ids"].get("order_id"))
           for i in items]
    assert got[:6] == [("running", "render", running), ("next", "render", queued),
                       ("next", "film", film), ("next", "agent_run", None),
                       ("next", "order_run", None), ("next", "work_order", mine)]
    assert items[3]["title"] == "Run daily-learn"  # due at 10:00, not started: after the line
    assert got[6][1] == "work_order" and items[6]["waits_on"] == "needs_instruction"
    assert items[6]["est_start"] is None
    # the running render: halfway after 60 s -> 60 s left
    assert parse_iso(items[0]["est_ready"]) == NOW + timedelta(seconds=60)
    assert items[0]["stage"] == "rendu" and items[0]["progress"] == 0.5
    assert items[1]["est_duration_s"] == 600 and items[1]["engine"] == "blender"
    nxt = _timed(i for i in items if i["section"] != "planned")
    for before, after in zip(nxt, nxt[1:]):
        assert after["est_start"] == before["est_ready"]
    assert all(i["waits_on"] == "gpu_busy" for i in items[1:6])
    assert all(i["estimated"] for i in items)
    # planned: tomorrow 03:00 and 10:00 Paris, the producing run's ETA from its real run
    planned = [i for i in items if i["section"] == "planned"]
    assert [i["title"] for i in planned] == ["Run daily-produce", "Run daily-learn"]
    assert parse_iso(planned[0]["est_start"]) == datetime(2026, 11, 18, 2, tzinfo=UTC)
    assert planned[0]["est_duration_s"] == 1200


def test_waits_on_grace_daily_cap_and_a_running_run(store, agent_dir, monkeypatch):
    s = cfg(order_run_debounce_minutes=3, max_order_runs_per_day=6, lemo_films_per_day=1)
    _order(store, monkeypatch, "Tout de suite", minutes_ago=1)
    run, = [i for i in planning.build_planning(store, s, NOW)["items"]
            if i["kind"] == "order_run"]
    assert run["waits_on"] == "order_grace"
    assert parse_iso(run["est_start"]) == NOW + timedelta(minutes=2)

    store.set_state("order_runs", {"day": "2026-11-17", "count": 6})
    _run(store, "lemo-film", NOW - timedelta(hours=2), minutes=40)  # today's one film
    _order(store, monkeypatch, "Un film", "lemo:watercolor", minutes_ago=30)
    items = planning.build_planning(store, s, NOW + timedelta(minutes=5))["items"]
    film = next(i for i in items if i["kind"] == "film")
    assert film["waits_on"] == "daily_cap" and parse_iso(film["est_start"]) == MIDNIGHT
    assert film["est_duration_s"] == 2400
    run = next(i for i in items if i["kind"] == "order_run")
    assert run["waits_on"] == "daily_cap" and parse_iso(run["est_start"]) >= MIDNIGHT

    store.set_state("order_runs", None)
    _run(store, "daily-learn", NOW)  # running: nothing new starts before it ends
    items = planning.build_planning(store, s, NOW + timedelta(minutes=5))["items"]
    assert items[0]["section"] == "running" and items[0]["kind"] == "agent_run"
    assert next(i for i in items if i["kind"] == "order_run")["waits_on"] == "agent_running"


def test_no_order_no_light_run(store, agent_dir):
    assert planning.build_planning(store, cfg(), NOW)["items"] == []


def test_producing_run_says_what_it_picks_up_first(store, agent_dir, monkeypatch):
    s = cfg(agent_schedule="daily-produce@03:00", batch_size=10)
    _order(store, monkeypatch, "Un")
    _order(store, monkeypatch, "Deux")
    _order(store, monkeypatch, "Un film", "lemo:watercolor")  # the film runner's, not the batch's
    sent_back = _job(store, "FactQuest", "done")
    with store._tx() as c:
        c.execute("UPDATE assets SET status='revision_requested' WHERE id=?", (sent_back,))
    items = planning.build_planning(store, s, NOW)["items"]
    produce, = [i for i in items if i["section"] == "planned"]
    assert produce["picks_up"] == {"orders": 2, "change_requests": 1, "dm_picks": 0,
                                   "ideas_left": 7}
    assert any(i["kind"] == "change_request" and i["ids"] == {"asset_id": sent_back}
               for i in items)


def test_route_is_a_thin_door_behind_the_login(store, agent_dir):
    with TestClient(create_app(cfg(), store=store), base_url=LOCAL,
                    headers={"Origin": LOCAL}) as tc:
        body = tc.get("/api/planning").json()
    assert body["items"] == [] and parse_iso(body["now"])
    with TestClient(create_app(cfg(ui_password="secret-pass-1234"), store=store),
                    base_url=LOCAL) as tc:
        assert tc.get("/api/planning").status_code == 401


def test_an_order_the_last_run_left_waits_for_the_next_run(store, agent_dir, monkeypatch):
    s = cfg(agent_schedule="daily-produce@03:00")
    _run(store, "daily-produce", NOW - timedelta(hours=7), minutes=20)
    mine = _order(store, monkeypatch, "Plus tard", minutes_ago=60)
    _run(store, "daily-revise", NOW - timedelta(minutes=30), minutes=5)  # saw it, left it
    items = planning.build_planning(store, s, NOW)["items"]
    assert not any(i["kind"] == "order_run" for i in items)
    order = next(i for i in items if i["ids"].get("order_id") == mine)
    assert order["waits_on"] == "next_ai_run"
    assert parse_iso(order["est_start"]) == datetime(2026, 11, 18, 2, tzinfo=UTC)
