"""Step 048: Python bridge to the motion templates (src/studio/motion.py) and its MCP tools."""

import json
import shutil
import threading
import time
from functools import partial
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import src.instagram_mcp_server as srv
from src.config import InstagramMCPSettings
from src.studio import motion, recipe, render
from src.studio.assets import transition
from src.studio.tts import LineTiming, Synthesis
from tests.test_studio_ffmpeg import needs_ffmpeg
from tests.test_studio_recipe import make_clip
from tests.test_studio_render import FAR_PAST

# ponytail: CI's Python job has no motion/node_modules (nor Chrome for Remotion); the motion CI
# job runs the schema-only tests below (`-k`), the real renders stay local.
needs_motion = pytest.mark.skipif(
    not (shutil.which("node") and (motion.MOTION_DIR / "node_modules").is_dir()),
    reason="node or motion/node_modules missing (npm ci in motion/)")

def _example(name):
    return json.loads((motion.MOTION_DIR / "props" / f"{name}.json").read_text("utf-8"))


FACTQUEST = _example("factquest")
VALID = {"props": {"title": "Hi"}, "fps": 30, "durationInFrames": 90, "coverFrame": 12}


def _settings(tmp_path, **kw):
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                                database_path=":memory:", media_root=str(tmp_path), **kw)


@needs_motion
def test_schema_export_lists_templates_with_json_schema():
    templates = {t["id"]: t for t in motion.list_templates()}
    fq = templates["FactQuest"]
    assert {"hook", "facts", "outro", "citations", "voice"} <= set(fq["jsonSchema"]["properties"])
    assert fq["jsonSchema"]["additionalProperties"] is False
    assert len(fq["defaultProps"]["facts"]) == 3


@needs_motion
def test_validate_props_uses_the_templates_own_message():
    ok = motion.validate_props("FactQuest", FACTQUEST)
    assert ok["props"]["hook"] == FACTQUEST["hook"]
    assert (ok["fps"], ok["coverFrame"]) == (30, 12) and ok["durationInFrames"] > 300
    bad = {**FACTQUEST, "facts": FACTQUEST["facts"][:2], "voice": {"lines": []}}
    with pytest.raises(ValueError, match="invalid props for FactQuest") as e:
        motion.validate_props("FactQuest", bad)
    assert "facts" in str(e.value) and "one timing per script line" in str(e.value)
    with pytest.raises(ValueError, match="unknown template Nope"):
        motion.validate_props("Nope", {})


@needs_motion
@pytest.mark.parametrize("template", ["FactQuest", "BossBattle", "QuizChest", "DialogStory",
                                      "PixelSkit", "VoxelQuest", "PaperStory"])
def test_schema_events_give_every_template_a_timeline(template):
    v = motion.validate_props(template, _example(template.lower()))
    timeline = recipe.compress_timeline(v["events"])
    total = v["durationInFrames"] / v["fps"]
    assert timeline[0]["t"] == 0 and timeline[0]["e"].startswith("hook card: '")
    assert all(e["t"] + e["d"] <= total + 0.1 for e in timeline)
    assert any(e["e"].startswith("music bed") for e in timeline)
    assert len(json.dumps(timeline)) <= recipe.TIMELINE_BYTES


def test_missing_node_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("NODE_BIN", "no-such-node-binary")
    with pytest.raises(motion.MotionError, match="NODE_BIN"):
        motion.find_node()


def test_build_props_fills_voice_lines_without_audio(tmp_path):
    props = motion.build_props("FactQuest", FACTQUEST, _settings(tmp_path))
    lines = props["voice"]["lines"]
    assert len(lines) == len(FACTQUEST["facts"]) + 2 and "audioSrc" not in props["voice"]
    assert lines[0]["text"] == FACTQUEST["hook"] and lines[-1]["text"] == FACTQUEST["outro"]
    assert motion.build_props("Hello", {"title": "x"}, _settings(tmp_path)) == {"title": "x"}
    assert motion.build_props("FactQuest", props, _settings(tmp_path)) is props  # has a voice


