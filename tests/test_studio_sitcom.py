"""The sitcom style (step 164): script -> troupe shot list rules, the wardrobe, the characters'
voices and the route through motion.py. Blender, Remotion and the voice are never run here."""

import json
import re
from pathlib import Path

import pytest

from src.config import InstagramMCPSettings
from src.studio import cinematic, motion, sitcom, troupe
from tests.test_studio_ffmpeg import needs_ffmpeg
from tests.test_studio_motion import _example, needs_motion
from tests.test_studio_recipe import make_clip

PROPS = {
    "hook": "Tu loggues même le dîner ?",
    "scenes": [
        {"set": "dinner", "cast": [
            {"who": "teen", "at": "stand1", "action": "phone_photo"},
            {"who": "dad", "at": "seat1", "action": "fork_up"},
            {"who": "mum", "at": "seat3", "action": "fork_up"},
            {"who": "uncle", "action": "fork_up"},
            {"who": "grandma", "at": "stand0"}],
         "beats": [
             {"line": "Chaque plat en photo.", "who": "teen", "action": "phone_photo", "speed": "normal"},
             {"line": "Tout le monde attend.", "who": "dad", "action": "fork_up", "speed": "normal",
              "say": {"who": "dad", "text": "On mange ?"}}]},
        {"set": "living", "cast": [
            {"who": "gym_mum", "action": "crunch"}, {"who": "kid_boy"}],
         "beats": [
             {"line": "Cent crunchs.", "who": "gym_mum", "action": "crunch", "speed": "x10"},
             {"line": "Et elle tombe.", "who": "kid_boy", "action": "Sitting_Idle_Loop", "speed": "slowmo"}]},
    ],
}


def _parts(props, line_s=3.1, say_s=1.6):
    """Parts end to end as the template times them: the hook, each beat's line (and say), the
    freeze on the last beat."""
    out, t = [{"scene": 0, "beat": 0, "part": "hook", "start_s": 0.0, "end_s": 1.7}], 1.7
    beats = [(i, j, b) for i, s in enumerate(props["scenes"]) for j, b in enumerate(s["beats"])]
    for i, j, b in beats:
        out.append({"scene": i, "beat": j, "part": "line", "start_s": t, "end_s": t + line_s})
        t += line_s
        if b.get("say"):
            out.append({"scene": i, "beat": j, "part": "say", "start_s": t, "end_s": t + say_s})
            t += say_s
    i, j, _ = beats[-1]
    out.append({"scene": i, "beat": j, "part": "freeze", "start_s": t, "end_s": t + 0.9})
    return out


def test_shot_list_cuts_every_one_to_two_seconds_with_three_angles_a_scene():
    parts = _parts(PROPS)
    shots = sitcom.shot_list(PROPS, parts)["shots"]
    assert all(sitcom.MIN_SHOT_S - 0.05 <= s["duration"] <= sitcom.CUT_S for s in shots)
    # the shots end to end are the whole picture up to the end card, to the frame
    assert sitcom.shot_starts({"shots": shots})[-1] == pytest.approx(parts[-1]["end_s"], abs=1 / 24)
    kinds = {}
    for s in shots:
        kinds.setdefault(s["set"], set()).add(s["camera"]["kind"])
    assert all(len(k) >= sitcom.MIN_ANGLES for k in kinds.values()), kinds
    assert {s["light"] for s in shots} == {"sitcom"}  # the saturated presets


def test_first_frame_is_action_not_a_static_picture():
    first = sitcom.shot_list(PROPS, _parts(PROPS))["shots"][0]
    assert first["camera"] == {"kind": "crash", "on": "teen"}  # a crash zoom into the action
    actor = next(a for a in first["cast"] if a["who"] == "teen")
    assert actor["action"] == "phone_photo"


