"""Step 188b: Claude's planned videos: planned with no job and no voice, reviewed, edited,
released into the line (now, at once ahead, or on a timer) or removed by the owner."""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.instagram_mcp_server as srv
from src import store as store_mod
from src.api.app import create_app
from src.store import MIGRATIONS, CampaignStore
from src.studio import ffmpeg, housekeeping, line, motion, planned, planning, remix, render, voices
from tests.test_studio_motion import FACTQUEST, VALID, _settings
from tests.test_studio_remix import SCRIPT, _idea, _source
from tests.test_studio_render import FAR_PAST, INFO
from tests.test_studio_voice_job import FakeTTS

from .conftest import LOCAL

NOW = datetime(2026, 11, 23, 10, tzinfo=timezone.utc)


@pytest.fixture
def s(tmp_path):
    return _settings(tmp_path, tts_provider="http", tts_http_url="http://127.0.0.1:1/tts",
                     tts_cache_dir=str(tmp_path / "cache"))


@pytest.fixture
def checked(monkeypatch):
    """validate_props echoes the props; every call is recorded (the re-validation)."""
    seen = []

    def validate(template, props):
        seen.append(props)
        return {**VALID, "props": props, "coverFrame": 12}

    monkeypatch.setattr(motion, "validate_props", validate)
    monkeypatch.setattr(motion, "list_templates", lambda: [{"id": "FactQuest", "style": "pixel"}])
    return seen


@pytest.fixture
def fake(tmp_path, monkeypatch):
    audio = tmp_path / "abc.wav"
    audio.write_bytes(b"RIFF")
    provider = FakeTTS(audio)
    monkeypatch.setattr(motion, "get_provider", lambda settings: provider)
    return provider


def _plan(store, s, **kw):
    idea = store.add_idea("motion", hook="Le mythe du jus détox", batch_date="2026-11-23",
                          citations=[{"url": "https://example.org/a", "title": "Étude"}])
    return motion.queue_motion_render(store, s, template="FactQuest", props=FACTQUEST,
                                      idea_id=idea["id"], plan=True, **kw)["asset"]


def _cards(store, s):
    return [i for i in planning.build_planning(store, s, NOW)["items"] if i["section"] == "ideas"]


def _run(store, s):
    rendered = []

    def render_fn(asset, media_root, progress):
        rendered.append(asset["recipe"])
        return INFO, {"file_path": "video.mp4"}

    job = store.claim_render_jobs(1, stale_before=FAR_PAST)[0]
    render.run_job(store, s.media_root, job, settings=s, render_fn=render_fn,
                   qc_fn=lambda *a: {"passed": True})
    return rendered


def test_a_plan_stores_the_recipe_with_no_job_no_voice_and_shows_a_card(store, s, checked,
                                                                         fake):
    a = _plan(store, s, caption="Le jus détox ? #nutrition", description="Trois faits.")
    assert a["status"] == "planned" and a["caption"] == "Le jus détox ? #nutrition"
    assert store.list_render_jobs(asset_id=a["id"]) == [] and fake.said == []
    assert a["recipe"]["voice_todo"] == {"voice": voices.default_voice(store)}
    assert render.voice_ahead(store, s) == 0 and line.waiting(store) == []
    assert store.list_assets() == []  # the Inbox and list_assets leave it out
    assert [x["id"] for x in store.list_assets(status="planned")] == [a["id"]]
    (card,) = _cards(store, s)
    assert card["kind"] == "claude_idea" and card["est_start"] is None
    assert card["title"] == "Le mythe du jus détox" and card["engine"] == "remotion"
    idea = card["idea"]
    assert idea["script"][0] == {"text": FACTQUEST["hook"], "editable": True}
    assert len(idea["script"]) == len(FACTQUEST["facts"]) + 2
    assert idea["template"] == "FactQuest" and idea["music"] == FACTQUEST.get("music")
    assert idea["sources"] == [{"url": "https://example.org/a", "title": "Étude"}]
    assert idea["description"] == "Trois faits." and "none" in idea["music_options"]
    with pytest.raises(ValueError, match="description"):
        _plan(store, s, description=" ")
    with pytest.raises(ValueError, match="not a re-render"):
        motion.queue_motion_render(store, s, template="FactQuest", props=FACTQUEST,
                                   asset_id=a["id"], plan=True)


def test_cards_newest_batch_first_oldest_first_inside_it(store, s, checked, fake):
    old = _plan(store, s)
    with store._tx() as c:
        c.execute("UPDATE assets SET batch_date='2026-11-20' WHERE id=?", (old["id"],))
    first, second = _plan(store, s), _plan(store, s)
    assert [c["ids"]["asset_id"] for c in _cards(store, s)] == [first["id"], second["id"],
                                                               old["id"]]


