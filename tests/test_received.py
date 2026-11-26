"""« Reçus » (owner 2026-11-25): a DM'd Reel waits `received` for the owner, who confirms it
with a route (style | new_style | rea) -> `confirmed` on Planning, where nothing starts until
his « Lancer » schedules it; and the rea-video breakdown the `rea` route reads."""

import subprocess

import pytest
from fastapi.testclient import TestClient

from src import store as store_mod
from src.agent import schedule
from src.api.app import create_app
from src.store import MIGRATIONS, CampaignStore
from src.studio import dm_picks, planning, rea, style_requests, work_orders

from .conftest import LOCAL
from .test_api_assets import _settings
from .test_dm_work_orders import _received
from .test_planning import NOW, agent_dir, cfg  # noqa: F401 - fixture


def test_confirm_checks_the_route_and_only_takes_a_received_dm(store):
    oid = _received(store, "fais pareil")
    with pytest.raises(ValueError, match="method"):
        work_orders.confirm(store, oid, "copy")
    with pytest.raises(ValueError, match="new style"):
        work_orders.confirm(store, oid, "new_style", "pixel")
    o = work_orders.confirm(store, oid, "new_style")
    assert (o["status"], o["method"], o["style"], o["instruction"]) == (
        "confirmed", "new_style", None, work_orders.METHOD_TEXT["new_style"])
    o = work_orders.confirm(store, oid, "rea", None, " garde la fin ")  # rewritten
    assert (o["method"], o["instruction"], o["scheduled_at"]) == ("rea", "garde la fin", None)
    assert work_orders.for_agent(store) == []  # confirmed: the agent never sees it
    work_orders.launch(store, oid)
    with pytest.raises(work_orders.InvalidTransition):
        work_orders.confirm(store, oid, "style")  # launched: too late


def test_api_confirm_and_discard(store):
    keep, drop = _received(store), _received(store)
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as tc:
        assert [o["id"] for o in tc.get("/api/work-orders?source=dm&status=received").json()
                ] == [drop, keep]
        assert tc.post(f"/api/work-orders/{keep}/confirm",
                       json={"method": "x"}).status_code == 422
        r = tc.post(f"/api/work-orders/{keep}/confirm", json={"method": "style"})
        assert r.status_code == 200 and r.json()["status"] == "confirmed"
        assert tc.delete(f"/api/research/work-orders/{drop}").status_code == 204  # « Écarter »
        assert tc.get("/api/dm-picks?status=skipped").json()[0]["skip_reason"] == (
            work_orders.CANCELLED)


@pytest.mark.usefixtures("agent_dir")
def test_lancer_on_planning_schedules_the_confirmed_order(store):
    oid = _received(store)
    with pytest.raises(ValueError):
        work_orders.launch(store, oid)  # received: confirm it first
    work_orders.confirm(store, oid, "rea")
    out = planning.launch(store, cfg(), [{"kind": "work_order", "id": oid}], NOW)
    assert out["requested"] == [{"kind": "work_order", "id": oid}] and not out["refused"]
    assert work_orders.get_order(store, oid)["status"] == "scheduled"
    [req] = schedule.launch_requests(store)
    assert req["only"]["order_ids"] == [oid]
    assert [o["method"] for o in work_orders.for_agent(store)] == ["rea"]


