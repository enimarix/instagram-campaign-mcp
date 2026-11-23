"""Step 196: « Lancer maintenant », one card or many (planning.launch, POST
/api/planning/launch), the launch requests catch_up honours first, and the light run on a
selection (its packet cut to it)."""

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from src.agent import packet, schedule
from src.api.app import create_app
from src.store import parse_iso, to_iso
from src.studio import line, planned, planning
from src.studio.feedback import add_comment

from .conftest import LOCAL
from .test_agent_packet import _asset
from .test_planning import NOW, _checkable, _job, _order, _run, agent_dir, cfg  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("agent_dir")


def _job_id(store, asset_id):
    return store.list_render_jobs(asset_id=asset_id)[0]["id"]


def _launch(store, s, *items):
    return planning.launch(store, s, [{"kind": k, "id": i} for k, i in items], NOW)


def test_renders_films_and_ideas_go_to_the_front_in_on_screen_order(
        store, monkeypatch):
    s = cfg()
    a, b, c = (_job_id(store, _job(store, "FactQuest", "queued")) for _ in range(3))
    film = _order(store, monkeypatch, "Un film", "lemo:watercolor")
    released = []
    monkeypatch.setattr(planned, "release", lambda st, se, asset_id, now: released.append(
        (asset_id, now)))
    out = _launch(store, s, ("render", c), ("film", film), ("claude_idea", 9), ("render", b))
    assert out["front"] == [{"kind": "render", "id": c}, {"kind": "film", "id": film},
                            {"kind": "claude_idea", "id": 9}, {"kind": "render", "id": b}]
    assert released == [(9, True)] and out["requested"] == out["refused"] == []
    assert [(i["kind"], i["id"]) for i in line.waiting(store)] == [
        ("render", c), ("film", film), ("render", b), ("render", a)]
    assert schedule.launch_requests(store) == [] and out["busy"] is None


def test_orders_change_requests_and_runs_become_launch_requests(store, monkeypatch):
    s = cfg()
    mine = _order(store, monkeypatch, "Pourquoi on a faim")
    other = _order(store, monkeypatch, "Une autre")
    parked = _asset(store)
    add_comment(store, parked, text="plus court", wants_changes=True)
    store.update_asset(parked, agent_decision={"kind": "waiting", "why": "erreur de rendu",
                                               "at": to_iso(NOW - timedelta(hours=8))})
    out = _launch(store, s, ("work_order", mine), ("change_request", parked),
                  ("agent_run", "daily-learn"))
    assert out["front"] == [] and out["refused"] == []
    assert out["requested"] == [{"kind": "work_order", "id": mine},
                                {"kind": "change_request", "id": parked},
                                {"kind": "agent_run", "id": "daily-learn"}]
    assert [(r["playbook"], r["only"]) for r in schedule.launch_requests(store)] == [
        ("daily-revise", {"order_ids": [mine], "asset_ids": [parked]}), ("daily-learn", None)]
    # a second launch joins the waiting request; the cards say they wait for the machine
    _launch(store, s, ("work_order", other))
    assert schedule.launch_requests(store)[0]["only"]["order_ids"] == sorted([mine, other])
    items = planning.build_planning(store, cfg(agent_schedule="daily-learn@03:00"), NOW)["items"]
    flags = {(i["kind"], i["ids"].get("order_id") or i["ids"].get("asset_id") or i["playbook"]):
             i["launch_requested"] for i in items if i["section"] == "next"}
    assert flags[("work_order", mine)] and flags[("change_request", parked)]
    assert flags[("agent_run", "daily-learn")]
    assert not any(i["launch_requested"] for i in items if i["section"] == "planned")  # tomorrow's


