"""Step 136: every DM pick is a work order (received since 2026-11-25: « Reçus »), the owner's
instruction from the app, the at-once run (debounce, daily cap, preflight), the analysis-only
finish, the list of both sources and the backfill of picks made before."""

import itertools
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
import respx
from fastapi.testclient import TestClient

import src.instagram_mcp_server as srv
from src import store as store_mod
from src.agent import packet, schedule
from src.agent.runner import AGENT_DIR, AgentError
from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.learning import brief as B
from src.store import MIGRATIONS, CampaignStore, to_iso
from src.studio import dm_picks as D
from src.studio import production, work_orders
from src.studio.assets import transition

from .conftest import API, LOCAL
from .test_api_assets import _settings
from .test_dm_picks import BRAND, FRIEND, _mock, _msg
from .test_trending import _ref

OURS = "https://www.instagram.com/reel/OURS1/"
THEIRS = "https://www.instagram.com/reel/THEIRS1/"
T0 = datetime(2026, 11, 17, 10, tzinfo=timezone.utc)  # 11:00 in Paris
_ids = itertools.count(1)


class Clock:
    """work_orders' clock (when an order is scheduled), moved by the test."""
    def __init__(self):
        self.at = T0

    def __call__(self):
        return self.at

    def set(self, minutes):
        self.at = T0 + timedelta(minutes=minutes)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(work_orders, "utcnow", c)
    return c


def _received(store, note=None, url=THEIRS):
    """A pick as the poll stores it, with its order (received)."""
    now = to_iso(work_orders.utcnow())
    with store._tx() as c:
        cur = c.execute("INSERT INTO dm_picks (message_id, sender_username, reel_url,"
                        " sender_note, received_at, created_at, updated_at)"
                        " VALUES (?, 'amine_xenima', ?, ?, ?, ?, ?)",
                        (f"m{next(_ids)}", url, note, now, now, now))
        work_orders.add_for_pick(c, cur.lastrowid, note, False, now)
        return c.execute("SELECT id FROM work_orders WHERE pick_id=?",
                         (cur.lastrowid,)).fetchone()[0]


def _dm_order(store, note=None, url=THEIRS):
    """A DM order as the owner moves it: with a note, confirmed on « Reçus » and launched
    from Planning (scheduled at work_orders' clock); without, still waiting on « Reçus »
    (received)."""
    oid = _received(store, note, url)
    if note:
        work_orders.confirm(store, oid, "style", None, note)
        work_orders.launch(store, oid)
    return oid


# --- the poll ---------------------------------------------------------------------------
@respx.mock
async def test_poll_makes_each_pick_a_work_order(client, store):
    D.pin_account(store, "friend.one")
    _mock([("C1", [BRAND, FRIEND])], {"C1": [
        _msg("m2", FRIEND, "05:00", share=THEIRS),
        _msg("m1", FRIEND, "01:00", "analyse-la, elle a marché", share=OURS)]})
    media = respx.get(f"{API}/1789/media").respond(json={"data": [{"id": "9",
                                                                   "permalink": OURS}]})
    assert (await D.poll_dm_picks(client, store, budget_left=lambda: True))["picks"] == 2
    assert media.call_count == 1  # our media asked once per poll
    by_url = {o["permalink"]: o for o in work_orders.list_orders(store, source="dm")}
    noted, bare = by_url[OURS], by_url[THEIRS]
    assert (noted["status"], noted["mode"], noted["instruction"], noted["own_reel"]) == (
        "received", "owner", "analyse-la, elle a marché", True)
    assert noted["scheduled_at"] is None and noted["sender_username"] == "friend.one"
    assert (bare["status"], bare["instruction"], bare["own_reel"]) == (
        "received", None, False)
    assert bare["embed_url"] == "https://www.instagram.com/reel/THEIRS1/embed"
    # a second poll stores nothing twice; the agent's dm_picks list stays empty
    assert (await D.poll_dm_picks(client, store, budget_left=lambda: True))["picks"] == 0
    assert len(work_orders.list_orders(store)) == 2 and D.for_agent(store) == []
    assert work_orders.for_agent(store) == []  # nothing starts from a DM alone (« Reçus »)


# --- 141: a DM Reel's text is always its note -------------------------------------------
async def _notes(client, store, messages):
    """One poll of conversation C1 (`messages` newest first, as the API lists them):
    {message_id: (sender_note, order status)}."""
    D.pin_account(store, "friend.one")
    _mock([("C1", [BRAND, FRIEND])], {"C1": messages})
    await D.poll_dm_picks(client, store, budget_left=lambda: True)
    by_pick = {o["pick_id"]: o["status"] for o in work_orders.list_orders(store)}
    return {p["message_id"]: (p["sender_note"], by_pick[p["id"]])
            for p in D.list_picks(store, None)}


