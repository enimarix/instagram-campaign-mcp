"""
The `blender` style: "PS2 cutscene" skits rendered by Blender (cinematic/, README there), a
second engine next to the Remotion templates in motion/.

It plugs in behind the motion door (src/studio/motion.py routes template `CinematicSkit` here),
so the agent, the MCP tools, the render queue and the website use it like any motion template:
same recipe envelope (`kind: motion`), same TTS voice filling, same QC.

A render: the voice (TTS, already in `props.voice`) → Rhubarb mouth cues (or simple mouth flaps
from the line timings without audio) → Blender renders the seated character in the dining set,
cutting between a close and a wide camera on each line → ffmpeg grade (bloom, warm balance,
S-curve, vignette) → the shared ffmpeg recipe ops: the "POV" hook text, the dialogue captions
and the animated live end card, then loudness.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..config import get_settings
from . import ffmpeg, gpu_lock, media, recipe
from .ffmpeg import MediaInfo, PathLike
from .tts import LineTiming, reading_timings

TEMPLATE = "CinematicSkit"
STYLE, STYLE_LABEL = "blender", "Blender"
ROOT = Path(__file__).resolve().parents[2] / "cinematic"
TOOLS = ROOT / "tools"
BLENDER = TOOLS / "blender-5.2.4-windows-x64" / "blender.exe"
RHUBARB = TOOLS / "Rhubarb-Lip-Sync-1.14.0-Windows" / "rhubarb.exe"
CAST: Dict[str, Dict[str, Any]] = {k: v for k, v in json.loads(
    (ROOT / "cast.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}

FPS = recipe.FPS  # the output; Blender renders at BLENDER_FPS, the PS2 cutscene rate
BLENDER_FPS = 24
RENDER_SIZE = (720, 1280)  # upscaled to 1080x1920 with lanczos (soft, like the reference)
TAIL_S = 0.8  # after the last line, before the end card
CARD_S = 3.5
COVER_S = 1.0  # the hook is on screen from frame 0
S_PER_FRAME = 8.0  # Blender timeout budget per frame (measured ~2.5 s at 720x1280, EEVEE)
TAIL_CHARS = 2000
AUDIO = ROOT.parent / "motion" / "public" / "audio"  # the generated beds (motion/scripts/make-assets.ts)
MUSIC_DB = -22.0  # under the voice
# Seated at the dining table (cast.json `location`): a close and a wide camera.
CAMERAS = {"close": {"pos": [0.28, -1.4, 1.3], "look_at": [0, 0.15, 1.15], "lens": 40},
           "wide": {"pos": [1.35, -2.35, 1.55], "look_at": [-0.1, -0.2, 1.0], "lens": 24}}
GRADE = ("scale=1080:1920:flags=lanczos,split[a][b];"
         "[b]gblur=sigma=28,curves=all='0/0 0.55/0.2 1/1'[glow];"  # only highlights glow
         "[a][glow]blend=all_mode=screen:all_opacity=0.35,"
         "colorbalance=rs=0.04:bs=-0.05:rm=0.03:bm=-0.03:rh=0.02:bh=-0.04,"  # warm
         "curves=all='0/0.02 0.25/0.22 0.75/0.8 1/0.98',"  # gentle S-curve, lifted blacks
         "vignette=angle=0.55,format=yuv420p")


class CinematicError(RuntimeError):
    """Blender or Rhubarb missing or failed (worth a retry; bad props raise ValueError)."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Line(_Model):
    text: str = Field(min_length=1, max_length=recipe.MAX_CAPTION)


class Timing(_Model):
    text: str
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)


class Voice(_Model):
    audioSrc: Optional[str] = None
    lines: Optional[List[Timing]] = None


class Citation(_Model):
    url: str
    title: Optional[str] = None


class Props(_Model):
    """A 10-20 s "PS2 cutscene" skit: one character at the dining table says 1-6 lines while
    the camera cuts between a close and a wide shot; the hook ("POV: ...") is on screen from
    frame 0, the lines are captioned, the video ends on the animated live end card."""

    hook: str = Field(min_length=1, max_length=80, description="The silent POV caption")
    hookSeconds: float = Field(4.0, ge=1, le=8)
    character: str = Field("dad", description="A cinematic/cast.json preset")
    lines: List[Line] = Field(min_length=1, max_length=6)
    shots: Literal["auto", "close", "wide"] = Field(
        "auto", description="auto: close on the first line, then cut close/wide each line")
    captions: bool = True
    outro: Optional[str] = Field(None, max_length=60, description="The end card's tagline")
    accent: recipe.Accent = "brand"
    music: Literal["music-lounge", "music-marimba", "music-kalimba", "none"] = Field(
        "music-lounge", description="Background bed, looped under the whole video and the card")
    citations: List[Citation] = []
    voice: Optional[Voice] = None

    @model_validator(mode="after")
    def _check(self) -> "Props":
        if self.character not in CAST:
            raise ValueError(f"character must be one of {', '.join(CAST)}")
        if self.voice and self.voice.lines is not None and len(self.voice.lines) != len(self.lines):
            raise ValueError("voice.lines needs one timing per script line")
        return self