def test_build_props_copies_the_voice_audio_into_the_media_root(tmp_path, monkeypatch):
    audio = tmp_path / "cache" / "abc.wav"
    audio.parent.mkdir()
    audio.write_bytes(b"RIFF")
    said = []

    class Fake:
        def synthesize(self, text, voice=None):
            said.append((text, voice))
            return Synthesis(audio, 9.0, [LineTiming(t, 0, 1) for t in text.splitlines()],
                             None, "fake")

    monkeypatch.setattr(motion, "get_provider", lambda s: Fake())
    props = {**FACTQUEST, "hook": "Two\nlines?"}
    out = motion.build_props("FactQuest", props, _settings(tmp_path / "media"), "nova")
    assert out["voice"]["audioSrc"] == "voice/abc.wav"
    assert (tmp_path / "media" / "voice" / "abc.wav").read_bytes() == b"RIFF"
    assert said[0][1] == "nova" and said[0][0].splitlines()[0] == "Two lines?"
    assert len(out["voice"]["lines"]) == len(FACTQUEST["facts"]) + 2


def _without_moral(props):
    return {k: v for k, v in props.items() if k != "moral"}


@needs_motion
@pytest.mark.parametrize("template,props", [
    *((t, _example(t.lower())) for t in sorted(motion.SCRIPTS)),
    ("DialogStory", _without_moral(_example("dialogstory"))),
    ("VoxelQuest", {k: v for k, v in _example("voxelquest").items() if k != "outro"}),
])
def test_script_gives_one_line_per_voice_timing(template, props):
    lines = motion.SCRIPTS[template](props)
    assert lines and all(isinstance(t, str) and t.strip() for t in lines)
    timings = [{"text": t, "start_s": i, "end_s": i + 1} for i, t in enumerate(lines)]
    motion.validate_props(template, {**props, "voice": {"lines": timings}})
    with pytest.raises(ValueError, match="one timing per script line"):
        motion.validate_props(template, {**props, "voice": {"lines": timings[:-1]}})


@needs_motion
def test_schema_export_gives_every_template_a_style():
    out = motion._node("schemas.mjs", [], timeout_s=motion.SCHEMA_TIMEOUT_S)
    styles = {s["id"]: s["label"] for s in out["styles"]}
    assert styles == {"pixel": "Pixel 8-bit", "voxel": "3D 8-bit", "paper": "Papier"}
    by_id = {t["id"]: t["style"] for t in out["templates"]}
    assert set(by_id.values()) <= set(styles)
    assert by_id["VoxelQuest"] == "voxel" and by_id["FactQuest"] == "pixel"
    assert by_id["PaperStory"] == "paper"


@needs_motion
def test_validate_props_voxelquest_examples_and_no_price():
    for name in ("voxelquest", "voxelquest-21h", "voxelquest-proteines"):
        v = motion.validate_props("VoxelQuest", _example(name))
        assert 20 <= v["durationInFrames"] / v["fps"] <= 30, name
        assert any(e["e"].startswith("end card (voxel)") for e in v["events"])
    bad = {**_example("voxelquest"), "outro": "Seulement 4,99 € par mois"}
    with pytest.raises(ValueError, match="no price on screen"):
        motion.validate_props("VoxelQuest", bad)


@needs_motion
def test_validate_props_paperstory_examples_events_and_no_price():
    for name in ("paperstory", "paperstory-proteines", "paperstory-moyenne"):
        v = motion.validate_props("PaperStory", _example(name))
        assert 20 <= v["durationInFrames"] / v["fps"] <= 30, name
        assert v["coverFrame"] <= 2.5 * v["fps"]  # the hook has landed by the cover
        assert any(e["e"].startswith("end card (paper)") for e in v["events"])
        assert any(e["e"].startswith("payoff") for e in v["events"])
    bad = {**_example("paperstory"), "outro": "Seulement 4,99 € par mois"}
    with pytest.raises(ValueError, match="no price on screen"):
        motion.validate_props("PaperStory", bad)


