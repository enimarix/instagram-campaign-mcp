"""The cinematic style (src/studio/cinematic.py): Blender is never run here, it is faked."""

import json
from pathlib import Path

import pytest

from src.studio import cinematic, ffmpeg, motion
from tests.test_studio_ffmpeg import needs_ffmpeg

ONE_LINE = {"hook": "POV: dad sees the meal prep", "hookSeconds": 1, "lines": [{"text": "Again?"}]}


def test_template_is_listed_with_its_style(monkeypatch):
    motion.list_templates.cache_clear()
    monkeypatch.setattr(motion, "_node", lambda *a, **k: {"templates": [{"id": "Hello"}]})
    try:
        ids = {t["id"]: t for t in motion.list_templates()}
    finally:
        motion.list_templates.cache_clear()
    t = ids[cinematic.TEMPLATE]
    assert t["style"] == "blender" and "Hello" in ids
    assert set(t["jsonSchema"]["properties"]) >= {"hook", "lines", "character", "voice"}
    assert motion.validate_props(cinematic.TEMPLATE, t["defaultProps"])  # defaults are valid


def test_validate_routes_without_node(monkeypatch):
    monkeypatch.setattr(motion, "_node", lambda *a, **k: pytest.fail("node called"))
    v = motion.validate_props(cinematic.TEMPLATE, {**ONE_LINE, "outro": "Mange mieux"})
    # "Again?" reads in MIN_LINE_S 1.2 s, then the 0.8 s tail and the 3.5 s end card
    assert v["durationInFrames"] == round((1.2 + 0.8 + 3.5) * 30)
    assert v["coverFrame"] == 30 and v["props"]["character"] == "dad"
    assert sorted(e["e"].split(":")[0] for e in v["events"]) == [
        "caption", "end card (live)", "hook text", "music bed (looped)"]
    quiet = motion.validate_props(cinematic.TEMPLATE, {**ONE_LINE, "music": "none"})
    assert quiet["events"][-1]["e"] == "end card (live)"
    assert (cinematic.AUDIO / "music-lounge.wav").is_file()  # the default bed exists


@pytest.mark.parametrize("bad", [
    {**ONE_LINE, "character": "robot"},
    {**ONE_LINE, "lines": []},
    {**ONE_LINE, "hook": "POV: 9,99 € par mois"},  # never a price on screen
    {**ONE_LINE, "voice": {"lines": []}},  # one timing per line
    {**ONE_LINE, "music": "music-unknown"},
])
def test_bad_props_are_value_errors(bad):
    with pytest.raises(ValueError):
        cinematic.validate(bad)


def test_script_lines_are_the_dialogue_only():
    props = cinematic.validate({**ONE_LINE, "lines": [{"text": "a"}, {"text": "b"}]})["props"]
    assert motion.SCRIPTS[cinematic.TEMPLATE](props) == ["a", "b"]


def test_cameras_cut_on_each_line():
    p = cinematic.Props.model_validate({**ONE_LINE, "lines": [{"text": "a"}] * 3})
    timings = cinematic._timings(p)
    cams = cinematic.cameras(p, timings)
    assert [c["lens"] for c in cams] == [40, 24, 40]  # close, wide, close
    assert cams[0]["frame"] == 1
    assert cams[1]["frame"] == 1 + round(timings[1].start_s * 24)


def test_flap_cues_cover_each_line_then_close():
    timings = cinematic._timings(cinematic.Props.model_validate(ONE_LINE))
    cues = cinematic.flap_cues(timings)
    assert cues[0]["start"] == 0 and cues[-1]["value"] == "X"
    assert all(c["value"] in "BCDX" for c in cues)


def test_missing_tools_say_how_to_fix(monkeypatch, tmp_path):
    monkeypatch.setattr(cinematic, "BLENDER", tmp_path / "blender.exe")
    with pytest.raises(cinematic.CinematicError, match="cinematic/setup.py"):
        cinematic.find_blender()


def test_mouth_cues_use_rhubarb_with_audio(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, what, timeout_s):
        calls.append(cmd)
        out = Path(cmd[cmd.index("-o") + 1])
        out.write_text(json.dumps({"mouthCues": [{"start": 0, "end": 0.2, "value": "D"}]}))

    monkeypatch.setattr(cinematic, "_require", lambda p: p)
    monkeypatch.setattr(cinematic, "_run", fake_run)
    monkeypatch.setattr(ffmpeg, "run", lambda *a, **k: None)
    cues = cinematic.mouth_cues(tmp_path / "v.mp3", [], tmp_path, 10)
    assert cues == [{"start": 0, "end": 0.2, "value": "D"}]
    assert "phonetic" in calls[0]  # language independent: French voices too


@needs_ffmpeg
def test_render_asset_finishes_fake_blender_frames(monkeypatch, tmp_path):
    """Blender faked by a few orange frames: grade, hook, captions, static end card, loudness."""
    seen = {}

    def fake_blender(p, timings, cues, frames, out, stills=None):
        seen.update(frames=frames, cues=cues, cams=cinematic.cameras(p, timings))
        (out / "frames").mkdir()
        ffmpeg.run(["-f", "lavfi", "-i", "color=c=orange:s=72x128:r=24", "-frames:v", frames,
                    out / "frames" / "f_%04d.png"], timeout_s=60)

    monkeypatch.setattr(cinematic, "_blender", fake_blender)
    out = tmp_path / "video.mp4"
    info, cover_ms, timeline, _ = cinematic.render_asset(ONE_LINE, out, tmp_path, timeout_s=120)
    assert seen["frames"] == 48 and seen["cues"][-1]["value"] == "X"  # flaps: no voice
    assert info.has_audio and info.width == 1080 and info.height == 1920
    assert info.duration == pytest.approx(2.0 + 3.5, abs=0.15)  # + the end card
    assert cover_ms == 1000
    assert timeline[-1]["e"] == "end card (live)"
    assert {"t": 0, "d": pytest.approx(info.duration), "e": "music bed (looped)"} in timeline
