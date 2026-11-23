"""Step 188c: the night run plans Claude's ideas only for the places left (packet number +
server guard), and the check run: what waits for a check, its trigger (debounce, the batch
still in the line, cap, paused, busy), the drop, and the Inbox gating with its fallback."""

import json
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import src.instagram_mcp_server as srv
from src.agent import packet, runner, schedule
from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.learning import brief as B
from src.store import to_iso, utcnow
from src.studio import checks, line, motion, planned, work_orders
from src.studio.assets import transition
from tests.test_studio_motion import FACTQUEST, VALID, _settings
from tests.test_trending import _ref

from .conftest import LOCAL

DAY = "2026-11-23"


def cfg(**kw):
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                                database_path=":memory:", timezone="Europe/Paris",
                                agent_schedule="", **kw)


# --- the places left: the packet's number and the server guard -------------------------
def test_the_packet_gives_the_places_left_and_opens_them(store, tmp_path, monkeypatch):
    monkeypatch.setattr(B, "BIBLE_PATH", tmp_path / "BIBLE.md")
    s = cfg(batch_size=4)
    work_orders.create_orders(store, [{"source_id": _ref(store, "A"), "mode": "react"}])
    work = packet.write_packet(store, s, "daily-produce", tmp_path)
    quotas = json.loads((tmp_path / "work" / "quotas.json").read_text(encoding="utf-8"))
    assert quotas["places"] == {"orders": 1, "change_requests": 0, "dm_picks": 0,
                                "ideas_left": 3}
    assert store.get_state(planned.PLACES_KEY) == {quotas["date"]: {"places": 3, "taken": 0}}
    assert work["manifest"]["sections"]["quotas"]["count"] == 1


@pytest.fixture
def s(tmp_path, monkeypatch):
    monkeypatch.setattr(motion, "validate_props",
                        lambda template, props: {**VALID, "props": props, "coverFrame": 12})
    monkeypatch.setattr(motion, "list_templates",
                        lambda: [{"id": "FactQuest", "style": "pixel"}])
    return _settings(tmp_path)


def _plan(store, s, day=DAY):
    idea = store.add_idea("motion", hook="Le mythe du jus détox", batch_date=day)
    return motion.queue_motion_render(store, s, template="FactQuest", props=FACTQUEST,
                                      idea_id=idea["id"], plan=True)["asset"]


def test_a_plan_past_the_places_left_is_refused(store, s):
    planned.open_places(store, DAY, 1)
    assert _plan(store, s)["status"] == "planned"
    with pytest.raises(ValueError, match="no place left"):
        _plan(store, s)
    assert len(store.list_assets(status="planned")) == 1  # nothing stored past it
    # the owner's items still render: a render is not a plan
    idea = store.add_idea("motion", hook="La commande du jour", batch_date=DAY)
    out = motion.queue_motion_render(store, s, template="FactQuest", props=FACTQUEST,
                                     idea_id=idea["id"])
    assert out["job"]["state"] == "queued"


def test_places_count_per_batch_day_minus_the_cards_already_planned(store, s):
    # 193: a retried packet (or a second run of the day) opens the places again: the cards
    # already planned for that day still count, and another day's plan keeps its own count
    assert planned.open_places(store, DAY, 2) == 2
    _plan(store, s)
    assert planned.open_places(store, DAY, 2) == 1  # the retry: one place left, not two
    other = store.add_idea("motion", hook="Demain", batch_date="2026-11-24")
    planned.open_places(store, "2026-11-24", 1)
    motion.queue_motion_render(store, s, template="FactQuest", props=FACTQUEST,
                               idea_id=other["id"], plan=True)
    _plan(store, s)  # today's last place: the other day's plan did not take it
    with pytest.raises(ValueError, match="no place left in the 2026-11-23 batch"):
        _plan(store, s)
    assert planned.open_places(store, DAY, 2) == 0