@respx.mock
async def test_same_second_text_after_the_share_is_its_note(client, store):
    respx.get(f"{API}/1789/media").respond(json={"data": []})
    # the live case (pick 38): the text was sent after the share, in the same second
    assert await _notes(client, store, [
        _msg("m2", FRIEND, "18:51", "Macrobody being crushed"),
        _msg("m1", FRIEND, "18:51", share=THEIRS)]) == {
        "m1": ("Macrobody being crushed", "received")}
    [order] = work_orders.list_orders(store)
    assert order["instruction"] == "Macrobody being crushed" and not order["scheduled_at"]


@respx.mock
async def test_text_just_before_the_share_is_its_note(client, store):
    respx.get(f"{API}/1789/media").respond(json={"data": []})
    assert await _notes(client, store, [
        _msg("m2", FRIEND, "01:00", share=THEIRS),
        _msg("m1", FRIEND, "00:30", "fais-en une réaction")]) == {
        "m2": ("fais-en une réaction", "received")}


@respx.mock
async def test_each_share_gets_its_own_text(client, store):
    respx.get(f"{API}/1789/media").respond(json={"data": []})
    assert await _notes(client, store, [
        _msg("s3", FRIEND, "00:40", share=THEIRS + "?3"),  # t2 is s2's: no note
        _msg("t2", FRIEND, "00:30", "second"),
        _msg("s2", FRIEND, "00:20", share=THEIRS + "?2"),
        _msg("t1", FRIEND, "00:10", "first"),
        _msg("s1", FRIEND, "00:00", share=THEIRS)]) == {
        "s1": ("first", "received"), "s2": ("second", "received"),
        "s3": (None, "received")}


@respx.mock
async def test_a_note_on_a_later_poll_is_the_waiting_orders_draft(client, store, clock):
    respx.get(f"{API}/1789/media").respond(json={"data": []})
    shares = [_msg("s2", FRIEND, "01:00", share=THEIRS + "?2"),
              _msg("s1", FRIEND, "00:00", share=THEIRS)]
    assert await _notes(client, store, shares) == {
        "s1": (None, "received"), "s2": (None, "received")}
    owner = next(o for o in work_orders.list_orders(store) if o["permalink"] == THEIRS + "?2")
    work_orders.confirm(store, owner["id"], "rea", None, "the owner's own words")
    texts = [_msg("t2", FRIEND, "01:10", "late for s2"),
             _msg("t1", FRIEND, "00:10", "late for s1")]
    assert await _notes(client, store, [texts[0], shares[0], texts[1], shares[1]]) == {
        "s1": ("late for s1", "received"), "s2": (None, "confirmed")}
    by_url = {o["permalink"]: o for o in work_orders.list_orders(store)}
    assert by_url[THEIRS]["instruction"] == "late for s1"
    assert not by_url[THEIRS]["scheduled_at"]
    assert by_url[THEIRS + "?2"]["instruction"] == "the owner's own words"  # untouched


# --- the owner's instruction ------------------------------------------------------------
def test_patch_rewrites_a_launched_order_never_a_received_one(store, settings):
    waiting = _dm_order(store)
    oid = _dm_order(store, "première consigne")
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as tc:
        def patch(**body):
            return tc.patch(f"/api/work-orders/{oid}", json=body)

        assert patch(instruction="  ").status_code == 422
        assert patch(instruction="x" * 501).status_code == 422
        assert patch(instruction="go", mode="copy").status_code == 422
        assert tc.patch("/api/work-orders/999", json={"instruction": "go"}).status_code == 404
        r = tc.patch(f"/api/work-orders/{waiting}", json={"instruction": "go"})
        assert r.status_code == 409 and "received" in r.json()["message"]  # « Reçus » first
        r = patch(instruction=" Réagis à la fin ", mode="react")
        assert r.status_code == 200, r.text
        assert (r.json()["status"], r.json()["instruction"], r.json()["mode"]) == (
            "scheduled", "Réagis à la fin", "react")
        r = patch(instruction="Inspire-toi, nos macros")  # rewritten while scheduled
        assert (r.json()["instruction"], r.json()["mode"]) == ("Inspire-toi, nos macros",
                                                             "react")
        patch(instruction="Inspire-toi", mode="owner")
        idea = production.create_idea(store, settings, "motion", hook="Nos macros",
                                      pillar="everyday_humor", work_order_id=oid)
        store.add_asset(idea["id"])  # the Inbox badge reads work_order.source (140)
        [row] = store.list_assets()
        assert (row["work_order"]["source"], row["work_order"]["mode"]) == ("dm", "owner")
        r = patch(instruction="too late")
        assert r.status_code == 409 and "in_production" in r.json()["message"]
    assert D.list_picks(store, "in_production")  # the pick follows its order


