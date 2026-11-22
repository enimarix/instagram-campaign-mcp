"""Step 138: styles as buttons. The style registry (src/studio/styles.py) from the templates +
brand/styles.json, the owner's Settings per style, GET /api/styles and its previews, the
two new launch points (« Créer une vidéo », « même vidéo, autre style »), the chosen style
stored on the order and the idea and enforced in create_idea / render_motion, the daily
share, the learning dimension and the migration. Node is never run: the templates are faked."""

import json
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src import store as store_mod
from src.api.app import create_app
from src.learning import brief as B
from src.learning import funnel
from src.learning.quotas import todays_quotas
from src.store import MIGRATIONS, CampaignStore
from src.studio import motion, production, styles, work_orders
from src.studio.assets import transition

from .conftest import LOCAL
from .test_api_assets import _settings
from .test_trending import _ref

DAY = "2026-11-17"
# The registry as motion.list_templates() lists it today (registry.ts STYLES + cinematic).
TEMPLATES = [
    ("FactQuest", "pixel", "Pixel 8-bit"), ("QuizChest", "pixel", "Pixel 8-bit"),
    ("VoxelQuest", "voxel", "3D 8-bit"), ("PaperStory", "paper", "Papier"),
    ("Cutaway", "cutaway", "Pixel explicatif"), ("Editorial", "editorial", "Éditorial"),
    ("PixelCinema", "cinema", "Pixel ciné"), ("Macro3D", "macro3d", "Macro 3D"),
    ("SitcomSkit", "sitcom", "Sitcom 3D"), ("CinematicSkit", "blender", "Blender"),
]
ALL = ["pixel", "voxel", "paper", "cutaway", "editorial", "cinema", "macro3d", "sitcom", "blender"]


def _fake_registry(monkeypatch, extra=()):
    rows = [{"id": t, "style": s, "styleLabel": label} for t, s, label in (*TEMPLATES, *extra)]
    monkeypatch.setattr(motion, "list_templates", lambda: rows)


@pytest.fixture(autouse=True)
def registry(monkeypatch, tmp_path):
    _fake_registry(monkeypatch)
    monkeypatch.setattr(styles, "SAMPLES_DIR", tmp_path / "samples")


def _idea(store, settings, hook, **kw):
    kw.setdefault("pillar", "stories")
    return production.create_idea(store, settings, "motion", hook=hook, batch_date=DAY, **kw)


# --- registry ---------------------------------------------------------------------------
def test_every_style_is_listed_with_its_json_entry(store):
    listed = styles.list_styles(store)
    assert [s["id"] for s in listed] == ALL
    by = {s["id"]: s for s in listed}
    assert by["voxel"]["label"] == "3D 8-bit" and by["voxel"]["address"] == "vous"
    assert by["voxel"]["description"] and by["voxel"]["end_card"] == "voxel"
    assert by["pixel"]["templates"] == ["FactQuest", "QuizChest"]
    assert all(s["enabled"] and s["share"] is None for s in listed)
    # no sample files here: no preview, never an error
    assert by["macro3d"]["preview"] == {"still": None, "clip": None}


def test_json_entries_match_the_registry_and_end_card_styles():
    entries = styles._entries()
    assert set(entries) == set(ALL)  # every style the templates have today
    assert {e["address"] for e in entries.values()} <= {"tu", "vous"}
    assert all(e["description"] and e["label"] for e in entries.values())


def test_new_template_style_shows_without_entry_and_unknown_entry_is_ignored(
        store, monkeypatch, tmp_path):
    _fake_registry(monkeypatch, extra=[("Clay", "clay", "Pâte à modeler")])
    path = tmp_path / "styles.json"
    path.write_text(json.dumps({"styles": {"ghost": {"label": "Ghost"},
                                           "pixel": {"label": "Rétro"}}}), "utf-8")
    monkeypatch.setattr(styles, "STYLES_PATH", path)
    by = {s["id"]: s for s in styles.list_styles(store)}
    assert "ghost" not in by
    assert by["clay"]["label"] == "Pâte à modeler" and by["clay"]["enabled"]
    assert by["clay"]["description"] is None and by["clay"]["templates"] == ["Clay"]
    assert by["pixel"]["label"] == "Rétro" and by["voxel"]["label"] == "3D 8-bit"


