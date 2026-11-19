"""Step 149: the render QC listens (synthetic WAVs written here, no real renders)."""

import random
import struct
import wave

import pytest

from src.studio import listen, qc
from tests.test_studio_ffmpeg import needs_ffmpeg
from tests.test_studio_qc import _settings, make

SR = listen.SR


def noise(seconds, level_db, seed):
    rng = random.Random(seed)
    amp = 10 ** (level_db / 20)
    return [rng.gauss(0, amp) for _ in range(round(seconds * SR))]


def write(path, samples):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", max(-32767, min(32767, round(s * 32767))))
                               for s in samples))
    return path


def voice_and_master(tmp_path, *, bed_db=(-15.0, -15.0), offset_s=0.5, gain=1.4):
    """A 'voice' (noise bursts at -20 dBFS, 1.0-2.5 s and 3.5-5.0 s) and a master: the voice
    `offset_s` later, at `gain`, over its own 'bed' (other noise) at bed_db[i] under the
    voice during span i (and the second level after 3 s)."""
    voice = [0.0] * round(6 * SR)
    for start, end in [(1.0, 2.5), (3.5, 5.0)]:
        burst = noise(end - start, -20, seed=round(start * 10))
        voice[round(start * SR):round(start * SR) + len(burst)] = burst
    bed = noise(6.5, -20 + bed_db[0], seed=99)[:3 * SR + round(offset_s * SR)]
    bed += noise(6.5, -20 + bed_db[1], seed=98)[:round(6.5 * SR) - len(bed)]
    pad = [0.0] * round(offset_s * SR)
    master = [gain * (v + b) for v, b in zip(pad + voice + [0.0] * SR, bed)]
    return write(tmp_path / "voice.wav", voice), write(tmp_path / "master.wav", master)


@needs_ffmpeg
def test_voice_above_bed_measures_each_span(tmp_path):
    voice, master = voice_and_master(tmp_path, bed_db=(-15, -6))
    spans = listen.voice_above_bed(listen.pcm(master, timeout_s=60),
                                   listen.pcm(voice, timeout_s=60))
    assert [s["t"] for s in spans] == pytest.approx([1.5, 4.0], abs=0.02)  # found 0.5 s later
    assert [s["lu"] for s in spans] == pytest.approx([15, 6], abs=1)


@needs_ffmpeg
def test_checks_flag_the_buried_span(tmp_path):
    voice, master = voice_and_master(tmp_path, bed_db=(-15, -6))
    [(name, ok, detail)] = listen.checks(master, voice, None, {}, timeout_s=60)
    assert name == "voice_above_bed" and not ok
    assert "bed too loud under the voice by" in detail and "at 4.0 s" in detail
    assert "1.5 s" not in detail  # the first span is fine

    voice, master = voice_and_master(tmp_path, bed_db=(-16, -16))
    [(_, ok, detail)] = listen.checks(master, voice, None, {}, timeout_s=60)
    assert ok and detail.startswith("voice 1") and "above the bed" in detail


@needs_ffmpeg
def test_a_voice_not_in_the_mix(tmp_path):
    _, master = voice_and_master(tmp_path)
    other = write(tmp_path / "other.wav", [0.0] * SR + noise(2, -20, seed=7))
    [(_, ok, detail)] = listen.checks(master, other, None, {}, timeout_s=60)
    assert not ok and detail == "the voice track is not heard in the mix"


def test_harsh_jumps():
    def series(*levels):
        return [(round(i * 0.1, 1), m) for i, m in enumerate(levels)]

    # the meter filling at the start, then speech onsets near the voice level: quiet
    speech = series(-120, -120, -120, -120, -30, -30, -30, -15, -14, -13, -30, -30, -14)
    assert listen.harsh_jumps(speech, -14) == []
    # thunder: 15 LU up in 0.2 s, landing 9 LU above the voice; one entry for the burst
    thunder = series(-20, -20, -20, -20, -12, -5, -6, -20, -20)
    assert listen.harsh_jumps(thunder, -14) == [(0.5, 15.0)]
    assert listen.harsh_jumps(thunder, -14, planned=[(0.4, 0.4)]) == []  # a planned BANG
    slow = series(-20, -18, -16, -14, -12, -10, -8, -6)  # a swell, not a jump
    assert listen.harsh_jumps(slow, -14) == []


