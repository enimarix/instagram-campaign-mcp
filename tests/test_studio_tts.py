"""Step 036: voice provider interface (respx for the HTTP engine, ffmpeg probe stubbed)."""

import base64
import json

import httpx
import pytest
import respx

from src.config import InstagramMCPSettings
from src.studio import ffmpeg, tts
from src.studio.tts import LineTiming, WordTiming

URL = "http://127.0.0.1:5002/tts"
SECRET = "Authorization: Bearer s3cret-token"
SCRIPT = "Did you know?\nOctopuses have three hearts."


def _settings(tmp_path, **kw):
    kw = {"tts_provider": "http", "tts_http_url": URL, "tts_cache_dir": str(tmp_path),
          "tts_voice": "nova", "tts_http_auth_header": SECRET, **kw}
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None, **kw)


@pytest.fixture(autouse=True)
def fake_probe(monkeypatch):
    def probe(path, **_):
        if path.read_bytes().startswith(b"junk"):
            raise ffmpeg.FFmpegError("not media")
        return ffmpeg.MediaInfo(4.0, None, None, None, None, True, "mp3", 24000, 10)

    monkeypatch.setattr(tts.ffmpeg, "probe", probe)


def spans(lines):
    return [(t.text, t.start_s, t.end_s) for t in lines]


def test_none_provider_reads_at_motion_speed():
    syn = tts.get_provider(InstagramMCPSettings(_env_file=None)).synthesize(
        "Hi\n\n" + "x" * 30 + "\n")
    assert syn.audio_path is None and syn.words is None and syn.provider == "none"
    assert spans(syn.lines) == [("Hi", 0.0, 1.2), ("x" * 30, 1.5, 3.5)]
    assert syn.duration_s == 3.8
    with pytest.raises(tts.TTSError):
        tts.NoneProvider().synthesize(" \n ")


def test_estimate_spreads_by_characters_and_keeps_gaps():
    assert spans(tts.estimate_line_timings(["ab", "abcdef"], 4.3)) == [
        ("ab", 0.0, 1.0), ("abcdef", 1.3, 4.3)]
    # too short for the gaps: lines share all the audio
    assert spans(tts.estimate_line_timings(["a", "b"], 0.4)) == [("a", 0.0, 0.2), ("b", 0.2, 0.4)]


def test_group_words_follows_letters_not_punctuation():
    words = [WordTiming("Did", 0.0, 0.2), WordTiming("you", 0.2, 0.4), WordTiming("know", 0.4, 0.8),
             WordTiming("Octo-", 1.1, 1.4), WordTiming("puses", 1.4, 1.7),
             WordTiming("have", 1.7, 1.9), WordTiming("three", 1.9, 2.2),
             WordTiming("hearts!", 2.2, 2.9)]
    lines = tts.script_lines(SCRIPT)
    assert spans(tts.group_words_into_lines(words, lines)) == [
        ("Did you know?", 0.0, 0.8), ("Octopuses have three hearts.", 1.1, 2.9)]
    # a line no word reached sits at the previous end
    assert tts.group_words_into_lines(words[:3], ["Did you know", "?"])[1] == LineTiming("?", 0.8,
                                                                                        0.8)


def test_template_escapes_quotes_newlines_accents():
    body = tts.render_body('{"text": "{text}", "voice": "{voice}"}', 'Il a dit "été"\nOK\\', "a")
    assert json.loads(body) == {"text": 'Il a dit "été"\nOK\\', "voice": "a"}
    with pytest.raises(tts.TTSError):
        tts.render_body('{"text": {text}}', "hi", "a")


@respx.mock
def test_http_raw_audio_then_cache_hit(tmp_path):
    route = respx.post(URL).mock(return_value=httpx.Response(
        200, content=b"ID3 mp3 bytes", headers={"content-type": "audio/mpeg"}))
    provider = tts.get_provider(_settings(tmp_path))
    syn = provider.synthesize(SCRIPT)
    req = route.calls.last.request
    assert json.loads(req.content) == {"text": SCRIPT, "voice": "nova"}
    assert req.headers["authorization"] == "Bearer s3cret-token"
    assert syn.audio_path.read_bytes() == b"ID3 mp3 bytes" and syn.duration_s == 4.0
    assert syn.words is None and syn.lines[-1].end_s == 4.0 and syn.lines[0].start_s == 0.0

    again = tts.get_provider(_settings(tmp_path)).synthesize(SCRIPT)
    assert route.call_count == 1
    assert again == syn
    # another voice is another audio
    provider.synthesize(SCRIPT, voice="echo")
    assert route.call_count == 2


@respx.mock
def test_http_json_with_word_timings(tmp_path):
    words = [{"text": "Did", "start_s": 0, "end_s": 0.2}, {"text": "you", "start_s": 0.2,
             "end_s": 0.4}, {"text": "know?", "start_s": 0.4, "end_s": 0.7},
             {"text": "Octopuses", "start_s": 1.0, "end_s": 1.6},
             {"text": "have three hearts.", "start_s": 1.6, "end_s": 3.1}]
    respx.post(URL).mock(return_value=httpx.Response(200, json={
        "data": base64.b64encode(b"RIFF wav").decode(), "words": words}))
    s = _settings(tmp_path, tts_http_response="json", tts_http_audio_field="data")
    syn = tts.get_provider(s).synthesize(SCRIPT)
    assert syn.audio_path.read_bytes() == b"RIFF wav" and len(syn.words) == 5
    assert spans(syn.lines) == [("Did you know?", 0.0, 0.7),
                                ("Octopuses have three hearts.", 1.0, 3.1)]
    assert tts.get_provider(s).synthesize(SCRIPT) == syn  # words survive the cache


@respx.mock
@pytest.mark.parametrize("answer, mode", [
    (httpx.Response(500, text="Authorization: Bearer s3cret-token"), "audio"),
    (httpx.TimeoutException("timed out"), "audio"),
    (httpx.Response(200, json={"nope": 1}), "json"),
    (httpx.Response(200, content=b"junk"), "audio"),
])
def test_http_errors_never_leak_the_header(tmp_path, answer, mode):
    respx.post(URL).mock(side_effect=[answer])
    s = _settings(tmp_path, tts_http_response=mode)
    with pytest.raises(tts.TTSError) as err:
        tts.get_provider(s).synthesize(SCRIPT)
    assert "s3cret" not in str(err.value) and "s3cret" not in repr(err.value.__cause__)
    if isinstance(answer, httpx.Response) and answer.status_code == 500:
        assert err.value.status == 500
    assert not any(tmp_path.glob("*.json"))  # nothing cached


def test_http_needs_url(tmp_path):
    with pytest.raises(tts.TTSError):
        tts.get_provider(_settings(tmp_path, tts_http_url=None))
