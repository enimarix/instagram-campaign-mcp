"""
The troupe engine's shot lists (step 163): the shared Blender base of the `Sitcom 3D absurde`
(164) and `Toon Chaos 3D` (165) styles, next to the single-character skit (cinematic.py).

A shot list is a list of shots. A shot: a set (cinematic/sets.json), 1-8 actors of the troupe
(cinematic/cast.json) on the set's spots, each doing an action (cinematic/actions.json: a
library clip or a hand-keyed move) with a face, one camera (wide, a reaction close-up on a named
actor, top-down, whip pan, crash zoom, dolly), a duration (1-2 s typical), a speed (x10
fast-forward, 0.3 slow-mo, or a [from, to] ramp) and a freeze (the last frame held, in seconds).

One Blender run (cinematic/engine/troupe.py) renders every shot not cached yet. Each shot is
graded like the skit (cinematic.GRADE, the PS2 look), its freeze added, and cached under
`<media root>/troupe/shots/<key>.mp4`, the key hashing the resolved shot and the engine's files;
the shots end to end are the track (`<media root>/troupe/tracks/<key>.mp4`, 24 fps, silent).
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import time
import zlib
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import cinematic, ffmpeg, guard, media
from .ffmpeg import PathLike

ENGINE = cinematic.ROOT / "engine" / "troupe.py"
SETS: Dict[str, Any] = json.loads((cinematic.ROOT / "sets.json").read_text(encoding="utf-8"))
ACTIONS = set(cinematic.ACTIONS["library"]) | set(cinematic.ACTIONS["moves"])
FACES = set(cinematic.ACTIONS["faces"])
FPS = cinematic.BLENDER_FPS
SIZE = cinematic.RENDER_SIZE
SAMPLES = 64  # EEVEE samples, as the skit
S_PER_FRAME = 8.0  # Blender timeout budget per frame
S_PER_ACTOR = 40.0  # ... and per actor built (measured ~10 s)
ON_ACTOR = ("close", "whip", "crash", "dolly")
Speed = Union[float, Tuple[float, float]]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Actor(_Model):
    who: str = Field(description="A cinematic/cast.json character")
    at: Union[str, Tuple[float, float]] = Field(description="A spot of the set, or [x, y] metres")
    facing: Optional[float] = Field(None, ge=-360, le=360, description="Degrees; default: the spot's")
    to: Optional[str] = Field(None, description="A spot to walk to during the shot")
    action: Optional[str] = Field(None, description="actions.json; default: sit on seats, else idle")
    face: Optional[str] = None
    face_at: float = Field(0.0, ge=0, description="When the face lands (s into the shot)")
    offset: Optional[float] = Field(None, ge=0, le=60, description="Action clock start (s); default: per actor")

    def sits(self) -> bool:
        move = cinematic.ACTIONS["moves"].get(self.action, {"base": self.action})
        return move["base"].startswith("Sitting") and not move.get("lie")


class Camera(_Model):
    kind: Literal["wide", "close", "top", "whip", "crash", "dolly"] = "wide"
    on: Optional[str] = Field(None, description="The actor the close / whip / crash / dolly lands on")


class Shot(_Model):
    set: str
    light: Optional[str] = Field(None, description="A sets.json light preset; default: the set's")
    cast: List[Actor] = Field(min_length=1, max_length=8)
    camera: Camera = Camera()
    duration: float = Field(1.5, ge=0.3, le=6)
    speed: Speed = 1.0
    freeze: float = Field(0.0, ge=0, le=3, description="The last frame held this long (s)")
    seed: int = 0

    @model_validator(mode="after")
    def _check(self) -> "Shot":
        spec = SETS["sets"].get(self.set)
        if spec is None:
            raise ValueError(f"set must be one of {', '.join(SETS['sets'])}")
        if self.light is not None and self.light not in SETS["lights"]:
            raise ValueError(f"light must be one of {', '.join(SETS['lights'])}")
        for s in (self.speed if isinstance(self.speed, tuple) else (self.speed,)):
            if not 0.1 <= s <= 10:
                raise ValueError("speed must lie in 0.1..10")
        who = [a.who for a in self.cast]
        if len(set(who)) != len(who):
            raise ValueError("an actor plays once per shot")
        for a in self.cast:
            if a.who not in cinematic.CAST:
                raise ValueError(f"{a.who!r} is not in the troupe ({', '.join(cinematic.CAST)})")
            for spot in (a.at, a.to):
                if isinstance(spot, str) and spot not in spec["spots"]:
                    raise ValueError(f"{self.set} has no spot {spot!r} ({', '.join(spec['spots'])})")
            seat = isinstance(a.at, str) and spec["spots"][a.at].get("seat", False)
            if a.action is None:
                a.action = "Sitting_Idle_Loop" if seat else "Idle_Loop"
            if a.action not in ACTIONS:
                raise ValueError(f"unknown action {a.action!r}")
            if a.sits() != seat:
                raise ValueError(f"{a.who}: sitting actions go on seat spots, others elsewhere")
            if a.face is not None and a.face not in FACES:
                raise ValueError(f"face must be one of {', '.join(FACES)}")
        tops = [(cinematic.CAST[w]["clothes"][0], tuple(cinematic.CAST[w].get("top") or ())) for w in who]
        if len(set(tops)) != len(tops):  # 164: never two in the same top (cast.json `top`)
            raise ValueError("two actors of the shot wear the same top (give one a cast.json top)")
        if self.camera.kind in ON_ACTOR and self.camera.on not in who:
            raise ValueError(f"a {self.camera.kind} camera lands on an actor of the shot (camera.on)")
        return self


class ShotList(_Model):
    shots: List[Shot] = Field(min_length=1, max_length=40)


def validate(data: Dict[str, Any]) -> ShotList:
    """The shot list, checked against the troupe, sets and actions; ValueError if bad."""
    try:
        return ShotList.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"shot list: {e}") from None


def _spot(spec: Dict[str, Any], at: Union[str, Tuple[float, float]]) -> Dict[str, Any]:
    return spec["spots"][at] if isinstance(at, str) else {"at": list(at), "facing": 0}


def _offset(a: Actor, seed: int) -> float:
    """A crowd never moves in sync: each actor's looping clip starts somewhere else (0-2 s);
    a clip that plays once (a faint) starts at its beginning."""
    move = cinematic.ACTIONS["moves"].get(a.action, {"base": a.action})
    if not move["base"].endswith("_Loop"):
        return 0.0
    return zlib.crc32(f"{a.who}/{seed}".encode()) % 1000 / 500


def job(shot: Shot) -> Dict[str, Any]:
    """The shot as engine/troupe.py reads it (everything resolved), minus its id and stills."""
    spec = SETS["sets"][shot.set]
    cast = [{"who": a.who, "look": cinematic.CAST[a.who], "spot": _spot(spec, a.at),
             "facing": a.facing, "to": _spot(spec, a.to) if a.to else None, "action": a.action,
             "face": a.face, "face_at": a.face_at,
             "offset": a.offset if a.offset is not None else _offset(a, shot.seed)}
            for a in shot.cast]
    return {"set": shot.set, "light": shot.light, "frames": max(2, round(shot.duration * FPS)),
            "speed": shot.speed, "seed": shot.seed, "camera": shot.camera.model_dump(), "cast": cast}


def engine_hash() -> str:
    """The engine's code and registries: an edit re-renders."""
    h = hashlib.sha256()
    files = sorted((cinematic.ROOT / "engine").glob("*.py")) + [
        cinematic.ROOT / n for n in ("cast.json", "sets.json", "actions.json")]
    for f in files:
        h.update(f.name.encode() + f.read_bytes())
    return h.hexdigest()[:12]


