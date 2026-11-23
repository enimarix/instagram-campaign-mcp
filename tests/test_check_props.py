"""Step 191: the check run gets each video's recipe back as its tool takes it (render_args:
the editable props, no filled voice), the failed job's reason, and a caption's literal
backslash-n becomes a line break."""

import pytest

from src.agent import packet
from src.store import to_iso, utcnow
from src.studio import checks, motion, remix, render, sitcom, voices
from src.studio.assets import checked_fields, transition
from tests.test_studio_motion import FACTQUEST, VALID, _settings
from tests.test_studio_remix import SCRIPT, _source, cfg, go, reel, root, tts  # noqa: F401
from tests.test_studio_sitcom import PROPS as SITCOM
from tests.test_studio_voice_job import URL, FakeTTS, _run

BS_N = "Ligne un" + chr(92) + "nLigne deux"  # what the agent stored: a backslash and an n


@pytest.fixture
def s(tmp_path):
    return _settings(tmp_path, tts_provider="http", tts_http_url=URL,
                     tts_cache_dir=str(tmp_path / "cache"))


@pytest.fixture(autouse=True)
def schema(monkeypatch):
    monkeypatch.setattr(motion, "validate_props",
                        lambda t, p: {**VALID, "props": p, "coverFrame": 12})
    monkeypatch.setattr(motion, "list_templates", lambda: [
        {"id": "FactQuest", "style": "pixel"}, {"id": sitcom.TEMPLATE, "style": "sitcom"}])


@pytest.fixture
def fake(tmp_path, monkeypatch):
    audio = tmp_path / "abc.wav"
    audio.write_bytes(b"RIFF")
    provider = FakeTTS(audio)
    monkeypatch.setattr(motion, "get_provider", lambda settings: provider)
    monkeypatch.setattr(sitcom, "get_provider", lambda settings: provider)
    return provider


def _row(store, asset_id):
    section = checks.for_agent(store, utcnow())
    packet.encode(section, "checks")  # its schema holds
    return {r["asset_id"]: r for r in section["renders"]}[asset_id]


def test_a_voiced_motion_video_comes_back_as_render_motion_takes_it(store, s, fake):
    voice = voices.default_voice(store)
    idea = store.add_idea("motion")
    first = motion.queue_motion_render(store, s, template="FactQuest", props=FACTQUEST,
                                       idea_id=idea["id"], voice=voice, caption=BS_N)["asset"]
    assert first["caption"] == "Ligne un\nLigne deux"  # queued: stored with a real break
    _run(store, s)  # the job voices it, then renders it: ready
    env = store.get_asset(first["id"])["recipe"]
    assert "audioSrc" in env["props"]["voice"] and env["voiced_with"]["voice"] == voice
    row = _row(store, first["id"])
    assert row["failure"] is None
    args = row["render_args"]
    assert args == {"tool": "render_motion", "template": "FactQuest",
                    "template_props": FACTQUEST, "voice": voice, "music_audio_id": None,
                    "music": FACTQUEST.get("music")}
    out = motion.queue_motion_render(store, s, template=args["template"],
                                     props=args["template_props"], voice=args["voice"],
                                     asset_id=first["id"])
    new = out["asset"]
    assert out["job"]["state"] == "queued" and new["parent_asset_id"] == first["id"]
    assert new["recipe"]["props"] == FACTQUEST and new["recipe"]["voice_todo"]["voice"] == voice


def test_a_sitcom_comes_back_without_its_filled_lines_with_the_job_failure(store, s, fake):
    voice = voices.default_voice(store)
    said = sitcom.voice_says(SITCOM, s, voice)  # each character line: seconds + audioSrc
    assert said["scenes"][0]["beats"][1]["say"]["audioSrc"] == "voice/abc.wav"
    idea = store.add_idea("motion", style="sitcom")
    env = {"kind": "motion", "template": sitcom.TEMPLATE, "voiced_with": {"voice": voice},
           "props": {**said, "voice": {"lines": [], "audioSrc": "voice/abc.wav"}}}
    asset = store.add_asset(idea["id"], recipe=render.validate_recipe(env, s.media_root))
    job = render.enqueue_render(store, asset["id"])
    store.update_render_job(job["id"], state="failed", finished_at=to_iso(utcnow()),
                            failure="ValidationError: 1 validation error\n  motion.x\n  Extra")
    transition(store, asset["id"], "failed", actor="worker")
    row = _row(store, asset["id"])
    assert row["failure"] == "ValidationError: 1 validation error motion.x Extra"
    args = row["render_args"]
    assert args["template_props"] == SITCOM and args["voice"] == voice
    # the check's fix: one beat's speed, the rest as it was
    fixed = {**SITCOM, "scenes": [SITCOM["scenes"][0], {**SITCOM["scenes"][1], "beats": [
        SITCOM["scenes"][1]["beats"][0], {**SITCOM["scenes"][1]["beats"][1], "speed": "normal"}]}]}
    out = motion.queue_motion_render(store, s, template=args["template"], props=fixed,
                                     voice=args["voice"], asset_id=asset["id"])
    again = store.get_asset(asset["id"])  # failed: rendered again in place
    assert out["job"]["state"] == "queued" and again["status"] == "rendering"
    assert again["recipe"]["props"] == fixed and "voice_todo" in again["recipe"]


