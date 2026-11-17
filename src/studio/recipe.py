"""
Recipes: an ordered, JSON-serialisable list of edit ops stored on the asset
(`assets.recipe`), and `render()` which runs them with ffmpeg (GOAL.md §3.1, §4.1).

An op is a pydantic model with a unique `op` name and an `apply()` method, added to the
registry with `@register`. Later steps plug in their ops the same way (audio, overlays,
captions). Never register a detection-evasion op (GOAL.md §5.1: no mirror/flip, speed or
pitch changes): a test guards the registry.

Every op writes a file in the output spec below, so the same recipe always gives the
same output spec. Audio ops copy the video stream as it is (no re-encode) and only
rewrite the sound; render() then brings every output to the same loudness.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Sequence, Type

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, field_validator

from src.studio import ffmpeg
from src.studio.ffmpeg import MediaInfo, PathLike

# Output spec (Instagram Reels): one place for every op.
WIDTH, HEIGHT, FPS = 1080, 1920, 30
SAMPLE_RATE = 48000
VIDEO_ARGS = ("-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS))
AUDIO_ARGS = ("-c:a", "aac", "-b:a", "128k", "-ar", str(SAMPLE_RATE), "-ac", "2")
CONTAINER_ARGS = ("-movflags", "+faststart")
# Final loudness of every render (EBU R128 integrated / true peak / range).
LOUDNESS_I, LOUDNESS_TP, LOUDNESS_LRA = -14.0, -1.5, 11.0
LOUDNORM = f"loudnorm=I={LOUDNESS_I}:TP={LOUDNESS_TP}:LRA={LOUDNESS_LRA}"
AUDIO_FORMAT = f"aresample={SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"

DEFAULT_TIMEOUT_S = 600.0  # per op
DEFAULT_PRESET = "medium"  # tests pass "ultrafast"


class Op(BaseModel):
    """Base of every op. Subclasses set `op: Literal["<name>"]` and implement apply()."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    op: str

    def apply(self, src: Path, info: MediaInfo, out: Path, *, inputs: Mapping[str, Path],
              timeout_s: float, preset: str) -> None:
        raise NotImplementedError


OPS: Dict[str, Type[Op]] = {}


def register(cls: Type[Op]) -> Type[Op]:
    """Class decorator: add an op to the registry under its `op` literal."""
    name = cls.model_fields["op"].default
    if name in OPS:
        raise ValueError(f"op {name!r} is already registered")
    OPS[name] = cls
    return cls


