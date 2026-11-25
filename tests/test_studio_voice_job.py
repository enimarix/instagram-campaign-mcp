"""Step 188a: queueing a voiced video never calls the voice; the render job makes it."""

from datetime import timedelta

import httpx
import pytest
import respx

from src.store import to_iso, utcnow
from src.studio import alerts, checks, line, motion, render, sitcom, tts, voices
from src.studio.ffmpeg import FFmpegError
from src.studio.gpu_lock import LockTimeout
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
    fake.fail = TTSError("the TTS service answered HTTP 400", status=400)  # not the machine
    for attempt in range(1, render.MAX_ATTEMPTS + 1):
        job, rendered = _run(store, s)
        assert rendered == [] and job["attempts"] == attempt
        assert job["failure"] == "TTSError: voice-over failed: the TTS service answered HTTP 400"
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


def test_no_voice_ahead_while_paused(store, s, fake):
    _queue(store, s)
    second = _queue(store, s)["asset"]
    line.pause(store, True)
    job, _ = _run(store, s)  # a job already running makes its own voice
    assert job["state"] == "done" and len(fake.said) == 1
    assert "voice_todo" in store.get_asset(second["id"])["recipe"]


def test_machine_failures_are_told_from_the_video_s():
    machine = [TTSError("x", status=503), TTSError("x", status=500),
               TTSError("x", unreachable=True), LockTimeout("x")]
    video = [TTSError("x", status=400), TTSError("the TTS service returned no audio"),
             ValueError("bad props"), FFmpegError("ffmpeg exited with code 1"),
             RuntimeError("x")]
    assert all(render.machine_failure(e) for e in machine)
    assert not any(render.machine_failure(e) for e in video)


@respx.mock
def test_an_unreachable_voice_service_is_a_machine_failure(s):
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(TTSError) as e:
        tts.HttpProvider(s).synthesize("Bonjour")
    assert e.value.machine


def test_a_machine_failure_waits_in_line_without_counting_against_the_video(
        store, s, fake, monkeypatch):
    now = utcnow()
    monkeypatch.setattr(render, "utcnow", lambda: now)  # the fake clock
    asset = _queue(store, s)["asset"]
    fake.fail = TTSError("the TTS service answered HTTP 503", status=503)
    for n, minutes in enumerate((5, 15, 45, 45, 45, 45), 1):
        job, rendered = _run(store, s)
        assert rendered == [] and job["state"] == "queued" and job["attempts"] == 0
        assert job["failure"] == (f"machine {n}/{render.MACHINE_RETRIES}: TTSError: voice-over"
                                  " failed: the TTS service answered HTTP 503")
        assert job["not_before"] == to_iso(now + timedelta(minutes=minutes))
        assert job["requeues"] == 0 and job["line_pos"] is None  # its place, no re-render
        assert store.get_asset(asset["id"])["status"] == "rendering"
        assert checks.waiting(store, now) == []  # the check run never sees it
        assert line.renders_next(store, s, now, 1) == []  # it waits for its timer
    assert store.get_state("alerts_raised") is None
    job, _ = _run(store, s)  # the 7th machine failure: the cap
    assert job["state"] == "failed" and job["failure"].startswith("machine: the machine could")
    a = store.get_asset(asset["id"])
    assert a["status"] == "failed" and "machine:" in a["qc"]["reason"]
    alert = store.get_state("alerts_raised")[f"render_machine:{asset['id']}"]
    assert alert["title"] == "La machine n'arrive pas à faire la voix / le rendu"
    assert alert["link"] == f"/assets/{asset['id']}"
    [waiting] = checks.waiting(store, now)
    assert waiting["id"] == asset["id"] and waiting["rerenders"] == 0  # budget untouched


def test_a_voice_that_waited_for_ram_is_no_machine_retry(store, s, fake, monkeypatch):
    """2026-11-25: the voice service waits for RAM (the owner plays), the TTS call times out:
    the video keeps its retries, however long the wait."""
    monkeypatch.setattr(render.guard, "free_ram_gb", lambda: 3.0)
    s.guard_min_free_ram_gb = 8.0
    _queue(store, s)
    fake.fail = TTSError("the TTS service did not answer within 1200 s", unreachable=True)
    for _ in range(render.MACHINE_RETRIES + 2):
        job, _ = _run(store, s)
        assert job["state"] == "queued" and job["failure"].startswith(
            "machine 1/6: waiting for RAM (not counted): TTSError")
    monkeypatch.setattr(render.guard, "free_ram_gb", lambda: 20.0)  # RAM back: it counts
    assert _run(store, s)[0]["failure"].startswith("machine 2/6: TTSError")


def _machine_failed(store, s, fake):
    """A queued voiced video whose job failed for the machine (past MACHINE_RETRIES)."""
    asset = _queue(store, s)["asset"]
    fake.fail = TTSError("the TTS service answered HTTP 503", status=503)
    for _ in range(render.MACHINE_RETRIES + 1):
        job, _ = _run(store, s)
    fake.fail = None
    assert job["failure"].startswith("machine:") and job["requeues"] == 0
    return store.get_asset(asset["id"]), job


async def _machine_alerts(store, s):
    return [a for a in await alerts.alerts(store, s, utcnow()) if a["kind"] == "render_machine"]


# --- step 198: audit fixes ------------------------------------------------------------------
@pytest.mark.parametrize("error, voiced_after", [
    (TTSError("no answer in time", unreachable=True), False),  # the machine: it stops
    (TTSError("the TTS service answered HTTP 400", status=400), True)])  # the video's: on