@needs_ffmpeg
def test_point_sounds_on_their_cut(tmp_path):
    quiet = noise(4, -50, seed=1)
    hit = noise(0.2, -10, seed=2)
    quiet[2 * SR:2 * SR + len(hit)] = hit
    master = write(tmp_path / "m.wav", quiet)
    timeline = [{"t": 0, "d": 4, "e": "hook card"}, {"t": 2.0, "d": 0, "e": "sting: hit"}]
    [(name, ok, detail)] = listen.checks(master, None, timeline, {}, timeout_s=60)
    assert name == "sound_sync" and ok, detail
    late = [{"t": 1.85, "d": 0, "e": "sting: hit"}, {"t": 3.5, "d": 0, "e": "sfx: pop"}]
    [(_, ok, detail)] = listen.checks(master, None, late, {}, timeout_s=60)
    assert not ok
    assert detail == ("sting: hit starts +150 ms off its cut at 1.85 s; "
                      "sfx: pop at 3.5 s: no sound starts there")


def test_voice_track(tmp_path):
    (tmp_path / "voice").mkdir()
    (tmp_path / "voice" / "a.audio").write_bytes(b"x")
    motion = {"kind": "motion", "props": {"voice": {"audioSrc": "voice/a.audio"}}}
    assert listen.voice_track(motion, tmp_path) == tmp_path / "voice" / "a.audio"
    remix = {"kind": "ffmpeg", "inputs": {"source": "s.mp4", "vo": "voice/a.audio"},
             "recipe": {"ops": [{"op": "voice_over", "input": "vo"}]}}
    assert listen.voice_track(remix, tmp_path) == tmp_path / "voice" / "a.audio"
    for env in [None, {"kind": "motion", "props": {}},
                {"kind": "motion", "props": {"voice": {"audioSrc": "https://x.org/a.mp3"}}},
                {"kind": "motion", "props": {"voice": {"audioSrc": "voice/gone.audio"}}},
                {"kind": "motion", "props": {"voice": {"audioSrc": "../outside.audio"}}},
                {"kind": "ffmpeg", "inputs": {"source": "s.mp4"}, "recipe": {"ops": []}}]:
        assert listen.voice_track(env, tmp_path) is None


@needs_ffmpeg
def test_qc_listens_but_never_fails_the_render(tmp_path):
    make(tmp_path / "clip.mp4")
    write(tmp_path / "voice.wav", [0.0] * SR + noise(2, -20, seed=7))  # not in the clip
    asset = {"caption": "Fun fact", "recipe": {"kind": "motion",
                                               "props": {"voice": {"audioSrc": "voice.wav"}}}}
    r = qc.run_qc(asset, None, "clip.mp4", tmp_path, _settings())
    heard = {c["name"]: c for c in r["checks"] if c.get("blocking") is False}
    assert sorted(heard) == ["jumps", "true_peak", "voice_above_bed"]
    assert heard["true_peak"]["ok"] and heard["jumps"]["ok"]
    assert not heard["voice_above_bed"]["ok"]
    assert r["passed"] and r["reasons"] == []  # flagged, not failed
    assert r["warnings"] == ["audio: the voice track is not heard in the mix"]


@needs_ffmpeg
def test_analysis_reads_true_peak_and_momentary_loudness(tmp_path):
    found = qc.analyze(make(tmp_path / "clip.mp4"), max_black_s=1.5, max_freeze_s=3,
                       has_audio=True)
    assert -6 < found["true_peak"] < -3  # the -14 LUFS tone
    times = [t for t, _ in found["momentary"]]
    assert len(times) == pytest.approx(60, abs=2) and times[1] == pytest.approx(0.1)
    assert found["momentary"][-1][1] == pytest.approx(-14, abs=1)