class Recipe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    ops: List[SerializeAsAny[Op]] = Field(min_length=1)

    @field_validator("ops", mode="before")
    @classmethod
    def _resolve_ops(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value  # pydantic reports the type error
        resolved = []
        for item in value:
            if isinstance(item, Op):
                resolved.append(item)
                continue
            name = item.get("op") if isinstance(item, dict) else None
            if name not in OPS:
                raise ValueError(f"unknown op {name!r}; registered ops: {', '.join(sorted(OPS))}")
            resolved.append(OPS[name].model_validate(item))
        return resolved


def encode(src: Path, info: MediaInfo, out: Path, *, filter_complex: str, timeout_s: float,
           preset: str) -> None:
    """Encode `src` through `filter_complex` (input [0:v], output [v]) into the output spec.
    The source's first audio track is re-encoded; a source without audio gets silence."""
    args: List[PathLike] = ["-i", src]
    if info.has_audio:
        audio_map = "0:a:0"
    else:
        args += ["-f", "lavfi", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo", "-shortest"]
        audio_map = "1:a:0"
    args += ["-filter_complex", filter_complex, "-map", "[v]", "-map", audio_map,
             *VIDEO_ARGS, "-preset", preset, *AUDIO_ARGS, *CONTAINER_ARGS, out]
    ffmpeg.run(args, timeout_s=timeout_s)


@register
class FitVertical(Op):
    """Make any clip 1080x1920. blur: the whole frame over a blurred, filled copy of
    itself; crop: fill the frame and cut the overflow from the centre."""

    op: Literal["fit_vertical"] = "fit_vertical"
    mode: Literal["blur", "crop"] = "blur"

    def apply(self, src, info, out, *, inputs, timeout_s, preset):
        fill = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={WIDTH}:{HEIGHT}")
        tail = f"setsar=1,fps={FPS},format=yuv420p[v]"
        if self.mode == "crop":
            graph = f"[0:v]{fill},{tail}"
        else:
            # Blur a quarter-size background, then scale it up: same look, far cheaper.
            graph = (
                f"[0:v]split[a][b];"
                f"[a]scale={WIDTH // 4}:{HEIGHT // 4}:force_original_aspect_ratio=increase,"
                f"crop={WIDTH // 4}:{HEIGHT // 4},boxblur=10:2,scale={WIDTH}:{HEIGHT}[bg];"
                f"[b]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{tail}"
            )
        encode(src, info, out, filter_complex=graph, timeout_s=timeout_s, preset=preset)


def _fit(duration: float) -> str:
    """Filter chain: pad with silence or cut to exactly `duration` seconds."""
    return f"apad=whole_dur={duration},atrim=end={duration}"


def _source_audio(info: MediaInfo) -> str:
    """Filter chain for the source's audio (silence if it has none) at the video's length."""
    head = "[0:a:0]" if info.has_audio else f"anullsrc=r={SAMPLE_RATE}:cl=stereo,"
    return f"{head}{AUDIO_FORMAT},{_fit(info.duration)}"


def _input_audio(index: int, info: MediaInfo, gain_db: float) -> str:
    """Filter chain for input `index`'s audio at `gain_db`, padded/cut to the video length."""
    return f"[{index}:a:0]{AUDIO_FORMAT},volume={gain_db}dB,{_fit(info.duration)}"


def remix_audio(src: Path, out: Path, *, filter_complex: str, timeout_s: float,
                extra_inputs: Sequence[PathLike] = ()) -> None:
    """Copy the video of `src` untouched and replace its audio with the [a] output of
    `filter_complex`. `extra_inputs` are the input args for inputs 1, 2, ..."""
    ffmpeg.run(["-i", src, *extra_inputs, "-filter_complex", filter_complex,
                "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", *AUDIO_ARGS, *CONTAINER_ARGS,
                out], timeout_s=timeout_s)


@register
class MuteOriginal(Op):
    """Replace the audio with silence of the same length (third-party music, GOAL.md §5.1)."""

    op: Literal["mute_original"] = "mute_original"

    def apply(self, src, info, out, *, inputs, timeout_s, preset):
        graph = f"anullsrc=r={SAMPLE_RATE}:cl=stereo,{AUDIO_FORMAT},{_fit(info.duration)}[a]"
        remix_audio(src, out, filter_complex=graph, timeout_s=timeout_s)


@register
class VoiceOver(Op):
    """Mix a voice track over the clip and duck the original by `duck_db` while it speaks.
    A voice shorter than the video is fine; a longer one is cut at the video's end."""

    op: Literal["voice_over"] = "voice_over"
    input: str = "voice"
    gain_db: float = Field(0.0, ge=-30, le=30)
    duck_db: float = Field(-12.0, ge=-60, le=0)

    def apply(self, src, info, out, *, inputs, timeout_s, preset):
        floor = 10 ** (self.duck_db / 20)
        # The original is split into a fixed part at the duck level plus the rest; a
        # compressor keyed by the voice squashes only the rest. So under the voice the
        # original sits at about duck_db, and elsewhere it is untouched.
        graph = (
            f"{_input_audio(1, info, self.gain_db)},asplit[key][voice];"
            f"{_source_audio(info)},asplit[o1][o2];"
            f"[o1]volume={floor:.6f}[floor];[o2]volume={1 - floor:.6f}[rest];"
            f"[rest][key]sidechaincompress=threshold=0.001:ratio=20:attack=5:release=250"
            f"[ducked];[floor][ducked][voice]amix=inputs=3:normalize=0[a]"
        )
        remix_audio(src, out, filter_complex=graph, timeout_s=timeout_s,
                    extra_inputs=["-i", inputs[self.input]])


@register
class Music(Op):
    """Mix a music bed at `level_db` under the existing audio, looped (or padded with
    silence when loop=False) and cut to the video's length."""

    op: Literal["music"] = "music"
    input: str = "music"
    level_db: float = Field(-20.0, ge=-60, le=0)
    loop: bool = True

    def apply(self, src, info, out, *, inputs, timeout_s, preset):
        graph = (f"{_input_audio(1, info, self.level_db)}[m];{_source_audio(info)}[o];"
                 f"[o][m]amix=inputs=2:normalize=0[a]")
        loop = ["-stream_loop", "-1"] if self.loop else []
        remix_audio(src, out, filter_complex=graph, timeout_s=timeout_s,
                    extra_inputs=[*loop, "-i", inputs[self.input]])


def normalize_loudness(src: Path, out: Path, *, timeout_s: float, log_path: Path) -> None:
    """Two-pass loudnorm to LOUDNESS_*: measure, then apply with the measured values
    (linear gain when the true-peak target allows it). The video is copied. Digital
    silence (integrated loudness -inf) passes through unchanged."""
    ffmpeg.run(["-i", src, "-map", "0:a:0", "-af", f"{LOUDNORM}:print_format=json",
                "-f", "null", "-"], timeout_s=timeout_s, log_path=log_path)
    text = log_path.read_text(encoding="utf-8")
    m = json.loads(text[text.rindex("{"):text.rindex("}") + 1])
    if math.isfinite(float(m["input_i"])):
        af = (f"{LOUDNORM}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
              f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
              f":offset={m['target_offset']}:linear=true")
    else:
        af = "anull"
    ffmpeg.run(["-i", src, "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", af,
                *AUDIO_ARGS, *CONTAINER_ARGS, out], timeout_s=timeout_s)


def render(recipe: Recipe, inputs: Mapping[str, PathLike], out: PathLike, *,
           timeout_s: float = DEFAULT_TIMEOUT_S, preset: str = DEFAULT_PRESET) -> MediaInfo:
    """Run `recipe` on `inputs["source"]` and write `out`. Other named inputs (music,
    voice-over, logo) are for the ops that use them. Every output gets a final loudness
    pass (LOUDNESS_*). Returns the output's MediaInfo. `timeout_s` applies to each
    ffmpeg run."""
    paths = {k: Path(v) for k, v in inputs.items()}
    if "source" not in paths:
        raise ValueError("inputs must contain 'source'")
    missing = sorted({op.input for op in recipe.ops
                      if getattr(op, "input", None) and op.input not in paths})
    if missing:
        raise ValueError(f"recipe needs input(s) {', '.join(missing)}; "
                         f"got {', '.join(sorted(paths))}")
    out = Path(out)
    # ponytail: one temp file per op (simple, debuggable); fuse into a single filtergraph
    # if render time matters.
    with tempfile.TemporaryDirectory(prefix="render-", dir=out.parent) as work:
        current = paths["source"]
        for i, op in enumerate(recipe.ops):
            nxt = Path(work) / f"{i:02d}-{op.op}.mp4"
            op.apply(current, ffmpeg.probe(current), nxt, inputs=paths, timeout_s=timeout_s,
                     preset=preset)
            current = nxt
        loud = Path(work) / "loudnorm.mp4"
        normalize_loudness(current, loud, timeout_s=timeout_s,
                           log_path=Path(work) / "loudnorm.log")
        os.replace(loud, out)
    return ffmpeg.probe(out)
