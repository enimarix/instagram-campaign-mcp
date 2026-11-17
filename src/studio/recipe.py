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
import re
import tempfile
import textwrap
import unicodedata
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple, Type

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializeAsAny,
    StringConstraints,
    field_validator,
    model_validator,
)

from src.studio import brand, ffmpeg
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

# End of every video filtergraph: square pixels, output frame rate and pixel format.
VIDEO_TAIL = f"setsar=1,fps={FPS},format=yuv420p[v]"

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
           preset: str, extra_inputs: Sequence[PathLike] = (), extend_s: float = 0.0,
           audio: Optional[str] = None) -> None:
    """Encode `src` through `filter_complex` (input [0:v], output [v]) into the output spec.
    `extra_inputs` are files for inputs 1, 2, ... The source's first audio track (silence
    if it has none) is re-encoded at exactly the source's length plus `extend_s` seconds
    of silence (for an op that makes the video longer): no AAC padding creeps in per op.
    `audio` replaces that with an unlabelled filter chain of the op's own (output -> [a])."""
    # ponytail: `apad` + `-shortest` would follow the video by itself, but -shortest never
    # ends an infinite pad inside -filter_complex (ffmpeg 7.1 hangs), so the length is explicit.
    args: List[PathLike] = ["-i", src]
    for path in extra_inputs:
        args += ["-i", path]
    audio = audio or _source_audio(info, info.duration + extend_s)
    args += ["-filter_complex", f"{filter_complex};{audio}[a]", "-map", "[v]", "-map", "[a]",
             *VIDEO_ARGS, "-preset", preset, *AUDIO_ARGS, *CONTAINER_ARGS, out]
    ffmpeg.run(args, timeout_s=timeout_s)


def _cover(width: int, height: int) -> str:
    """Filter chain: fill a width x height box and cut the overflow from the centre."""
    return (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}")


@register
class FitVertical(Op):
    """Make any clip 1080x1920. blur: the whole frame over a blurred, filled copy of
    itself; crop: fill the frame and cut the overflow from the centre."""

    op: Literal["fit_vertical"] = "fit_vertical"
    mode: Literal["blur", "crop"] = "blur"

    def apply(self, src, info, out, *, inputs, timeout_s, preset):
        if self.mode == "crop":
            graph = f"[0:v]{_cover(WIDTH, HEIGHT)},{VIDEO_TAIL}"
        else:
            # Blur a quarter-size background, then scale it up: same look, far cheaper.
            graph = (
                f"[0:v]split[a][b];"
                f"[a]scale={WIDTH // 4}:{HEIGHT // 4}:force_original_aspect_ratio=increase,"
                f"crop={WIDTH // 4}:{HEIGHT // 4},boxblur=10:2,scale={WIDTH}:{HEIGHT}[bg];"
                f"[b]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{VIDEO_TAIL}"
            )
        encode(src, info, out, filter_complex=graph, timeout_s=timeout_s, preset=preset)


def _fit(duration: float) -> str:
    """Filter chain: pad with silence or cut to exactly `duration` seconds."""
    return f"apad=whole_dur={duration},atrim=end={duration}"


def _source_audio(info: MediaInfo, duration: Optional[float] = None) -> str:
    """Filter chain for the source's audio (silence if it has none) at `duration` seconds,
    by default the video's length."""
    head = "[0:a:0]" if info.has_audio else f"anullsrc=r={SAMPLE_RATE}:cl=stereo,"
    return f"{head}{AUDIO_FORMAT},{_fit(info.duration if duration is None else duration)}"


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


# --- Brand overlays (GOAL.md §3.1 Track A steps 5-6, §5.1 credit). Styled from the brand
# kit, every overlay inside its safe area. They add to the picture; they never move it.

Corner = Literal["top_left", "top_right", "bottom_left", "bottom_right"]
MAX_TEXT = 60  # characters, hook and credit
TEXT_PAD = 16  # px of background box around text
OverlayText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                               max_length=MAX_TEXT)]