def test_a_day_no_packet_opened_counts_its_places_at_once(store, s):
    planned.open_places(store, "2026-11-22", 0)  # yesterday's: not today's
    s = s.model_copy(update={"batch_size": 1})
    _plan(store, s)
    with pytest.raises(ValueError, match="no place left"):
        _plan(store, s)


def test_a_second_produce_run_the_same_day_keeps_the_first_places(store, s, tmp_path,
                                                                 monkeypatch):
    # 199 (#5): once the first run made the owner's items, ideas_left() grows back; the
    # day's first packet fixed its places, a later one only lowers them
    monkeypatch.setattr(B, "BIBLE_PATH", tmp_path / "BIBLE.md")
    s4 = cfg(batch_size=4)
    [order] = work_orders.create_orders(store, [{"source_id": _ref(store, "A"),
                                                 "mode": "react"}])

    def places():
        packet.write_packet(store, s4, "daily-produce", tmp_path)
        q = json.loads((tmp_path / "work" / "quotas.json").read_text(encoding="utf-8"))
        return q["date"], q["places"]["ideas_left"]

    day, left = places()
    assert left == 3
    _plan(store, s, day)
    with store._tx() as c:  # the first run made the owner's item
        c.execute("UPDATE work_orders SET status='in_production' WHERE id=?", (order["id"],))
    assert planned.ideas_left(store, s4)["ideas_left"] == 4
    assert places() == (day, 2)  # not 3: the batch stays 4 with the owner's item
    _plan(store, s, day)
    _plan(store, s, day)
    with pytest.raises(ValueError, match="no place left"):
        _plan(store, s, day)
    assert planned.open_places(store, day, 0) == 0  # a later packet may lower them
    assert store.get_state(planned.PLACES_KEY)[day] == {"places": 0, "taken": 3}


def test_a_removed_card_gives_its_place_back_a_released_one_keeps_it(store, s):
    # 199 (#17): the cap is how many of Claude's ideas wait or get made
    planned.open_places(store, DAY, 2)
    one, two = _plan(store, s), _plan(store, s)
    with pytest.raises(ValueError, match="no place left"):
        _plan(store, s)
    planned.remove(store, one["id"])
    assert planned.open_places(store, DAY, 2) == 1
    three = _plan(store, s)  # the removed card's place
    planned.release(store, s, two["id"])
    assert store.get_asset(two["id"])["status"] == "rendering"
    assert planned.open_places(store, DAY, 2) == 0  # the released card keeps its place
    with pytest.raises(ValueError, match="no place left"):
        _plan(store, s)
    planned.archive(store, three["id"])  # the Inbox's « Archiver »: remove() too
    assert planned.open_places(store, DAY, 2) == 1
    planned.give_place(store, "2026-01-01")  # a day no packet opened: nothing to give


# --- what waits for a check -------------------------------------------------------------
def _done(store, minutes_ago, *, status="ready", style=None, parent=None, jobs=1, now=None):
    """A video whose last render finished `minutes_ago`."""
    at = to_iso((now or utcnow()) - timedelta(minutes=minutes_ago))
    idea_id = (store.get_asset(parent)["idea_id"] if parent else
               store.add_idea("motion", hook="Un fait", batch_date=DAY, style=style)["id"])
    a = store.add_asset(idea_id, batch_date=DAY, parent_asset_id=parent)
    with store._tx() as c:
        c.execute("UPDATE assets SET status=? WHERE id=?", (status, a["id"]))
        for n in range(jobs):
            c.execute("INSERT INTO render_jobs (asset_id, idempotency_key, state, finished_at,"
                      " created_at, updated_at) VALUES (?, ?, 'done', ?, ?, ?)",
                      (a["id"], f"{a['id']}:{n}", at, at, at))
    return a["id"]