def test_breakdown_runs_rea_once_then_reuses_it(store, settings, tmp_path, monkeypatch):
    src = store.add_source("instagram", url="https://www.instagram.com/reel/A/", role="clip",
                           local_path="clips/a.mp4")["id"]
    with pytest.raises(ValueError, match="download_reel"):
        rea.breakdown(store, settings, store.add_source("instagram")["id"])
    ok = []
    monkeypatch.setattr(rea, "installed", lambda: bool(ok))
    monkeypatch.setattr(rea, "OUT_DIR", tmp_path / "rea")
    with pytest.raises(ValueError, match="not installed"):
        rea.breakdown(store, settings, src)
    ok.append(1)
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        assert "INSTAGRAM_ACCESS_TOKEN" not in kw["env"]  # the allow-list only
        out = tmp_path / "rea" / str(src)
        (out / "video").mkdir(parents=True)
        (out / "VIDEO.md").write_text("# card", encoding="utf-8")
        (out / "video" / "timeline.md").write_text("#1 0.0s hook", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(rea.subprocess, "run", run)
    got = rea.breakdown(store, settings, src)
    assert calls[0][1:4] == ["-m", "rea_video", "decompose"]
    assert "--no-vlm" in calls[0]  # offline, whatever rea-video's own prefs say
    assert calls[0][4].endswith("a.mp4")
    assert "# card" in got["breakdown"] and "#1 0.0s hook" in got["breakdown"]
    assert rea.breakdown(store, settings, src)["breakdown"] == got["breakdown"]
    assert len(calls) == 1  # reused


def test_the_agent_never_sees_nor_skips_an_order_waiting_for_the_owner(store):
    received, confirmed = _received(store), _received(store)
    work_orders.confirm(store, confirmed, "style")
    assert work_orders.for_agent(store, None) == []  # status None: all but the owner's
    for oid in (received, confirmed):
        with pytest.raises(ValueError, match="waits for the owner"):
            work_orders.skip_for_agent(store, oid, "no")
    assert {o["status"] for o in work_orders.list_orders(store)} == {"received", "confirmed"}


def test_switching_route_drops_the_old_routes_default_text(store):
    oid = _received(store)
    first = work_orders.confirm(store, oid, "rea")["instruction"]
    assert first == work_orders.METHOD_TEXT["rea"]
    # the page sends the textarea back as it is: the old default is not the owner's words
    o = work_orders.confirm(store, oid, "style", None, first)
    assert o["instruction"] == work_orders.METHOD_TEXT["style"]


def test_a_route_reuses_nothing_and_new_style_waits_for_its_style(store, settings):
    oid = _received(store, url="https://www.instagram.com/reel/THEIRS9/")
    work_orders.confirm(store, oid, "new_style")
    work_orders.launch(store, oid)
    reel = store.add_source("instagram", url="https://www.instagram.com/reel/THEIRS9/",
                            role="clip")["id"]
    with pytest.raises(ValueError, match="Reel itself is not used"):
        work_orders.check_idea(store, oid, "remix", reel)
    with pytest.raises(ValueError, match="request_style"):
        work_orders.check_idea(store, oid, "motion", None)
    req = style_requests.request_style(store, "reference", "Scan", "the Reel's look",
                                       ["a", "b", "c"], reference="the Reel",
                                       unblocks_order_ids=[oid])
    style_requests.mark(store, req["id"], "building")
    style_requests.mark(store, req["id"], "live")
    assert work_orders.check_idea(store, oid, "motion", None)["id"] == oid


def test_migration_moves_waiting_dm_orders_to_received(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    monkeypatch.setattr(store_mod, "MIGRATIONS",
                        MIGRATIONS[:MIGRATIONS.index(store_mod.RECEIVED_SCHEMA)])
    old = CampaignStore(path)
    with old._tx() as c:
        for i, status in enumerate(("needs_instruction", "scheduled")):
            c.execute("INSERT INTO dm_picks (message_id, sender_username, reel_url,"
                      " received_at, created_at, updated_at) VALUES (?, 'x', 'u', 't', 't', 't')",
                      (f"m{i}",))
            c.execute("INSERT INTO work_orders (origin, pick_id, mode, status, created_at,"
                      " updated_at) VALUES ('dm', ?, 'owner', ?, 't', 't')", (i + 1, status))
    old.close()
    monkeypatch.setattr(store_mod, "MIGRATIONS", MIGRATIONS)
    new = CampaignStore(path)
    assert [(o["status"], o["method"]) for o in work_orders.list_orders(new, newest=False)] == [
        ("received", None), ("scheduled", None)]  # one already scheduled keeps its path
    new.close()


def test_migration_30_moves_what_a_draft_of_29_left(tmp_path, monkeypatch):
    path = str(tmp_path / "draft.db")
    monkeypatch.setattr(store_mod, "MIGRATIONS",
                        MIGRATIONS[:MIGRATIONS.index(store_mod.RECEIVED_AGAIN_SCHEMA)])
    old = CampaignStore(path)
    with old._tx() as c:  # as a draft of 29 left it: still needs_instruction
        c.execute("INSERT INTO dm_picks (message_id, sender_username, reel_url,"
                  " received_at, created_at, updated_at) VALUES ('m', 'x', 'u', 't', 't', 't')")
        c.execute("INSERT INTO work_orders (origin, pick_id, mode, status, created_at,"
                  " updated_at) VALUES ('dm', 1, 'owner', 'needs_instruction', 't', 't')")
    old.close()
    monkeypatch.setattr(store_mod, "MIGRATIONS", MIGRATIONS)
    new = CampaignStore(path)
    assert [o["status"] for o in work_orders.list_orders(new)] == ["received"]
    new.close()


def test_a_failed_reel_stays_to_retry_or_take_off(store):
    oid = _received(store)
    work_orders.confirm(store, oid, "style")
    work_orders.launch(store, oid)
    work_orders.skip_order(store, oid, "le rendu a échoué")
    pick = work_orders.get_order(store, oid)["pick_id"]
    assert store._get("dm_picks", pick)["status"] == "skipped"
    o = work_orders.confirm(store, oid, "rea")  # « Relancer »
    assert (o["status"], o["skip_reason"], o["scheduled_at"]) == ("confirmed", None, None)
    assert (store._get("dm_picks", pick)["status"], store._get("dm_picks", pick)["skip_reason"]
            ) == ("new", None)  # its pick lives again with it
    work_orders.launch(store, oid)
    work_orders.skip_order(store, oid, "encore")
    work_orders.delete_order(store, oid)  # « Retirer »: kept, off the page
    o = work_orders.get_order(store, oid)
    assert (o["status"], o["skip_reason"]) == ("skipped", work_orders.CANCELLED)
    with pytest.raises(work_orders.InvalidTransition):
        work_orders.confirm(store, oid, "style")


def test_the_style_built_for_it_is_the_only_one_it_is_made_in(store, monkeypatch):
    monkeypatch.setattr(style_requests.styles, "get_style", lambda store, s: {"id": s})
    oid = _received(store)
    work_orders.confirm(store, oid, "new_style")
    work_orders.launch(store, oid)
    req = style_requests.request_style(store, "reference", "Scan", "look", ["a", "b", "c"],
                                       reference="the Reel", unblocks_order_ids=[oid])
    with pytest.raises(ValueError, match="live"):
        style_requests.mark(store, req["id"], "building", "physique")
    style_requests.mark(store, req["id"], "building")
    style_requests.mark(store, req["id"], "live", "physique")
    assert work_orders.get_order(store, oid)["style"] == "physique"
    with pytest.raises(ValueError, match="asks for style 'physique'"):
        work_orders.check_idea(store, oid, "motion", None, "pixel")
    assert work_orders.check_idea(store, oid, "motion", None, "physique")["id"] == oid


def test_the_agent_cannot_mark_a_pick_or_hold_an_order_waiting_for_the_owner(store):
    oid = _received(store)
    pick = work_orders.get_order(store, oid)["pick_id"]
    with pytest.raises(ValueError, match="waits for the owner"):
        dm_picks.mark_for_agent(store, pick, "skipped", "nope")
    with pytest.raises(ValueError, match="not open"):
        style_requests.request_style(store, "reference", "Scan", "look", ["a", "b", "c"],
                                     reference="r", unblocks_order_ids=[oid])
    assert work_orders.get_order(store, oid)["status"] == "received"
    dm_picks.mark_pick(store, pick, "skipped", "the owner's own skip")  # the owner still may
    assert work_orders.get_order(store, oid)["status"] == "skipped"


@pytest.mark.usefixtures("agent_dir")
def test_a_confirmed_card_is_titled_by_the_owner_words_else_the_sender(store):
    plain, said = _received(store), _received(store)
    work_orders.confirm(store, plain, "style")
    work_orders.confirm(store, said, "style", None, "garde la chute")
    titles = {i["ids"]["order_id"]: i["title"] for i in
              planning.build_planning(store, cfg(), NOW)["items"] if i["waits_on"] == "launch"}
    assert titles == {plain: "Reel de @amine_xenima", said: "garde la chute"}