def test_release_start_now_and_timer_put_it_in_the_line(store, s, checked, fake):
    queued = motion.queue_motion_render(store, s, template="FactQuest", props=FACTQUEST,
                                        idea_id=store.add_idea("motion")["id"])["job"]
    a, b, c = _plan(store, s), _plan(store, s), _plan(store, s)
    out = planned.release(store, s, a["id"])
    assert out["asset"]["status"] == "rendering" and out["job"]["state"] == "queued"
    assert out["job"]["created_at"] >= queued["created_at"]  # arrives at its release
    now = planned.release(store, s, b["id"], now=True)["job"]
    at = NOW + timedelta(hours=3)
    timed = planned.release(store, s, c["id"], at=at)["job"]
    order = [(i["id"], i["not_before"]) for i in line.waiting(store)]
    assert [i for i, _ in order] == [now["id"], queued["id"], out["job"]["id"], timed["id"]]
    assert order[-1][1] == "2026-11-23T13:00:00+00:00"
    assert fake.said == [] and _cards(store, s) == []
    with pytest.raises(ValueError, match="n'est plus une idée à valider"):
        planned.release(store, s, a["id"])
    with pytest.raises(ValueError, match="pas les deux"):
        planned.release(store, s, _plan(store, s)["id"], now=True, at=at)


def test_edit_revalidates_and_changes_what_the_job_voices(store, s, checked, fake):
    a = _plan(store, s)
    lines = [x["text"] for x in planned.cards(store)[0]["script"]]
    before = len(checked)
    with pytest.raises(ValueError, match="not available"):  # nothing saved on a refusal
        planned.edit(store, s, a["id"], voice="no-such-voice", lines=["Nouveau", *lines[1:]])
    assert store.get_asset(a["id"])["recipe"] == a["recipe"]
    with pytest.raises(ValueError, match="envoie"):
        planned.edit(store, s, a["id"], lines=lines[:1])
    edited = planned.edit(store, s, a["id"], lines=["Le jus  détox ne détoxifie rien.",
                                                    *lines[1:]],
                          music="none", caption="Nouvelle légende", description="Trois faits.")
    assert len(checked) > before and checked[-1]["hook"] == "Le jus détox ne détoxifie rien."
    card = planned.cards(store)[0]
    assert card["script"][0]["text"] == "Le jus détox ne détoxifie rien."
    assert card["music"] == "none" and card["caption"] == "Nouvelle légende"
    assert edited["recipe"]["props"]["music"] == "none"
    planned.release(store, s, a["id"])
    _run(store, s)
    assert fake.said[0][0].splitlines()[0] == "Le jus détox ne détoxifie rien."
    with pytest.raises(ValueError, match="n'est plus une idée à valider"):
        planned.edit(store, s, a["id"], caption="trop tard")


def test_a_line_made_of_several_texts_is_shown_but_not_editable():
    props = {"hook": {"labels": ["Un", "deux"]}, "beats": [{"labels": ["Trois"]}]}
    have = planned._paths("PaperStory", props)
    assert have == [("Un deux", None), ("Trois", ("beats", 0, "labels", 0))]
    assert planned._set_lines("PaperStory", props, ["Un deux", "Quatre"])["beats"][0][
        "labels"] == ["Quatre"]
    with pytest.raises(ValueError, match="plusieurs textes"):
        planned._set_lines("PaperStory", props, ["Autre", "Trois"])


def test_remove_archives_it_and_housekeeping_leaves_planned_alone(store, s, checked, fake):
    a, b = _plan(store, s), _plan(store, s)
    with store._tx() as c:  # long past every unreviewed / best_before limit
        c.execute("UPDATE assets SET batch_date='2026-01-01', best_before='2026-01-02'")
    assert housekeeping.archive_stale(store, s, date(2026, 11, 23)) == []
    assert planned.remove(store, a["id"]) == {"asset_id": a["id"], "removed": True}
    assert store.get_asset(a["id"])["status"] == "archived"
    assert store.get_asset(b["id"])["status"] == "planned"
    with pytest.raises(ValueError, match="statut archived"):
        planned.remove(store, a["id"])


@pytest.fixture
def remix_cfg(tmp_path):
    return _settings(tmp_path / "media", tts_provider="http",
                     tts_http_url="http://127.0.0.1:1/tts")