def test_refusals_say_why_and_the_rest_still_goes(store, monkeypatch):
    s = cfg()
    running = _job_id(store, _job(store, "FactQuest", "running"))
    done = _job_id(store, _job(store, "FactQuest", "done"))
    ok = _job_id(store, _job(store, "FactQuest", "queued"))
    mine = _order(store, monkeypatch, "Ma commande")
    with store._tx() as c:
        c.execute("UPDATE work_orders SET status = 'needs_instruction' WHERE id = ?", (mine,))
    _run(store, "daily-learn", NOW - timedelta(minutes=5))  # still running
    out = _launch(store, s, ("render", running), ("render", done), ("render", 999),
                  ("work_order", mine), ("change_request", _asset(store)),
                  ("agent_run", "daily-learn"), ("agent_run", "nope"), ("party", 1),
                  ("render", "6"), ("render", ok))
    assert out["front"] == [{"kind": "render", "id": ok}]
    why = {(r["kind"], r["id"]): r["message"] for r in out["refused"]}
    assert "en cours" in why[("render", running)] and "terminé" in why[("render", done)]
    assert why[("render", 999)] == "Introuvable."
    assert "consigne" in why[("work_order", mine)]
    assert "n'attend pas de changement" in next(m for (k, _), m in why.items()
                                                if k == "change_request")
    assert "déjà en cours" in why[("agent_run", "daily-learn")]
    assert "unknown playbook" in why[("agent_run", "nope")]
    assert "ne se lance pas" in why[("party", 1)] and "nombre" in why[("render", "6")]
    assert len(out["refused"]) == 9 and schedule.launch_requests(store) == []


def test_catch_up_honours_a_request_first_once_the_machine_is_free_never_while_paused(
        store, monkeypatch):
    s = cfg(agent_schedule="daily-produce@03:00")  # due: the request still goes first
    started = []

    def start(st, se, playbook):
        started.append(playbook)

    queued = _job(store, "FactQuest", "queued")  # the line is busy: the request waits
    schedule.request_launch(store, "daily-learn", NOW)
    assert schedule.catch_up(store, s, start=start, now=lambda: NOW) == []
    line.pause(store, True)
    store.update_render_job(_job_id(store, queued), state="done")
    assert schedule.catch_up(store, s, start=start, now=lambda: NOW) == []  # paused: kept
    assert [r["playbook"] for r in schedule.launch_requests(store)] == ["daily-learn"]
    line.pause(store, False)
    assert schedule.catch_up(store, s, start=start, now=lambda: NOW) == ["daily-learn"]
    assert started == ["daily-learn"] and schedule.launch_requests(store) == []


def test_a_request_whose_run_is_already_running_is_kept(store):
    from src.agent.runner import AgentRunRefused

    schedule.request_launch(store, "daily-revise", NOW, order_ids=[3])

    def refused(*a):
        raise AgentRunRefused("already running")

    assert schedule.launched(store, cfg(), NOW, start=refused) is None
    assert schedule.launch_requests(store)[0]["only"] == {"order_ids": [3], "asset_ids": []}
    assert store.get_state(packet.SCOPE_KEY) is None  # no stale scope for the next run


def test_a_start_that_raises_drops_the_request_said_with_no_stale_scope(store):
    # 199 (#14): never lost silently, never a scope the next light run would take
    from src.studio import alerts

    schedule.request_launch(store, "daily-revise", NOW, order_ids=[3])

    def broken(*a):
        raise OSError("python.exe introuvable")

    assert schedule.launched(store, cfg(), NOW, start=broken) is None
    assert schedule.launch_requests(store) == []
    assert store.get_state(packet.SCOPE_KEY) is None
    alert = store.get_state(alerts.RAISED_KEY)["agent_launch:daily-revise"]
    assert "python.exe introuvable" in alert["detail"] and alert["severity"] == "error"
    assert any(a["id"] == "agent_launch:daily-revise" for a in alerts._raised(store, NOW))


def test_the_light_run_on_a_selection_sees_only_it(store, monkeypatch, tmp_path):
    s = cfg()
    mine = _order(store, monkeypatch, "La mienne", minutes_ago=2)  # in its grace
    other = _order(store, monkeypatch, "Une autre", minutes_ago=2)
    picked, left = _asset(store), _asset(store)
    for a in (picked, left):
        add_comment(store, a, text="plus court", wants_changes=True)
    planning.launch(store, s, [{"kind": "work_order", "id": mine},
                               {"kind": "change_request", "id": picked}], NOW)
    assert schedule.order_wait(store, s, NOW)[0] == "order_grace"  # bypassed by the request

    def start(st, se, playbook):  # the runner's first steps: its row, then the packet
        run = st.start_agent_run(playbook)
        with st._tx() as c:
            c.execute("UPDATE agent_runs SET started_at = ? WHERE id = ?", (to_iso(NOW), run["id"]))
        start.packet = packet.write_packet(st, se, playbook, tmp_path, now=NOW)

    assert schedule.catch_up(store, s, start=start, now=lambda: NOW) == ["daily-revise"]
    work = tmp_path / "work"
    orders = json.loads((work / "work_orders.json").read_text(encoding="utf-8"))["orders"]
    revisions = json.loads((work / "revisions.json").read_text(encoding="utf-8"))["requests"]
    assert [o["id"] for o in orders] == [mine]
    assert [r["asset"]["id"] for r in revisions] == [picked]
    assert start.packet["manifest"]["sections"]["dm_picks"]["count"] == 0
    assert {f["asset"]["id"] for f in json.loads(
        (work / "feedback.json").read_text(encoding="utf-8"))} == {picked}
    # the scope is taken once: the next light run gets everything again
    assert store.get_state(packet.SCOPE_KEY) is None
    full = packet.write_packet(store, s, "daily-revise", tmp_path, now=NOW)
    assert [o["id"] for o in json.loads(
        (work / "work_orders.json").read_text(encoding="utf-8"))["orders"]] == [mine, other]
    assert full["manifest"]["sections"]["revisions"]["count"] == 2