def test_paperstory_script_joins_the_strips_like_the_template():
    # Same lines as sceneLine in motion/src/templates/PaperStory/schema.ts (test/paperstory.test.ts).
    lines = motion.SCRIPTS["PaperStory"](_example("paperstory"))
    assert lines[:2] == ["21 h. Il vous reste 308 kcal. Vous mangez quoi ?",
                         "Trois parts de pizza ? Trop."]
    assert lines[-1] == "Terminez la journée pile sur vos objectifs."
    assert motion._paper_line(["Léa mange", "2 000 kcal", "comme sur l'étiquette."]) ==         "Léa mange 2 000 kcal comme sur l'étiquette."


@needs_motion
def test_every_voiced_template_has_a_script():
    voiced = {t["id"] for t in motion.list_templates()
              if "voice" in t["jsonSchema"].get("properties", {})}
    assert voiced == set(motion.SCRIPTS)  # a new voiced template needs a SCRIPTS entry


def test_file_lock_makes_the_second_holder_wait(tmp_path):
    lock = tmp_path / "bundle.lock"
    held, order = threading.Event(), []

    def first():
        with motion.file_lock(lock, timeout_s=5):
            held.set()
            time.sleep(0.5)
            order.append("first done")

    t = threading.Thread(target=first)
    t.start()
    held.wait(5)
    start = time.monotonic()
    with motion.file_lock(lock, timeout_s=5, poll_s=0.05):  # another handle, like a process
        order.append("second in")
        waited = time.monotonic() - start
    t.join()
    assert order == ["first done", "second in"] and waited >= 0.3
    with motion.file_lock(lock, timeout_s=1):  # released: free again
        with pytest.raises(motion.MotionError, match="still locked"):
            with motion.file_lock(lock, timeout_s=0.2, poll_s=0.05):
                pass


def test_stage_audio_copies_media_audio_into_the_bundle(tmp_path):
    (tmp_path / "voice").mkdir()
    (tmp_path / "voice" / "a.wav").write_bytes(b"RIFF")
    bundle = tmp_path / "bundle"
    props = {"voice": {"audioSrc": "voice/a.wav", "lines": []}}
    staged = motion._stage_audio(bundle, props, tmp_path)
    assert staged["voice"] == {"audioSrc": "public/voice/a.wav", "lines": []}
    assert (bundle / "public" / "voice" / "a.wav").is_file()
    assert motion._stage_audio(bundle, {"x": 1}, tmp_path) == {"x": 1}
    with pytest.raises(ValueError):
        motion._stage_audio(bundle, {"voice": {"audioSrc": "../a.wav"}}, tmp_path)


def test_preview_stills_default_frames(tmp_path, monkeypatch):
    rendered = []

    def fake_render(template, props, out, work, *, timeout_s, extra=()):
        rendered.append(extra[-1])
        out.write_bytes(b"png")

    monkeypatch.setattr(motion, "validate_props", lambda t, p: VALID)
    monkeypatch.setattr(motion, "_render", fake_render)
    paths = motion.preview_stills("Hello", {"title": "Hi"}, tmp_path)
    assert rendered == [12, 29, 59, 89]
    assert all(p.startswith("previews/") and (tmp_path / p).is_file() for p in paths)
    with pytest.raises(ValueError, match="0..89"):
        motion.preview_stills("Hello", {}, tmp_path, frames=[90])