def test_what_waits_for_a_check(store):
    now = utcnow()
    ready, failed = _done(store, 10), _done(store, 20, status="failed", jobs=3)
    _done(store, 10, style="lemo:impasto")  # the film runner checks its own film
    _done(store, 60 * 30)  # older than the horizon: the owner's, as before
    submitted = _done(store, 5)
    store.update_asset(submitted, self_score_reason="")
    old = _done(store, 30)
    child = _done(store, 2, parent=old)  # the re-render took over from `old`
    shown = _done(store, 40)
    store.update_asset(shown, self_score_reason="")
    _done(store, 1, parent=shown)  # the owner's own re-render of a submitted video
    rows = checks.for_agent(store, now)["renders"]
    assert [r["asset_id"] for r in rows] == [failed, ready, child]
    by = {r["asset_id"]: r for r in rows}
    assert by[failed]["rerenders_left"] == 0 and by[ready]["rerenders_left"] == 2
    assert by[child]["rerenders_left"] == 1 and by[child]["version_of"] == old
    raw = packet.encode(checks.for_agent(store, now), "checks")  # its schema holds
    assert json.loads(raw)["max_rerenders"] == checks.MAX_RERENDERS


def test_an_unchanged_re_render_counts_for_the_cap(store):
    # 192: the same recipe re-queues the same job row; it still counts
    from src.studio import render
    now = utcnow()
    failed = _done(store, 20, status="failed")
    left = {r["asset_id"]: r["rerenders_left"] for r in checks.for_agent(store, now)["renders"]}
    assert left[failed] == checks.MAX_RERENDERS
    transition(store, failed, "rendering", actor="agent")
    job = render.enqueue_render(store, failed, key=f"{failed}:0")
    assert job["state"] == "queued" and job["requeues"] == 1
    store.update_render_job(job["id"], state="failed", finished_at=to_iso(utcnow()))
    transition(store, failed, "failed", actor="worker")
    left = {r["asset_id"]: r["rerenders_left"] for r in checks.for_agent(store, now)["renders"]}
    assert left[failed] == checks.MAX_RERENDERS - 1


def test_drop_shows_the_reason_and_skips_the_order(store):
    now = utcnow()
    [order] = work_orders.create_orders(store, [{"source_id": _ref(store, "A"),
                                                 "mode": "inspired"}])
    a = _done(store, 10)
    with store._tx() as c:
        c.execute("UPDATE work_orders SET status='in_production', idea_id="
                  "(SELECT idea_id FROM assets WHERE id=?) WHERE id=?", (a, order["id"]))
    with pytest.raises(ValueError, match="say why"):
        checks.drop(store, a, " ")
    out = checks.drop(store, a, "le texte sort du cadre après 2 rendus")
    assert out["agent_decision"]["kind"] == "dropped"
    assert out["agent_decision"]["text"] == "Écartée par l'IA : le texte sort du cadre après 2 rendus"
    assert out["status"] == "ready"  # only the owner archives
    assert checks.waiting(store, now) == []
    got = work_orders.get_order(store, order["id"])
    assert (got["status"], got["skip_reason"]) == ("skipped", "le texte sort du cadre après 2 rendus")
    store.update_asset(a, self_score_reason="")  # submitted: not the check's any more
    with pytest.raises(ValueError, match="not waiting for its check"):
        checks.drop(store, a, "encore")