def test_preview_files_when_present(store, tmp_path):
    clip = tmp_path / "samples" / "154" / "macro3d-phone.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"mp4")
    by = {s["id"]: s for s in styles.list_styles(store)}
    assert by["macro3d"]["preview"] == {"still": None,
                                        "clip": "/api/styles/macro3d/preview/clip"}
    assert styles.preview_file("macro3d", "clip") == clip
    assert styles.preview_file("macro3d", "still") is None
    assert styles.preview_file("nope", "clip") is None


def test_owner_turns_styles_off_and_sets_a_share(store):
    assert styles.set_choice(store, "paper", enabled=False)["enabled"] is False
    with pytest.raises(ValueError, match="turned off in Settings"):
        styles.check_style(store, "paper")
    assert styles.check_style(store, None) is None
    with pytest.raises(ValueError, match="unknown style 'nope'"):
        styles.check_style(store, "nope")
    s = styles.set_choice(store, "voxel", share=0.3)
    assert (s["share"], s["enabled"]) == (0.3, True)
    assert styles.set_choice(store, "voxel", enabled=False)["share"] == 0.3  # kept
    assert styles.set_choice(store, "voxel", share=None)["share"] is None
    for bad in (0, 1.5, -0.1):
        with pytest.raises(ValueError, match="share must be"):
            styles.set_choice(store, "voxel", share=bad)


# --- enforcement ------------------------------------------------------------------------
def test_create_idea_checks_the_style(store, settings):
    with pytest.raises(ValueError, match="unknown style"):
        _idea(store, settings, "a hook", style="nope")
    styles.set_choice(store, "paper", enabled=False)
    with pytest.raises(ValueError, match="turned off"):
        _idea(store, settings, "a hook", style="paper")
    assert _idea(store, settings, "another hook", style="voxel")["style"] == "voxel"


def test_order_style_fills_the_idea_and_refuses_another(store, settings):
    order = work_orders.create_video(store, "Les protéines du soir", "macro3d")
    assert (order["source"], order["style"], order["mode"], order["status"]) == (
        "create", "macro3d", "owner", "scheduled")
    with pytest.raises(ValueError, match="asks for style 'macro3d', not 'paper'"):
        _idea(store, settings, "Protéines", style="paper", work_order_id=order["id"])
    styles.set_choice(store, "macro3d", enabled=False)  # the owner's pick still stands
    idea = _idea(store, settings, "Protéines", work_order_id=order["id"])
    assert idea["style"] == "macro3d"
    assert work_orders.get_order(store, order["id"])["status"] == "in_production"


def test_an_order_shows_what_the_ai_wrote_and_its_video_status(store, settings):
    """174: « Créer »'s pile reads the idea's hook and the newest video's status."""
    order = work_orders.create_video(store, "Les protéines du soir")
    assert (order["idea_hook"], order["video_status"]) == (None, None)
    idea = _idea(store, settings, "Ton estomac a une horloge", work_order_id=order["id"])
    assert work_orders.get_order(store, order["id"])["idea_hook"] == "Ton estomac a une horloge"
    first = store.add_asset(idea["id"])
    assert work_orders.get_order(store, order["id"])["video_status"] == "rendering"
    transition(store, first["id"], "failed", actor="worker")
    assert work_orders.list_orders(store, source="mine")[0]["video_status"] == "failed"
    store.add_asset(idea["id"])  # a newer version: its status is the one shown
    assert work_orders.get_order(store, order["id"])["video_status"] == "rendering"


