"""The troupe engine's shot lists (src/studio/troupe.py). Blender is never run here: it is
faked (ffmpeg draws the frames)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.studio import cinematic, ffmpeg, troupe
from tests.test_studio_ffmpeg import needs_ffmpeg

PROOF = json.loads((cinematic.ROOT / "shotlists" / "proof.json").read_text(encoding="utf-8"))
SHOT = {"set": "dinner", "duration": 1.0, "cast": [{"who": "dad", "at": "seat1"}]}


def test_troupe_sets_and_actions_registries():
    assert len(cinematic.CAST) >= 12
    ages = sorted(c["phenotype"]["age"] for c in cinematic.CAST.values())
    assert ages[0] < 0.2 and ages[-1] > 0.9  # child to grandparent
    assert {"gym", "kid", "elder"} <= {t for c in cinematic.CAST.values() for t in c["tags"]}
    for c in cinematic.CAST.values():
        assert sum(c["phenotype"]["race"].values()) == pytest.approx(1)
        assert {"label", "skin", "hair", "clothes"} <= set(c)
    sets = troupe.SETS["sets"]
    assert set(sets) == {"dinner", "living", "gym", "kitchen", "restaurant", "beach"}
    assert sum(s.get("seat", False) for s in sets["dinner"]["spots"].values()) >= 7
    for name, spec in sets.items():
        assert (cinematic.ROOT / "engine" / f"{spec['module']}.py").is_file(), name
        assert spec["light"] in troupe.SETS["lights"]
    moves = cinematic.ACTIONS["moves"]
    assert {"crunch", "fork_up", "faint", "cheer", "phone_photo", "carry_plate"} <= set(moves)
    assert all(m["base"] in cinematic.ACTIONS["library"] for m in moves.values())
    assert len(cinematic.ACTIONS["library"]) == 46


def test_proof_shot_list_is_valid():
    shots = troupe.validate(PROOF).shots
    assert len(shots) == 8 and len(shots[0].cast) == 7
    assert {s.camera.kind for s in shots} == {"wide", "top", "whip", "crash", "dolly"}


def test_defaults_sit_on_seats_and_stand_elsewhere():
    shot = troupe.validate({"shots": [{"set": "dinner", "cast": [
        {"who": "dad", "at": "seat1"}, {"who": "mum", "at": "door"}, {"who": "teen", "at": [0.5, -2]}]}]}).shots[0]
    assert [a.action for a in shot.cast] == ["Sitting_Idle_Loop", "Idle_Loop", "Idle_Loop"]
    job = troupe.job(shot)
    assert job["frames"] == 36 and job["cast"][2]["spot"] == {"at": [0.5, -2], "facing": 0}
    assert job["cast"][0]["look"] == cinematic.CAST["dad"]
    offsets = [a["offset"] for a in job["cast"]]
    assert len(set(offsets)) == 3 and all(0 <= o < 2 for o in offsets)  # never in sync
    faint = troupe.validate({"shots": [{"set": "dinner", "cast": [
        {"who": "dad", "at": "door", "action": "faint"}]}]}).shots[0]
    assert troupe.job(faint)["cast"][0]["offset"] == 0  # a clip played once starts at its start


@pytest.mark.parametrize("change, match", [
    ({"set": "moon"}, "set must be"),
    ({"cast": [{"who": "robot", "at": "seat1"}]}, "troupe"),
    ({"cast": [{"who": "dad", "at": "seat9"}]}, "no spot"),
    ({"cast": [{"who": "dad", "at": "seat1", "action": "moonwalk"}]}, "unknown action"),
    ({"cast": [{"who": "dad", "at": "seat1", "action": "Idle_Loop"}]}, "seat"),
    ({"cast": [{"who": "dad", "at": "door", "action": "fork_up"}]}, "seat"),
    ({"cast": [{"who": "dad", "at": "seat1", "face": "meh"}]}, "face"),
    ({"cast": [{"who": "dad", "at": "seat1"}, {"who": "dad", "at": "seat2"}]}, "once"),
    ({"camera": {"kind": "close"}}, "camera.on"),
    ({"camera": {"kind": "crash", "on": "mum"}}, "camera.on"),
    ({"speed": 20}, "speed"),
    ({"speed": [1, 0.01]}, "speed"),
    ({"light": "disco"}, "light"),
    ({"duration": 9}, "duration"),
    ({"cast": [{"who": "dad", "at": "seat1"}] * 9}, "cast"),
])
def test_bad_shots_are_value_errors(change, match):
    with pytest.raises(ValueError, match=match):
        troupe.validate({"shots": [{**SHOT, **change}]})


def test_lying_moves_go_on_the_floor():
    shot = {"set": "living", "cast": [{"who": "gym_mum", "at": "floor", "action": "crunch"}]}
    assert troupe.validate({"shots": [shot]})
    with pytest.raises(ValueError, match="seat"):
        troupe.validate({"shots": [{**shot, "cast": [{"who": "gym_mum", "at": "sofa0", "action": "crunch"}]}]})


def test_shot_key_follows_what_blender_draws():
    shot = troupe.validate({"shots": [SHOT]}).shots[0]
    key = troupe.shot_key(shot, "e1")
    for change in ({"duration": 2}, {"speed": [1, 0.3]}, {"freeze": 0.5}, {"camera": {"kind": "top"}},
                   {"cast": [{"who": "dad", "at": "seat1", "face": "smile"}]},
                   {"cast": [{"who": "mum", "at": "seat1"}]}, {"seed": 1}):
        other = troupe.validate({"shots": [{**SHOT, **change}]}).shots[0]
        assert troupe.shot_key(other, "e1") != key, change
    assert troupe.shot_key(shot, "e2") != key  # an engine edit re-renders
    assert troupe.shot_key(troupe.validate({"shots": [SHOT]}).shots[0], "e1") == key


def test_engine_hash_covers_the_registries(monkeypatch, tmp_path):
    root = tmp_path / "cinematic"
    (root / "engine").mkdir(parents=True)
    for name in ("cast.json", "sets.json", "actions.json", "engine/troupe.py"):
        (root / name).write_text("{}")
    monkeypatch.setattr(cinematic, "ROOT", root)
    before = troupe.engine_hash()
    (root / "cast.json").write_text('{"x": 1}')
    assert troupe.engine_hash() != before


def test_tools_path_override(monkeypatch, tmp_path):
    """CINEMATIC_TOOLS points the engine at the main checkout's tools (no link in a worktree)."""
    code = "from src.studio import cinematic as c; print(c.TOOLS); print(c.BLENDER)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=cinematic.ROOT.parent, env={**os.environ, "CINEMATIC_TOOLS": str(tmp_path)})
    tools, blender = out.stdout.splitlines()
    assert Path(tools) == tmp_path and Path(blender).is_relative_to(tmp_path)
    seen = {}
    monkeypatch.setattr(cinematic.subprocess, "run", lambda cmd, **k: seen.update(k) or
                        type("Done", (), {"returncode": 0})())
    cinematic._run(["x"], "x", 1)
    assert seen["env"]["CINEMATIC_TOOLS"] == str(cinematic.TOOLS)  # Blender's kit.py reads it