def test_speeds_freeze_reactions_and_close_ups():
    shots = sitcom.shot_list(PROPS, _parts(PROPS))["shots"]
    crunch = [s for s in shots if s["set"] == "living" and
              any(a["who"] == "gym_mum" and a.get("action") == "crunch" and "offset" in a for a in s["cast"])]
    assert crunch and all(s["speed"] == 10.0 for s in crunch)  # x10 on the repeated gesture
    last = [s for s in shots if s["set"] == "living"][-1]
    assert last["freeze"] == pytest.approx(0.9, abs=1 / 24)  # the punchline frozen
    beat = PROPS["scenes"][-1]["beats"][-1]  # a whip lands on the punchline's actor
    assert last["camera"] == {"kind": "whip", "on": beat["who"]}
    slow = [s for s in shots if s["speed"] in ([1.0, 0.3], 0.3)]
    assert slow[0]["speed"] == [1.0, 0.3]  # a ramp into the slow motion
    said = [s for s in shots if s["camera"] == {"kind": "dolly", "on": "dad"}]  # the speaker's line
    assert said and next(a for a in said[0]["cast"] if a["who"] == "dad")["face"] == "shout"
    for s in shots:
        on = s["camera"].get("on")
        if on and s["set"] == "dinner":
            assert len(s["cast"]) <= sitcom.CLOSE_CAST and on in {a["who"] for a in s["cast"]}
        reacting = [a for a in s["cast"] if a.get("face") in sitcom.REACT_FACES and a["who"] != on]
        assert all(a["face_at"] > 0 for a in reacting if "face_at" in a)


def test_doers_action_continues_across_cuts():
    shots = sitcom.shot_list(PROPS, _parts(PROPS))["shots"]
    offsets = [a["offset"] for s in shots for a in s["cast"] if a["who"] == "teen" and "offset" in a]
    assert offsets[0] == 0 and offsets == sorted(offsets) and offsets[-1] > 0


def test_spots_are_picked_for_what_each_one_does():
    places = sitcom._places(PROPS["scenes"][0])
    assert places["uncle"].startswith("seat")  # fork_up sits
    assert sitcom._places(PROPS["scenes"][1])["gym_mum"] == "floor"  # a crunch lies on the floor
    crowd = {"set": "living", "cast": [{"who": w, "action": "Sitting_Idle_Loop"}
                                       for w in ("dad", "mum", "teen")], "beats": []}
    with pytest.raises(ValueError, match="no free seat"):
        sitcom._places(crowd)


@pytest.mark.parametrize("change,message", [
    ({"set": "moon"}, "set must be one of"),
    ({"cast": [{"who": "alien"}]}, "not in the troupe"),
])
def test_a_skit_the_troupe_cannot_play_is_refused(change, message):
    scene = {**PROPS["scenes"][1], **change}
    if "cast" in change:
        scene["beats"] = [{**scene["beats"][0], "who": "alien", "action": "Idle_Loop"}]
    props = {**PROPS, "scenes": [scene]}
    parts = [{**p, "scene": 0, "beat": 0} for p in _parts(props)[:2]]
    with pytest.raises(ValueError, match=message):
        sitcom.shot_list(props, parts)


# --- wardrobe ------------------------------------------------------------------------------
RAW = json.loads((cinematic.ROOT / "cast.json").read_text("utf-8"))


def test_every_logo_garment_is_repainted_and_no_two_characters_share_a_top():
    garments = RAW["_garments"]
    for who, look in cinematic.CAST.items():
        garment = Path(look["clothes"][0]).stem
        if garment in garments:  # the MakeHuman tees and their shared prints
            assert look.get("top"), f"{who} wears {garment} as is"
    tops = [(c["clothes"][0], tuple(c.get("top") or ())) for c in cinematic.CAST.values()]
    assert len(set(tops)) == len(tops)
    for name, spec in garments.items():
        assert spec["mode"] in ("flat", "pattern")
        assert all(0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1 for x0, y0, x1, y1 in spec["keep"]), name
    for logo in ("male_casualsuit02", "male_casualsuit04", "male_casualsuit06",
                 "female_casualsuit01", "female_casualsuit02"):
        assert garments[logo]["mode"] == "flat"  # the AO shading only: the print never shows


