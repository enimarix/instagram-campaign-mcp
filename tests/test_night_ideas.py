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
    assert store.get_state(planned.PLACES_KEY) == {"day": quotas["date"], "left": 3}
    assert work["manifest"]["sections"]["quotas"]["count"] == 1


@pytest.fixture
def s(tmp_path, monkeypatch):
    monkeypatch.setattr(motion, "validate_props",
                        lambda template, props: {**VALID, "props": props, "coverFrame": 12})
    monkeypatch.setattr(motion, "list_templates",
                        lambda: [{"id": "FactQuest", "style": "pixel"}])
    return _settings(tmp_path)


def _plan(store, s):
    idea = store.add_idea("motion", hook="Le mythe du jus détox", batch_date=DAY)
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


def test_a_day_no_packet_opened_counts_its_places_at_once(store, s):
    planned.open_places(store, "2026-11-22", 0)  # yesterday's: not today's
    s = s.model_copy(update={"batch_size": 1})
    _plan(store, s)
    with pytest.raises(ValueError, match="no place left"):
        _plan(store, s)


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
    from src.studio.assets import transition

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
        def flags():
            rows = tc.get("/api/assets", params={"batch_date": DAY}).json()
            return {a["id"]: a["awaiting_check"] for a in rows}

        assert flags() == {fresh: True, late: False}  # past the grace: shown anyway
        store.update_asset(fresh, self_score_reason="")  # the check submitted it
        assert flags() == {fresh: False, late: False}
        waiting = _done(store, 5)
        replaced = _done(store, 60 * 5)
        _done(store, 1, parent=replaced, status="rendering")  # the check re-renders it
        assert flags()[waiting] is True and flags()[replaced] is True
        run = store.start_agent_run(checks.PLAYBOOK)
        store.finish_agent_run(run["id"], "failed", summary="exit 1")
        assert not flags()[waiting] and not flags()[replaced]  # failing: nothing held back


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
                 "@<creator>"):
        assert rule in text, rule
    named = set(re.findall(r"`(\w+)", text))
    assert "wait_for_renders" not in named and "create_idea" not in named