def test_list_endpoint_both_sources(store):
    trend = work_orders.create_orders(store, [{"source_id": _ref(store, "A"),
                                               "mode": "inspired"}])[0]["id"]
    dm = _dm_order(store)
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as tc:
        def ids(q=""):
            return [o["id"] for o in tc.get(f"/api/work-orders{q}").json()]

        assert ids() == [dm, trend]  # newest first
        assert ids("?source=dm") == [dm] and ids("?source=trend") == [trend]
        assert ids("?source=all&status=received") == [dm]
        assert tc.get("/api/work-orders?source=web").status_code == 422
        [row] = tc.get("/api/work-orders?source=dm").json()
        for key in ("sender_username", "received_at", "permalink", "embed_url",
                    "instruction", "status", "asset_id", "blocked_reason"):
            assert key in row, key
        assert row["source"] == "dm" and row["permalink"] == THEIRS
        assert [o["id"] for o in tc.get("/api/research/work-orders").json()] == [trend]


# --- the at-once run --------------------------------------------------------------------
def cfg(**kw):
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                                database_path=":memory:", timezone="Europe/Paris", **kw)


class Starts:
    def __init__(self):
        self.runs, self.checks = [], 0

    def start(self, store, settings, playbook):
        self.runs.append(playbook)

    def check(self, settings):
        self.checks += 1


def test_debounce_starts_exactly_one_run_for_several_orders(store, clock):
    s, f = cfg(), Starts()
    _dm_order(store, "réagis")
    clock.set(1)
    work_orders.create_orders(store, [{"source_id": _ref(store, "A"), "mode": "react"}])
    _dm_order(store)  # received: never starts a run
    run = lambda m: schedule.order_run(store, s, T0 + timedelta(minutes=m),  # noqa: E731
                                       start=f.start, check=f.check)
    assert run(3) is None and f.runs == []  # 2 min after the newest send: debounce
    assert run(4) == "daily-revise" and f.runs == ["daily-revise"]
    assert run(5) is None and run(30) is None and f.runs == ["daily-revise"]
    # a new instruction after that run: one more run, after its own debounce
    clock.set(31)
    oid = _dm_order(store, "garde la fin")  # confirmed on « Reçus », launched now
    assert run(33) is None and run(35) == "daily-revise" and len(f.runs) == 2
    # a run that reads the orders started after the newest one (it has them): no other
    clock.set(40)
    work_orders.set_instruction(store, oid, "garde le début")
    store.start_agent_run("daily-revise")  # started now, after T0 + 40 min
    assert run(60) is None and len(f.runs) == 2


def test_no_scheduled_order_no_run(store, clock):
    f = Starts()
    _dm_order(store)
    assert schedule.order_run(store, cfg(), T0 + timedelta(hours=1), start=f.start,
                              check=f.check) is None
    assert f.checks == 0


def test_daily_cap(store, clock):
    s, f = cfg(max_order_runs_per_day=1), Starts()
    _dm_order(store, "one")
    assert schedule.order_run(store, s, T0 + timedelta(minutes=5), start=f.start,
                              check=f.check)
    clock.set(6)
    oid = _dm_order(store, "two")
    assert schedule.order_run(store, s, T0 + timedelta(minutes=10), start=f.start,
                              check=f.check) is None
    assert "1 at-once runs are used" in work_orders.get_order(store, oid)["blocked_reason"]
    assert len(f.runs) == 1
    # the next owner-local day has a fresh cap
    assert schedule.order_run(store, s, T0 + timedelta(days=1), start=f.start, check=f.check)
    assert work_orders.get_order(store, oid)["blocked_reason"] is None


def test_preflight_failure_is_the_blocked_reason(store, clock):
    s, f = cfg(), Starts()
    oid = _dm_order(store, "réagis")

    def signed_out(settings):
        f.checks += 1
        raise AgentError("Claude Code CLI is not signed in")

    def run(m, check):
        return schedule.order_run(store, s, T0 + timedelta(minutes=m), start=f.start,
                                  check=check)

    assert run(5, signed_out) is None and f.runs == []
    order = work_orders.get_order(store, oid)
    assert order["status"] == "scheduled"
    assert order["blocked_reason"] == "the agent cannot start: Claude Code CLI is not signed in"
    assert run(8, signed_out) is None and f.checks == 1  # asked again after ORDER_RETRY
    assert run(16, f.check) == "daily-revise"
    assert work_orders.get_order(store, oid)["blocked_reason"] is None


