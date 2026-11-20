"""
The `macro3d` style's 3D plates (step 154): Blender renders the shots the Remotion template
`Macro3D` lists (motion/src/templates/Macro3D/layout.ts `shotsOf`, handed over by
`schemas.mjs --validate` as `plates`), then src/studio/motion.py composes the captions,
Marco, labels and end card on top of them.

A shot: one subject in the black studio void with one slow macro move
(cinematic/engine/macro.py), rendered at 720x1280 and 30 fps, graded (lanczos upscale to
1080x1920, a soft highlight glow, fine grain) and cached under
`<media root>/macro3d/shots/<key>.mp4`, the key hashing the shot and the engine's source, so
re-renders and re-used angles cost nothing. All shots end to end are the plate track
(`<media root>/macro3d/plates/<key>.mp4`, cached the same way).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Sequence

from . import cinematic, ffmpeg, media
from .ffmpeg import PathLike

TEMPLATE = "Macro3D"
ENGINE = cinematic.ROOT / "engine" / "macro.py"
FPS = 30  # the plates play 1:1 under the 30 fps template
SIZE = (720, 1280)
S_PER_FRAME = 4.0  # Blender timeout budget per frame (measured: report in the step-154 PR)
GRADE = ("scale=1080:1920:flags=lanczos,split[a][b];"
         "[b]gblur=sigma=22,curves=all='0/0 0.6/0.12 1/1'[glow];"  # only highlights glow
         "[a][glow]blend=all_mode=screen:all_opacity=0.22,"
         "noise=alls=4:allf=t,format=yuv420p")
KEYS = ("subject", "move", "look", "seed", "text")


def _engine_hash() -> str:
    """The engine's own source (and the kit it imports): a changed engine re-renders."""
    h = hashlib.sha256()
    for f in (ENGINE, cinematic.ROOT / "engine" / "kit.py"):
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


def shot_key(shot: Dict[str, Any], engine: str) -> str:
    spec = {k: shot.get(k) for k in KEYS}
    spec.update(frames=shot["end"] - shot["start"], engine=engine, size=SIZE)
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]


def _blender(shots: List[Dict[str, Any]], out: Path, timeout_s: float) -> None:
    cfg = {"out": str(out), "fps": FPS, "size": list(SIZE), "shots": shots}
    cfg_path = out / "plates.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    n = sum(len(s["stills"]) if s.get("stills") else s["frames"] for s in shots)
    cinematic.blender(["-b", "-P", ENGINE, "--", cfg_path], "Blender macro plates",
                      max(timeout_s, 120 + n * S_PER_FRAME))


def _job(shot: Dict[str, Any], key: str) -> Dict[str, Any]:
    """The shot as macro.py reads it (`stills` None: every frame)."""
    return {"id": key, **{k: shot[k] for k in KEYS if k in shot},
            "frames": shot["end"] - shot["start"], "stills": None}


def render_plates(shots: List[Dict[str, Any]], media_root: PathLike, *, timeout_s: float) -> str:
    """The plate track for `shots` (rendering the shots not cached yet); its media path."""
    root = Path(media_root) / "macro3d"
    engine = _engine_hash()
    keys = [shot_key(s, engine) for s in shots]
    track = root / "plates" / f"{hashlib.sha256('/'.join(keys).encode()).hexdigest()[:16]}.mp4"
    if track.is_file():
        return media.relative(media_root, track)
    clips = root / "shots"
    clips.mkdir(parents=True, exist_ok=True)
    track.parent.mkdir(parents=True, exist_ok=True)
    todo = {k: s for k, s in zip(keys, shots) if not (clips / f"{k}.mp4").is_file()}
    with tempfile.TemporaryDirectory(prefix="macro3d-", dir=root) as tmp:
        work = Path(tmp)
        if todo:
            _blender([_job(s, k) for k, s in todo.items()], work, timeout_s)
            for k in todo:
                part = work / f"{k}.mp4"
                ffmpeg.run(["-framerate", FPS, "-i", work / k / "f_%04d.png",
                            "-filter_complex", f"[0:v]{GRADE}[v]", "-map", "[v]",
                            "-c:v", "libx264", "-crf", "16", "-preset", "medium", part],
                           timeout_s=timeout_s)
                part.replace(clips / f"{k}.mp4")
        listing = work / "concat.txt"
        quoted = [(clips / f"{k}.mp4").as_posix().replace("'", r"'\''") for k in keys]
        listing.write_text("".join(f"file '{q}'\n" for q in quoted), encoding="utf-8")
        part = work / "track.mp4"
        ffmpeg.run(["-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", part],
                   timeout_s=timeout_s)
        part.replace(track)
    return media.relative(media_root, track)


def plate_stills(shots: List[Dict[str, Any]], frames: Sequence[int], folder: Path, *,
                 timeout_s: float) -> Dict[int, Path]:
    """One graded plate picture per output frame in `frames` that falls on a shot (frames on
    the end card have none), rendered as Blender stills into `folder`: {frame: png}."""
    engine = _engine_hash()
    want: Dict[str, Dict[str, Any]] = {}
    where: Dict[int, tuple] = {}
    for f in frames:
        shot = next((s for s in shots if s["start"] <= f < s["end"]), None)
        if shot is None:
            continue
        key = shot_key(shot, engine)
        job = want.setdefault(key, {**_job(shot, key), "stills": []})
        job["stills"].append(f - shot["start"] + 1)
        where[f] = (key, f - shot["start"] + 1)
    if not want:
        return {}
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        work = Path(tmp)
        _blender(list(want.values()), work, timeout_s)
        out = {}
        for f, (key, n) in where.items():
            dest = folder / f"plate-{f}.png"
            ffmpeg.run(["-i", work / key / f"still_{n}.png", "-filter_complex",
                        f"[0:v]{GRADE.replace(',format=yuv420p', '')}[v]", "-map", "[v]",
                        "-frames:v", "1", "-update", "1", dest], timeout_s=timeout_s)
            out[f] = dest
    return out


def stage(bundle: Path, path: Path, name: str) -> str:
    """Copy a plate (video or picture) into the bundle's public/macro3d/ as `name`; its
    bundle path."""
    dest = bundle / "public" / "macro3d" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file() or dest.stat().st_size != path.stat().st_size:
        shutil.copyfile(path, dest)
    return f"public/macro3d/{name}"