@needs_ffmpeg
def test_render_shots_grades_freezes_concats_and_caches(monkeypatch, tmp_path):
    calls = []

    def fake(jobs, out, timeout_s):
        calls.append(jobs)
        for job in jobs:
            (out / job["id"]).mkdir(parents=True)
            ffmpeg.run(["-f", "lavfi", "-i", "color=c=orange:s=72x128:r=24", "-frames:v", job["frames"],
                        out / job["id"] / "f_%04d.png"], timeout_s=30)

    monkeypatch.setattr(troupe, "_blender", fake)
    data = {"shots": [SHOT, {**SHOT, "duration": 0.5, "freeze": 0.5, "camera": {"kind": "top"}}]}
    path = troupe.render_shots(data, tmp_path, timeout_s=120)
    info = ffmpeg.probe(tmp_path / path)
    assert path.startswith("troupe/tracks/") and (info.width, info.height) == (1080, 1920)
    assert info.duration == pytest.approx(1.0 + 0.5 + 0.5, abs=0.1)  # the freeze holds 0.5 s
    assert [len(j) for j in calls] == [2] and calls[0][0]["cast"][0]["look"]["label"] == "Papa"
    assert troupe.render_shots(data, tmp_path, timeout_s=120) == path  # cached track
    troupe.render_shots({"shots": [SHOT, {**SHOT, "seed": 3}]}, tmp_path, timeout_s=120)
    assert [len(j) for j in calls] == [2, 1]  # only the new shot renders
    assert not list((tmp_path / "troupe").glob("troupe-*"))  # work dirs cleaned up