def test_a_planned_remix_claims_its_piece_and_checks_its_rights_at_release(
        store, remix_cfg, reel):
    src = _source(store)
    idea = _idea(store, src)
    out = remix.render_remix(store, remix_cfg, idea["id"], src["id"], hook="Wait for it",
                             script=SCRIPT, trim=(10, 30), caption="Wow @creator", plan=True)
    a = out["asset"]
    assert out["job"] is None and out["piece"] is None and a["status"] == "planned"
    assert store.get_reaction_reel(reel["id"])["cursor_s"] == 0  # no piece yet
    assert "reaction" not in a["recipe"]["inputs"]
    (card,) = planned.cards(store)
    assert card["kind"] == "remix" and card["script"] == [{"text": SCRIPT, "editable": True}]
    assert card["music"] == "music-overworld"
    planned.edit(store, remix_cfg, a["id"], music="none", lines=["Regarde sa tête."])
    env = store.get_asset(a["id"])["recipe"]
    assert "music" not in env["inputs"] and env["voice_todo"]["script"] == "Regarde sa tête."
    with store._tx() as c:  # the rights changed since the plan
        c.execute("UPDATE sources SET rights_basis='unknown' WHERE id=?", (src["id"],))
    with pytest.raises(ValueError):
        planned.release(store, remix_cfg, a["id"])
    assert store.get_asset(a["id"])["status"] == "planned"
    assert store.get_reaction_reel(reel["id"])["cursor_s"] == 0
    with store._tx() as c:
        c.execute("UPDATE sources SET rights_basis='commentary' WHERE id=?", (src["id"],))
    job = planned.release(store, remix_cfg, a["id"])["job"]
    asset = store.get_asset(a["id"])
    assert job["state"] == "queued" and asset["status"] == "rendering"
    assert asset["recipe"]["inputs"]["reaction"].endswith(".mp4")
    assert store.get_reaction_reel(reel["id"])["cursor_s"] == pytest.approx(20)


@pytest.fixture
def reel(store, monkeypatch):
    # the piece cut writes its file, no ffmpeg
    monkeypatch.setattr(ffmpeg, "run", lambda args, **kw: Path(args[-1]).write_bytes(b"piece"))
    r = store.add_reaction_reel(".mp4", 600.0, True, [])
    return store.activate_reaction_reel(r["id"])


def test_routes_are_thin_doors(store, s, checked, fake, monkeypatch):
    a, b = _plan(store, s), _plan(store, s)
    with TestClient(create_app(s, store=store), base_url=LOCAL,
                    headers={"Origin": LOCAL}) as tc:
        r = tc.patch(f"/api/planning/idea/{a['id']}", json={"caption": "Une autre légende"})
        assert r.status_code == 200 and r.json()["caption"] == "Une autre légende"
        assert tc.patch(f"/api/planning/idea/{a['id']}", json={"x": 1}).status_code == 422
        r = tc.post(f"/api/planning/idea/{a['id']}/release", json={"now": True})
        assert r.json()["job"]["line_pos"] < 0
        r = tc.post(f"/api/planning/idea/{a['id']}/remove")
        assert r.status_code == 422 and "n'est plus une idée" in r.json()["message"]
        assert tc.post(f"/api/planning/idea/{b['id']}/remove").json()["removed"] is True
        assert tc.post("/api/planning/idea/999/release", json={}).status_code == 404


async def test_the_mcp_tool_plans(monkeypatch):
    seen = {}

    def queue(store, settings, **kw):
        seen.update(kw)
        return {"asset": {"id": 7, "status": "planned"}, "job": None}

    monkeypatch.setattr(motion, "queue_motion_render", queue)
    monkeypatch.setattr(srv, "store", lambda: None)
    monkeypatch.setattr(srv, "get_settings", srv.config.get_settings)
    assert await srv.render_motion("FactQuest", {}, idea_id=1, plan=True,
                                   description="d") == {
        "asset_id": 7, "job_id": None, "state": "planned"}
    assert seen["plan"] is True and seen["description"] == "d"
    assert "render_motion" in srv.AGENT_TOOLS and "render_remix" in srv.AGENT_TOOLS


def test_migration_lets_old_assets_table_take_planned(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    monkeypatch.setattr(store_mod, "MIGRATIONS", MIGRATIONS[:-1])
    old = CampaignStore(path)
    kept = old.add_asset(old.add_idea("motion")["id"])
    old.add_render_job(kept["id"], "k")  # a child row: the table is not rebuilt
    old.close()
    monkeypatch.setattr(store_mod, "MIGRATIONS", MIGRATIONS)
    new = CampaignStore(path)
    try:
        assert new.get_asset(kept["id"])["status"] == "rendering"
        assert new.add_asset(kept["idea_id"], status="planned")["status"] == "planned"
        with pytest.raises(sqlite3.IntegrityError), new._tx() as c:
            c.execute("UPDATE assets SET status='bogus'")
    finally:
        new.close()
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    con.close()