def test_relaunching_a_dropped_video_revives_it_its_order_and_its_pick(store, tmp_path):
    # audit 200 #6: « Relancer » (render.rerender) on a video the check run dropped: it
    # follows the normal path again (its check, then the Inbox), its order back in production
    from src.studio import render
    from tests.test_studio_render import FFMPEG

    [order, other] = work_orders.create_orders(store, [
        {"source_id": _ref(store, "A"), "mode": "inspired"},
        {"source_id": _ref(store, "B"), "mode": "inspired"}])
    a = _done(store, 10, status="failed")
    with store._tx() as c:
        pick = c.execute("INSERT INTO dm_picks (message_id, sender_username, reel_url,"
                         " received_at, status, created_at, updated_at) VALUES"
                         " ('m1', 'pal', 'https://x', 't', 'in_production', 't', 't')").lastrowid
        c.execute("UPDATE work_orders SET status='in_production', pick_id=?, idea_id="
                  "(SELECT idea_id FROM assets WHERE id=?) WHERE id=?", (pick, a, order["id"]))
        c.execute("UPDATE work_orders SET status='in_production', idea_id="
                  "(SELECT idea_id FROM assets WHERE id=?) WHERE id=?", (a, other["id"]))
    work_orders.skip_order(store, other["id"], "un doublon")  # skipped for another reason
    checks.drop(store, a, "le rendu plante deux fois")
    assert work_orders.get_order(store, order["id"])["status"] == "skipped"
    assert store._get("dm_picks", pick)["status"] == "skipped"
    render.rerender(store, tmp_path, a, FFMPEG)
    got = store.get_asset(a)
    assert got["agent_decision"] is None and got["status"] == "rendering"
    revived = work_orders.get_order(store, order["id"])
    assert (revived["status"], revived["skip_reason"]) == ("in_production", None)
    assert store._get("dm_picks", pick)["status"] == "in_production"
    assert work_orders.get_order(store, other["id"])["status"] == "skipped"  # not this drop's
    transition(store, a, "ready", actor="worker")
    assert a in [r["id"] for r in checks.waiting(store, utcnow())]  # checked, then the Inbox


def test_a_re_render_of_a_video_never_dropped_changes_no_order(store, tmp_path):
    from src.studio import render
    from tests.test_studio_render import FFMPEG

    [order] = work_orders.create_orders(store, [{"source_id": _ref(store, "A"),
                                                 "mode": "inspired"}])
    a = _done(store, 10, status="failed")
    with store._tx() as c:
        c.execute("UPDATE work_orders SET idea_id=(SELECT idea_id FROM assets WHERE id=?)"
                  " WHERE id=?", (a, order["id"]))
    work_orders.skip_order(store, order["id"], "le rendu plante deux fois")
    render.rerender(store, tmp_path, a, FFMPEG)
    assert work_orders.get_order(store, order["id"])["status"] == "skipped"


def test_a_fix_s_new_version_keeps_the_dm_pick_going(store):
    # 193: the remix fix flow: render_remix makes a new version, drop_render the old one;
    # the pick (no order) stays in_production until no version of the idea lives
    src = store.add_source("downloader", url="https://example.org/r", author="creator",
                           rights_basis="commentary")
    with store._tx() as c:
        pick = c.execute("INSERT INTO dm_picks (message_id, sender_username, reel_url,"
                         " received_at, status, source_id, created_at, updated_at) VALUES"
                         " ('m1', 'pal', 'https://x', 't', 'in_production', ?, 't', 't')",
                         (src["id"],)).lastrowid
    idea = store.add_idea("remix", source_id=src["id"], batch_date=DAY)
    old = store.add_asset(idea["id"], batch_date=DAY)["id"]
    new = store.add_asset(idea["id"], batch_date=DAY)["id"]  # the fix, still rendering
    with store._tx() as c:
        c.execute("UPDATE assets SET status='ready' WHERE id=?", (old,))
    checks.drop(store, old, "replaced by a new version")
    assert store._get("dm_picks", pick)["status"] == "in_production"
    with store._tx() as c:
        c.execute("UPDATE assets SET status='failed' WHERE id=?", (new,))
    checks.drop(store, new, "le rendu plante deux fois")  # no version of the idea lives now
    got = store._get("dm_picks", pick)
    assert (got["status"], got["skip_reason"]) == ("skipped", "le rendu plante deux fois")


