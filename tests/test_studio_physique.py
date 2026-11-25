"""The physique style (« Physique Scan », owner order 75): the template's timed shots become the
troupe's blueprint shot list (src/studio/physique.py), the bands checked by the troupe
(src/studio/troupe.py), the statues kept out of every other look. Blender is never run."""

import pytest

from src.studio import physique, planning, troupe

PROPS = {
    "hero": "hero",
    "scenes": [
        {"set": "gym", "action": "curl", "beats": 4,
         "bands": [{"on": "arm_r", "text": "Protéines 180 g", "tone": "light"},
                   {"on": "chest", "text": "2 800 kcal", "tone": "dark"}]},
        {"set": "dinner", "action": "fork_up", "beats": 2,
         "bands": [{"on": "chest", "text": "520 kcal", "tone": "orange"}]},
        {"set": "gym", "action": "cheer", "at": "stand2", "beats": 2,
         "bands": [{"on": "abs", "text": "macroBody", "tone": "orange"}]},
    ],
}
PLATES = [
    {"scene": 0, "shot": 0, "start_s": 0, "end_s": 1.07, "camera": "orbit", "part": "chest"},
    {"scene": 0, "shot": 1, "start_s": 1.07, "end_s": 2.14, "camera": "close", "part": "arm_r"},
    {"scene": 1, "shot": 0, "start_s": 2.14, "end_s": 3.2, "camera": "wide", "part": "chest"},
    {"scene": 2, "shot": 0, "start_s": 3.2, "end_s": 4.27, "camera": "dolly", "part": "chest"},
]


def test_each_shot_is_the_statue_in_its_scene_with_its_bands_on_the_beat():
    shots = physique.shot_list(PROPS, PLATES)["shots"]
    assert [s["set"] for s in shots] == ["gym", "gym", "dinner", "gym"]
    assert all(s["look"] == "blueprint" for s in shots)
    # sitting actions take a seat, the others a standing mark, a named spot is kept
    assert [s["cast"][0]["at"] for s in shots] == ["bench", "bench", "seat0", "stand2"]
    # the scene's action plays on through its shots
    assert [s["cast"][0]["offset"] for s in shots] == [0.0, 1.083, 0.0, 0.0]
    assert [b["text"] for b in shots[0]["bands"]] == ["Protéines 180 g", "2 800 kcal"]
    assert all(b["who"] == "hero" for s in shots for b in s["bands"])
    # neighbouring bands roll opposite ways, and each shot turns them back
    assert [b["turns"] for b in shots[0]["bands"]] == [0.35, -0.35]
    assert [b["turns"] for b in shots[1]["bands"]] == [-0.35, 0.35]
    assert shots[1]["camera"] == {"kind": "close", "on": "hero", "part": "arm_r"}
    assert shots[2]["camera"] == {"kind": "wide"}
    # 24 fps frames add up to the plates' seconds
    assert sum(round(s["duration"] * troupe.FPS) for s in shots) == round(4.27 * troupe.FPS)


def test_a_scene_that_does_not_fit_the_troupe_names_the_problem():
    bad = {**PROPS, "scenes": [{**PROPS["scenes"][0], "set": "moon"}]}
    with pytest.raises(ValueError, match="set must be one of"):
        physique.shot_list(bad, PLATES[:1])
    bad = {**PROPS, "scenes": [{**PROPS["scenes"][0], "action": "moonwalk"}]}
    with pytest.raises(ValueError, match="unknown action"):
        physique.shot_list(bad, PLATES[:1])
    with pytest.raises(ValueError, match="at least one shot"):
        physique.shot_list(PROPS, [])


def test_the_statues_only_exist_in_the_blueprint_look():
    shot = {"set": "gym", "cast": [{"who": "hero", "at": "stand0"}]}
    with pytest.raises(ValueError, match="only in the physique style"):
        troupe.validate({"shots": [shot]})
    troupe.validate({"shots": [{**shot, "look": "blueprint"}]})


def test_bands_wrap_an_actor_of_the_shot_in_the_blueprint_look_only():
    band = {"who": "coach", "on": "chest", "text": "x"}
    with pytest.raises(ValueError, match="belong to the blueprint look"):
        troupe.validate({"shots": [{"set": "gym", "cast": [{"who": "coach", "at": "stand0"}],
                                    "bands": [band]}]})
    with pytest.raises(ValueError, match="wraps an actor of the shot"):
        troupe.validate({"shots": [{"set": "gym", "look": "blueprint",
                                    "cast": [{"who": "hero", "at": "stand0"}], "bands": [band]}]})
    with pytest.raises(ValueError, match="slide lies in 0..1"):
        troupe.validate({"shots": [{"set": "gym", "look": "blueprint",
                                    "cast": [{"who": "hero", "at": "stand0"}],
                                    "bands": [{**band, "who": "hero", "slide": [0, 2]}]}]})


def test_a_troupe_shot_keeps_its_cache_key_and_a_blueprint_one_gets_its_own():
    shot = troupe.validate({"shots": [{"set": "gym", "cast": [{"who": "coach", "at": "stand0"}],
                                       "camera": {"kind": "close", "on": "coach"}}]}).shots[0]
    job = troupe.job(shot)
    assert "look" not in job and "part" not in job["camera"]  # the sitcom's cache stays valid
    blue = troupe.validate({"shots": [{"set": "gym", "look": "blueprint",
                                       "cast": [{"who": "hero", "at": "stand0"}],
                                       "camera": {"kind": "orbit", "on": "hero", "part": "chest"},
                                       "bands": [{"who": "hero", "on": "chest", "text": "x"}]}]}).shots[0]
    job = troupe.job(blue)
    assert job["look"] == "blueprint" and job["camera"]["part"] == "chest"
    assert job["bands"] == [{"who": "hero", "on": "chest", "text": "x", "tone": "light", "turns": 0.5}]


def test_the_planning_page_times_it_as_a_blender_render():
    assert planning.TEMPLATE_ENGINES[physique.TEMPLATE] == "blender"
    assert planning.STYLE_ENGINES[physique.STYLE] == "blender"
