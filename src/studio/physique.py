"""
The `physique` style (« Physique Scan », owner order 75, rebuilt 2026-11-25 after the owner's
review: no statue, detailed 3D objects, many bands, free colours, lots of effects): kinetic type
on bands that grip an object (a muscle cut open, a dumbbell, a kettlebell, a heart, a femur),
rock, whoosh up and down it twice a shot and squeeze it, each stop its own grip, under a motion
design layer (shockwaves, halos, specks, motion blur, punches, bloom, colour fringes).

The Remotion template `PhysiqueScan` (motion/src/templates/PhysiqueScan/schema.ts) cuts the
scenes on the bed's beat and hands over its shots (`plates`: [{scene, shot, start_s, end_s,
camera}], end to end from 0 to the end card); this module turns them into the anatomy engine's
shots (cinematic/engine/anatomy.py): the scene's object and palette, its bands spaced down it and
moving between formations, LEGS a shot (never through each other), the shot's camera.
Blender renders them (cached per shot), the template draws the hook, the readouts and the end
card over them (src/studio/motion.py).
"""

from __future__ import annotations

import hashlib
import json
import random
import tempfile
import zlib
from pathlib import Path
from typing import Any, Dict, List, Sequence

from . import cinematic, ffmpeg, media
from .ffmpeg import PathLike

TEMPLATE = "PhysiqueScan"
STYLE = "physique"
ENGINE = cinematic.ROOT / "engine" / "anatomy.py"
FPS = cinematic.BLENDER_FPS
SIZE = cinematic.RENDER_SIZE
SAMPLES = 64
S_PER_FRAME = 6.0  # Blender timeout budget per frame (measured ~1.5 s)
# the 720x1280 frames upscaled, a light grain
GRADE = "scale=1080:1920:flags=lanczos,noise=alls=5:allf=t,format=yuv420p"
# where the bands stand: (centre, spread) along the object's span (0 bottom, 1 top); each leg
# whooshes them from one formation to the next, so they go up and down together
FORMATIONS = [(0.5, 0.9), (0.66, 0.6), (0.38, 0.72), (0.58, 1.0), (0.34, 0.6), (0.62, 0.8), (0.45, 0.66)]
LEGS = 2  # whooshes a shot (motion/src/templates/PhysiqueScan/schema.ts LEGS)


def _positions(n: int, formation: tuple) -> List[float]:
    """The n bands' places (top band first) in a formation: evenly spread round its centre."""
    c, k = formation
    return [round(c + k * (0.5 - (j + 0.5) / n), 3) for j in range(n)]


def shot_list(props: Dict[str, Any], plates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The anatomy engine's shots of the template's parsed `props` and its timed `plates`."""
    if not plates:
        raise ValueError("a physique video needs at least one shot")
    bounds = [round(p["start_s"] * FPS) for p in plates] + [round(plates[-1]["end_s"] * FPS)]
    shots: List[Dict[str, Any]] = []
    for i, p in enumerate(plates):
        frames = bounds[i + 1] - bounds[i]
        if frames < 2:
            continue
        scene = props["scenes"][p["scene"]]
        seed = zlib.crc32(f"{p['scene']}/{p['shot']}".encode()) % 1000
        rng = random.Random(seed)
        n, k = len(scene["bands"]), LEGS * p["shot"] + p["scene"]
        stops = [_positions(n, FORMATIONS[(k + leg) % len(FORMATIONS)]) for leg in range(LEGS + 1)]
        bands = []
        for j, b in enumerate(scene["bands"]):
            way = 1 if (j + k) % 2 == 0 else -1
            bands.append({
                "text": b["text"], "tone": b.get("tone", "light"), "path": [at[j] for at in stops],
                # a grip of its own at each stop: some parts squeezed hard, some barely
                "squeeze": [round(min(1.2, b.get("squeeze", 0.8) * rng.uniform(0.5, 1.3)), 2) for _ in stops],
                "turns": 0.6 * way, "tilt": round(way * rng.uniform(7, 14), 1), "cinch": p["shot"] == 0})
        shots.append({"frames": frames, "subject": scene.get("subject", "muscle"),
                      "palette": scene.get("palette", "lab"), "bands": bands,
                      "camera": {"kind": p["camera"], "start": round(rng.uniform(-45, 45))},
                      "seed": seed})
    return {"shots": shots}


def engine_hash() -> str:
    """The engine's code: an edit re-renders."""
    return hashlib.sha256(ENGINE.read_bytes()).hexdigest()[:12]


def shot_key(shot: Dict[str, Any], engine: str) -> str:
    spec = {**shot, "engine": engine, "size": list(SIZE), "samples": SAMPLES, "grade": GRADE}
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]


