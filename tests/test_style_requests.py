"""Step 156: the AI never parks a change request. Its decision on each video sent back
(src/studio/feedback.py decide_revision), style requests incl. invented ones
(src/studio/style_requests.py), the packet (styles in revisions, the weekly style), the
re-wake on new capability (src/agent/schedule.py), the API, the CLI, the MCP tools and the
migration. Node is never run: the templates are faked."""

import json
import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import src.instagram_mcp_server as srv
from src import scheduler
from src import store as store_mod
from src.agent import packet, runner, schedule
from src.api.app import create_app
from src.store import MIGRATIONS
from src.studio import feedback, motion, production, style_requests, work_orders
from src.studio.assets import transition
from src.studio.feedback import add_comment

from .conftest import LOCAL
from .test_agent_packet import _asset
from .test_api_assets import _settings
from .test_dm_work_orders import T0, Clock, Starts, cfg
from .test_styles import ALL, _fake_registry

INVENTED = dict(look="néon sur fond nuit", palette="noir, cyan, magenta",
                motion="coupes au rythme", typography="grotesk large", sound="synthwave")
SCENES = ["la balance s'allume", "le plat se compose", "le total s'affiche"]


@pytest.fixture(autouse=True)
def registry(monkeypatch, tmp_path):
    _fake_registry(monkeypatch)


def _sent_back(store, text="plus de scènes, plus de gens"):
    return add_comment(store, _asset(store), text=text, wants_changes=True)["asset"]["id"]


def _invented(store, name="Néon", **kw):
    return style_requests.request_style(store, "invented", name, "les vidéos nettes gagnent",
                                        SCENES, **{**INVENTED, **kw})


# --- decisions ----------------------------------------------------------------------------
def test_remade_and_waiting_are_shown_on_the_video(store):
    aid = _sent_back(store)
    got = feedback.decide_revision(store, aid, "remade", "hook plus court")
    d = got["asset"]["agent_decision"]
    assert (d["kind"], d["text"], d["why"], got["order"]) == (
        "remade", "Refaite", "hook plus court", None)
    got = feedback.decide_revision(store, aid, "waiting", "rendu en cours")
    assert got["asset"]["agent_decision"]["text"] == "En attente : rendu en cours"
    assert store.list_assets(status="revision_requested")[0]["agent_decision"]["kind"] == \
        "waiting"
    with pytest.raises(ValueError, match="say why"):
        feedback.decide_revision(store, aid, "waiting", "  ")
    with pytest.raises(ValueError, match="request_style"):
        feedback.decide_revision(store, aid, "style_requested", "x")
    with pytest.raises(ValueError, match="only a video sent back"):
        feedback.decide_revision(store, _asset(store), "remade", "x")  # ready
    with pytest.raises(KeyError):
        feedback.decide_revision(store, 999, "remade", "x")


def test_restyled_makes_a_change_order_and_the_remake_retires_the_old_video(store, settings):
    aid = _sent_back(store)
    with pytest.raises(ValueError, match="needs the style"):
        feedback.decide_revision(store, aid, "restyled", "plus de vie")
    with pytest.raises(ValueError, match="unknown style"):
        feedback.decide_revision(store, aid, "restyled", "plus de vie", style="nope")
    got = feedback.decide_revision(store, aid, "restyled", "plusieurs décors", style="macro3d")
    order, d = got["order"], got["asset"]["agent_decision"]
    assert (d["text"], d["order_id"], d["style"]) == ("Refaite en Macro 3D", order["id"],
                                                     "macro3d")
    assert (order["source"], order["style"], order["from_asset_id"]) == (
        "change", "macro3d", aid)
    assert order["instruction"].endswith("plusieurs décors")
    idea = production.create_idea(store, settings, "motion", hook="Did you know?",
                                  pillar="stories", batch_date="2026-11-17",
                                  work_order_id=order["id"])  # the same hook may come back
    new = store.add_asset(idea["id"], batch_date="2026-11-17",
                          recipe={"kind": "motion", "template": "Macro3D", "props": {}})
    transition(store, new["id"], "ready", actor="worker")
    assert store.get_asset(aid)["status"] == "revision_requested"  # not before it is in
    production.submit_asset(store, settings, new["id"], self_score=7,
                            self_score_reason="Changed: Macro 3D", caption="c")
    assert store.get_asset(aid)["status"] == "archived"
    assert work_orders.get_order(store, order["id"])["status"] == "in_feed"


# --- style requests -----------------------------------------------------------------------
def test_an_invented_style_needs_the_whole_concept(store):
    with pytest.raises(ValueError, match="palette is required"):
        _invented(store, palette=None)
    with pytest.raises(ValueError, match="exactly 3 example scenes"):
        style_requests.request_style(store, "invented", "N", "w", SCENES[:2], **INVENTED)
    with pytest.raises(ValueError, match="kind must be"):
        style_requests.request_style(store, "copied", "N", "w", SCENES)
    with pytest.raises(ValueError, match="name is at most"):
        _invented(store, name="x" * 61)
    row = _invented(store)
    assert row["status"] == "proposed" and row["kind"] == "invented"
    assert row["concept"]["scenes"] == SCENES and row["concept"]["reference"] is None
    with pytest.raises(ValueError, match=f"style request {row['id']} already asks"):
        _invented(store, name="néon")