def test_a_scoped_run_has_not_seen_the_others(store, monkeypatch, tmp_path):
    s = cfg()
    _order(store, monkeypatch, "Plus tard", minutes_ago=60)
    run = _run(store, "daily-revise", NOW - timedelta(minutes=30))  # running, started since
    assert schedule.order_wait(store, s, NOW)[0] == "seen"
    store.set_state(packet.SCOPE_KEY, {"order_ids": [], "asset_ids": [], "at": to_iso(NOW)})
    packet.write_packet(store, s, "daily-revise", tmp_path, now=NOW)  # it takes the scope
    assert store.get_state(packet.SCOPED_RUNS_KEY) == [run]
    assert schedule.order_wait(store, s, NOW)[0] is None  # the order keeps its own path


def test_an_old_scope_is_ignored(store, monkeypatch, tmp_path):
    s = cfg()
    _order(store, monkeypatch, "Une")
    _order(store, monkeypatch, "Deux")
    store.set_state(packet.SCOPE_KEY, {"order_ids": [], "asset_ids": [],
                                       "at": to_iso(NOW - packet.SCOPE_TTL - timedelta(1))})
    out = packet.write_packet(store, s, "daily-revise", tmp_path, now=NOW)
    assert out["manifest"]["sections"]["work_orders"]["count"] == 2


def test_preview_says_what_the_selection_pushes_back(store):
    s = cfg()
    first = _job(store, "CinematicSkit", "queued")
    last = _job_id(store, _job(store, "CinematicSkit", "queued"))
    pushed = planning.preview_launch(store, s, NOW, [{"kind": "render", "id": last},
                                                     {"kind": "work_order", "id": 1}])["pushed"]
    assert [p["kind"] for p in pushed] == ["render"] and pushed[0]["by_s"] > 0
    assert line.waiting(store)[0]["id"] == _job_id(store, first)  # the real line is untouched


def test_route_is_a_thin_door(store):
    job = _job_id(store, _job(store, "FactQuest", "queued"))
    with TestClient(create_app(cfg(), store=store), base_url=LOCAL,
                    headers={"Origin": LOCAL}) as tc:
        body = tc.post("/api/planning/launch", json={"items": [
            {"kind": "render", "id": job}, {"kind": "agent_run", "id": "daily-learn"}]}).json()
        assert tc.post("/api/planning/launch/preview",
                       json={"items": [{"kind": "render", "id": job}]}).json() == {"pushed": []}
    assert body["front"] == [{"kind": "render", "id": job}]
    assert body["requested"] == [{"kind": "agent_run", "id": "daily-learn"}]
    assert body["busy"] == "renders are waiting" and body["paused"] is None


# --- step 200: audit (b) ----------------------------------------------------------------------
def _next(items, kind, **ids):
    return next(i for i in items if i["section"] == "next" and i["kind"] == kind
                and all(i["ids"].get(k) == v for k, v in ids.items()))


def test_a_launched_run_is_the_next_thing_on_the_ai_track(store, monkeypatch):
    # audit 200 #8: not its grace end, nor tomorrow's scheduled time
    s = cfg(agent_schedule="daily-learn@15:00")  # 16:00 Paris: later today
    mine = _order(store, monkeypatch, "Tout de suite", minutes_ago=1)  # in its grace
    _launch(store, s, ("work_order", mine), ("agent_run", "daily-learn"))
    items = planning.build_planning(store, s, NOW)["items"]
    run, learn = _next(items, "order_run"), _next(items, "agent_run")
    assert parse_iso(run["est_start"]) == NOW and run["waits_on"] is None
    assert run["launch_requested"] and learn["launch_requested"]
    order = _next(items, "work_order", order_id=mine)
    assert order["est_start"] == run["est_ready"] and order["launch_requested"]
    assert learn["est_start"] == order["est_ready"]  # the next launch, in request order
    # launched today: due_runs skips its 15:00, the placeholder is gone
    assert not [i for i in items if i["section"] == "planned"]