def test_queue_motion_render_stores_recipe_and_enqueues(store, tmp_path, monkeypatch):
    monkeypatch.setattr(motion, "validate_props", lambda t, p: {**VALID, "props": p})
    s = _settings(tmp_path)
    idea = store.add_idea("motion")
    out = motion.queue_motion_render(store, s, template="Hello", props={"title": "Hi"},
                                     idea_id=idea["id"], caption="cap")
    a = out["asset"]
    assert a["recipe"] == {"kind": "motion", "template": "Hello", "props": {"title": "Hi"},
                           "thumb_offset_ms": 400}
    assert (a["status"], a["caption"], out["job"]["state"]) == ("rendering", "cap", "queued")
    transition(store, a["id"], "failed", actor="worker")
    again = motion.queue_motion_render(store, s, template="Hello", props={"title": "Yo"},
                                       asset_id=a["id"])
    assert again["asset"]["id"] == a["id"] and again["asset"]["status"] == "rendering"
    with pytest.raises(ValueError, match="exactly one"):
        motion.queue_motion_render(store, s, template="Hello", props={})


@needs_ffmpeg
def test_render_queue_motion_branch_writes_all_files(store, tmp_path, monkeypatch):
    def fake_motion(template, props, out, media_root, *, timeout_s):
        make_clip(out, "1080x1920", duration=2)
        return motion.ffmpeg.probe(out), 1500, [{"t": 0.0, "d": 2.0, "e": "hook card"}]

    monkeypatch.setattr(motion, "render_motion_asset", fake_motion)
    a = store.add_asset(store.add_idea("motion")["id"],
                        recipe={"kind": "motion", "template": "Hello", "props": {}})
    info, files = render.render_files(a, tmp_path, lambda p: None, preset="ultrafast")
    assert info.duration == pytest.approx(2.0, abs=0.1)
    timeline = files.pop("timeline")
    assert timeline == [{"t": 0.0, "d": 2.0, "e": "hook card"}]
    assert sorted(Path(f).name for f in files.values()) == [
        "poster.jpg", "preview.mp4", "thumb.jpg", "video.mp4"]
    assert all((tmp_path / f).is_file() for f in files.values())


@needs_motion
@needs_ffmpeg
@pytest.mark.parametrize("template", ["FactQuest", "BossBattle"])
def test_real_render_through_the_queue_passes_qc(store, tmp_path, template):
    """One real render (~40 s): none voice, render.mjs, music bed, loudness, QC -> ready."""
    s = _settings(tmp_path)
    idea = store.add_idea("motion")
    queued = motion.queue_motion_render(store, s, template=template,
                                        props=_example(template.lower()),
                                        idea_id=idea["id"], caption="Ton cœur ?")
    job = store.claim_render_jobs(1, stale_before=FAR_PAST)[0]
    assert job["id"] == queued["job"]["id"]
    job = render.run_job(store, tmp_path, job, settings=s,
                         render_fn=partial(render.render_files, preset="ultrafast"))
    a = store.get_asset(queued["asset"]["id"])
    assert job["state"] == "done", job["failure"]
    assert a["status"] == "ready", a["qc"]["reasons"]
    assert a["qc"]["passed"] is True and a["recipe"]["thumb_offset_ms"] == 400
    assert all((tmp_path / a[k]).is_file()
               for k in ("file_path", "preview_path", "poster_path", "thumbnail_path"))


async def test_mcp_tools_call_the_services(monkeypatch):
    calls = {}
    monkeypatch.setattr(motion, "list_templates", lambda: [{"id": "Hello"}])

    def queue(store, settings, **kw):
        calls["queue"] = kw
        return {"asset": {"id": 7}, "job": {"id": 3, "state": "queued"}}

    monkeypatch.setattr(motion, "queue_motion_render", queue)
    monkeypatch.setattr(srv, "store", lambda: None)
    monkeypatch.setattr(srv, "get_settings", srv.config.get_settings)  # no store to read
    assert await srv.list_motion_templates() == {"templates": [{"id": "Hello"}]}
    assert await srv.render_motion("Hello", {"title": "Hi"}, idea_id=1) == {
        "asset_id": 7, "job_id": 3, "state": "queued"}
    assert calls["queue"]["idea_id"] == 1 and calls["queue"]["template"] == "Hello"

    def bad(*a, **kw):
        raise ValueError("invalid props for Hello")

    monkeypatch.setattr(motion, "queue_motion_render", bad)
    with pytest.raises(ToolError, match="invalid props"):
        await srv.render_motion("Hello", {}, idea_id=1)