def _brand_kit(info: MediaInfo) -> Tuple[Dict[str, Any], Path]:
    """The brand kit and its folder; refuses a clip that is not in the output spec yet
    (the safe area is in output pixels)."""
    if (info.width, info.height) != (WIDTH, HEIGHT):
        raise ValueError(f"brand overlays need a {WIDTH}x{HEIGHT} clip, got "
                         f"{info.width}x{info.height}: put fit_vertical first")
    return brand.load_brand(), brand.DEFAULT_PATH.parent


def _filter_value(value: str) -> str:
    """Escape a value for a filter option inside -filter_complex: first for the option
    parser, then for the filtergraph parser (ffmpeg-filters, "Notes on filtergraph
    escaping"). Windows paths need it for the drive colon."""
    value = re.sub(r"([\\':])", r"\\\1", value)
    return re.sub(r"([\\'\[\],;])", r"\\\1", value)


def _brand_font(kit: Dict[str, Any], root: Path) -> Path:
    """The brand font file (fonts.files[0])."""
    if not kit["fonts"].get("files"):
        raise ValueError("the brand kit has no font file (fonts.files)")
    return (root / kit["fonts"]["files"][0]).resolve()


def _wrap_width(width: int, size: int) -> int:
    """Characters per line in `width` px less the box padding. Press Start 2P is
    monospaced with a 1 em advance (`size` px per character)."""
    return (width - 2 * TEXT_PAD) // size


def _drawtext(text: str, info: MediaInfo, out: Path, *, size: int, x: str, y: str,
              enable: str = "") -> str:
    """A drawtext filter: `text` wrapped to the safe width in the brand font and text
    colour on a semi-transparent background box. `x`/`y` pick from "left", "right",
    "center" / "top", "center", "bottom" inside the safe area."""
    kit, root = _brand_kit(info)
    sx, sy, sw, sh = brand.safe_area(kit)
    lines = textwrap.wrap(text, _wrap_width(sw, size))
    textfile = out.with_suffix(".txt")  # in render()'s work dir; no drawtext text escaping
    textfile.write_text("\n".join(lines), encoding="utf-8")
    xs = {"left": f"{sx + TEXT_PAD}", "right": f"{sx + sw - TEXT_PAD}-text_w",
          "center": f"{sx}+({sw}-text_w)/2"}
    ys = {"top": f"{sy + TEXT_PAD}", "bottom": f"{sy + sh - TEXT_PAD}-text_h",
          "center": f"{sy}+({sh}-text_h)/2"}
    colors = kit["colors"]
    graph = (f"drawtext=fontfile={_filter_value(_brand_font(kit, root).as_posix())}"
             f":textfile={_filter_value(textfile.resolve().as_posix())}:expansion=none"
             f":fontsize={size}:line_spacing={-size // 4}:fontcolor=0x{colors['text'][1:]}"
             f":box=1:boxcolor=0x{colors['background'][1:]}@0.6:boxborderw={TEXT_PAD}"
             f":x={xs[x]}:y={ys[y]}")
    return graph + (f":enable={_filter_value(enable)}" if enable else "")


@register
class Logo(Op):
    """The brand logo (brand kit `logo_png`) as a watermark in a corner of the safe area,
    `scale` = logo width as a fraction of the frame width."""

    op: Literal["logo"] = "logo"
    position: Corner = "bottom_right"
    opacity: float = Field(0.8, ge=0, le=1)
    scale: float = Field(0.12, gt=0, le=0.5)

    def apply(self, src, info, out, *, inputs, timeout_s, preset):
        kit, root = _brand_kit(info)
        sx, sy, sw, sh = brand.safe_area(kit)
        x = f"{sx}" if self.position.endswith("left") else f"{sx + sw}-w"
        y = f"{sy}" if self.position.startswith("top") else f"{sy + sh}-h"
        width = max(2, round(WIDTH * self.scale / 2) * 2)
        graph = (f"[1:v]scale={width}:-2,format=rgba,colorchannelmixer=aa={self.opacity}[logo];"
                 f"[0:v][logo]overlay={x}:{y},{VIDEO_TAIL}")
        encode(src, info, out, filter_complex=graph, timeout_s=timeout_s, preset=preset,
               extra_inputs=[root / kit["logo_png"]])