def test_a_launched_run_waits_for_the_renders_and_goes_before_the_film(store, monkeypatch):
    s = cfg()
    (schedule.AGENT_DIR / "playbooks" / "check-renders.md").write_text("Run.\n")
    _job(store, "FactQuest", "queued", created_at=to_iso(NOW - timedelta(minutes=50)))
    _order(store, monkeypatch, "Un film", "lemo:watercolor", minutes_ago=40)
    _checkable(store, 1)  # in the check's grace: the launch bypasses it
    assert _launch(store, s, ("agent_run", "check-renders"))["requested"]
    items = planning.build_planning(store, s, NOW)["items"]
    render, film = _next(items, "render"), _next(items, "film")
    check = _next(items, "check_run")
    assert check["est_start"] == render["est_ready"] and check["waits_on"] == "gpu_busy"
    assert film["est_start"] == check["est_ready"]  # catch_up: the launch first, then the film
    assert len([i for i in items if i["kind"] == "check_run"]) == 1


def test_a_run_that_ran_today_hides_its_later_placeholder_not_tomorrows(store):
    s = cfg(agent_schedule="daily-learn@15:00,daily-produce@14:00")
    _run(store, "daily-learn", NOW - timedelta(hours=2), minutes=5)  # by hand, this morning
    items = planning.build_planning(store, s, NOW)["items"]
    assert [i["playbook"] for i in items if i["section"] == "planned"] == ["daily-produce"]


def test_a_launch_on_a_selection_leaves_the_others_their_own_path(store, monkeypatch):
    s = cfg()
    mine = _order(store, monkeypatch, "La mienne", minutes_ago=1)
    other = _order(store, monkeypatch, "Une autre", minutes_ago=1)
    _launch(store, s, ("work_order", mine))
    items = planning.build_planning(store, s, NOW)["items"]
    runs = [i for i in items if i["kind"] == "order_run"]
    assert [(r["launch_requested"], r["waits_on"]) for r in runs] == [
        (True, None), (False, "order_grace")]
    assert [(i["ids"]["order_id"], i["launch_requested"]) for i in items
            if i["kind"] == "work_order"] == [(mine, True), (other, False)]


def test_bulk_launch_leaves_held_timer_and_machine_cards(store, monkeypatch):
    # audit 200 #10: « Tout lancer » leaves them, one card's own « Lancer maintenant » not
    s = cfg()
    ok, held, timer, machine = (_job_id(store, _job(store, "FactQuest", "queued"))
                                for _ in range(4))
    line.hold(store, "render", held, True)
    line.set_timer(store, "render", timer, NOW + timedelta(hours=1))
    store.update_render_job(machine, not_before=to_iso(NOW + timedelta(minutes=5)),
                            failure="machine 1/6: out of memory")
    past = _job_id(store, _job(store, "FactQuest", "queued"))  # its timer is over: it goes
    store.update_render_job(past, not_before=to_iso(NOW - timedelta(minutes=1)))
    items = [{"kind": "render", "id": i} for i in (held, timer, machine, ok, past)]
    waiting = items[:3]  # the preview leaves them too
    assert planning.preview_launch(store, s, NOW, waiting, bulk=True)["pushed"] == []
    assert planning.preview_launch(store, s, NOW, waiting)["pushed"]
    out = planning.launch(store, s, items, NOW, bulk=True)
    assert out["left"] == [{"kind": "render", "id": held, "why": "held"},
                           {"kind": "render", "id": timer, "why": "timer"},
                           {"kind": "render", "id": machine, "why": "machine"}]
    assert out["front"] == [{"kind": "render", "id": ok}, {"kind": "render", "id": past}]
    assert line.waiting(store)[2]["not_before"] == line.HELD  # untouched
    out = planning.launch(store, s, [{"kind": "render", "id": machine}], NOW)  # one card
    assert out["front"] == [{"kind": "render", "id": machine}] and out["left"] == []
    assert store.get_render_job(machine)["not_before"] is None
