"""The macro3d style's plates (src/studio/macro3d.py) and their route through motion.py.
Blender and Remotion are never run here: they are faked (ffmpeg draws the frames)."""

import json
from pathlib import Path

import pytest

from src.studio import ffmpeg, macro3d, motion
from tests.test_studio_ffmpeg import needs_ffmpeg
from tests.test_studio_recipe import make_clip

SHOTS = [{"start": 0, "end": 12, "scene": 0, "subject": "apple", "move": "push", "look": "plain",
          "seed": 1},
         {"start": 12, "end": 30, "scene": 1, "subject": "scale", "move": "top", "look": "plain",
          "seed": 2, "text": "71,0"}]


@pytest.fixture
def blender(monkeypatch):
    """A fake Blender: writes each job's frames (or stills) as small PNGs; records the jobs."""
    calls = []

    def fake(jobs, out, timeout_s):
        calls.append(jobs)
        for job in jobs:
            folder = out / job["id"]
            folder.mkdir(parents=True)
            names = ([f"still_{n}.png" for n in job["stills"]] if job["stills"] else
                     [f"f_{i:04d}.png" for i in range(1, job["frames"] + 1)])
            for name in names:
                ffmpeg.run(["-f", "lavfi", "-i", "color=c=gray:s=72x128", "-frames:v", "1",
                            folder / name], timeout_s=30)
    monkeypatch.setattr(macro3d, "_blender", fake)
    return calls


def test_shot_key_follows_what_blender_draws():
    key = macro3d.shot_key(SHOTS[0], "e1")
    assert key == macro3d.shot_key({**SHOTS[0], "start": 40, "end": 52, "scene": 3}, "e1")
    for change in ({"end": 13}, {"move": "orbit"}, {"seed": 2}, {"look": "heat"}, {"text": "1"}):
        assert macro3d.shot_key({**SHOTS[0], **change}, "e1") != key
    assert macro3d.shot_key(SHOTS[0], "e2") != key  # an engine edit re-renders


@needs_ffmpeg
def test_render_plates_concats_the_shots_and_caches_them(tmp_path, blender):
    path = macro3d.render_plates(SHOTS, tmp_path, timeout_s=120)
    track = tmp_path / path
    assert path.startswith("macro3d/plates/") and track.is_file()
    info = ffmpeg.probe(track)
    assert (info.width, info.height) == (1080, 1920)
    assert info.duration == pytest.approx(30 / 30, abs=0.05)
    assert [len(jobs) for jobs in blender] == [2]
    assert {j["frames"] for j in blender[0]} == {12, 18} and blender[0][1]["text"] == "71,0"
    # the same shots again: the track is cached; one changed shot renders alone
    assert macro3d.render_plates(SHOTS, tmp_path, timeout_s=120) == path
    other = macro3d.render_plates([SHOTS[0], {**SHOTS[1], "seed": 9}], tmp_path, timeout_s=120)
    assert other != path and [len(jobs) for jobs in blender] == [2, 1]
    assert not list((tmp_path / "macro3d").glob("macro3d-*"))  # work dirs cleaned up


@needs_ffmpeg
def test_plate_stills_render_the_frames_on_shots(tmp_path, blender):
    out = macro3d.plate_stills(SHOTS, [5, 20, 40], tmp_path, timeout_s=120)
    assert sorted(out) == [5, 20]  # frame 40 is on the end card: no plate
    assert all(p.is_file() for p in out.values())
    assert [(j["subject"], j["stills"]) for j in blender[0]] == [("apple", [6]), ("scale", [9])]
    assert macro3d.plate_stills(SHOTS, [99], tmp_path, timeout_s=120) == {}


def _validated(props):
    return {"props": props, "fps": 30, "durationInFrames": 45, "coverFrame": 12, "events": [],
            "plates": SHOTS}


@needs_ffmpeg
def test_render_routes_macro3d_through_the_plates(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    track = tmp_path / "macro3d" / "plates" / "abc.mp4"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"mp4")
    seen = {}

    def render(template, props, out, work, *, timeout_s, extra=()):
        seen.update(template=template, props=props)
        make_clip(out, "108x192", duration=1.5)

    monkeypatch.setattr(motion, "validate_props", lambda t, p: _validated(p))
    monkeypatch.setattr(motion, "bundle_dir", lambda: bundle)
    monkeypatch.setattr(motion, "_render", render)
    monkeypatch.setattr(macro3d, "render_plates", lambda shots, root, timeout_s: (
        seen.setdefault("shots", shots), "macro3d/plates/abc.mp4")[1])
    out = tmp_path / "video.mp4"
    info, cover_ms, _, parts = motion.render_motion_asset("Macro3D", {"scenes": []}, out, tmp_path,
                                                   timeout_s=120)
    assert seen["template"] == "Macro3D" and seen["shots"] == SHOTS
    assert seen["props"]["plate"] == "public/macro3d/abc.mp4"
    assert (bundle / "public" / "macro3d" / "abc.mp4").read_bytes() == b"mp4"
    assert out.is_file() and cover_ms == 400
    assert parts == motion.listen.VOICE_FROM_START  # the fake validation has no voiceParts


def test_preview_puts_a_plate_under_the_frames_on_shots(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    rendered = []

    def stills(shots, frames, folder, timeout_s):
        pic = folder / "plate-5.png"
        pic.write_bytes(b"png")
        return {5: pic}

    def render(template, props, out, work, *, timeout_s, extra=()):
        rendered.append((extra[-1], props.get("plate")))
        Path(out).write_bytes(b"png")

    monkeypatch.setattr(motion, "validate_props", lambda t, p: _validated(p))
    monkeypatch.setattr(motion, "bundle_dir", lambda: bundle)
    monkeypatch.setattr(motion, "_render", render)
    monkeypatch.setattr(macro3d, "plate_stills", stills)
    paths = motion.preview_stills("Macro3D", {"scenes": []}, tmp_path, frames=[5, 40])
    assert len(paths) == 2
    name = rendered[0][1].rsplit("/", 1)[1]
    assert rendered[0][1].startswith("public/macro3d/") and name.endswith("-5.png")
    assert rendered[1] == (40, None)  # the end card needs no plate
    assert (bundle / "public" / "macro3d" / name).read_bytes() == b"png"


def test_engine_config_shape_matches_macro_py(tmp_path, monkeypatch):
    """_blender hands Blender the plates.json macro.py reads, under the GPU lock."""
    ran = []
    monkeypatch.setattr(macro3d.cinematic, "find_blender", lambda: "blender.exe")
    monkeypatch.setattr(macro3d.cinematic, "_run", lambda cmd, what, t: ran.append((cmd, t)))
    jobs = [macro3d._job(SHOTS[1], "k1")]
    macro3d._blender(jobs, tmp_path, 10)
    cfg = json.loads((tmp_path / "plates.json").read_text(encoding="utf-8"))
    assert cfg["fps"] == 30 and cfg["size"] == [720, 1280]
    assert cfg["shots"] == [{"id": "k1", "subject": "scale", "move": "top", "look": "plain",
                             "seed": 2, "text": "71,0", "frames": 18, "stills": None}]
    assert ran[0][0][-1] == tmp_path / "plates.json" and ran[0][1] >= 120 + 18 * macro3d.S_PER_FRAME
