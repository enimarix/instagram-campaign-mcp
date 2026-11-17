"""Step 110: every asset knows what happens in it (assets.timeline, assets.description)."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.store import MIGRATIONS, CampaignStore
from src.studio import motion, production, render
from src.studio.recipe import (
    EVENT_CHARS,
    TIMELINE_BYTES,
    TIMELINE_EVENTS,
    Recipe,
    compress_timeline,
    recipe_timeline,
)
from tests.test_studio_motion import _example, needs_motion
from tests.test_studio_production import _asset, _finish
from tests.test_studio_render import FAR_PAST, INFO

from .conftest import LOCAL


def _timeline(ops, duration):
    return recipe_timeline(Recipe(ops=ops), duration)


def test_hook_text_window_is_cut_at_the_clip_end():
    assert _timeline([{"op": "fit_vertical"},
                      {"op": "hook_text", "text": "Wait for it", "start_s": 0.5, "end_s": 3}],
                     10.04) == [{"t": 0.5, "d": 2.5, "e": "hook text: 'Wait for it'"}]
    assert _timeline([{"op": "hook_text", "text": "Hi", "start_s": 1, "end_s": 9}],
                     4) == [{"t": 1, "d": 3, "e": "hook text: 'Hi'"}]
    assert _timeline([{"op": "hook_text", "text": "Hi", "start_s": 5, "end_s": 9}], 4) == []


def test_each_caption_line_is_an_event():
    lines = [{"start_s": 0, "end_s": 1.25, "text": "First"},
             {"start_s": 1.25, "end_s": 2.5, "text": "Second"},
             {"start_s": 9, "end_s": 10, "text": "after the end"}]
    assert _timeline([{"op": "captions", "lines": lines}], 5) == [
        {"t": 0, "d": 1.2, "e": "caption: 'First'"},
        {"t": 1.2, "d": 1.2, "e": "caption: 'Second'"}]


def test_reaction_collage_credit_logo_and_audio_span_the_clip():
    ops = [{"op": "reaction_collage", "layout": "split"}, {"op": "mute_original"},
           {"op": "voice_over"}, {"op": "credit", "text": "@creator"}, {"op": "logo"}]
    assert _timeline(ops, 12.0) == [
        {"t": 0, "d": 12.0, "e": "reaction split: the clip on top, the owner's reaction below"},
        {"t": 0, "d": 12.0, "e": "original sound muted"},
        {"t": 0, "d": 12.0, "e": "voice-over over the clip"},
        {"t": 0, "d": 12.0, "e": "credit: '@creator'"},
        {"t": 0, "d": 12.0, "e": "logo (bottom_right)"}]
    pip = _timeline([{"op": "reaction_collage", "layout": "pip", "pip_corner": "top_left"}], 3)
    assert pip[0]["e"] == "reaction pip: the owner's reaction in a box, top left"


def test_end_card_extends_the_video_and_music_after_it_spans_both():
    ops = [{"op": "music", "loop": False}, {"op": "end_card", "text": "Follow!", "duration_s": 2},
           {"op": "music"}]
    assert _timeline(ops, 10.0) == [
        {"t": 0, "d": 8.0, "e": "music bed"},
        {"t": 0, "d": 10.0, "e": "music bed (looped)"},
        {"t": 8.0, "d": 2, "e": "end card: 'Follow!'"}]


def test_long_text_is_quoted_and_truncated():
    [event] = compress_timeline([{"t": 1.04, "d": 2.06, "e": "fact 3", "text": "word " * 40}])
    assert (event["t"], event["d"]) == (1.0, 2.1)
    assert event["e"].startswith("fact 3: 'word word") and event["e"].endswith("…'")
    assert len(event["e"]) <= EVENT_CHARS


def test_too_many_or_too_big_events_are_cut_with_a_count():
    many = compress_timeline([{"t": 50 - i, "d": 1, "e": f"beat {i}"} for i in range(50)])
    assert len(many) == TIMELINE_EVENTS + 1 and many[-1] == {"e": "+10 more"}
    assert [e["t"] for e in many[:-1]] == sorted(e["t"] for e in many[:-1])
    big = compress_timeline([{"t": i, "d": 1, "e": "caption", "text": "é" * 70}
                             for i in range(30)])
    assert len(json.dumps(big)) <= TIMELINE_BYTES
    assert big[-1]["e"] == f"+{30 - (len(big) - 1)} more"


@needs_motion
@pytest.mark.parametrize("template", ["FactQuest", "BossBattle", "QuizChest", "DialogStory",
                                      "PixelSkit"])
def test_schema_events_give_every_template_a_timeline(template):
    v = motion.validate_props(template, _example(template.lower()))
    timeline = compress_timeline(v["events"])
    total = v["durationInFrames"] / v["fps"]
    assert timeline[0]["t"] == 0 and timeline[0]["e"].startswith("hook card: '")
    assert all(e["t"] + e["d"] <= total + 0.1 for e in timeline)
    assert any(e["e"].startswith("music bed") for e in timeline)
    assert len(json.dumps(timeline)) <= TIMELINE_BYTES


def test_render_stores_the_timeline_and_an_automatic_description(store, tmp_path):
    idea = store.add_idea("motion", hook="Did you know?", hypothesis="myth busts keep viewers")
    a = store.add_asset(idea["id"], recipe={"kind": "motion", "template": "FactQuest",
                                            "props": {}})
    render.enqueue_render(store, a["id"])
    timeline = [{"t": 0.0, "d": 2.0, "e": "hook card: 'Did you know?'"}]
    render.run_job(store, tmp_path, store.claim_render_jobs(1, stale_before=FAR_PAST)[0],
                   render_fn=lambda *a: (INFO, {"file_path": "v.mp4", "timeline": timeline}),
                   qc_fn=lambda *a: {"passed": True})
    a = store.get_asset(a["id"])
    assert a["timeline"] == timeline
    assert a["description"] == ('A FactQuest video with the hook "Did you know?".'
                                " Angle: myth busts keep viewers")


def test_auto_description_names_a_reaction_remix():
    asset = {"recipe": {"kind": "ffmpeg", "recipe": {"ops": [{"op": "reaction_collage"}]}}}
    assert render.auto_description({"hook": None}, asset) == "A reaction remix."


def test_submit_stores_the_description_or_keeps_a_fallback(store, settings):
    a, j = _asset(store)
    _finish(store, a, j)
    row = production.submit_asset(store, settings, a, self_score=7, self_score_reason="ok",
                                  caption="Cap")
    assert store.get_asset(a)["description"] == 'A FactQuest video with the hook "Did you know?".'
    assert row["description"] == 'A FactQuest video with the hook "Did you know?".'
    production.submit_asset(store, settings, a, self_score=7, self_score_reason="ok",
                            caption="Cap", description=" Three facts. The hook asks. ")
    assert store.get_asset(a)["description"] == "Three facts. The hook asks."
    production.submit_asset(store, settings, a, self_score=7, self_score_reason="ok",
                            caption="Cap")  # none given: the stored one stays
    assert store.get_asset(a)["description"] == "Three facts. The hook asks."
    with pytest.raises(ValueError, match="description must be 1-400"):
        production.submit_asset(store, settings, a, self_score=7, self_score_reason="ok",
                                caption="Other", description="x" * 401)
    assert store.get_asset(a)["caption"] == "Cap"  # nothing written


def test_migration_adds_description_and_timeline(tmp_path):
    path = tmp_path / "db.sqlite"
    CampaignStore(path).close()
    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(assets)")}
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    conn.close()
    assert {"description", "timeline"} <= cols


def test_api_detail_carries_both_and_patch_edits_the_description(store):
    idea = store.add_idea("motion")
    timeline = [{"t": 0.0, "d": 1.0, "e": "hook card"}, {"e": "+3 more"}]
    a = store.add_asset(idea["id"], description="One.", timeline=timeline)
    settings = InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                                    database_path=":memory:")
    with TestClient(create_app(settings, store=store), base_url=LOCAL) as tc:
        body = tc.get(f"/api/assets/{a['id']}").json()
        assert (body["description"], body["timeline"]) == ("One.", timeline)
        r = tc.patch(f"/api/assets/{a['id']}", json={"description": "Two."},
                     headers={"Origin": LOCAL})
        assert r.status_code == 200 and r.json()["description"] == "Two."
        r = tc.patch(f"/api/assets/{a['id']}", json={"description": " "},
                     headers={"Origin": LOCAL})
        assert r.status_code == 422