def test_render_motion_refuses_a_template_outside_the_style(store, settings, tmp_path,
                                                           monkeypatch):
    calls = []
    monkeypatch.setattr(motion, "validate_props", lambda t, p: calls.append(t) or {
        "props": p, "fps": 30, "durationInFrames": 90, "coverFrame": None})
    monkeypatch.setattr(motion, "build_props", lambda t, p, s, v=None: p)  # no TTS
    s = _settings(media_root=str(tmp_path))
    idea = _idea(store, settings, "Voxel hook", style="voxel")
    with pytest.raises(ValueError, match=r"style 'voxel': template PaperStory is 'paper';"
                                         r" use one of VoxelQuest"):
        motion.queue_motion_render(store, s, template="PaperStory", props={},
                                   idea_id=idea["id"])
    assert calls == []  # refused before anything else
    motion.queue_motion_render(store, s, template="VoxelQuest", props={}, idea_id=idea["id"])
    # Auto: an idea without a style takes its template's, recorded once
    auto = _idea(store, settings, "Auto hook")
    out = motion.queue_motion_render(store, s, template="Cutaway", props={}, idea_id=auto["id"])
    assert store.get_idea(auto["id"])["style"] == "cutaway"
    with pytest.raises(ValueError, match="template FactQuest is 'pixel'"):  # re-render too
        motion.queue_motion_render(store, s, template="FactQuest", props={},
                                   asset_id=out["asset"]["id"])
    styles.set_choice(store, "editorial", enabled=False)
    off = _idea(store, settings, "Off hook")
    with pytest.raises(ValueError, match="turned off"):
        motion.queue_motion_render(store, s, template="Editorial", props={}, idea_id=off["id"])


def test_daily_share_limits_a_style(store, settings):
    styles.set_choice(store, "pixel", share=0.2)  # batch 10 -> at most 2
    for w in ("apple", "brick"):
        _idea(store, settings, w * 3, style="pixel")
    q = todays_quotas(store, settings, DAY)
    assert q["styles"]["pixel"] == {"count": 2, "limit": 2}
    with pytest.raises(ValueError, match="style 'pixel' share used: 2/2"):
        _idea(store, settings, "cloud" * 3, style="pixel")
    _idea(store, settings, "dune" * 3, style="paper")
    assert todays_quotas(store, settings, DAY)["styles"]["paper"] == {"count": 1, "limit": None}
    order = work_orders.create_video(store, "Encore du pixel", "pixel")  # the owner's own
    _idea(store, settings, "ember" * 3, work_order_id=order["id"])


# --- launch points ----------------------------------------------------------------------
def test_trending_and_dm_orders_carry_a_style(store, settings):
    a, b = _ref(store, "A"), _ref(store, "B")
    with pytest.raises(ValueError, match="unknown style"):
        work_orders.create_orders(store, [{"source_id": a, "mode": "inspired", "style": "x"}])
    o1, o2 = work_orders.create_orders(store, [
        {"source_id": a, "mode": "inspired", "style": "paper"},
        {"source_id": b, "mode": "react"}])
    assert (o1["style"], o2["style"], o1["source"]) == ("paper", None, "trend")
    # set_instruction keeps the style unless given; None = back to Auto
    assert work_orders.set_instruction(store, o1["id"], "plus court")["style"] == "paper"
    assert work_orders.set_instruction(store, o1["id"], "plus court", style="voxel")["style"] \
        == "voxel"
    assert work_orders.set_instruction(store, o1["id"], "plus court", style=None)["style"] is None
    assert [o["id"] for o in work_orders.list_orders(store, source="trend")] == [o2["id"], o1["id"]]