def _blender(jobs: List[Dict[str, Any]], out: Path, timeout_s: float) -> None:
    cfg = {"out": str(out), "fps": FPS, "size": list(SIZE), "samples": SAMPLES, "shots": jobs}
    cfg_path = out / "shots.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    n = sum(len(j["stills"]) if j.get("stills") else j["frames"] for j in jobs)
    cinematic.blender(["-b", "--python-exit-code", "1", "-P", ENGINE, "--", cfg_path],
                      "Blender physique shots", max(timeout_s, 120 + n * S_PER_FRAME))


def render_track(data: Dict[str, Any], media_root: PathLike, *, timeout_s: float) -> str:
    """The video's picture: the shots rendered (those not cached yet, one Blender call each, so
    a crash loses one shot and the GPU lock frees between shots), graded, end to end."""
    root = Path(media_root) / "physique"
    engine = engine_hash()
    keys = [shot_key(s, engine) for s in data["shots"]]
    track = root / "tracks" / f"{hashlib.sha256('/'.join(keys).encode()).hexdigest()[:16]}.mp4"
    if track.is_file():
        return media.relative(media_root, track)
    clips = root / "shots"
    clips.mkdir(parents=True, exist_ok=True)
    track.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="physique-", dir=root) as tmp:
        work = Path(tmp)
        for k, s in zip(keys, data["shots"]):
            if (clips / f"{k}.mp4").is_file():
                continue
            _blender([{"id": k, **s}], work, timeout_s)
            part = work / f"{k}.mp4"
            ffmpeg.run(["-framerate", FPS, "-i", work / k / "f_%04d.png", "-vf", GRADE, "-r", FPS,
                        "-c:v", "libx264", "-crf", "17", part], timeout_s=timeout_s)
            part.replace(clips / f"{k}.mp4")
        listing = work / "concat.txt"
        quoted = [(clips / f"{k}.mp4").as_posix().replace("'", r"'\''") for k in keys]
        listing.write_text("".join(f"file '{q}'\n" for q in quoted), encoding="utf-8")
        part = work / "track.mp4"
        ffmpeg.run(["-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", part],
                   timeout_s=timeout_s)
        part.replace(track)
    return media.relative(media_root, track)


def track_stills(data: Dict[str, Any], seconds: Dict[int, float], folder: Path, *,
                 timeout_s: float) -> Dict[int, Path]:
    """One graded picture per output frame `{frame: s into the video}` that falls on a shot,
    rendered as Blender stills into `folder` (one call): {frame: png}."""
    shots = data["shots"]
    starts = [0]
    for s in shots:
        starts.append(starts[-1] + s["frames"])
    engine = engine_hash()
    want: Dict[str, Dict[str, Any]] = {}
    where: Dict[int, tuple] = {}
    for f, t in seconds.items():
        n = round(t * FPS)
        i = next((k for k in range(len(shots)) if starts[k] <= n < starts[k + 1]), None)
        if i is None:
            continue
        key = shot_key(shots[i], engine)
        still = n - starts[i] + 1
        want.setdefault(key, {"id": key, **shots[i], "stills": []})["stills"].append(still)
        where[f] = (key, still)
    if not want:
        return {}
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        work = Path(tmp)
        _blender(list(want.values()), work, timeout_s)
        out = {}
        for f, (key, n) in where.items():
            dest = folder / f"plate-{f}.png"
            ffmpeg.run(["-i", work / key / f"still_{n}.png", "-vf", GRADE.replace(",format=yuv420p", ""),
                        "-frames:v", "1", "-update", "1", dest], timeout_s=timeout_s)
            out[f] = dest
    return out