def test_a_shot_refuses_two_actors_in_the_same_top(monkeypatch):
    twin = {**cinematic.CAST["dad"]}
    monkeypatch.setitem(cinematic.CAST, "dad_twin", twin)
    shot = {"set": "dinner", "cast": [{"who": "dad", "at": "seat0"}, {"who": "dad_twin", "at": "seat1"}]}
    with pytest.raises(ValueError, match="same top"):
        troupe.validate({"shots": [shot]})


def test_the_engine_dresses_every_actor():
    for script in ("troupe.py", "shot.py"):
        src = (cinematic.ROOT / "engine" / script).read_text("utf-8")
        assert "people.dress(" in src, script
    people = (cinematic.ROOT / "engine" / "people.py").read_text("utf-8")
    assert "_garments" in people and "_ao.png" in people


def test_bubble_names_match_the_troupe():
    ts = (motion.MOTION_DIR / "src" / "templates" / "SitcomSkit" / "cast.ts").read_text("utf-8")
    names = dict(re.findall(r"^  (\w+): \"([^\"]+)\",$", ts, re.M))
    assert names == {who: c["label"] for who, c in cinematic.CAST.items()}


# --- voices --------------------------------------------------------------------------------
def test_characters_speak_in_another_approved_voice_than_the_narrator():
    voices = {v["id"] for v in json.loads(Path("brand/voices/voices.json").read_text("utf-8"))["voices"]}
    for narrator in (None, *voices):
        for who in ("dad", "grandma", "kid_boy"):
            v = sitcom.say_voice(who, narrator)
            assert v in voices and v != (narrator or sitcom.NARRATOR)
    assert sitcom.say_voice("dad", None) == "conteur_grave"
    assert sitcom.say_voice("grandma", None) == "douce_nuit"
    assert sitcom.say_voice("grandma", "douce_nuit") == "conteur_grave"


def test_voice_says_fills_each_character_line_once(tmp_path, monkeypatch):
    s = InstagramMCPSettings(_env_file=None, instagram_access_token=None, database_path=":memory:",
                             media_root=str(tmp_path))  # tts none: estimated lengths, no audio
    filled = sitcom.voice_says(PROPS, s, None)
    say = filled["scenes"][0]["beats"][1]["say"]
    assert say["seconds"] > 0 and "audioSrc" not in say
    assert sitcom.voice_says(filled, s, None) is filled  # nothing left to fill
    heard = []

    class Provider:
        def synthesize(self, text, voice):
            heard.append(voice)
            return type("S", (), {"duration_s": 1.2, "audio_path": None})()

    monkeypatch.setattr(sitcom, "get_provider", lambda settings: Provider())
    sitcom.voice_says(PROPS, s.model_copy(update={"tts_voice": "conteur_grave"}), None)
    assert heard == ["douce_nuit"]  # the default narrator voice is never a character's
    assert motion.SCRIPTS["SitcomSkit"](PROPS) == [
        PROPS["hook"], "Chaque plat en photo.", "Tout le monde attend.", "Cent crunchs.", "Et elle tombe."]


# --- the template ----------------------------------------------------------------------------
@needs_motion
@pytest.mark.parametrize("name", ["sitcomskit", "sitcomskit-salle", "sitcomskit-salon"])
def test_examples_validate_into_a_shot_list(name):
    v = motion.validate_props("SitcomSkit", _example(name))
    shots = v["shots"]["shots"]
    assert v["plates"][0]["part"] == "hook" and v["plates"][-1]["part"] == "freeze"
    end = v["plates"][-1]["end_s"]
    assert sitcom.shot_starts(v["shots"])[-1] == pytest.approx(end, abs=1 / 24)
    assert v["durationInFrames"] / v["fps"] >= end + 3.5  # the end card after the picture
    assert all(s["duration"] <= sitcom.CUT_S for s in shots)
    cast = {a["who"] for s in v["props"]["scenes"] for a in s["cast"]}
    assert 5 <= len(cast) <= 8
    assert any(e["e"].startswith("end card (sitcom)") for e in v["events"])