def test_restyle_remakes_the_same_video_in_another_style(store, settings):
    idea = _idea(store, settings, "Le gras ne fait pas grossir", style="paper",
                 script="Le gras ne fait pas grossir. Le total, si.")
    asset = store.add_asset(idea["id"], recipe={"kind": "motion", "template": "PaperStory"})
    with pytest.raises(ValueError, match="already in style 'paper'"):
        work_orders.restyle(store, asset["id"], "paper")
    with pytest.raises(KeyError):
        work_orders.restyle(store, 999, "voxel")
    order = work_orders.restyle(store, asset["id"], "voxel", "garde la fin")
    assert (order["source"], order["style"], order["from_asset_id"]) == (
        "change", "voxel", asset["id"])
    assert "refais la vidéo" in order["instruction"] and "« 3D 8-bit »" in order["instruction"]
    assert order["instruction"].endswith("garde la fin")
    auto = work_orders.restyle(store, asset["id"], None)
    assert auto["style"] is None and "au choix de l'IA" in auto["instruction"]
    [seen, _] = work_orders.for_agent(store)
    assert seen["from_video"] == {"id": idea["id"], "track": "motion", "pillar": "stories",
                                  "hook": "Le gras ne fait pas grossir", "hook_type": None,
                                  "script": "Le gras ne fait pas grossir. Le total, si.",
                                  "style": "paper", "template": "PaperStory"}
    # the remake may reuse the original's hook (no near-duplicate refusal)
    remake = _idea(store, settings, "Le gras ne fait pas grossir", work_order_id=order["id"])
    assert remake["style"] == "voxel"
    assert [o["source"] for o in work_orders.list_orders(store, source="mine")] == [
        "change", "change"]


# --- API --------------------------------------------------------------------------------
@pytest.fixture
def tc(store):
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as c:
        yield c


def test_styles_api(tc, store, tmp_path):
    body = tc.get("/api/styles").json()
    assert [s["id"] for s in body] == ALL
    assert tc.get("/api/styles/voxel/preview/clip").status_code == 404
    still = tmp_path / "samples" / "130" / "voxelquest-cover.png"
    still.parent.mkdir(parents=True)
    still.write_bytes(b"png")
    r = tc.get("/api/styles/voxel/preview/still")
    assert r.status_code == 200 and r.content == b"png"
    assert tc.get("/api/styles/voxel/preview/other").status_code == 422
    r = tc.patch("/api/styles/voxel", json={"enabled": False, "share": 0.5})
    assert (r.json()["enabled"], r.json()["share"]) == (False, 0.5)
    assert tc.patch("/api/styles/voxel", json={"enabled": True}).json()["share"] == 0.5
    assert tc.patch("/api/styles/nope", json={"enabled": True}).status_code == 422
    assert tc.patch("/api/styles/voxel", json={"share": 2}).status_code == 422


def test_launch_routes(tc, store, settings):
    r = tc.post("/api/work-orders", json={"instruction": "Les fibres", "style": "editorial"})
    assert r.status_code == 200 and (r.json()["source"], r.json()["style"]) == (
        "create", "editorial")
    assert tc.post("/api/work-orders", json={"instruction": " "}).status_code == 422
    assert tc.post("/api/work-orders", json={"instruction": "x", "style": "no"}).status_code == 422
    idea = _idea(store, settings, "Le sel", style="paper")
    asset = store.add_asset(idea["id"])
    r = tc.post(f"/api/assets/{asset['id']}/restyle", json={"style": "cinema"})
    assert r.status_code == 200 and r.json()["from_asset_id"] == asset["id"]
    assert tc.post("/api/assets/999/restyle", json={"style": "cinema"}).status_code == 404
    sid = _ref(store, "A")
    [o] = tc.post("/api/research/work-orders", json={"items": [
        {"source_id": sid, "mode": "inspired", "style": "pixel"}]}).json()
    assert o["style"] == "pixel"
    r = tc.patch(f"/api/work-orders/{o['id']}", json={"instruction": "court", "style": None})
    assert r.json()["style"] is None
    r = tc.patch(f"/api/work-orders/{o['id']}", json={"instruction": "court", "style": "paper"})
    assert r.json()["style"] == "paper"
    assert tc.patch(f"/api/work-orders/{o['id']}", json={"instruction": "x"}).json()["style"] \
        == "paper"
    mine = tc.get("/api/work-orders?source=mine").json()
    assert [w["source"] for w in mine] == ["change", "create"]
    [feed] = store.list_assets(limit=10)
    assert feed["style"] == "paper"