def test_catch_up_starts_the_order_run(store, clock, monkeypatch):
    monkeypatch.setattr(schedule, "preflight", lambda settings: "claude")
    f = Starts()
    _dm_order(store, "réagis")
    later = T0 + timedelta(minutes=5)
    assert schedule.catch_up(store, cfg(agent_schedule=""), start=f.start,
                             now=lambda: later) == ["daily-revise"]


# --- analyse only -----------------------------------------------------------------------
async def test_analysed_path(store, settings, monkeypatch):
    monkeypatch.setattr(srv, "store", lambda: store)
    oid = _dm_order(store, "cette vidéo a marché, analyse-la", url=OURS)
    sid = store.add_source("downloader", url=OURS, rights_basis="commentary", author="x")["id"]
    other = store.add_source("downloader", url=THEIRS)["id"]
    with pytest.raises(ValueError, match="not the Reel of work order"):
        work_orders.analyse(store, oid, other, "why")
    with pytest.raises(ValueError, match="no timeline"):
        work_orders.analyse(store, oid, sid, "why")
    timeline = [{"t": 0.0, "event": "hook: the fork drops"}]
    store.patch_source_stats(sid, {"timeline": timeline, "summary": "fork gag"})
    with pytest.raises(ValueError, match="why must be"):
        work_orders.analyse(store, oid, sid, " ")
    got = await srv.analyse_work_order(oid, sid, "The drop at 0 s stops the scroll.")
    assert got["status"] == "analysed" and got["source_id"] == sid
    assert got["analysis"] == {"why": "The drop at 0 s stops the scroll.",
                               "summary": "fork gag", "timeline": timeline}
    with pytest.raises(srv.ToolError):
        await srv.analyse_work_order(oid, sid, "again")
    assert (await srv.list_work_orders("analysed"))["orders"][0]["id"] == oid
    assert D.list_picks(store, None)[0]["status"] == "skipped"  # closed with its order
    assert "analyse_work_order" in srv.AGENT_TOOLS


def test_skipping_a_dm_order_skips_its_pick(store):
    oid = _dm_order(store, "recoupe-la")
    work_orders.skip_order(store, oid, "not our Reel: no recut of someone else's")
    assert D.list_picks(store, "skipped")[0]["skip_reason"].startswith("not our Reel")


# --- the owner's cancel / skip stops the work; the order follows its video ---------------
def _started(store):
    """A DM order in production, with its idea's first video (rendering)."""
    oid = _dm_order(store, "fais-en une vidéo")
    idea = store.add_idea("motion", pillar="myths", hook_type="pov")
    work_orders.start(store, oid, idea)
    return oid, store.add_asset(idea["id"])["id"]


def test_cancelling_a_dm_order_skips_its_pick(store):
    oid = _dm_order(store)
    work_orders.delete_order(store, oid)
    [pick] = D.list_picks(store, None)
    assert (pick["status"], pick["skip_reason"]) == ("skipped", work_orders.CANCELLED)
    assert D.for_agent(store) == []  # never back as a pre-orders pick


def test_skipping_a_pick_skips_its_open_order(store):
    oid = _dm_order(store, "réagis")
    pick_id = work_orders.get_order(store, oid)["pick_id"]
    D.mark_pick(store, pick_id, "skipped", "pas pour nous")
    got = work_orders.get_order(store, oid)
    assert (got["status"], got["skip_reason"]) == ("skipped", "pas pour nous")
    assert store._get("dm_picks", pick_id)["status"] == "skipped"


def test_the_order_follows_its_video_to_the_feed_or_out(store):
    kept, a = _started(store)
    gone, b = _started(store)
    for asset_id in (a, b):
        transition(store, asset_id, "ready", actor="worker")
    transition(store, a, "approved", actor="owner")  # never through submit_asset
    transition(store, b, "archived", actor="owner")
    got = work_orders.get_order(store, kept)
    assert (got["status"], got["asset_id"]) == ("in_feed", a)
    got = work_orders.get_order(store, gone)
    assert got["status"] == "skipped" and "archivée" in got["skip_reason"]
    assert store._get("dm_picks", got["pick_id"])["status"] == "skipped"


def test_a_published_owner_video_posts_its_dm_pick(store):
    oid, a = _started(store)  # an owner idea: no source to match the pick by
    for to, actor in (("ready", "worker"), ("approved", "owner"), ("scheduled", "system"),
                      ("published", "worker")):
        transition(store, a, to, actor=actor)
    pick_id = work_orders.get_order(store, oid)["pick_id"]
    assert store._get("dm_picks", pick_id)["status"] == "posted"


