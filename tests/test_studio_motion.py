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
from src.studio import motion, render
from src.studio.assets import transition
from src.studio.tts import LineTiming, Synthesis
from tests.test_studio_ffmpeg import needs_ffmpeg
from tests.test_studio_recipe import make_clip
from tests.test_studio_render import FAR_PAST

# ponytail: local-only. CI's Python job has no motion/node_modules (nor Chrome for Remotion);
# the motion CI job covers the templates themselves.
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
        return motion.ffmpeg.probe(out), 1500

    monkeypatch.setattr(motion, "render_motion_asset", fake_motion)
    a = store.add_asset(store.add_idea("motion")["id"],
                        recipe={"kind": "motion", "template": "Hello", "props": {}})
    info, files = render.render_files(a, tmp_path, lambda p: None, preset="ultrafast")
    assert info.duration == pytest.approx(2.0, abs=0.1)
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
    monkeypatch.setattr(motion, "preview_stills",
                        lambda *a: calls.setdefault("preview", a) and ["previews/x/frame-0.png"])

    def queue(store, settings, **kw):
        calls["queue"] = kw
        return {"asset": {"id": 7}, "job": {"id": 3, "state": "queued"}}

    monkeypatch.setattr(motion, "queue_motion_render", queue)
    monkeypatch.setattr(srv, "store", lambda: None)
    assert await srv.list_motion_templates() == {"templates": [{"id": "Hello"}]}
    assert await srv.preview_motion("Hello", {"title": "Hi"}, [0]) == {
        "stills": ["previews/x/frame-0.png"]}
    assert calls["preview"][0:2] == ("Hello", {"title": "Hi"}) and calls["preview"][3] == [0]
    assert await srv.render_motion("Hello", {"title": "Hi"}, idea_id=1) == {
        "asset_id": 7, "job_id": 3, "state": "queued"}
    assert calls["queue"]["idea_id"] == 1 and calls["queue"]["template"] == "Hello"

    def bad(*a, **kw):
        raise ValueError("invalid props for Hello")

    monkeypatch.setattr(motion, "queue_motion_render", bad)
    with pytest.raises(ToolError, match="invalid props"):
        await srv.render_motion("Hello", {}, idea_id=1)