DEFAULTS = {"hook": "POV: dad found out about meal prep",
            "lines": [{"text": "So you're telling me it's chicken and rice..."},
                      {"text": "seven days a week?"}]}


def template_info() -> Dict[str, Any]:
    """This template as motion.list_templates() lists the Remotion ones."""
    schema = Props.model_json_schema()
    return {"id": TEMPLATE, "style": STYLE, "styleLabel": STYLE_LABEL, "jsonSchema": schema,
            "defaultProps": Props.model_validate(DEFAULTS).model_dump(exclude_none=True),
            "description": schema.get("description")}


def _timings(p: Props) -> List[LineTiming]:
    if p.voice and p.voice.lines:
        return [LineTiming(t.text, t.start_s, t.end_s) for t in p.voice.lines]
    return reading_timings([line.text for line in p.lines])


def _plan(p: Props) -> Tuple[List[LineTiming], float, recipe.Recipe]:
    """Line timings, the length of the Blender part (s) and the finishing recipe."""
    timings = _timings(p)
    body_s = max(timings[-1].end_s + TAIL_S, p.hookSeconds)
    ops: List[Dict[str, Any]] = [{"op": "hook_text", "text": p.hook, "start_s": 0,
                                  "end_s": min(p.hookSeconds, body_s), "position": "top"}]
    if p.captions:
        ops.append({"op": "captions", "lines": [
            {"start_s": t.start_s, "end_s": t.end_s, "text": line.text}
            for t, line in zip(timings, p.lines)]})
    ops.append({"op": "end_card", "style": "live", "accent": p.accent, "duration_s": CARD_S,
                **({"text": p.outro} if p.outro else {})})
    if p.music != "none":  # after the end card, so the bed runs under the card too
        ops.append({"op": "music", "level_db": MUSIC_DB})
    return timings, body_s, recipe.Recipe.model_validate({"ops": ops})


def validate(props: Dict[str, Any]) -> Dict[str, Any]:
    """Same shape as motion.validate_props: {props, fps, durationInFrames, coverFrame,
    events}; ValueError for bad props."""
    try:
        p = Props.model_validate(props)
        _, body_s, rec = _plan(p)
    except ValidationError as e:
        raise ValueError(f"{TEMPLATE}: {e}") from None
    total = body_s + CARD_S
    return {"props": p.model_dump(exclude_none=True), "fps": FPS,
            "durationInFrames": round(total * FPS), "coverFrame": round(COVER_S * FPS),
            "events": recipe.recipe_timeline(rec, total)}


def flap_cues(timings: Sequence[LineTiming], step_s: float = 0.12) -> List[Dict[str, Any]]:
    """Mouth cues without audio: open / half / closed shapes while each line is read."""
    cues, shapes = [], "DCBC"
    for t in timings:
        n = max(1, int((t.end_s - t.start_s) / step_s))
        cues += [{"start": round(t.start_s + i * step_s, 3),
                  "end": round(t.start_s + (i + 1) * step_s, 3), "value": shapes[i % 4]}
                 for i in range(n)]
        cues.append({"start": round(t.end_s, 3), "end": round(t.end_s + 0.1, 3), "value": "X"})
    return cues


def cameras(p: Props, timings: Sequence[LineTiming]) -> List[Dict[str, Any]]:
    """A cut at each line's start (Blender frames, 1-based); `auto` alternates close / wide."""
    order = ["close", "wide"] if p.shots == "auto" else [p.shots]
    out = []
    for i, t in enumerate(timings):
        frame = 1 if i == 0 else 1 + round(t.start_s * BLENDER_FPS)
        out.append({**CAMERAS[order[i % len(order)]], "frame": frame})
    return out


def _require(path: Path) -> Path:
    if not path.is_file():
        raise CinematicError(f"{path.name} missing in {TOOLS}: run python cinematic/setup.py")
    return path


def find_blender() -> str:
    return str(_require(BLENDER))


def _run(cmd: Sequence[Any], what: str, timeout_s: float) -> None:
    try:
        done = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise CinematicError(f"{what} ran past {timeout_s:g} s") from None
    if done.returncode != 0:
        raise CinematicError(f"{what} failed: {(done.stderr or done.stdout).strip()[-TAIL_CHARS:]}")