def test_recover_closes_orders_a_decided_video_left_in_production(store):
    approved, a = _started(store)
    gone, b = _started(store)
    with store._tx() as c:  # decided before the orders followed their videos
        c.execute("UPDATE assets SET status='approved' WHERE id=?", (a,))
        c.execute("UPDATE assets SET status='archived' WHERE id=?", (b,))
    work_orders.recover(store, T0)
    got = work_orders.get_order(store, approved)
    assert (got["status"], got["asset_id"]) == ("in_feed", a)
    assert work_orders.get_order(store, gone)["status"] == "skipped"


def test_restyle_keeps_a_long_owner_note_whole(store):
    asset = store.add_asset(store.add_idea("motion", pillar="myths", hook_type="pov")["id"])
    note = "garde la fin " * 35  # ~450 characters: the note alone fits
    order = work_orders.restyle(store, asset["id"], None, note)
    assert order["instruction"].endswith(note.strip())
    with pytest.raises(ValueError, match="the note is at most 500"):
        work_orders.restyle(store, asset["id"], None, "x" * 501)


def test_packet_and_brief_carry_dm_orders(store, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(B, "BIBLE_PATH", tmp_path / "BIBLE.md")
    oid = _dm_order(store, "réagis", url=OURS)
    _dm_order(store)  # received: not in the packet
    for playbook in ("daily-produce", "daily-revise"):
        out = packet.write_packet(store, settings, playbook, tmp_path / playbook)
        assert out["manifest"]["sections"]["work_orders"]["count"] == 1
    data = json.loads((tmp_path / "daily-revise" / "work" / "work_orders.json").read_bytes())
    [o] = data["orders"]
    assert (o["id"], o["source"], o["source_id"], o["sender_username"]) == (
        oid, "dm", None, "amine_xenima")
    brief = json.loads((tmp_path / "daily-produce" / "work" / "brief.json").read_bytes())
    assert brief["work_orders"][0]["mode"] == "owner"


# --- backfill ---------------------------------------------------------------------------
def test_migration_backfills_existing_picks(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    monkeypatch.setattr(store_mod, "MIGRATIONS",
                        MIGRATIONS[:MIGRATIONS.index(store_mod.DM_ORDERS_SCHEMA)])  # 134
    old = CampaignStore(path)
    sid = _ref(old, "A")
    with old._tx() as c:
        c.execute("INSERT INTO work_orders (source_id, mode, created_at, updated_at)"
                  " VALUES (?, 'react', 't0', 't0')", (sid,))
        for mid, note, status in (("m1", None, "new"), ("m2", None, "new"),
                                  ("m3", "réagis", "new"), ("m4", None, "skipped")):
            c.execute("INSERT INTO dm_picks (message_id, sender_username, reel_url,"
                      " sender_note, status, skip_reason, received_at, created_at,"
                      " updated_at) VALUES (?, 'amine_xenima', ?, ?, ?, ?, 't', 't1', 't1')",
                      (mid, THEIRS, note, status, "dupe" if status == "skipped" else None))
    old.close()
    monkeypatch.undo()
    new = CampaignStore(path)
    try:
        orders = {o["pick_id"]: o for o in work_orders.list_orders(new, source="dm")}
        assert {k: (o["status"], o["instruction"], o["mode"]) for k, o in orders.items()} == {
            # migration 29 (« Reçus ») then moves the waiting ones to received
            1: ("received", None, "owner"), 2: ("received", None, "owner"),
            3: ("scheduled", "réagis", "owner"), 4: ("skipped", None, "owner")}
        assert orders[3]["scheduled_at"] == "t1" and orders[4]["skip_reason"] == "dupe"
        [trend] = work_orders.list_orders(new, source="trend")
        assert (trend["status"], trend["scheduled_at"]) == ("scheduled", "t0")
    finally:
        new.close()
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    con.close()


# --- playbooks --------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["daily-produce", "daily-revise"])
def test_playbooks_know_the_owner_orders(name):
    text = " ".join((AGENT_DIR / "playbooks" / f"{name}.md").read_text(
        encoding="utf-8").lower().split())
    for rule in ("`owner`", "own_reel", "recut of our own reel", "analyse only",
                 "analyse_work_order", "set_clip_timeline", "add_learning",
                 "skip_work_order", "never a recut", "rights", "source: \"dm\"",
                 "sender_username"):
        assert rule in text, rule
