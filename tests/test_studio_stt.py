"""Step 068: clip transcription (faster-whisper faked in sys.modules, ffmpeg stubbed)."""

import sys
import types
from types import SimpleNamespace as Seg

import pytest

from src.config import InstagramMCPSettings
from src.studio import ffmpeg, stt
from src.studio.recipe import CaptionLine, Captions


def _settings(tmp_path, **kw):
    kw = {"stt_provider": "faster_whisper", "stt_cache_dir": str(tmp_path / "cache"),
          "media_root": str(tmp_path / "media"), **kw}
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None, **kw)


@pytest.fixture
def whisper(monkeypatch):
    """A fake faster_whisper module; `calls` records every transcribe()."""
    calls, segments = [], [Seg(start=0.0, end=2.0, text=" Hello there. "),
                           Seg(start=2.5, end=4.0, text="Bye")]

    class WhisperModel:
        def __init__(self, model, *, device, compute_type):
            assert (device, compute_type) == ("cpu", "int8")

        def transcribe(self, audio, *, language, vad_filter):
            calls.append((audio, language))
            return iter(segments), Seg(language="en")

    monkeypatch.setitem(sys.modules, "faster_whisper",
                        types.SimpleNamespace(WhisperModel=WhisperModel))
    monkeypatch.setattr(stt.ffmpeg, "probe", lambda p: ffmpeg.MediaInfo(
        4.0, 1080, 1920, 30, "h264", True, "aac", 44100, 10))
    monkeypatch.setattr(stt.ffmpeg, "run", lambda args, **kw: None)
    return calls


def test_short_segments_stay_whole_and_clean():
    assert stt.to_lines([Seg(start=1.0, end=2.0, text="  Hi   you ")]) == [
        {"start_s": 1.0, "end_s": 2.0, "text": "Hi you"}]


def test_long_segment_splits_evenly_with_time_by_characters():
    text = " ".join(["word"] * 20)  # 99 chars → two lines, not 80 + 19
    lines = stt.to_lines([Seg(start=0.0, end=10.0, text=text)])
    assert [len(x["text"]) for x in lines] == [49, 49]
    assert all(len(x["text"]) <= 80 for x in lines)
    assert lines[0]["start_s"] == 0.0 and lines[-1]["end_s"] == 10.0
    assert lines[0]["end_s"] == lines[1]["start_s"] == 5.0
    assert stt.split_text("x" * 170) == ["x" * 57, "x" * 57, "x" * 56]


def test_drops_silence_sorts_and_trims_overlaps():
    lines = stt.to_lines([
        Seg(start=3.0, end=5.0, text="late"),
        Seg(start=0.0, end=3.5, text="early"),
        Seg(start=5.0, end=6.0, text="   "),
        Seg(start=6.0, end=7.0, text="🎵"),
        Seg(start=7.0, end=8.0, text="music", no_speech_prob=0.9, avg_logprob=-1.5),
        Seg(start=8.0, end=9.0, text="inside", no_speech_prob=0.9, avg_logprob=-0.2),
        Seg(start=8.5, end=8.9, text="swallowed"),
    ])
    assert [(x["start_s"], x["end_s"], x["text"]) for x in lines] == [
        (0.0, 3.5, "early"), (3.5, 5.0, "late"), (8.0, 9.0, "inside")]


def test_output_validates_as_captions_op():
    segs = [Seg(start=i * 3.0, end=i * 3.0 + 3.2, text="talk " * (i * 9 + 1)) for i in range(4)]
    lines = stt.to_lines(segs)
    Captions(lines=[CaptionLine(**x) for x in lines])


def test_none_provider_returns_nothing(tmp_path):
    provider = stt.get_provider(InstagramMCPSettings(_env_file=None))
    assert provider.name == "none" and provider.transcribe(tmp_path / "x.mp4") == []


def test_missing_dependency_is_a_clear_error_only_when_selected(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # import raises ImportError
    stt.get_provider(_settings(tmp_path, stt_provider="none"))
    with pytest.raises(stt.STTError, match=r"pip install -e \.\[stt\]"):
        stt.get_provider(_settings(tmp_path))


def test_cache_hit_skips_the_model(tmp_path, whisper):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")
    provider = stt.get_provider(_settings(tmp_path))
    first = provider.transcribe(clip)
    assert first == [{"start_s": 0.0, "end_s": 2.0, "text": "Hello there."},
                     {"start_s": 2.5, "end_s": 4.0, "text": "Bye"}]
    assert stt.get_provider(_settings(tmp_path)).transcribe(clip) == first
    assert len(whisper) == 1 and whisper[0][1] is None  # auto-detect
    provider.transcribe(clip, language="fr")  # other language → other cache entry
    assert len(whisper) == 2 and whisper[1][1] == "fr"


def test_clip_without_audio_has_no_lines(tmp_path, whisper, monkeypatch):
    monkeypatch.setattr(stt.ffmpeg, "probe", lambda p: ffmpeg.MediaInfo(
        4.0, 1080, 1920, 30, "h264", False, None, None, 10))
    clip = tmp_path / "silent.mp4"
    clip.write_bytes(b"video")
    assert stt.get_provider(_settings(tmp_path)).transcribe(clip) == [] and whisper == []


def test_transcribe_source_keeps_lines_in_stats(tmp_path, whisper, store):
    settings = _settings(tmp_path)
    (tmp_path / "media" / "clips").mkdir(parents=True)
    (tmp_path / "media" / "clips" / "a.mp4").write_bytes(b"video")
    src = store.add_source("local_inbox", local_path="clips/a.mp4", stats={"views": 9})
    lines = stt.transcribe_source(store, settings, src["id"])
    stats = store.get_source(src["id"])["stats"]
    assert stats["views"] == 9
    assert stats["transcript"] == {"provider": "faster_whisper", "model": "small",
                                   "lines": lines}
    with pytest.raises(stt.STTError):
        stt.transcribe_source(store, settings, store.add_source("demo")["id"])