def test_a_reference_style_unblocks_the_waiting_videos(store):
    aid, ready = _sent_back(store), _asset(store)
    with pytest.raises(ValueError, match="reference is required"):
        style_requests.request_style(store, "reference", "Danse", "w", SCENES)
    with pytest.raises(ValueError, match=f"video {ready} is not waiting"):
        style_requests.request_style(store, "reference", "Danse", "w", SCENES,
                                     reference="https://www.instagram.com/reel/X/",
                                     unblocks_asset_ids=[ready])
    row = style_requests.request_style(store, "reference", "Danse", "plusieurs personnages",
                                       SCENES, reference="https://www.instagram.com/reel/X/",
                                       unblocks_asset_ids=[aid, aid])
    assert row["unblocks"] == {"asset_ids": [aid], "order_ids": []}
    d = store.get_asset(aid)["agent_decision"]
    assert (d["kind"], d["text"], d["request_id"]) == (
        "style_requested", "Nouveau style demandé : Danse", row["id"])


def test_owner_decides_then_the_lead_builds(store):
    rid = _invented(store)["id"]
    with pytest.raises(ValueError, match="cannot become building"):
        style_requests.mark(store, rid, "building")
    with pytest.raises(ValueError, match="decision must be"):
        style_requests.decide(store, rid, "building")
    got = style_requests.decide(store, rid, "declined", "  trop sombre ")
    assert (got["status"], got["owner_note"]) == ("declined", "trop sombre")
    assert got["decided_at"]
    assert style_requests.decide(store, rid, "accepted")["status"] == "accepted"  # mind changed
    assert style_requests.list_requests(store, "accepted")[0]["id"] == rid
    assert style_requests.mark(store, rid, "building")["status"] == "building"
    with pytest.raises(ValueError, match="cannot become declined"):
        style_requests.decide(store, rid, "declined")  # the build started
    assert style_requests.mark(store, rid, "live")["status"] == "live"
    _invented(store)  # a live style's name is free again: not an open request


def test_the_weekly_invented_style_is_due_until_one_is_proposed(store):
    assert style_requests.for_agent(store)["invent_due"] is True
    style_requests.request_style(store, "reference", "Danse", "w", SCENES, reference="r")
    assert style_requests.for_agent(store)["invent_due"] is True  # a reference doesn't count
    row = _invented(store)
    view = style_requests.for_agent(store)
    assert view["invent_due"] is False and view["last_invented_at"] == row["created_at"]
    later = store_mod.parse_iso(row["created_at"]) + style_requests.INVENT_EVERY
    assert style_requests.for_agent(store, later)["invent_due"] is True
    assert [r["name"] for r in view["requests"]] == ["Néon", "Danse"]