def mouth_cues(audio: Optional[Path], timings: Sequence[LineTiming], work: Path,
               timeout_s: float) -> List[Dict[str, Any]]:
    """Rhubarb cues for the voice (phonetic recognizer: works for French too), or flaps."""
    if audio is None:
        return flap_cues(timings)
    wav, out = work / "voice.wav", work / "mouth.json"
    ffmpeg.run(["-i", audio, "-ac", "1", "-ar", "16000", wav], timeout_s=timeout_s)
    _run([_require(RHUBARB), "-q", "-r", "phonetic", "-f", "json", "-o", out, wav],
         "Rhubarb", timeout_s)
    return json.loads(out.read_text(encoding="utf-8"))["mouthCues"]


def _blender(p: Props, timings: Sequence[LineTiming], cues: List[Dict[str, Any]],
             frames: int, out: Path, stills: Optional[List[int]] = None) -> None:
    cfg = {"out": str(out), "fps": BLENDER_FPS, "frames": frames, "size": list(RENDER_SIZE),
           "cues": cues, "character": CAST[p.character], "cameras": cameras(p, timings),
           "stills": stills}
    cfg_path = out / "shot.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    n = len(stills) if stills else frames
    blender = find_blender()
    with gpu_lock.hold("Blender render", get_settings().gpu_lock_path):  # step 145
        _run([blender, "-b", "-P", ROOT / "engine" / "shot.py", "--", cfg_path],
             "Blender", 120 + n * S_PER_FRAME)


def _voice_path(p: Props, media_root: PathLike) -> Optional[Path]:
    src = p.voice.audioSrc if p.voice else None
    if not src:
        return None
    path = media.resolve(media_root, src)
    if not path.is_file():
        raise ValueError(f"voice audio {src!r} is missing")
    return path


def render_asset(props: Dict[str, Any], out: PathLike, media_root: PathLike, *,
                 timeout_s: float, end_card: Optional[recipe.CardRenderer] = None
                 ) -> Tuple[MediaInfo, int, List[Dict[str, Any]]]:
    """Render the master to `out` (same return as motion.render_motion_asset)."""
    out = Path(out)
    p = Props.model_validate(validate(props)["props"])
    timings, body_s, rec = _plan(p)
    audio = _voice_path(p, media_root)
    frames = math.ceil(body_s * BLENDER_FPS)
    with tempfile.TemporaryDirectory(prefix="cinematic-", dir=out.parent) as tmp:
        work = Path(tmp)
        _blender(p, timings, mouth_cues(audio, timings, work, timeout_s), frames, work)
        raw = work / "raw.mp4"
        sound = (["-i", audio] if audio else
                 ["-f", "lavfi", "-i", f"anullsrc=r={recipe.SAMPLE_RATE}:cl=stereo"])
        ffmpeg.run(["-framerate", BLENDER_FPS, "-i", work / "frames" / "f_%04d.png", *sound,
                    "-filter_complex", f"[0:v]{GRADE}[v]", "-map", "[v]", "-map", "1:a",
                    "-af", f"apad,atrim=0:{frames / BLENDER_FPS:.3f}", "-t",
                    f"{frames / BLENDER_FPS:.3f}", "-c:v", "libx264", "-crf", "17",
                    "-c:a", "aac", "-b:a", "192k", raw], timeout_s=timeout_s)
        inputs = {"source": raw, **({"music": AUDIO / f"{p.music}.wav"} if p.music != "none" else {})}
        info = recipe.render(rec, inputs, out, timeout_s=timeout_s, end_card=end_card)
    return info, round(COVER_S * 1000), recipe.recipe_timeline(rec, info.duration)


def preview_stills(props: Dict[str, Any], media_root: PathLike,
                   frames: Optional[Sequence[int]], key: Callable[[Any], str]) -> List[str]:
    """Like motion.preview_stills: PNG stills (output frames, default cover + three spread)
    into `<media root>/previews/<key>/`. The 3D picture only: hook, captions and end card are
    drawn by the full render. ponytail: one Blender scene build per call (~40 s)."""
    v = validate(props)
    last = v["durationInFrames"] - 1
    if frames is None:
        frames = [v["coverFrame"], last // 3, 2 * last // 3, last]
    if any(not 0 <= f <= last for f in frames):
        raise ValueError(f"frames must lie in 0..{last}")
    p = Props.model_validate(v["props"])
    timings, body_s, _ = _plan(p)
    n = math.ceil(body_s * BLENDER_FPS)
    to_blender = {f: min(n, 1 + round(f / FPS * BLENDER_FPS)) for f in dict.fromkeys(frames)}
    folder = Path(media_root) / "previews" / key([TEMPLATE, v["props"]])
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        work = Path(tmp)
        _blender(p, timings, flap_cues(timings), n, work, sorted(set(to_blender.values())))
        paths = []
        for f, b in to_blender.items():
            dest = folder / f"frame-{f}.png"
            shutil.copyfile(work / f"still_{b}.png", dest)
            paths.append(media.relative(media_root, dest))
    return paths