@register
class HookText(Op):
    """The hook as a title card from `start_s` to `end_s`, readable with the sound off.
    The text keeps its case (the pixel font draws accented capitals small)."""

    op: Literal["hook_text"] = "hook_text"
    text: OverlayText
    start_s: float = Field(0.0, ge=0)
    end_s: float = Field(3.0, gt=0)
    position: Literal["top", "center"] = "top"

    @model_validator(mode="after")
    def _window(self) -> "HookText":
        if self.end_s <= self.start_s:
            raise ValueError("end_s must be after start_s")
        return self

    def apply(self, src, info, out, *, inputs, timeout_s, preset):
        text = _drawtext(self.text, info, out, size=48, x="center", y=self.position,
                         enable=f"between(t,{self.start_s},{self.end_s})")
        encode(src, info, out, filter_complex=f"[0:v]{text},{VIDEO_TAIL}",
               timeout_s=timeout_s, preset=preset)


@register
class Credit(Op):
    """A visible source credit for the whole video, e.g. "@creator" or "Clip: Name /
    Pexels" (GOAL.md §5.1), at the bottom of the safe area. The pixel font has no emoji."""

    op: Literal["credit"] = "credit"
    text: OverlayText
    position: Literal["bottom_left", "bottom_right"] = "bottom_left"

    def apply(self, src, info, out, *, inputs, timeout_s, preset):
        text = _drawtext(self.text, info, out, size=24, x=self.position.removeprefix("bottom_"),
                         y="bottom")
        encode(src, info, out, filter_complex=f"[0:v]{text},{VIDEO_TAIL}",
               timeout_s=timeout_s, preset=preset)


MAX_CAPTION = 80  # characters per caption line


def _strip_emoji(text: str) -> str:
    """Drop emoji and pictographs: the pixel font has none, and a fallback emoji font is
    not on every machine (CI has none), so they would render as boxes or not at all.
    Letters the font lacks (e.g. Romanian Ș) still fall back to a system font."""
    # ponytail: Unicode-category heuristic, not the font's real cmap; read the cmap if a
    # symbol the font does have (e.g. ™) ever needs to survive.
    return "".join(c for c in text if not (
        ord(c) >= 0x1F000 or c in "\u200d\u20e3\ufe0e\ufe0f"
        or (ord(c) > 0xFF and unicodedata.category(c) == "So")))


def _ass_text(text: str) -> str:
    """User text as literal ASS text: braces can't open an override block ({\\b1} etc.),
    and a word joiner after each backslash keeps "\\N" / "\\h" literal."""
    text = text.replace("\\", "\\\u2060")
    return text.replace("{", "\\{").replace("}", "\\}")