def test_voice_ahead_stops_at_a_machine_failure(store, s, fake, monkeypatch, error,
                                                voiced_after):
    _queue(store, s)
    nxt, after = _queue(store, s)["asset"], _queue(store, s)["asset"]
    real = render.voice_first

    def first_ahead_fails(store_, asset, settings):
        if asset["id"] == nxt["id"]:
            raise error
        return real(store_, asset, settings)

    monkeypatch.setattr(render, "voice_first", first_ahead_fails)
    job, _ = _run(store, s)
    assert job["state"] == "done" and job["asset_id"] not in (nxt["id"], after["id"])
    assert ("voice_todo" not in store.get_asset(after["id"])["recipe"]) is voiced_after


def test_voice_ahead_stops_once_the_studio_is_paused(store, s, fake, monkeypatch):
    _queue(store, s)
    nxt, after = _queue(store, s)["asset"], _queue(store, s)["asset"]
    real = render.voice_first

    def pause_meanwhile(store_, asset, settings):
        out = real(store_, asset, settings)
        if asset["id"] == nxt["id"]:
            line.pause(store, True)  # the owner pauses while the voice of `nxt` is made
        return out

    monkeypatch.setattr(render, "voice_first", pause_meanwhile)
    _run(store, s)
    assert "voice_todo" not in store.get_asset(nxt["id"])["recipe"]
    assert "voice_todo" in store.get_asset(after["id"])["recipe"]


def test_voice_ahead_voices_every_next_one_when_all_succeed(store, s, fake):
    _queue(store, s)
    later = [_queue(store, s)["asset"] for _ in range(3)]
    _run(store, s)
    assert len(fake.said) == 4
    assert all("voice_todo" not in store.get_asset(a["id"])["recipe"] for a in later)


def test_a_relaunch_after_a_machine_failure_is_not_a_re_render(store, s, fake):
    asset, job = _machine_failed(store, s, fake)
    again = render.rerender(store, s.media_root, asset["id"], asset["recipe"])["job"]
    assert again["id"] == job["id"] and again["state"] == "queued" and again["requeues"] == 0
    job = store.claim_render_jobs(1, stale_before=FAR_PAST)[0]
    render.run_job(store, s.media_root, job, settings=s,
                   render_fn=lambda *a: (INFO, {"file_path": "video.mp4"}),
                   qc_fn=lambda *a: {"passed": False, "reason": "black frames"})
    [waiting] = checks.waiting(store, utcnow())
    assert waiting["id"] == asset["id"] and waiting["rerenders"] == 0


def test_a_relaunch_after_a_video_failure_still_counts(store, s, fake):
    idea = store.add_idea("motion")  # voiced already: the relaunch is the same recipe (job)
    asset = store.add_asset(idea["id"], recipe={
        "kind": "motion", "template": "FactQuest",
        "props": {**FACTQUEST, "voice": {"lines": [], "audioSrc": "voice/old.wav"}}})
    render.enqueue_render(store, asset["id"])
    job = store.claim_render_jobs(1, stale_before=FAR_PAST)[0]
    job = render.run_job(store, s.media_root, job, settings=s,
                         render_fn=lambda *a: (INFO, {"file_path": "video.mp4"}),
                         qc_fn=lambda *a: {"passed": False, "reason": "black frames"})
    asset = store.get_asset(asset["id"])
    again = render.rerender(store, s.media_root, asset["id"], asset["recipe"])["job"]
    assert again["id"] == job["id"] and again["requeues"] == 1


async def test_the_machine_alert_goes_once_the_video_renders(store, s, fake):
    asset, _ = _machine_failed(store, s, fake)
    [alert] = await _machine_alerts(store, s)  # the cap: it fires
    assert alert["id"] == f"render_machine:{asset['id']}"
    render.rerender(store, s.media_root, asset["id"], asset["recipe"])
    job, _ = _run(store, s)
    assert job["state"] == "done" and store.get_asset(asset["id"])["status"] == "ready"
    assert await _machine_alerts(store, s) == []


async def test_the_machine_alert_goes_once_the_video_is_relaunched_or_removed(store, s, fake):
    asset, _ = _machine_failed(store, s, fake)
    other, _ = _machine_failed(store, s, fake)
    assert len(await _machine_alerts(store, s)) == 2
    job = render.rerender(store, s.media_root, asset["id"], asset["recipe"])["job"]
    [left] = await _machine_alerts(store, s)  # relaunched: the owner acted on it
    assert left["id"] == f"render_machine:{other['id']}"
    line.remove(store, "render", job["id"])  # then taken out of the Planning
    assert store.get_asset(asset["id"])["status"] == "archived"
    [left] = await _machine_alerts(store, s)
    assert left["id"] == f"render_machine:{other['id']}"


def test_a_qc_fail_after_a_machine_wait_counts_as_before(store, s, fake):
    asset = _queue(store, s)["asset"]
    fake.fail = TTSError("the TTS service answered HTTP 503", status=503)
    _run(store, s)
    fake.fail = None
    job = store.claim_render_jobs(1, stale_before=FAR_PAST)[0]
    job = render.run_job(store, s.media_root, job, settings=s,
                         render_fn=lambda *a: (INFO, {"file_path": "video.mp4"}),
                         qc_fn=lambda *a: {"passed": False, "reason": "black frames"})
    assert job["state"] == "done" and job["attempts"] == 1
    assert store.get_asset(asset["id"])["status"] == "failed"
    [waiting] = checks.waiting(store, utcnow())
    assert waiting["id"] == asset["id"] and waiting["rerenders"] == 0