@needs_motion
def test_template_refuses_a_bad_skit():
    p = _example("sitcomskit")
    with pytest.raises(ValueError, match="6 words at most"):
        motion.validate_props("SitcomSkit", {**p, "hook": "un deux trois quatre cinq six sept"})
    lonely = {**p, "scenes": [{**p["scenes"][0], "cast": p["scenes"][0]["cast"][:3],
                               "beats": p["scenes"][0]["beats"][:1]}]}
    with pytest.raises(ValueError, match="troupe of 5-8"):
        motion.validate_props("SitcomSkit", lonely)
    stranger = json.loads(json.dumps(p))
    stranger["scenes"][0]["beats"][0]["who"] = "chef"
    with pytest.raises(ValueError, match="must be in the scene's cast"):
        motion.validate_props("SitcomSkit", stranger)
    with pytest.raises(ValueError, match="price|prix"):
        motion.validate_props("SitcomSkit", {**p, "outro": "Seulement 4,99 € par mois"})


@needs_motion
def test_character_lines_pause_the_narrator():
    p = _example("sitcomskit")
    lines = motion.SCRIPTS["SitcomSkit"](p)
    timings = [{"text": t, "start_s": 2.0 * i, "end_s": 2.0 * i + 1.5} for i, t in enumerate(lines)]
    say = {**p["scenes"][0]["beats"][1]["say"], "seconds": 1.0}
    p["scenes"][0]["beats"][1]["say"] = say
    v = motion.validate_props("SitcomSkit", {**p, "voice": {"audioSrc": "voice/a.wav", "lines": timings}})
    parts = v["voiceParts"]
    assert parts[0] == {"audio_s": 0, "at_s": 0}
    # after the dad's line (script line 2) the voice waits for his line and its gaps
    assert parts[1]["audio_s"] == pytest.approx(timings[2]["end_s"])
    assert parts[1]["at_s"] - parts[1]["audio_s"] == pytest.approx(1.0 + 2 * 0.2)
    # then for the uncle's line, then for the freeze on the punchline
    shift = [x["at_s"] - x["audio_s"] for x in parts]
    assert len(parts) == 4 and shift[2] > shift[1]
    assert shift[3] - shift[2] == pytest.approx(0.9)


@needs_ffmpeg
def test_render_routes_sitcom_through_the_troupe_and_stages_the_voices(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    track = tmp_path / "troupe" / "tracks" / "abc.mp4"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"mp4")
    voice = tmp_path / "voice" / "dad.wav"
    voice.parent.mkdir()
    voice.write_bytes(b"wav")
    seen = {}
    props = {"scenes": [{"beats": [{"say": {"who": "dad", "text": "Hé", "audioSrc": "voice/dad.wav"}}]}]}
    validated = {"props": props, "fps": 30, "durationInFrames": 45, "coverFrame": 21, "events": [],
                 "plates": [], "shots": {"shots": ["s"]}}

    def render(template, p, out, work, *, timeout_s, extra=()):
        seen.update(template=template, props=p)
        make_clip(out, "108x192", duration=1.5)

    monkeypatch.setattr(motion, "validate_props", lambda t, p: validated)
    monkeypatch.setattr(motion, "bundle_dir", lambda: bundle)
    monkeypatch.setattr(motion, "_render", render)
    monkeypatch.setattr(motion.recipe, "dialogue_voice", lambda p: p)
    monkeypatch.setattr(troupe, "render_shots", lambda data, root, timeout_s, grade: (
        seen.update(shots=data, grade=grade), "troupe/tracks/abc.mp4")[1])
    out = tmp_path / "video.mp4"
    _, cover_ms, _, _ = motion.render_motion_asset("SitcomSkit", props, out, tmp_path, timeout_s=120)
    assert seen["shots"] == {"shots": ["s"]} and seen["grade"] == sitcom.GRADE
    assert "saturation" in sitcom.GRADE
    assert seen["props"]["plate"] == "public/macro3d/abc.mp4"
    staged = seen["props"]["scenes"][0]["beats"][0]["say"]["audioSrc"]
    assert staged == "public/voice/dad.wav" and (bundle / staged).read_bytes() == b"wav"
    assert out.is_file() and cover_ms == 700