def test_a_parent_whose_new_version_dies_is_offered_again(store):
    # 199 (#4): only a living newer version replaces the old one; when it fails or is
    # dropped the old one is back in the check list and the Inbox, its order not parked
    now = utcnow()
    [order] = work_orders.create_orders(store, [{"source_id": _ref(store, "A"),
                                                 "mode": "inspired"}])
    a = _done(store, 30)
    with store._tx() as c:
        c.execute("UPDATE work_orders SET status='in_production', idea_id="
                  "(SELECT idea_id FROM assets WHERE id=?) WHERE id=?", (a, order["id"]))
    b = _done(store, 5, parent=a)  # the check's re-render

    def checked():
        return [r["asset_id"] for r in checks.for_agent(store, now)["renders"]]

    def replaced():
        return checks.flag(store, cfg(), [{"id": a}], now)[0]["replaced"]

    assert checked() == [b] and replaced()
    with store._tx() as c:
        c.execute("UPDATE assets SET status='failed' WHERE id=?", (b,))
    assert checked() == [a, b] and not replaced()  # its render failed: `a` is back
    with store._tx() as c:  # re-rendered in place: it lives again
        c.execute("UPDATE assets SET status='ready' WHERE id=?", (b,))
    assert checked() == [b] and replaced()
    checks.drop(store, b, "le texte sort encore du cadre après 2 rendus")
    assert checked() == [a] and not replaced()
    assert work_orders.get_order(store, order["id"])["status"] == "in_production"  # `a` lives
    checks.drop(store, a, "la première version non plus")
    assert work_orders.get_order(store, order["id"])["status"] == "skipped"  # never parked


def test_an_old_version_stays_out_once_the_owner_declined_its_new_one(store):
    # review round 1: archived (the owner declined it, the worker or a restyle retired it)
    # still replaces: the version the check judged broken never comes back
    now = utcnow()
    [order] = work_orders.create_orders(store, [{"source_id": _ref(store, "A"),
                                                 "mode": "inspired"}])
    a = _done(store, 30)
    with store._tx() as c:
        c.execute("UPDATE work_orders SET status='in_production', idea_id="
                  "(SELECT idea_id FROM assets WHERE id=?) WHERE id=?", (a, order["id"]))
    b = _done(store, 5, parent=a)
    store.update_asset(b, self_score_reason="")  # the check submitted it
    transition(store, b, "archived", actor="owner")  # the owner declined it
    assert [r["asset_id"] for r in checks.for_agent(store, now)["renders"]] == []
    assert checks.flag(store, cfg(), [{"id": a}], now)[0]["replaced"]
    # drop's `alive` follows the same rule: the hidden `a` carries nothing on
    c2 = _done(store, 2, parent=a)
    with store._tx() as cx:
        cx.execute("UPDATE assets SET status='failed' WHERE id=?", (c2,))
    checks.drop(store, c2, "le rendu plante")
    assert work_orders.get_order(store, order["id"])["status"] == "skipped"


def test_an_old_version_stays_replaced_up_the_chain(store):
    # old #17 still holds: out for good, beyond 24 h, up the chain (the owner sent the new
    # version back: archived once its own new one is ready)
    now = utcnow()
    a = _done(store, 60 * 30)
    b = _done(store, 60 * 29, parent=a)
    store.update_asset(b, self_score_reason="")  # the check submitted the new version
    c = _done(store, 60 * 28, parent=b)

    def replaced():
        return {r["id"]: r["replaced"] for r in checks.flag(store, cfg(), [{"id": a}], now)}

    with store._tx() as cx:
        cx.execute("UPDATE assets SET status='archived' WHERE id=?", (b,))
    assert replaced() == {a: True}
    with store._tx() as cx:  # the owner declined the last one too: still out
        cx.execute("UPDATE assets SET status='archived' WHERE id=?", (c,))
    assert replaced() == {a: True}


# --- the trigger --------------------------------------------------------------------------
class Starts:
    def __init__(self):
        self.runs = []

    def start(self, store, settings, playbook):
        self.runs.append(playbook)

    def check(self, settings):
        pass


