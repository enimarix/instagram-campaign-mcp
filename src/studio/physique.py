"""
The `physique` style (« Physique Scan », owner order 75, 2026-11-25): the owner's reference Reel
(3D kinetic type on rolling bands, a cream drafting grid, navy, orange, teal) round a jacked
statue who trains and eats.

The Remotion template `PhysiqueScan` (motion/src/templates/PhysiqueScan/schema.ts) cuts the
scenes on the bed's beat and hands over its shots (`plates`: [{scene, shot, start_s, end_s,
camera, part}], end to end from 0 to the end card); this module turns them into the troupe's
shot list in the blueprint look (src/studio/troupe.py, cinematic/engine/bands.py): the scene's
set, the statue doing the scene's action, the scene's bands round his muscles, rolling one way
then the other, and the shot's camera (an orbit, a close-up on a band's muscle, a push in, a
wide). Blender renders them (cached), the template draws the hook, the readouts and the end card
over them (src/studio/motion.py).
"""

from __future__ import annotations

import zlib
from pathlib import Path
from typing import Any, Dict, List, Sequence

from . import cinematic, sitcom, troupe
from .ffmpeg import PathLike

TEMPLATE = "PhysiqueScan"
STYLE = "physique"
FPS = troupe.FPS
# the flat print colours stay flat: the 720x1280 frames upscaled, a light paper grain, no PS2 grade
GRADE = "scale=1080:1920:flags=lanczos,noise=alls=5:allf=t,format=yuv420p"
TURNS = 0.35  # a band's roll over one shot (alternating ways, band by band)
WIDE = "wide"


def _spot(scene: Dict[str, Any]) -> str:
    """Where the statue goes when the scene names no spot: a seat for a sitting action, the
    floor for a lying one, else the set's first standing mark."""
    if scene.get("at"):
        return scene["at"]
    spots = troupe.SETS["sets"].get(scene["set"])
    if spots is None:
        raise ValueError(f"set must be one of {', '.join(troupe.SETS['sets'])}")
    spots = spots["spots"]
    move = cinematic.ACTIONS["moves"].get(scene["action"], {"base": scene["action"]})
    if move.get("lie") and "floor" in spots:
        return "floor"
    sits = move["base"].startswith("Sitting")
    pick = next((n for n, s in spots.items() if bool(s.get("seat")) == sits and n != "floor"), None)
    if pick is None:
        raise ValueError(f"set {scene['set']} has no {'seat' if sits else 'standing spot'} for "
                         f"{scene['action']}: give the scene an `at`")
    return pick


def shot_list(props: Dict[str, Any], plates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The troupe shot list of the template's parsed `props` and its timed `plates`.
    ValueError when a scene does not fit the troupe (an unknown set, spot or action: the
    troupe's own message)."""
    if not plates:
        raise ValueError("a physique video needs at least one shot")
    hero = props["hero"]
    bounds = [round(p["start_s"] * FPS) for p in plates] + [round(plates[-1]["end_s"] * FPS)]
    shots: List[Dict[str, Any]] = []
    for i, p in enumerate(plates):
        frames = bounds[i + 1] - bounds[i]
        if frames < 2:
            continue
        scene = props["scenes"][p["scene"]]
        way = -1 if p["shot"] % 2 else 1
        bands = [{"who": hero, "on": b["on"], "text": b["text"], "tone": b.get("tone", "light"),
                  "turns": round(way * TURNS * (1 if j % 2 == 0 else -1), 3)}
                 for j, b in enumerate(scene["bands"])]
        camera: Dict[str, Any] = {"kind": p["camera"]}
        if p["camera"] != WIDE:
            camera.update(on=hero, part=p["part"])
        shots.append({"set": scene["set"], "look": "blueprint",
                      "cast": [{"who": hero, "at": _spot(scene), "action": scene["action"],
                                # the action plays on through the scene's shots
                                "offset": round(sum(bounds[k + 1] - bounds[k] for k in range(i)
                                                    if plates[k]["scene"] == p["scene"]) / FPS, 3)}],
                      "bands": bands, "camera": camera, "duration": round(frames / FPS, 4),
                      "seed": zlib.crc32(f"{p['scene']}/{p['shot']}".encode()) % 1000})
    data = {"shots": shots}
    troupe.validate(data)  # the troupe's own checks and messages
    return data


def render_track(data: Dict[str, Any], media_root: PathLike, *, timeout_s: float) -> str:
    """The video's picture: the shot list rendered by the troupe in the physique grade."""
    return troupe.render_shots(data, media_root, timeout_s=timeout_s, grade=GRADE)


def track_stills(data: Dict[str, Any], seconds: Dict[int, float], folder: Path, *,
                 timeout_s: float) -> Dict[int, Path]:
    """One picture per output frame `{frame: s into the video}` that falls on a shot (the
    sitcom's way, in this grade): {frame: png}."""
    return sitcom.track_stills(data, seconds, folder, timeout_s=timeout_s, grade=GRADE)
