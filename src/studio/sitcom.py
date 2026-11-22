"""
The `sitcom` style (« Sitcom 3D », step 164): absurd family / gym / kitchen skits played by the
troupe (cinematic/, step 163) under a French voice-over, cut every 1-2 s.

The agent writes the skit as scenes (motion/src/templates/SitcomSkit/schema.ts): a set, a cast of
the troupe with roles, beats (one action each, the voice-over line, maybe a short character line,
a big number). The Remotion template times it (`plates`: the parts hook / line / say / freeze, in
seconds on the video's clock); this module turns those parts into the troupe's shot list
(src/studio/troupe.py): a cut every 1-2 s, at least three angles per scene (wide, reaction
close-ups, top-down, whip, dolly), x10 fast-forward or slow-mo ramps from the beat's `speed`, the
punchline frozen, and the action running from the very first frame (a crash zoom onto the first
beat). Blender renders the shots (cached), the template draws the captions, the big numbers, the
speech bubbles and the end card over them (src/studio/motion.py).

Character lines get their own voice (`voice_says`): an approved voice other than the narrator's,
picked by the character's gender, so a skit never sounds like one person.
"""

from __future__ import annotations

import math
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..config import InstagramMCPSettings
from . import cinematic, ffmpeg, media, troupe
from .ffmpeg import PathLike
from .tts import get_provider

TEMPLATE = "SitcomSkit"
FPS = troupe.FPS  # the shots render at the troupe's 24 fps
CUT_S = 2.0  # a shot never lasts longer (the concept: a cut every 1-2 s)
MIN_SHOT_S = 0.4
MIN_ANGLES = 3  # distinct camera kinds per scene: wide, reaction close-up, top-down...
CLOSE_CAST = 3  # a close-up builds its actor and the two nearest (the rest is out of frame)
# Saturated warm sets, contrasted video-game light (sets.json `sitcom*` presets), PS2 grade.
LIGHTS = {"dinner": "sitcom", "living": "sitcom", "restaurant": "sitcom", "gym": "sitcom_gym",
          "kitchen": "sitcom_night", "beach": "sitcom_beach"}
GRADE = cinematic.GRADE.replace("vignette=", "eq=saturation=1.35:contrast=1.06,vignette=")
# After the first shot of a scene, the angles come round in this order (`react`: a close-up on
# someone else than the beat's actor, the next one each time).
ROTATION = ("react", "top", "wide", "close", "react", "whip", "react", "dolly")
REACT_FACES = ("jaw_drop", "outraged", "disgust", "shout")
SPEEDS = {"normal": 1.0, "x10": 10.0, "slowmo": 0.3}
# Character lines: an approved voice (brand/voices/voices.json) by gender, never the narrator's.
SAY_VOICES = {"male": ("conteur_grave", "douce_nuit"), "female": ("douce_nuit", "conteur_grave")}
NARRATOR = "coach_energique"


def _gender(who: str) -> str:
    return "male" if cinematic.CAST[who]["phenotype"].get("gender", 0.5) >= 0.5 else "female"


def say_voice(who: str, narrator: Optional[str]) -> str:
    """The voice of `who`'s lines: its gender's approved voice, the other one when the
    narrator already speaks with it."""
    first, other = SAY_VOICES[_gender(who)]
    return other if first == (narrator or NARRATOR) else first


def voice_says(props: Dict[str, Any], settings: InstagramMCPSettings,
               narrator: Optional[str]) -> Dict[str, Any]:
    """`props` with each character line's `seconds` (and `audioSrc` when the provider makes
    audio) filled, one TTS call per line in the character's own voice. Props whose lines are
    all filled come back unchanged (the same object)."""
    narrator = narrator or settings.tts_voice or None  # the voice the narrator gets
    provider, out, changed = get_provider(settings), [], False
    for scene in props["scenes"]:
        beats = []
        for b in scene["beats"]:
            say = b.get("say")
            if say and "seconds" not in say:
                synth = provider.synthesize(" ".join(say["text"].split()),
                                            say_voice(say["who"], narrator))
                say = {**say, "seconds": round(max(0.4, synth.duration_s), 3)}
                if synth.audio_path:
                    from .motion import store_voice  # motion imports us

                    say["audioSrc"] = store_voice(settings, synth.audio_path)
                b, changed = {**b, "say": say}, True
            beats.append(b)
        out.append({**scene, "beats": beats})
    return {**props, "scenes": out} if changed else props