def shot_key(shot: Shot, engine: str, grade: str = cinematic.GRADE) -> str:
    spec = {**job(shot), "freeze": shot.freeze, "engine": engine, "size": SIZE, "samples": SAMPLES,
            "texture_px": cinematic.TEXTURE_PX, "grade": grade}
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]


def _blender(jobs: List[Dict[str, Any]], out: Path, timeout_s: float) -> None:
    cfg = {"out": str(out), "fps": FPS, "size": list(SIZE), "samples": SAMPLES,
           "texture_px": cinematic.TEXTURE_PX, "shots": jobs}
    cfg_path = out / "shots.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    n = sum(len(j["stills"]) if j.get("stills") else j["frames"] for j in jobs)
    actors = sum(len(j["cast"]) for j in jobs)
    cinematic.blender(["-b", "--python-exit-code", "1", "-P", ENGINE, "--", cfg_path], "Blender troupe shots",
                      max(timeout_s, 120 + n * S_PER_FRAME + actors * S_PER_ACTOR))


def render_shots(data: Dict[str, Any], media_root: PathLike, *, timeout_s: float,
                 grade: str = cinematic.GRADE) -> str:
    """The track of the shot list (rendering the shots not cached yet), each shot graded with
    `grade` (an ffmpeg filter from the 720x1280 frames to 1080x1920 yuv420p): its media path."""
    shots = validate(data).shots
    root = Path(media_root) / "troupe"
    engine = engine_hash()
    keys = [shot_key(s, engine, grade) for s in shots]
    track = root / "tracks" / f"{hashlib.sha256('/'.join(keys).encode()).hexdigest()[:16]}.mp4"
    if track.is_file():
        return media.relative(media_root, track)
    clips = root / "shots"
    clips.mkdir(parents=True, exist_ok=True)
    track.parent.mkdir(parents=True, exist_ok=True)
    todo = {k: s for k, s in zip(keys, shots) if not (clips / f"{k}.mp4").is_file()}
    with tempfile.TemporaryDirectory(prefix="troupe-", dir=root) as tmp:
        work = Path(tmp)
        # One Blender call per shot, cached at once: a crash, a kill or a power cut (171) loses
        # one shot, and the GPU lock is free between shots (heat pauses, other jobs).
        for k, s in todo.items():
            _blender([{"id": k, **job(s), "stills": None}], work, timeout_s)
            part = work / f"{k}.mp4"
            hold = f"tpad=stop_mode=clone:stop_duration={s.freeze:g}," if s.freeze else ""
            ffmpeg.run(["-framerate", FPS, "-i", work / k / "f_%04d.png", "-filter_complex",
                        f"[0:v]{hold}{grade}[v]", "-map", "[v]", "-r", FPS,
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


def measure(data: Dict[str, Any], out: PathLike, *, shot: Optional[int] = None,
            frame: Optional[int] = None, timeout_s: float = 1800,
            every_s: float = 0.2) -> Dict[str, Any]:
    """What one frame of a shot costs the GPU (step 177): renders frame `frame` (default the
    middle) of shot `shot` (default the one with the most actors) through cinematic.blender()
    into `out`, sampling nvidia-smi's used VRAM every `every_s` meanwhile. Blender's VRAM =
    the peak minus the baseline taken just before (run it with the GPU otherwise idle);
    the scene's texture memory comes from the engine (stats.json). Also in out/measure.json."""
    shots = validate(data).shots
    i = shot if shot is not None else max(range(len(shots)), key=lambda n: len(shots[n].cast))
    spec = job(shots[i])
    f = frame or max(1, spec["frames"] // 2)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    base = guard.vram_used_gb()
    peak, stop = [base or 0.0], threading.Event()

    def sample() -> None:
        while not stop.wait(every_s):
            used = guard.vram_used_gb()
            if used is not None:
                peak[0] = max(peak[0], used)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    started = time.monotonic()
    try:
        _blender([{"id": "measure", **spec, "stills": [f]}], out, timeout_s)
    finally:
        stop.set()
        sampler.join()
    stats = json.loads((out / "measure" / "stats.json").read_text(encoding="utf-8"))
    known = base is not None
    result = {"shot": i, "set": spec["set"], "actors": len(spec["cast"]), "frame": f,
              "seconds": round(time.monotonic() - started, 1), "baseline_vram_gb": base,
              "peak_vram_gb": round(peak[0], 2) if known else None,
              "blender_vram_gb": round(peak[0] - base, 2) if known else None,
              **stats, "still": str(out / "measure" / f"still_{f}.png")}
    (out / "measure.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":  # python -m src.studio.troupe measure <shots.json> <out> [shot] [frame]
    if len(sys.argv) < 4 or sys.argv[1] != "measure":
        sys.exit("usage: python -m src.studio.troupe measure <shots.json> <out dir> [shot] [frame]")
    extra = [int(a) for a in sys.argv[4:6]]
    print(json.dumps(measure(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")),
                             sys.argv[3], shot=extra[0] if extra else None,
                             frame=extra[1] if len(extra) > 1 else None), indent=1))