def test_check_run_debounce_seen_and_cap(store):
    s, f, now = cfg(max_check_runs_per_day=1), Starts(), utcnow()
    run = lambda m: schedule.check_run(store, s, now + timedelta(minutes=m),  # noqa: E731
                                       start=f.start, check=f.check)
    assert run(0) is None and f.runs == []  # nothing waits
    _done(store, 2, now=now)
    assert schedule.check_wait(store, s, now)[0] == "check_grace"
    assert run(0) is None and f.runs == []  # 2 min after the render: debounce
    assert run(3) == "check-renders" and f.runs == ["check-renders"]
    assert run(4) is None  # it started since the newest render: it has it
    _done(store, -10, now=now)  # a render finished after that start
    assert schedule.check_wait(store, s, now + timedelta(minutes=20))[0] == "daily_cap"
    assert run(20) is None and f.runs == ["check-renders"]


def test_a_video_a_check_run_left_is_offered_again(store):
    # 193: never parked: CHECK_RECHECK_HOURS after the run that left it, within the cap
    from datetime import datetime, timezone

    s, f = cfg(check_recheck_hours=4, max_check_runs_per_day=2), Starts()
    now = datetime(2026, 11, 23, 1, 0, tzinfo=timezone.utc)  # 02:00 in Paris: one local day
    run = lambda h: schedule.check_run(store, s, now + timedelta(hours=h),  # noqa: E731
                                       start=f.start, check=f.check)
    _done(store, 30, now=now)
    assert run(0) == "check-renders"
    assert schedule.check_wait(store, s, now + timedelta(hours=3.9))[0] == "seen"
    assert run(4) == "check-renders" and len(f.runs) == 2  # it left it: offered again
    assert schedule.check_wait(store, s, now + timedelta(hours=5))[0] == "seen"
    assert schedule.check_wait(store, s, now + timedelta(hours=8))[0] == "daily_cap"


def test_the_re_check_keys_on_an_owner_launched_check_run(store):
    # 199 (#9): a check run the owner launched (no _launch time) starts the re-check clock
    from datetime import datetime, timezone

    s = cfg(check_recheck_hours=4)
    now = datetime(2026, 11, 23, 1, 0, tzinfo=timezone.utc)
    _done(store, 30, now=now)
    schedule.request_launch(store, checks.PLAYBOOK, now)

    def start(st, settings, playbook):  # what the started process does: its row
        run = st.start_agent_run(playbook)
        st.finish_agent_run(run["id"], "succeeded")
        with st._tx() as c:
            c.execute("UPDATE agent_runs SET started_at=? WHERE id=?", (to_iso(now), run["id"]))

    assert schedule.launched(store, s, now, start=start) == checks.PLAYBOOK
    assert store.get_state("check_run_started_at") is None
    assert schedule.check_started_at(store) == now
    assert schedule.check_wait(store, s, now + timedelta(hours=3.9))[0] == "seen"
    assert schedule.check_wait(store, s, now + timedelta(hours=4))[0] is None  # not « seen »


def test_check_run_preflight_retry(store):
    s, f, now = cfg(), Starts(), utcnow()
    _done(store, 30, now=now)

    def signed_out(settings):
        raise runner.AgentError("Claude Code CLI is not signed in")

    assert schedule.check_run(store, s, now, start=f.start, check=signed_out) is None
    assert store.get_state(checks.PREFLIGHT_KEY) and checks.failing(store)
    assert schedule.check_wait(store, s, now + timedelta(minutes=5))[0] == "preflight"
    assert schedule.check_run(store, s, now + timedelta(minutes=11), start=f.start,
                              check=f.check) == "check-renders"
    assert not store.get_state(checks.PREFLIGHT_KEY)