def says(props: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every character line, in order."""
    return [b["say"] for s in props["scenes"] for b in s["beats"] if b.get("say")]


# ---------------- script → shot list ----------------

def _spot_of(member: Dict[str, Any], scene: Dict[str, Any], free: List[str],
             spots: Dict[str, Any]) -> str:
    """Where a member without `at` goes: a seat when everything it does sits, the floor when
    it lies (crunch), else a standing mark; the set's spots in order."""
    acts = [member.get("action")] + [b["action"] for b in scene["beats"] if b["who"] == member["who"]]
    moves = [cinematic.ACTIONS["moves"].get(a, {"base": a}) for a in acts if a]
    lie = any(m.get("lie") for m in moves)
    sits = bool(moves) and all(m["base"].startswith("Sitting") and not m.get("lie") for m in moves)
    want = (lambda n: n == "floor") if lie else (lambda n: spots[n].get("seat", False) == sits)
    pick = next((n for n in free if want(n)), None) or next(
        (n for n in free if spots[n].get("seat", False) == sits), None)
    if pick is None:
        raise ValueError(f"set {scene['set']} has no free {'seat' if sits else 'spot'} left for "
                         f"{member['who']}: give it an `at`")
    free.remove(pick)
    return pick


def _places(scene: Dict[str, Any]) -> Dict[str, str]:
    spec = troupe.SETS["sets"].get(scene["set"])
    if spec is None:
        raise ValueError(f"set must be one of {', '.join(troupe.SETS['sets'])}")
    taken = {m["at"] for m in scene["cast"] if m.get("at")}
    free = [n for n in spec["spots"] if n not in taken]
    return {m["who"]: m.get("at") or _spot_of(m, scene, free, spec["spots"]) for m in scene["cast"]}


def _xy(spot: Any, spots: Dict[str, Any]) -> Sequence[float]:
    return spots[spot]["at"] if isinstance(spot, str) else spot


def _frames(parts: Sequence[Dict[str, Any]]) -> List[int]:
    """The parts' boundaries in the shots' frames (rounded once, so shots sum to the track)."""
    return [round(p["start_s"] * FPS) for p in parts] + [round(parts[-1]["end_s"] * FPS)]


def _counts(parts: Sequence[Dict[str, Any]], bounds: List[int]) -> List[int]:
    """Shots per part: as many as keep each under CUT_S, then more in a scene's longest part
    until the scene has MIN_ANGLES shots (never under MIN_SHOT_S)."""
    n = [0 if p["part"] == "freeze" else max(1, math.ceil((bounds[i + 1] - bounds[i]) / (CUT_S * FPS)))
         for i, p in enumerate(parts)]
    for scene in {p["scene"] for p in parts}:
        idx = [i for i, p in enumerate(parts) if p["scene"] == scene and n[i]]
        while idx and sum(n[i] for i in idx) < MIN_ANGLES:
            i = max(idx, key=lambda k: (bounds[k + 1] - bounds[k]) / (n[k] + 1))
            if (bounds[i + 1] - bounds[i]) / (n[i] + 1) < MIN_SHOT_S * FPS:
                break
            n[i] += 1
    return n


def shot_list(props: Dict[str, Any], parts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The troupe shot list for the skit `props` (the template's parsed props) and its `parts`
    (the template's `plates`: [{scene, beat, part: hook | line | say | freeze, start_s, end_s}],
    end to end from 0 to the end card). ValueError when the skit does not fit the troupe (an
    unknown character, set, spot or action: the troupe's own message)."""
    if not parts:
        raise ValueError("a skit needs at least one part")
    bounds = _frames(parts)
    counts = _counts(parts, bounds)
    places = [_places(s) for s in props["scenes"]]
    shots: List[Dict[str, Any]] = []
    angle: Dict[int, int] = {}  # shots so far in each scene
    reacted: Dict[int, int] = {}
    beat_clock: Dict[tuple, float] = {}  # action seconds already played in each beat
    for i, part in enumerate(parts):
        f0, f1 = bounds[i], bounds[i + 1]
        if part["part"] == "freeze":  # the punchline's last picture held (troupe `freeze`)
            if shots and f1 > f0:
                shots[-1]["freeze"] = round(shots[-1].get("freeze", 0) + (f1 - f0) / FPS, 4)
            continue
        si, bi = part["scene"], part["beat"]
        scene, beat = props["scenes"][si], props["scenes"][si]["beats"][bi]
        spots = troupe.SETS["sets"][scene["set"]]["spots"]
        place = places[si]
        n = counts[i]
        cuts = [f0 + round((f1 - f0) * k / n) for k in range(n + 1)]
        speaker = beat["say"]["who"] if part["part"] == "say" and beat.get("say") else None
        lead = speaker or beat["who"]
        others = [m["who"] for m in scene["cast"] if m["who"] != beat["who"]]
        frozen = i + 1 < len(parts) and parts[i + 1]["part"] == "freeze"
        for k in range(n):
            frames = cuts[k + 1] - cuts[k]
            if frames < 2:
                continue
            j = angle.get(si, 0)
            angle[si] = j + 1
            if j == 0:  # a scene opens wide; the skit opens on a crash zoom into the action
                kind, on = ("crash", lead) if si == 0 else ("wide", None)
            elif speaker and k == 0:
                kind, on = "dolly", speaker
            elif k == n - 1 and frozen:  # a whip lands on the punchline's actor, frozen there:
                # its whole body at ~2 m (a wide can miss a standing mark, a close-up a faint)
                kind, on = "whip", beat["who"]
            else:
                kind = ROTATION[(j - 1) % len(ROTATION)]
                on = lead
                if kind == "react":
                    if others:
                        on = others[reacted.get(si, 0) % len(others)]
                        reacted[si] = reacted.get(si, 0) + 1
                    kind = "close"
                if kind in ("wide", "top"):
                    on = None
            duration = frames / FPS
            speed: Any = SPEEDS[beat.get("speed", "normal")]
            if beat.get("speed") == "slowmo" and k == 0 and part["part"] != "say":
                speed = [1.0, SPEEDS["slowmo"]]  # the ramp into the slow motion
            played = beat_clock.get((si, bi), 0.0)
            pace = (speed[0] + speed[1]) / 2 if isinstance(speed, list) else speed
            beat_clock[(si, bi)] = played + duration * pace
            who = [m["who"] for m in scene["cast"]]
            if on is not None and len(who) > CLOSE_CAST:  # the actor and its nearest neighbours
                x, y = _xy(place[on], spots)
                who = sorted(who, key=lambda w: (w != on, math.dist((x, y), _xy(place[w], spots))))[:CLOSE_CAST]
            react = beat.get("react")
            cast = []
            for m in scene["cast"]:
                if m["who"] not in who:
                    continue
                a: Dict[str, Any] = {"who": m["who"], "at": place[m["who"]]}
                if m["who"] == beat["who"]:
                    a["action"] = beat["action"]
                    a["offset"] = round(min(60.0, played), 3)
                    if beat.get("face"):
                        a["face"] = beat["face"]
                elif m.get("action"):
                    a["action"] = m["action"]
                if m["who"] == speaker:
                    a["face"] = "shout"
                elif m["who"] != beat["who"]:
                    a["face"] = react or REACT_FACES[zlib.crc32(f"{m['who']}/{si}/{bi}".encode()) % len(REACT_FACES)]
                    a["face_at"] = round(min(duration * 0.5, 0.15 + (zlib.crc32(m["who"].encode()) % 5) * 0.06), 3)
                cast.append(a)
            shot: Dict[str, Any] = {"set": scene["set"], "light": LIGHTS.get(scene["set"]),
                                    "cast": cast, "camera": {"kind": kind, **({"on": on} if on else {})},
                                    "duration": round(duration, 4), "speed": speed,
                                    "seed": zlib.crc32(f"{si}/{bi}/{k}".encode()) % 1000}
            shots.append(shot)
    data = {"shots": shots}
    troupe.validate(data)  # the troupe's own checks and messages
    return data


def shot_starts(data: Dict[str, Any]) -> List[float]:
    """Where each shot starts on the track (s), and its end last."""
    out, t = [0.0], 0.0
    for s in data["shots"]:
        t += round(s["duration"] * FPS) / FPS + round(s.get("freeze", 0) * FPS) / FPS
        out.append(t)
    return out


def render_track(data: Dict[str, Any], media_root: PathLike, *, timeout_s: float) -> str:
    """The skit's picture: the shot list rendered by the troupe in the sitcom grade."""
    return troupe.render_shots(data, media_root, timeout_s=timeout_s, grade=GRADE)


def track_stills(data: Dict[str, Any], seconds: Dict[int, float], folder: Path, *,
                 timeout_s: float) -> Dict[int, Path]:
    """One graded picture per output frame `{frame: s into the video}` that falls on a shot,
    rendered as Blender stills into `folder`: {frame: png}. ponytail: each still builds its
    shot's set and actors (~10 s an actor)."""
    shots = troupe.validate(data).shots
    starts = shot_starts(data)
    engine = troupe.engine_hash()
    want: Dict[str, Dict[str, Any]] = {}
    where: Dict[int, tuple] = {}
    for f, t in seconds.items():
        i = next((k for k in range(len(shots)) if starts[k] <= t < starts[k + 1]), None)
        if i is None:
            continue
        job = troupe.job(shots[i])
        n = min(job["frames"], 1 + int((t - starts[i]) * FPS))
        key = troupe.shot_key(shots[i], engine, GRADE)
        want.setdefault(key, {"id": key, **job, "stills": []})["stills"].append(n)
        where[f] = (key, n)
    if not want:
        return {}
    import tempfile

    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        work = Path(tmp)
        troupe._blender(list(want.values()), work, timeout_s)
        out = {}
        for f, (key, n) in where.items():
            dest = folder / f"plate-{f}.png"
            ffmpeg.run(["-i", work / key / f"still_{n}.png", "-filter_complex",
                        f"[0:v]{GRADE.replace(',format=yuv420p', '')}[v]", "-map", "[v]",
                        "-frames:v", "1", "-update", "1", dest], timeout_s=timeout_s)
            out[f] = dest
    return out


def say_files(props: Dict[str, Any], media_root: PathLike) -> List[Path]:
    """The character lines' audio files (media paths resolved), in order."""
    out = []
    for say in says(props):
        src = say.get("audioSrc")
        if src and "://" not in src:
            path = media.resolve(media_root, src)
            if not path.is_file():
                raise ValueError(f"character line audio {src!r} is missing")
            out.append(path)
    return out
