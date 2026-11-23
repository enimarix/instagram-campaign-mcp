"""Step 188a: queueing a voiced video never calls the voice; the render job makes it."""

import httpx
import pytest
import respx

from src.studio import line, motion, render, sitcom, tts, voices
from src.studio.tts import LineTiming, Synthesis, TTSError
from tests.test_studio_motion import FACTQUEST, VALID, _settings
from tests.test_studio_render import FAR_PAST, INFO

URL = "http://127.0.0.1:1/tts"


@pytest.fixture
def s(tmp_path):
    return _settings(tmp_path, tts_provider="http", tts_http_url=URL,
                     tts_cache_dir=str(tmp_path / "cache"))


@pytest.fixture(autouse=True)
def schema(monkeypatch):
    # The voiced props time the video on the voice: a later cover frame than the estimate.
    monkeypatch.setattr(motion, "validate_props", lambda t, p: {
        **VALID, "props": p, "coverFrame": 30 if "voice" in p else 12})
    monkeypatch.setattr(motion, "list_templates", lambda: [{"id": "FactQuest", "style": "pixel"}])


class FakeTTS:
    def __init__(self, audio):
        self.audio, self.said, self.fail = audio, [], None

    def synthesize(self, text, voice=None):
        if self.fail:
            raise self.fail
        self.said.append((text, voice))
        return Synthesis(self.audio, 9.0, [LineTiming(t, i, i + 1)
                                           for i, t in enumerate(text.splitlines())],
                         None, "fake")


@pytest.fixture
def fake(tmp_path, monkeypatch):
    audio = tmp_path / "abc.wav"
    audio.write_bytes(b"RIFF")
    provider = FakeTTS(audio)
    monkeypatch.setattr(motion, "get_provider", lambda settings: provider)
    return provider


def _queue(store, s, **kw):
    idea = store.add_idea("motion")
    return motion.queue_motion_render(store, s, template="FactQuest", props=FACTQUEST,
                                      idea_id=idea["id"], **kw)


def _run(store, s):
    rendered = []

    def render_fn(asset, media_root, progress):
        rendered.append(asset["recipe"])
        return INFO, {"file_path": "video.mp4"}

    job = store.claim_render_jobs(1, stale_before=FAR_PAST)[0]
    job = render.run_job(store, s.media_root, job, settings=s, render_fn=render_fn,
                         qc_fn=lambda *a: {"passed": True})
    return job, rendered


def test_queue_stores_the_voice_to_make_and_never_calls_it(store, s, fake):
    out = _queue(store, s)
    env = out["asset"]["recipe"]
    assert fake.said == [] and out["job"]["state"] == "queued"
    assert "voice" not in env["props"] and "thumb_offset_ms" not in env
    assert env["voice_todo"].get("voice") == voices.default_voice(store)
    with pytest.raises(ValueError, match="not available"):  # the voice is checked now
        _queue(store, s, voice="no-such-voice")


def test_the_job_voices_the_recipe_then_renders_it(store, s, fake, tmp_path):
    asset = _queue(store, s)["asset"]
    job, rendered = _run(store, s)
    assert job["state"] == "done" and len(fake.said) == 1
    lines = fake.said[0][0].splitlines()
    assert lines[0] == FACTQUEST["hook"] and len(lines) == len(FACTQUEST["facts"]) + 2
    env = store.get_asset(asset["id"])["recipe"]
    assert rendered == [env] and "voice_todo" not in env  # kept: never synthesised again
    assert env["props"]["voice"]["audioSrc"] == "voice/abc.wav"
    assert (tmp_path / "voice" / "abc.wav").is_file()
    assert env["props"]["voice"]["lines"][1] == {"text": lines[1], "start_s": 1, "end_s": 2}
    assert env["thumb_offset_ms"] == 1000  # the voiced cover frame, not the estimate's


def test_a_voice_failure_is_retried_then_fails_the_job_with_the_reason(store, s, fake):
    asset = _queue(store, s)["asset"]
    fake.fail = TTSError("the TTS service answered HTTP 503", status=503)
    for attempt in range(1, render.MAX_ATTEMPTS + 1):
        job, rendered = _run(store, s)
        assert rendered == [] and job["attempts"] == attempt
        assert job["failure"] == "TTSError: voice-over failed: the TTS service answered HTTP 503"
    assert job["state"] == "failed"
    a = store.get_asset(asset["id"])
    assert a["status"] == "failed" and "voice-over failed" in a["qc"]["reason"]
    assert "voice_todo" in a["recipe"]  # a re-render of it voices it then