def test_a_voiced_remix_comes_back_as_render_remix_takes_it(store, cfg, tts, reel):  # noqa: F811
    source = _source(store)
    out = go(store, cfg, source, trim=(10, 30), caption="Wow" + chr(92) + "n@creator")
    assert store.get_asset(out["asset"]["id"])["caption"] == "Wow\n@creator"
    asset = render.voice_first(store, store.get_asset(out["asset"]["id"]), cfg)
    assert "voice_todo" not in asset["recipe"] and "voice" in asset["recipe"]["inputs"]
    transition(store, asset["id"], "ready", actor="worker")
    row = _row(store, asset["id"])
    args = row["render_args"]
    assert args == {"tool": "render_remix", "source_id": source["id"], "hook": "Wait for it",
                    "script": SCRIPT, "voice": voices.default_voice(store),
                    "trim_start_s": 10, "trim_end_s": 30, "layout": "pip",
                    "captions": None,  # 193: the transcript's: derived again from the trim
                    "music": "music-overworld"}
    again = remix.render_remix(store, cfg, row["idea_id"], args["source_id"],
                               hook=args["hook"], script=args["script"],
                               trim=(args["trim_start_s"], args["trim_end_s"]),
                               layout=args["layout"], captions=args["captions"],
                               voice=args["voice"], music=args["music"])
    env = again["asset"]["recipe"]
    assert again["job"]["state"] == "queued"
    assert env["recipe"] == asset["recipe"]["recipe"] and env["voice_todo"]["script"] == SCRIPT


def _remix_args(store, out):
    transition(store, out["asset"]["id"], "ready", actor="worker")
    return _row(store, out["asset"]["id"])["render_args"]


def _captions(asset):
    return next(op for op in asset["recipe"]["recipe"]["ops"] if op["op"] == "captions")["lines"]


def test_a_changed_trim_derives_the_transcript_captions_again(store, cfg, tts, reel):  # noqa: F811
    # 193: transcript captions are not sent back, so the check's new trim re-times them
    source = _source(store)
    args = _remix_args(store, go(store, cfg, source, trim=(10, 30)))
    assert args["captions"] is None
    again = remix.render_remix(store, cfg, store.add_idea(
        "remix", source_id=source["id"])["id"], source["id"], hook=args["hook"],
        script=args["script"], trim=(11, 30), captions=args["captions"])["asset"]
    assert _captions(again) == [{"start_s": 1.0, "end_s": 3.0, "text": "inside"}]
    # written ones come back as they are
    own = [{"start_s": 0.5, "end_s": 2.0, "text": "Regarde bien"}]
    args = _remix_args(store, go(store, cfg, source, trim=(10, 30), captions=own))
    assert args["captions"] == own


def test_a_remix_keeps_its_music_and_its_description(store, cfg, tts, reel):  # noqa: F811
    # 193: render_remix takes the card edit's music values; the description is stored
    # without plan too, checked the same way
    source = _source(store)
    out = go(store, cfg, source, trim=(10, 30), music="none",
             description="  Refait : la musique enlevée.  ")
    assert out["asset"]["description"] == "Refait : la musique enlevée."
    assert "music" not in out["asset"]["recipe"]["inputs"]
    args = _remix_args(store, out)
    assert args["music"] == "none"
    with pytest.raises(ValueError, match="description must be"):
        go(store, cfg, source, trim=(10, 30), description=" ")


def test_a_motion_render_stores_its_description(store, s, fake):
    idea = store.add_idea("motion")
    first = motion.queue_motion_render(store, s, template="FactQuest", props=FACTQUEST,
                                       idea_id=idea["id"], description="Le mythe du détox.")
    assert first["asset"]["description"] == "Le mythe du détox."
    transition(store, first["asset"]["id"], "failed", actor="worker")
    again = motion.queue_motion_render(store, s, template="FactQuest", props=FACTQUEST,
                                       asset_id=first["asset"]["id"],
                                       description="Refait : le titre coupé.")
    assert again["asset"]["description"] == "Refait : le titre coupé."
    with pytest.raises(ValueError, match="description must be"):
        motion.queue_motion_render(store, s, template="FactQuest", props=FACTQUEST,
                                   idea_id=idea["id"], description="x" * 5000)


def test_very_large_props_are_left_out_with_a_note(monkeypatch):
    monkeypatch.setattr(checks, "PROPS_MAX", 10)
    args = checks.render_args({"kind": "motion", "template": "FactQuest", "props": FACTQUEST},
                              None)
    assert args["template_props"] is None and "too large" in args["note"]
    assert checks.render_args(None, None) is None


def test_a_planned_or_submitted_caption_gets_real_line_breaks():
    assert checked_fields("planned", caption=BS_N)["caption"] == "Ligne un\nLigne deux"
    crlf = "a" + chr(92) + "r" + chr(92) + "nb"
    assert checked_fields("ready", caption=crlf)["caption"] == "a\nb"