def _ass_time(seconds: float) -> str:
    cs = round(seconds * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _ass_color(hex_color: str, opacity: float = 1.0) -> str:
    """#RRGGBB -> ASS &HAABBGGRR (alpha 00 = opaque)."""
    r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    return f"&H{round(255 * (1 - opacity)):02X}{b}{g}{r}".upper()


class CaptionLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    text: str

    @field_validator("text")
    @classmethod
    def _clean(cls, value: str) -> str:
        value = " ".join(_strip_emoji(value).split())
        if not value:
            raise ValueError("text is empty (emoji are removed)")
        if len(value) > MAX_CAPTION:
            raise ValueError(f"text must be at most {MAX_CAPTION} characters")
        return value

    @model_validator(mode="after")
    def _window(self) -> "CaptionLine":
        if self.end_s <= self.start_s:
            raise ValueError("end_s must be after start_s")
        return self


@register
class Captions(Op):
    """Timed caption lines burned in with libass in the brand font and text colour on a
    semi-transparent box, wrapped to the safe width. bottom: just above the bottom safe
    inset; center: the middle of the safe area. Emoji are dropped (see _strip_emoji)."""

    op: Literal["captions"] = "captions"
    lines: List[CaptionLine] = Field(min_length=1)
    position: Literal["bottom", "center"] = "bottom"
    size: int = Field(40, ge=24, le=64)

    @field_validator("lines")
    @classmethod
    def _sorted(cls, lines: List[CaptionLine]) -> List[CaptionLine]:
        for a, b in zip(lines, lines[1:]):
            if b.start_s < a.end_s:
                raise ValueError("lines must be sorted by start_s and must not overlap")
        return lines

    def apply(self, src, info, out, *, inputs, timeout_s, preset):
        kit, root = _brand_kit(info)
        font = _brand_font(kit, root)
        sx, sy, sw, sh = brand.safe_area(kit)
        if self.position == "bottom":
            anchor = f"\\an2\\pos({sx + sw // 2},{sy + sh - TEXT_PAD})"
        else:
            anchor = f"\\an5\\pos({sx + sw // 2},{sy + sh // 2})"
        text, box = _ass_color(kit["colors"]["text"]), _ass_color(kit["colors"]["background"], 0.6)
        # WrapStyle 2: no libass wrapping, the lines are wrapped here. BorderStyle 3: an
        # opaque box (OutlineColour) padded by Outline px around each line.
        width = _wrap_width(sw, self.size)
        events = [
            f"Dialogue: 0,{_ass_time(line.start_s)},{_ass_time(line.end_s)},Brand,,0,0,0,,"
            f"{{{anchor}}}" + "\\N".join(_ass_text(t) for t in textwrap.wrap(line.text, width))
            for line in self.lines
        ]
        ass = out.with_suffix(".ass")  # in render()'s work dir
        ass.write_text("\n".join([
            "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {WIDTH}", f"PlayResY: {HEIGHT}",
            "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Brand,{kit['fonts']['display']},{self.size},{text},{text},{box},{box},"
            f"0,0,0,0,100,100,0,0,3,{TEXT_PAD},0,2,0,0,0,1", "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events, ""]), encoding="utf-8")
        graph = (f"[0:v]ass=filename={_filter_value(ass.resolve().as_posix())}"
                 f":fontsdir={_filter_value(font.parent.as_posix())},{VIDEO_TAIL}")
        encode(src, info, out, filter_complex=graph, timeout_s=timeout_s, preset=preset)


@register
class EndCard(Op):
    """A call-to-action card appended after the clip: the brand background, `text` in the
    middle of the safe area and (with_logo) the logo at its top. The video gets
    `duration_s` longer and the audio goes on under the card as silence; to run a music
    bed under the card too, put `music` after `end_card` in the recipe."""

    op: Literal["end_card"] = "end_card"
    text: OverlayText
    duration_s: float = Field(2.0, ge=1, le=4)
    with_logo: bool = True

    def apply(self, src, info, out, *, inputs, timeout_s, preset):
        kit, root = _brand_kit(info)
        _, sy, _, _ = brand.safe_area(kit)
        text = _drawtext(self.text, info, out, size=48, x="center", y="center")
        card = (f"color=c=0x{kit['colors']['background'][1:]}:s={WIDTH}x{HEIGHT}:r={FPS}"
                f":d={self.duration_s},{text}")
        extra: List[PathLike] = []
        if self.with_logo:
            width = round(WIDTH * 0.24 / 2) * 2
            card += f"[bg];[1:v]scale={width}:-2[logo];[bg][logo]overlay=(W-w)/2:{sy}"
            extra = [root / kit["logo_png"]]
        graph = (f"[0:v]setsar=1,fps={FPS},format=yuv420p[clip];"
                 f"{card},setsar=1,format=yuv420p[card];"
                 f"[clip][card]concat=n=2:v=1:a=0,{VIDEO_TAIL}")
        encode(src, info, out, filter_complex=graph, timeout_s=timeout_s, preset=preset,
               extra_inputs=extra, extend_s=self.duration_s)


@register
class ReactionCollage(Op):
    """The clip (the source) and the owner's reaction video (`inputs[reaction_input]`) in
    one frame. split: the clip on top (`split_ratio` of the height), the reaction below.
    pip: the clip fills the frame, the reaction sits in a 9:16 box `pip_scale` of the frame
    width in a corner of the safe area. Each part is scaled to cover its box and cut from
    the centre: fitting a layout, not a detection-evasion edit (no mirror, flip, speed or
    pitch change, GOAL.md §5.1).

    The reaction starts `offset_s` after the clip (negative: its first -offset_s seconds
    are skipped). Its first frame holds until it starts and its last frame after it ends;
    it is cut at the clip's end, so the output is as long as the clip. Audio: the clip at
    `clip_gain_db` (ducked under the reaction by default) mixed with the reaction's mic at
    `reaction_gain_db`; render() normalises the loudness afterwards."""

    op: Literal["reaction_collage"] = "reaction_collage"
    layout: Literal["split", "pip"]
    reaction_input: str = "reaction"
    offset_s: float = Field(0.0, ge=-3600, le=3600)
    split_ratio: float = Field(0.5, ge=0.4, le=0.7)
    pip_corner: Corner = "bottom_right"
    pip_scale: float = Field(0.3, ge=0.15, le=0.5)  # 0.5: 540x960 still fits the safe area
    reaction_gain_db: float = Field(0.0, ge=-30, le=30)
    clip_gain_db: float = Field(-6.0, ge=-60, le=0)

    def apply(self, src, info, out, *, inputs, timeout_s, preset):
        reaction, length = inputs[self.reaction_input], info.duration
        skip, delay = max(-self.offset_s, 0.0), max(self.offset_s, 0.0)
        if self.layout == "split":
            top = round(HEIGHT * self.split_ratio / 2) * 2
            clip, (rw, rh) = _cover(WIDTH, top), (WIDTH, HEIGHT - top)
            join = "vstack"
        else:
            sx, sy, sw, sh = brand.safe_area(brand.load_brand())
            rw = round(WIDTH * self.pip_scale / 2) * 2
            rh = round(rw * 16 / 9 / 2) * 2
            x = sx if self.pip_corner.endswith("left") else sx + sw - rw
            y = sy if self.pip_corner.startswith("top") else sy + sh - rh
            clip, join = _cover(WIDTH, HEIGHT), f"overlay={x}:{y}"
        graph = (f"[0:v]fps={FPS},{clip},setsar=1,format=yuv420p[clip];"
                 f"[1:v]trim=start={skip},setpts=PTS-STARTPTS,fps={FPS},{_cover(rw, rh)},"
                 f"setsar=1,format=yuv420p,tpad=start_duration={delay}:start_mode=clone"
                 f":stop_mode=clone:stop_duration={length},trim=duration={length}[re];"
                 f"[clip][re]{join},{VIDEO_TAIL}")
        audio = f"{_source_audio(info)},volume={self.clip_gain_db}dB"
        if ffmpeg.probe(reaction).has_audio:
            audio = (f"{audio}[ca];[1:a:0]atrim=start={skip},asetpts=PTS-STARTPTS,"
                     f"{AUDIO_FORMAT},adelay={round(delay * 1000)}:all=1,"
                     f"volume={self.reaction_gain_db}dB,{_fit(length)}[ra];"
                     f"[ca][ra]amix=inputs=2:normalize=0")
        encode(src, info, out, filter_complex=graph, timeout_s=timeout_s, preset=preset,
               extra_inputs=[reaction], audio=audio)


def normalize_loudness(src: Path, out: Path, *, timeout_s: float, log_path: Path) -> None:
    """Two-pass loudnorm to LOUDNESS_*: measure, then apply with the measured values
    (linear gain when the true-peak target allows it). The video is copied. Digital
    silence (integrated loudness -inf) passes through unchanged. The audio is cut back to
    the source's length: loudnorm flushes ~0.1 s more than it was given."""
    duration = ffmpeg.probe(src).duration
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
    ffmpeg.run(["-i", src, "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
                "-af", f"{af},{AUDIO_FORMAT},{_fit(duration)}", *AUDIO_ARGS, *CONTAINER_ARGS,
                out], timeout_s=timeout_s)


def render(recipe: Recipe, inputs: Mapping[str, PathLike], out: PathLike, *,
           timeout_s: float = DEFAULT_TIMEOUT_S, preset: str = DEFAULT_PRESET) -> MediaInfo:
    """Run `recipe` on `inputs["source"]` and write `out`. Other named inputs (music,
    voice-over, reaction) are for the ops that use them. Every output gets a final loudness
    pass (LOUDNESS_*). Returns the output's MediaInfo. `timeout_s` applies to each
    ffmpeg run."""
    paths = {k: Path(v) for k, v in inputs.items()}
    if "source" not in paths:
        raise ValueError("inputs must contain 'source'")
    needed = {name for op in recipe.ops
              for name in (getattr(op, "input", None), getattr(op, "reaction_input", None))
              if name}
    missing = sorted(needed - set(paths))
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
