"""
Recipes: an ordered, JSON-serialisable list of edit ops stored on the asset
(`assets.recipe`), and `render()` which runs them with ffmpeg (GOAL.md §3.1, §4.1).

An op is a pydantic model with a unique `op` name and an `apply()` method, added to the
registry with `@register`. Later steps plug in their ops the same way (audio, overlays,
captions). Never register a detection-evasion op (GOAL.md §5.1: no mirror/flip, speed or
pitch changes): a test guards the registry.

Every op writes a file in the output spec below, so the same recipe always gives the
same output spec.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Literal, Mapping, Type

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, field_validator

from src.studio import ffmpeg
from src.studio.ffmpeg import MediaInfo, PathLike

# Output spec (Instagram Reels): one place for every op.
WIDTH, HEIGHT, FPS = 1080, 1920, 30
SAMPLE_RATE = 48000
VIDEO_ARGS = ("-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS))
AUDIO_ARGS = ("-c:a", "aac", "-b:a", "128k", "-ar", str(SAMPLE_RATE), "-ac", "2")
CONTAINER_ARGS = ("-movflags", "+faststart")

DEFAULT_TIMEOUT_S = 600.0  # per op
DEFAULT_PRESET = "medium"  # tests pass "ultrafast"


class Op(BaseModel):
    """Base of every op. Subclasses set `op: Literal["<name>"]` and implement apply()."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: ClassVar[str]

    def apply(self, src: Path, info: MediaInfo, out: Path, *, inputs: Mapping[str, Path],
              timeout_s: float, preset: str) -> None:
        raise NotImplementedError


OPS: Dict[str, Type[Op]] = {}


def register(cls: Type[Op]) -> Type[Op]:
    """Class decorator: add an op to the registry under its `op` literal."""
    name = cls.model_fields["op"].default
    if name in OPS:
        raise ValueError(f"op {name!r} is already registered")
    cls.name = name
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


def render(recipe: Recipe, inputs: Mapping[str, PathLike], out: PathLike, *,
           timeout_s: float = DEFAULT_TIMEOUT_S, preset: str = DEFAULT_PRESET) -> MediaInfo:
    """Run `recipe` on `inputs["source"]` and write `out`. Other named inputs (music,
    voice-over, logo) are for the ops that use them. Returns the output's MediaInfo.
    `timeout_s` applies to each op's ffmpeg run."""
    paths = {k: Path(v) for k, v in inputs.items()}
    if "source" not in paths:
        raise ValueError("inputs must contain 'source'")
    out = Path(out)
    # ponytail: one temp file per op (simple, debuggable); fuse into a single filtergraph
    # if render time matters.
    with tempfile.TemporaryDirectory(prefix="render-", dir=out.parent) as work:
        current = paths["source"]
        for i, op in enumerate(recipe.ops):
            nxt = Path(work) / f"{i:02d}-{op.name}.mp4"
            op.apply(current, ffmpeg.probe(current), nxt, inputs=paths, timeout_s=timeout_s,
                     preset=preset)
            current = nxt
        os.replace(current, out)
    return ffmpeg.probe(out)