@needs_motion
@pytest.mark.parametrize("template", ["FactQuest", "BossBattle", "QuizChest", "DialogStory",
                                      "PixelSkit"])
def test_schema_events_end_on_the_pixel_end_card(template):
    """Step 137: every 8-bit template ends on the pixel end card, long enough to hold."""
    v = motion.validate_props(template, _example(template.lower()))
    total = v["durationInFrames"] / v["fps"]
    [card] = [e for e in v["events"] if e["e"].startswith("end card (pixel)")]
    assert total - card["t"] >= 4.0  # CARD_S.pixel (the loop fade comes on top)


def test_render_end_card_is_cached_and_stages_the_backdrop(tmp_path, monkeypatch):
    rendered = []

    def fake_render(template, props, out, work, *, timeout_s, extra=()):
        rendered.append((template, props))
        out.write_bytes(b"mp4")

    bundle = tmp_path / "bundle"
    monkeypatch.setattr(motion, "_render", fake_render)
    monkeypatch.setattr(motion, "bundle_dir", lambda: bundle)
    frame = tmp_path / "last.jpg"
    frame.write_bytes(b"frame one")
    props = {"style": "live", "tagline": "Ton tour.", "accent": "kcal", "seconds": 3.5}
    first = motion.render_end_card(tmp_path, props, frame, timeout_s=60)
    assert first.parent == tmp_path / "endcards" and first.read_bytes() == b"mp4"
    [(template, staged)] = rendered
    assert template == "EndCard" and staged["backdrop"].startswith("public/endcards/")
    assert (bundle / staged["backdrop"]).read_bytes() == b"frame one"
    assert motion.render_end_card(tmp_path, props, frame, timeout_s=60) == first  # cached
    assert len(rendered) == 1
    frame.write_bytes(b"another video's last frame")
    assert motion.render_end_card(tmp_path, props, frame, timeout_s=60) != first
    clean = motion.render_end_card(tmp_path, {**props, "style": "clean"}, None, timeout_s=60)
    assert "backdrop" not in rendered[-1][1] and clean.is_file() and len(rendered) == 3


@needs_ffmpeg
@pytest.mark.parametrize("works", [True, False])
def test_ffmpeg_render_uses_the_motion_end_card_or_warns(store, tmp_path, monkeypatch, works):
    make_clip(tmp_path / "src.mp4", "1080x1920", duration=1)
    calls = []

    def fake_card(media_root, props, backdrop, *, timeout_s):
        calls.append(props)
        if not works:
            raise motion.MotionError("Node.js not found")
        clip = tmp_path / "card.mp4"
        make_clip(clip, "1080x1920", duration=props["seconds"])
        return clip

    monkeypatch.setattr(motion, "render_end_card", fake_card)
    env = {"kind": "ffmpeg", "inputs": {"source": "src.mp4"},
           "recipe": {"ops": [{"op": "end_card", "text": "Ton tour.", "duration_s": 3}]}}
    a = store.add_asset(store.add_idea("remix")["id"], recipe=env)
    info, files = render.render_files(a, tmp_path, lambda p: None, preset="ultrafast")
    assert info.duration == pytest.approx(4.0, abs=0.1)
    assert calls[0]["style"] == "live" and calls[0]["tagline"] == "Ton tour."
    if works:
        assert "render_warnings" not in files
    else:
        [warning] = files["render_warnings"]
        assert warning.startswith("static end card (fallback)") and "Node.js" in warning


@needs_motion
@needs_ffmpeg
def test_real_end_card_clip(tmp_path):
    """One real card render (~15 s with the bundle): the clean card at its own length."""
    clip = motion.render_end_card(tmp_path, {"style": "clean", "accent": "fat",
                                             "seconds": 2.5}, None, timeout_s=300)
    info = motion.ffmpeg.probe(clip)
    assert (info.width, info.height) == (1080, 1920)
    assert info.duration == pytest.approx(2.5, abs=0.1)
