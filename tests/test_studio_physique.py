"""The physique style (« Physique Scan », owner order 75): the template's timed shots become the
anatomy engine's shots (src/studio/physique.py, cinematic/engine/anatomy.py). Blender is never
run."""

import re

import pytest

from src.studio import physique, planning

BAND = {"text": "x", "tone": "light", "squeeze": 0.8}
PROPS = {"scenes": [
    {"palette": "lab", "bands": [{**BAND, "text": f"b{j}"} for j in range(5)]},
    {"subject": "heart", "palette": "neon", "bands": [BAND, {**BAND, "tone": "accent", "squeeze": 0.2}]},
]}
PLATES = [
    {"scene": 0, "shot": 0, "start_s": 0, "end_s": 1.07, "camera": "orbit"},
    {"scene": 0, "shot": 1, "start_s": 1.07, "end_s": 2.14, "camera": "top"},
    {"scene": 1, "shot": 0, "start_s": 2.14, "end_s": 3.2, "camera": "push"},
]


def test_each_shot_moves_the_bands_up_or_down_together_never_through_each_other():
    shots = physique.shot_list(PROPS, PLATES)["shots"]
    assert [s["subject"] for s in shots] == ["muscle", "muscle", "heart"]
    assert [s["palette"] for s in shots] == ["lab", "lab", "neon"]
    # they whoosh LEGS times a shot: LEGS + 1 stops, a grip at each
    assert all(len(b["path"]) == len(b["squeeze"]) == physique.LEGS + 1 for s in shots for b in s["bands"])
    assert [s["camera"]["kind"] for s in shots] == ["orbit", "top", "push"]
    for s in shots:
        for end in range(physique.LEGS + 1):  # top band first, in order, inside the span, at every stop
            us = [b["path"][end] for b in s["bands"]]
            assert us == sorted(us, reverse=True) and 0 < us[-1] and us[0] < 1
    # one shot hands its bands' place to the next
    assert [b["path"][-1] for b in shots[0]["bands"]] == [b["path"][0] for b in shots[1]["bands"]]
    # and it moves: up then down, or down then up
    assert len({round(sum(b["path"][k] for b in shots[0]["bands"]), 3) for k in range(3)}) == 3
    # the scene's first shot pulls them tight; neighbours roll and tilt opposite ways
    assert [s["bands"][0]["cinch"] for s in shots] == [True, False, True]
    assert [b["turns"] for b in shots[0]["bands"][:2]] == [0.6, -0.6]
    assert shots[0]["bands"][0]["tilt"] * shots[0]["bands"][1]["tilt"] < 0
    # the 24 fps frames add up to the plates' seconds
    assert sum(s["frames"] for s in shots) == round(3.2 * physique.FPS)


def test_each_stop_has_its_own_grip():
    shots = physique.shot_list(PROPS, PLATES)["shots"]
    grips = [g for s in shots for b in s["bands"] for g in b["squeeze"]]
    assert len(set(grips)) > len(grips) // 2 and max(grips) <= 1.2
    assert max(shots[2]["bands"][1]["squeeze"]) < min(shots[2]["bands"][0]["squeeze"]) + 0.6


def test_the_template_objects_palettes_and_tones_are_the_engines():
    engine = physique.ENGINE.read_text(encoding="utf-8")
    schema = (physique.cinematic.ROOT.parent / "motion" / "src" / "templates" / "PhysiqueScan"
              / "schema.ts").read_text(encoding="utf-8")
    palettes = re.search(r"PALETTES = \[([^\]]*)\]", schema).group(1)
    for name in re.findall(r'"(\w+)"', palettes):
        assert f'"{name}": {{"bg"' in engine
    subjects = re.search(r"SUBJECTS = \[([^\]]*)\]", schema).group(1)
    for name in re.findall(r'"(\w+)"', subjects):
        assert f'    "{name}": {{"build": {name},' in engine
    for tone in ("light", "dark", "accent", "pop"):
        assert engine.count(f'"{tone}": (') == 3  # in each palette


def test_no_plate_no_video():
    with pytest.raises(ValueError, match="at least one shot"):
        physique.shot_list(PROPS, [])


def test_a_shot_is_cached_by_what_it_shows():
    s = physique.shot_list(PROPS, PLATES[:1])["shots"][0]
    assert physique.shot_key(s, "e") == physique.shot_key(dict(s), "e")
    assert physique.shot_key(s, "e") != physique.shot_key({**s, "palette": "neon"}, "e")
    assert physique.shot_key(s, "e") != physique.shot_key(s, "f")


def test_the_planning_page_times_it_as_a_blender_render():
    assert planning.TEMPLATE_ENGINES[physique.TEMPLATE] == "blender"
    assert planning.STYLE_ENGINES[physique.STYLE] == "blender"