def test_catch_up_starts_the_check_run_only_when_the_line_is_idle(store, monkeypatch):
    monkeypatch.setattr(schedule, "preflight", lambda settings: "claude")
    s, f, now = cfg(), Starts(), utcnow()
    _done(store, 30, now=now)
    other = _done(store, 30, status="rendering", now=now)
    job = store.add_render_job(other, "queued-one")  # the batch's next render, queued

    def tick():
        return schedule.catch_up(store, s, start=f.start, now=lambda: now)

    assert tick() == [] and f.runs == []
    line.set_timer(store, "render", job["id"], now + timedelta(hours=2))  # waits its timer
    line.pause(store, True)
    assert tick() == []  # paused: nothing starts
    line.pause(store, False)
    busy = store.start_agent_run("daily-revise")  # another run runs
    assert tick() == []
    store.finish_agent_run(busy["id"], "succeeded")
    assert tick() == ["check-renders"] and f.runs == ["check-renders"]


def test_the_planning_lists_the_check_run(store):
    from src.studio import planning

    s, now = cfg(), utcnow()
    _done(store, 1, now=now)
    item = next(i for i in planning.build_planning(store, s, now)["items"]
                if i["kind"] == "check_run")
    assert item["waits_on"] == "check_grace" and item["section"] == "next"


# --- the Inbox ----------------------------------------------------------------------------
def test_the_inbox_hides_a_video_until_its_check_with_a_fallback(store):
    fresh, late = _done(store, 10), _done(store, 4 * 60)
    with TestClient(create_app(cfg(check_inbox_grace_hours=3), store=store),
                    base_url=LOCAL) as tc:
        def flags(key="awaiting_check"):
            rows = tc.get("/api/assets", params={"batch_date": DAY}).json()
            return {a["id"]: a[key] for a in rows}

        assert flags() == {fresh: True, late: False}  # past the grace: shown anyway
        store.update_asset(fresh, self_score_reason="")  # the check submitted it
        assert flags() == {fresh: False, late: False}
        waiting = _done(store, 5)
        replaced = _done(store, 60 * 30)  # 193: older than the horizon, still out for good
        _done(store, 1, parent=replaced, status="rendering")  # the check re-renders it
        assert flags()[waiting] is True and flags("replaced")[replaced] is True
        assert not flags("replaced")[waiting] and not flags()[replaced]
        run = store.start_agent_run(checks.PLAYBOOK)
        store.finish_agent_run(run["id"], "failed", summary="exit 1")
        assert not flags()[waiting]  # failing: nothing waiting is held back
        assert flags("replaced")[replaced] is True  # its newer version carries on


# --- the tool and the playbooks -----------------------------------------------------------
def test_drop_render_is_in_the_agent_profile():
    assert "drop_render" in srv.AGENT_TOOLS


def _book(name):
    return (runner.AGENT_DIR / "playbooks" / f"{name}.md").read_text(encoding="utf-8")


def test_daily_produce_never_waits_and_plans_its_own_ideas():
    text = _book("daily-produce")
    for gone in ("wait_for_renders", "get_asset_frames", "wait list"):
        assert gone not in text, gone
    assert "plan=True" in text and "places.ideas_left" in text and "no place left" in text
    assert "« yours N + Claude M = total »" in text
    dry = text.split("## Dry run", 1)[1]
    assert "with or without `plan`" in dry and "no `preview_motion`" in dry


def test_check_renders_playbook_does_the_broken_check():
    assert packet.RUNS["check-renders"] == ("light", ("checks",))
    text = " ".join(_book("check-renders").split())
    for rule in ("work/manifest.json", "checks.json", "get_asset_frames", "cut text",
                 "unreadable first frame", "voice vs picture", "the remix credit",
                 "rerenders_left", "drop_render", "submit_asset", "Work order #<id>: ",
                 "@<creator>",
                 # 193: never parked; the remix's music round-trips
                 "exactly one decision", "Never leave one waiting", "music=…",
                 # 197: the machine's failures are never the video's
                 "A machine failure is never a reason to drop", "`machine:`"):
        assert rule in text, rule
    named = set(re.findall(r"`(\w+)", text))
    assert "wait_for_renders" not in named and "create_idea" not in named