# --- the packet ---------------------------------------------------------------------------
def test_revisions_carry_the_enabled_styles_and_a_decision_handles_one(store, tmp_path):
    aid, other = _sent_back(store), _sent_back(store)
    out = packet.write_packet(store, cfg(), "daily-revise", tmp_path)
    data = json.loads((tmp_path / "work" / "revisions.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in data["styles"]] == ALL
    assert data["styles"][0]["description"]
    assert [r["asset"]["id"] for r in data["requests"]] == out["ids"]["revisions"]
    assert out["manifest"]["sections"]["revisions"]["count"] == 2
    feedback.decide_revision(store, aid, "waiting", "rendu de nuit")
    assert packet.gaps(store, out).startswith(f"1 of 2 revisions not handled: #{other};")


def test_the_style_requests_section_reads_the_style_breakdown(store, tmp_path):
    out = packet.write_packet(store, cfg(), "daily-learn", tmp_path)
    data = json.loads((tmp_path / "work" / "style_requests.json").read_text(encoding="utf-8"))
    assert data["invent_due"] and data["breakdown"]["tag"] == "style"
    assert [s["id"] for s in data["styles"]][:2] == ["pixel", "voxel"]
    assert out["manifest"]["sections"]["style_requests"]["count"] == 1


# --- re-wake on new capability -------------------------------------------------------------
@pytest.fixture
def clock(monkeypatch):
    c = Clock()  # every stamp (feedback, runs, orders) on one clock, as in 147's tests
    for mod in (work_orders, store_mod, runner):
        monkeypatch.setattr(mod, "utcnow", c)
    return c


def _run(store, minutes, f):
    return schedule.order_run(store, cfg(), T0 + timedelta(minutes=minutes), start=f.start,
                              check=f.check)


def test_a_new_template_or_style_wakes_the_waiting_videos(store, monkeypatch, clock):
    f = Starts()
    assert _run(store, 0, f) is None  # nothing waits; the first look records the registry
    _sent_back(store)
    clock.set(5)
    run = store.start_agent_run("daily-revise")  # it read the request and left it waiting
    store.finish_agent_run(run["id"], "succeeded")
    assert _run(store, 60, f) is None
    _fake_registry(monkeypatch, extra=[("DanceFloor", "dance", "Danse")])  # it went live
    assert _run(store, 61, f) is None  # the debounce
    assert _run(store, 64, f) == "daily-revise" and f.runs == ["daily-revise"]
    assert store.get_state(schedule.CAPABILITIES_KEY)["styles"]["dance"] == ["DanceFloor"]
    clock.set(64)
    store.start_agent_run("daily-revise")  # the run it started
    assert _run(store, 120, f) is None  # once per gain


def test_a_style_turned_off_wakes_nothing_and_nothing_waiting_wakes_nothing(store, monkeypatch):
    from src.studio import styles

    f = Starts()
    _run(store, 0, f)
    styles.set_choice(store, "voxel", enabled=False)
    assert _run(store, 10, f) is None
    styles.set_choice(store, "voxel", enabled=True)  # back on: a gain, but nothing waits
    assert _run(store, 20, f) is None and f.runs == []
    assert store.get_state(schedule.CAPABILITIES_KEY)["gained_at"]


def test_no_node_keeps_the_last_known_registry(store, monkeypatch):
    def broken():
        raise motion.MotionError("no node")

    monkeypatch.setattr(motion, "list_templates", broken)
    assert schedule.capability_gained(store, T0) is None
    assert store.get_state(schedule.CAPABILITIES_KEY) is None


# --- API, CLI, MCP, migration --------------------------------------------------------------
@pytest.fixture
def tc(store):
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as c:
        yield c


def test_style_requests_api(tc, store):
    rid = _invented(store)["id"]
    [row] = tc.get("/api/style-requests").json()
    assert row["id"] == rid and row["concept"]["palette"] == INVENTED["palette"]
    assert tc.get("/api/style-requests?status=accepted").json() == []
    assert tc.get("/api/style-requests?status=nope").status_code == 422
    r = tc.patch(f"/api/style-requests/{rid}", json={"decision": "accepted", "note": "go"})
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert tc.patch(f"/api/style-requests/{rid}", json={"decision": "live"}).status_code == 422
    assert tc.patch("/api/style-requests/999", json={"decision": "declined"}).status_code == 404
    aid = _sent_back(store)
    feedback.decide_revision(store, aid, "waiting", "rendu de nuit")
    [a] = tc.get("/api/assets?status=revision_requested").json()
    assert a["agent_decision"]["text"] == "En attente : rendu de nuit"


def test_cli_lists_and_marks(store, monkeypatch, capsys):
    rid = _invented(store)["id"]
    style_requests.decide(store, rid, "accepted")
    monkeypatch.setattr(scheduler, "CampaignStore", lambda path: store)
    monkeypatch.setattr(store, "close", lambda: None)
    with pytest.raises(SystemExit) as done:
        scheduler.main(["style-requests", "list", "--status", "accepted"])
    assert done.value.code == 0 and json.loads(capsys.readouterr().out)[0]["id"] == rid
    with pytest.raises(SystemExit) as done:
        scheduler.main(["style-requests", "mark", str(rid), "live"])
    assert done.value.code == 1 and "cannot become live" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        scheduler.main(["style-requests", "mark", str(rid), "building"])
    assert style_requests.get_request(store, rid)["status"] == "building"


async def test_mcp_tools(store, monkeypatch):
    monkeypatch.setattr(srv, "store", lambda: store)
    aid = _sent_back(store)
    got = await srv.request_style("invented", "Néon", "why", SCENES, motion_language="m",
                                  **{k: v for k, v in INVENTED.items() if k != "motion"},
                                  unblocks_asset_ids=[aid])
    assert got["concept"]["motion"] == "m"
    with pytest.raises(srv.ToolError, match="already asks"):
        await srv.request_style("invented", "Néon", "why", SCENES, motion_language="m",
                                **{k: v for k, v in INVENTED.items() if k != "motion"})
    got = await srv.decide_revision(aid, "restyled", "plus de décors", style="cinema")
    assert got["asset"]["agent_decision"]["text"] == "Refaite en Pixel ciné"


def test_migration_25_adds_the_table_and_the_decision(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    for i, script in enumerate(MIGRATIONS[:MIGRATIONS.index(store_mod.STYLE_REQUESTS_SCHEMA)]):
        con.executescript(script)
        con.execute(f"PRAGMA user_version={i + 1}")
    con.close()
    s = store_mod.CampaignStore(str(db))
    try:
        assert _invented(s)["id"] == 1
        with s._tx() as c:
            assert "agent_decision" in {r[1] for r in c.execute("PRAGMA table_info(assets)")}
            assert c.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    finally:
        s.close()