def test_an_old_recipe_with_its_voice_filled_renders_unchanged(store, s, fake):
    voiced = {**FACTQUEST, "voice": {"lines": [], "audioSrc": "voice/old.wav"}}
    idea = store.add_idea("motion")
    env = {"kind": "motion", "template": "FactQuest", "props": voiced, "thumb_offset_ms": 400}
    asset = store.add_asset(idea["id"], recipe=env)
    render.enqueue_render(store, asset["id"])
    job, rendered = _run(store, s)
    assert job["state"] == "done" and rendered == [env] and fake.said == []
    assert store.get_asset(asset["id"])["recipe"] == env


@respx.mock
def test_a_re_render_of_the_same_lines_is_a_cache_hit(store, s, monkeypatch):
    route = respx.post(URL).mock(return_value=httpx.Response(
        200, content=b"ID3 mp3", headers={"content-type": "audio/mpeg"}))
    monkeypatch.setattr(tts.ffmpeg, "probe", lambda path, **_: INFO)
    first = _queue(store, s)["asset"]
    assert route.call_count == 0  # queueing never calls the service
    _run(store, s)
    assert route.call_count == 1
    # The agent sends the same props again (a new version of the ready video).
    motion.queue_motion_render(store, s, template="FactQuest", props=FACTQUEST,
                               asset_id=first["id"])
    job, _ = _run(store, s)
    assert job["state"] == "done" and route.call_count == 1  # the provider's cache
    (child,) = [a for a in store.list_assets() if a["parent_asset_id"] == first["id"]]
    assert child["recipe"]["props"]["voice"] == store.get_asset(first["id"])["recipe"][
        "props"]["voice"]


def test_a_none_engine_still_fills_the_reading_estimate_at_queue(store, tmp_path):
    out = _queue(store, _settings(tmp_path))  # TTS_PROVIDER=none: nothing to wait for
    env = out["asset"]["recipe"]
    assert "voice_todo" not in env and "audioSrc" not in env["props"]["voice"]
    assert env["thumb_offset_ms"] == 1000


def test_sitcom_character_lines_wait_for_the_job_too():
    said = {"text": "Non !", "who": "dad", "seconds": 1.0}
    props = {"voice": {"lines": []}, "scenes": [{"beats": [{"say": said}]}]}
    assert not motion.voice_pending(sitcom.TEMPLATE, props)
    unsaid = {**props, "scenes": [{"beats": [{"say": {"text": "Non !", "who": "dad"}}]}]}
    assert motion.voice_pending(sitcom.TEMPLATE, unsaid)
    assert motion.voice_pending("FactQuest", {}) and not motion.voice_pending("Hello", {})


def test_a_warm_voice_makes_the_next_voices_in_line_once(store, s, fake):
    first, second = _queue(store, s)["asset"], _queue(store, s)["asset"]
    job, _ = _run(store, s)
    assert job["asset_id"] == first["id"] and len(fake.said) == 2  # one model load, two voices
    assert "voice_todo" not in store.get_asset(second["id"])["recipe"]
    job, rendered = _run(store, s)
    assert job["asset_id"] == second["id"] and job["state"] == "done"
    assert len(fake.said) == 2 and rendered[0]["props"]["voice"]["audioSrc"] == "voice/abc.wav"


def test_held_renders_and_failures_are_not_voiced_ahead(store, s, fake, monkeypatch):
    _queue(store, s)
    held = _queue(store, s)
    line.hold(store, "render", held["job"]["id"], True)
    _run(store, s)
    assert len(fake.said) == 1 and "voice_todo" in store.get_asset(held["asset"]["id"])["recipe"]
    line.hold(store, "render", held["job"]["id"], False)
    later = _queue(store, s)["asset"]
    ahead = {"n": 0}
    real = render.voice_first

    def flaky(store_, asset, settings):  # the job itself voices, the one ahead fails
        ahead["n"] += 1
        if ahead["n"] > 1:
            raise TTSError("the TTS service answered HTTP 503")
        return real(store_, asset, settings)

    monkeypatch.setattr(render, "voice_first", flaky)
    job, _ = _run(store, s)
    assert job["state"] == "done"  # a voice made ahead that fails never fails this job
    assert "voice_todo" in store.get_asset(later["id"])["recipe"]