# --- learning ---------------------------------------------------------------------------
def test_brief_lists_the_enabled_styles(store, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(B, "BIBLE_PATH", tmp_path / "BIBLE.md")
    styles.set_choice(store, "paper", enabled=False)
    styles.set_choice(store, "voxel", share=0.3)
    b = B.creative_brief(store, settings, datetime(2026, 11, 17, 10, tzinfo=timezone.utc))
    assert [s["id"] for s in b["styles"]] == [s for s in ALL if s != "paper"]
    voxel = next(s for s in b["styles"] if s["id"] == "voxel")
    assert (voxel["share"], voxel["templates"], voxel["address"]) == (0.3, ["VoxelQuest"], "vous")
    assert b["quotas"]["styles"] == {"voxel": {"count": 0, "limit": 3}}


def test_inbox_restyle_sends_the_note_and_retires_the_video(tc, store, settings):
    """181: from the Inbox, the note + reasons go with the style, become a comment, and the
    ready video leaves the Inbox (archived); a bad reason writes nothing."""
    from src.studio.assets import transition
    idea = _idea(store, settings, "Le sel", style="paper")
    ready = store.add_asset(idea["id"])
    transition(store, ready["id"], "ready", actor="worker")
    assert tc.post(f"/api/assets/{ready['id']}/restyle",
                   json={"style": "cinema", "reasons": ["nope"]}).status_code == 422
    assert store.get_asset(ready["id"])["status"] == "ready"
    assert not work_orders.list_orders(store, source="mine")
    r = tc.post(f"/api/assets/{ready['id']}/restyle",
                json={"style": "cinema", "note": "hook plus court", "reasons": ["too_slow"]})
    assert r.status_code == 200
    assert r.json()["instruction"].endswith("Raisons : too_slow. Et aussi : hook plus court")
    assert store.get_asset(ready["id"])["status"] == "archived"
    [fb] = store.list_feedback(ready["id"])
    assert (fb["text"], fb["reason_codes"]) == ("hook plus court", ["too_slow"])


def test_style_is_a_funnel_dimension(store, settings):
    for style, hook in (("paper", "apple" * 3), ("voxel", "brick" * 3)):
        idea = _idea(store, settings, hook, style=style)
        store.add_asset(idea["id"], batch_date=DAY)
    out = funnel.funnel(store, settings, days=3650, group_by="style")
    assert sorted(g["key"] for g in out["groups"]) == ["paper", "voxel"]


# --- migration --------------------------------------------------------------------------
def test_migration_keeps_orders_and_adds_the_style(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    monkeypatch.setattr(store_mod, "MIGRATIONS",
                        MIGRATIONS[:MIGRATIONS.index(store_mod.STYLES_SCHEMA)])  # 155
    old = CampaignStore(path)
    sid = _ref(old, "A")
    with old._tx() as c:
        c.execute("INSERT INTO work_orders (source_id, mode, instruction, created_at,"
                  " updated_at) VALUES (?, 'react', 'vas-y', 't0', 't0')", (sid,))
        pick = c.execute("INSERT INTO dm_picks (message_id, sender_username, reel_url,"
                         " received_at, created_at, updated_at) VALUES ('m1', 'amine_xenima',"
                         " 'https://www.instagram.com/reel/X/', 't', 't', 't')").lastrowid
        c.execute("INSERT INTO work_orders (pick_id, mode, status, created_at, updated_at)"
                  " VALUES (?, 'owner', 'needs_instruction', 't1', 't1')", (pick,))
        old.add_idea("motion", batch_date=DAY)
    old.close()
    monkeypatch.undo()
    new = CampaignStore(path)
    try:
        orders = work_orders.list_orders(new, newest=False)
        assert [(o["source"], o["mode"], o["style"], o["instruction"]) for o in orders] == [
            ("trend", "react", None, "vas-y"), ("dm", "owner", None, None)]
        assert new.list_ideas()[0]["style"] is None
        with pytest.raises(ValueError, match="already has an open work order"):  # index kept
            work_orders.create_orders(new, [{"source_id": sid, "mode": "inspired"}])
    finally:
        new.close()
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    con.close()
