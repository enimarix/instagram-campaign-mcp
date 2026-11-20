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

import hashlib
import json
import math
import os
import re
import struct
import tempfile
import unicodedata
from pathlib import Path
from typing import (
    Annotated,
    Any,
    Callable,
    ClassVar,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
)

from pydantic import (
    AfterValidator,
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
from src.studio.fontmetrics import ascent_descent, ass_em, text_width

# Output spec (Instagram Reels): one place for every op.
WIDTH, HEIGHT, FPS = 1080, 1920, 30
SAMPLE_RATE = 48000
VIDEO_ARGS = ("-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS))
AUDIO_ARGS = ("-c:a", "aac", "-b:a", "128k", "-ar", str(SAMPLE_RATE), "-ac", "2")
CONTAINER_ARGS = ("-movflags", "+faststart")
# Final loudness of every render (EBU R128 integrated / true peak / range).
LOUDNESS_I, LOUDNESS_TP, LOUDNESS_LRA = -14.0, -1.5, 11.0
LOUDNORM = f"loudnorm=I={LOUDNESS_I}:TP={LOUDNESS_TP}:LRA={LOUDNESS_LRA}"
# Step 158: the encoded master must measure at most TRUE_PEAK_MAX and within LOUDNESS_TOL of
# LOUDNESS_I (the AAC encode after loudnorm overshot its -1.5 target by up to 3 dB): a
# 4x-oversampled limiter (a true-peak estimate) at LIMIT_DB, the encoded file measured, and
# encoded again with the limiter lower by the overshoot, and the gain into it up by what the
# limiting took off, while it is out (at most LIMIT_TRIES encodes).
TRUE_PEAK_MAX, LOUDNESS_TOL, LIMIT_DB, LIMIT_TRIES = -1.0, 0.5, -2.0, 4
# Step 161: a voiced mix gets the gain that puts its voice at LOUDNESS_I, as long as the mix
# itself lands within this of LOUDNESS_I (so within LOUDNESS_TOL more of it once encoded).
DIALOGUE_SPREAD = 0.5
# dialogue_voice(): the voice is limited at VOICE_REF_LUFS + VOICE_PEAK_LU once brought to
# VOICE_REF_LUFS (alimiter's ceiling must lie in -24..0 dB).
VOICE_REF_LUFS, VOICE_PEAK_LU = -20.0, 10.0
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

    def events(self, length: float) -> List[Dict[str, Any]]:
        """What the op shows or plays in a clip of `length` seconds, for recipe_timeline():
        [{t, d, e, text?}] (step 110). Ops that only reshape the picture add none."""
        return []

    def texts(self) -> List[str]:
        """The texts the op draws on screen (QC checks them: never a price, step 137)."""
        return []


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


@register
class Trim(Op):
    """Keep only `start_s`..`end_s` of the clip (cut at its end): the part being reacted to
    (GOAL.md §5.1). A plain cut: picture, speed and pitch are untouched."""

    op: Literal["trim"] = "trim"
    start_s: float = Field(0.0, ge=0)
    end_s: float = Field(gt=0)

    @model_validator(mode="after")
    def _window(self) -> "Trim":
        if self.end_s <= self.start_s:
            raise ValueError("end_s must be after start_s")
        return self

    def apply(self, src, info, out, *, inputs, timeout_s, preset):
        end = min(self.end_s, info.duration)
        if end <= self.start_s:
            raise ValueError(f"trim starts at {self.start_s} s, after the clip's end")
        cut = f"start={self.start_s}:end={end}"
        head = (f"[0:a:0]atrim={cut},asetpts=PTS-STARTPTS," if info.has_audio
                else f"anullsrc=r={SAMPLE_RATE}:cl=stereo,")
        encode(src, info, out, filter_complex=f"[0:v]trim={cut},setpts=PTS-STARTPTS,{VIDEO_TAIL}",
               timeout_s=timeout_s, preset=preset,
               audio=f"{head}{AUDIO_FORMAT},{_fit(end - self.start_s)}")


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

    def events(self, length):
        return [{"t": 0, "d": length, "e": "original sound muted"}]


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
                    extra_inputs=["-i", dialogue_voice(inputs[self.input], timeout_s=timeout_s)])

    def events(self, length):
        return [{"t": 0, "d": length, "e": "voice-over over the clip"}]


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

    def events(self, length):
        return [{"t": 0, "d": length, "e": "music bed" + (" (looped)" if self.loop else "")}]


# --- Brand overlays (GOAL.md §3.1 Track A steps 5-6, §5.1 credit). Styled from the brand
# kit, every overlay inside its safe area. They add to the picture; they never move it.

Corner = Literal["top_left", "top_right", "bottom_left", "bottom_right"]
MAX_TEXT = 60  # characters, hook and credit
TEXT_PAD = 16  # px of background box around text
OverlayText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                               max_length=MAX_TEXT)]
# Text the agent writes for the screen: never a price (owner rule, brand.no_price).
ScreenText = Annotated[OverlayText, AfterValidator(brand.no_price)]


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


NBSP = "\u00a0"


def french_spaces(text: str) -> str:
    """French typography for every text the studio draws: a no-break space before ? ! : ;
    and » and after «, so wrapping never leaves the mark alone at a line start. Only a
    space that is already there before ? ! : ; changes, so English "Why?" stays as is."""
    text = re.sub(r"«[ \u00a0]*", "«" + NBSP, text)
    text = re.sub(r"[ \u00a0]*»", NBSP + "»", text)
    return re.sub(r" +([?!:;])", NBSP + r"\1", text)


def _wrap(text: str, width: float, size: float, font: Path) -> List[str]:
    """`text` (French spaces applied) in lines of at most `width` px at `size` px per em
    in `font`, broken at plain spaces only (never at a no-break space); a word wider than
    a line is cut."""
    lines: List[str] = []
    line = ""
    for word in french_spaces(text).split(" "):
        if not word:
            continue
        joined = f"{line} {word}" if line else word
        if text_width(joined, size, font) <= width:
            line = joined
            continue
        if line:
            lines.append(line)
        line = ""
        for c in word:  # rarely more than a long URL
            if line and text_width(line + c, size, font) > width:
                lines.append(line)
                line = ""
            line += c
    return lines + [line] if line else lines


def _png_size(path: Path) -> Tuple[int, int]:
    """(width, height) of a PNG, from its IHDR header."""
    return struct.unpack(">II", path.read_bytes()[16:24])


def _surface(kit: Dict[str, Any], name: str) -> Tuple[str, str]:
    """(text, background) colours of a brand surface: dark.text on dark.bg, light.ink on
    light.bg."""
    s = kit["colors"][name]
    return s.get("text") or s["ink"], s["bg"]


def _text_filter(lines: Sequence[str], out: Path, tag: str, *, font: Path, size: float,
                 color: str, x: str, y: str, box: str = "", enable: str = "") -> str:
    """A drawtext filter for `lines` (already wrapped) in `font`, `color` #RRGGBB, at the
    drawtext expressions `x`/`y`; `box`: a box colour like 0x0E1117@0.6, padded by
    TEXT_PAD. The text goes through a file named after `tag` in render()'s work dir (no
    drawtext text escaping)."""
    textfile = out.with_name(f"{out.stem}-{tag}.txt")
    # newline: drawtext breaks on "\r" too, so a Windows "\r\n" would double each break.
    textfile.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    graph = (f"drawtext=fontfile={_filter_value(font.as_posix())}"
             f":textfile={_filter_value(textfile.resolve().as_posix())}:expansion=none"
             f":fontsize={size}:line_spacing={-round(size) // 8}:fontcolor=0x{color[1:]}"
             f":x={_filter_value(x)}:y={_filter_value(y)}")
    if box:
        graph += f":box=1:boxcolor={box}:boxborderw={TEXT_PAD}"
    return graph + (f":enable={_filter_value(enable)}" if enable else "")


def _drawtext(text: str, info: MediaInfo, out: Path, *, size: int, x: str, y: str,
              enable: str = "") -> str:
    """A drawtext filter: `text` wrapped to the safe width in the brand font, dark.text on
    a semi-transparent dark.bg box. `x`/`y` pick from "left", "right", "center" / "top",
    "center", "bottom" inside the safe area."""
    kit, root = _brand_kit(info)
    font = _brand_font(kit, root)
    sx, sy, sw, sh = brand.safe_area(kit)
    xs = {"left": f"{sx + TEXT_PAD}", "right": f"{sx + sw - TEXT_PAD}-text_w",
          "center": f"{sx}+({sw}-text_w)/2"}
    ys = {"top": f"{sy + TEXT_PAD}", "bottom": f"{sy + sh - TEXT_PAD}-text_h",
          "center": f"{sy}+({sh}-text_h)/2"}
    fg, bg = _surface(kit, "dark")
    return _text_filter(_wrap(text, sw - 2 * TEXT_PAD, size, font), out, "text", font=font,
                        size=size, color=fg, x=xs[x], y=ys[y], box=f"0x{bg[1:]}@0.6",
                        enable=enable)


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

    def events(self, length):
        return [{"t": 0, "d": length, "e": f"logo ({self.position})"}]


@register
class HookText(Op):
    """The hook as a title card from `start_s` to `end_s`, readable with the sound off.
    The text keeps its case."""

    op: Literal["hook_text"] = "hook_text"
    text: ScreenText
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

    def events(self, length):
        return _window(self.start_s, self.end_s, length, "hook text", self.text)

    def texts(self):
        return [self.text]


@register
class Credit(Op):
    """A visible source credit for the whole video, e.g. "@creator" or "Clip: Name /
    Pexels" (GOAL.md §5.1), at the bottom of the safe area. The brand font has no emoji."""

    op: Literal["credit"] = "credit"
    text: ScreenText
    position: Literal["bottom_left", "bottom_right"] = "bottom_left"

    def apply(self, src, info, out, *, inputs, timeout_s, preset):
        text = _drawtext(self.text, info, out, size=24, x=self.position.removeprefix("bottom_"),
                         y="bottom")
        encode(src, info, out, filter_complex=f"[0:v]{text},{VIDEO_TAIL}",
               timeout_s=timeout_s, preset=preset)

    def events(self, length):
        return [{"t": 0, "d": length, "e": "credit", "text": self.text}]

    def texts(self):
        return [self.text]


MAX_CAPTION = 80  # characters per caption line
CAPTION_GAP = 12  # px between the boxes of a caption's wrapped lines


def _strip_emoji(text: str) -> str:
    """Drop emoji and pictographs: the brand font has none, and a fallback emoji font is
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
    semi-transparent box, wrapped to the safe width, each wrapped line centred in its own
    box with CAPTION_GAP px between boxes (they never overlap). bottom: just above the
    bottom safe inset; center: the middle of the safe area. Emoji are dropped (see
    _strip_emoji)."""

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
        fg, bg = _surface(kit, "dark")
        text, box = _ass_color(fg), _ass_color(bg, 0.6)
        # WrapStyle 2: no libass wrapping, the lines are wrapped here. BorderStyle 3: an
        # opaque box (OutlineColour) padded by Outline px around each line, `size` +
        # 2 x Outline px tall; one event per line, `step` apart, so boxes never touch.
        em, step = ass_em(self.size, font), self.size + 2 * TEXT_PAD + CAPTION_GAP
        events = []
        for line in self.lines:
            rows = _wrap(line.text, sw - 2 * TEXT_PAD, em, font)
            for i, row in enumerate(rows):
                if self.position == "bottom":
                    pos = f"\\an2\\pos({sx + sw // 2},{sy + sh - TEXT_PAD - (len(rows) - 1 - i) * step})"
                else:
                    y = sy + sh // 2 + round((i - (len(rows) - 1) / 2) * step)
                    pos = f"\\an5\\pos({sx + sw // 2},{y})"
                events.append(f"Dialogue: 0,{_ass_time(line.start_s)},{_ass_time(line.end_s)},"
                              f"Brand,,0,0,0,,{{{pos}}}{_ass_text(row)}")
        ass = out.with_suffix(".ass")  # in render()'s work dir
        ass.write_text("\n".join([
            "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {WIDTH}", f"PlayResY: {HEIGHT}",
            "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Brand,{kit['fonts']['display']},{self.size},{text},{text},{box},{box},"
            f"{kit['fonts']['display_weight']},0,0,0,100,100,0,0,3,{TEXT_PAD},0,2,0,0,0,1", "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events, ""]), encoding="utf-8")
        graph = (f"[0:v]ass=filename={_filter_value(ass.resolve().as_posix())}"
                 f":fontsdir={_filter_value(font.parent.as_posix())},{VIDEO_TAIL}")
        encode(src, info, out, filter_complex=graph, timeout_s=timeout_s, preset=preset)

    def events(self, length):
        return [e for line in self.lines
                for e in _window(line.start_s, line.end_s, length, "caption", line.text)]

    def texts(self):
        return [line.text for line in self.lines]


# Renders the animated end card (motion EndCard, step 137): (its props, the backdrop picture
# or None) -> the card clip, or None when Remotion is unavailable. render() gets one from the
# render job (src/studio/render.py, which caches the clips under the media root).
CardRenderer = Callable[[Dict[str, Any], Optional[Path]], Optional[Path]]
END_CARD_MIN_S = 2.5  # owner: an end card lasts at least 2.5 s (= motion END_CARD_MIN_S)
Accent = Literal["brand", "protein", "carbs", "fat", "kcal"]


@register
class EndCard(Op):
    """The brand's animated call-to-action card appended after the clip (owner, 2026-11-18:
    end cards are motion design, one per style): the motion `EndCard` of `style` live (the
    clip's last frame freezes, blurs and dims, the card animates over it) or clean (the light
    v5 look), with the tagline `text` and the topic's `accent`; the mB tile, the wordmark,
    the brand kit's `cta.trial` pill and `cta.url` are the fixed base. Never a price. The clip
    comes from the CardRenderer render() is given. Without one, or when it returns None
    (Remotion unavailable), the static card below is drawn instead, as in the owner's own
    end cards on the light surface: the logo tile (with_logo), the wordmark (brand name, from
    its second capital in emerald: "macro" + "Body"), the tagline, the pill and the url,
    centred on the frame's vertical axis inside the safe area; the render job then adds a QC
    warning. The video gets `duration_s` longer (at least END_CARD_MIN_S) and the audio goes
    on under the card as silence; to run a music bed under the card too, put `music` after
    `end_card` in the recipe."""

    op: Literal["end_card"] = "end_card"
    text: Optional[ScreenText] = None
    style: Literal["live", "clean"] = "live"
    accent: Accent = "brand"
    duration_s: float = Field(3.5, gt=0, le=6)
    with_logo: bool = True

    @field_validator("duration_s")
    @classmethod
    def _long_enough(cls, value: float) -> float:
        return max(value, END_CARD_MIN_S)  # older recipes asked for 2 s

    LOGO_W: ClassVar[int] = 260  # px, the tile
    SIZES: ClassVar[Dict[str, int]] = {"text": 44, "pill": 52, "url": 44}
    PILL_H: ClassVar[int] = 104
    PILL_PAD: ClassVar[int] = 56  # px left and right of the pill text
    GAP: ClassVar[int] = 40  # px between blocks (the tagline's lines touch)

    def card_props(self, kit: Dict[str, Any]) -> Dict[str, Any]:
        """Props of the motion EndCard (motion/src/endcards/schema.ts) for this card."""
        props: Dict[str, Any] = {"style": self.style, "accent": self.accent,
                                 "seconds": self.duration_s,
                                 "address": kit["address"]["live" if self.style == "live"
                                                           else "default"]}
        return {**props, "tagline": self.text} if self.text else props

    def apply(self, src, info, out, *, inputs, timeout_s, preset,
              card: Optional[CardRenderer] = None):
        kit, _ = _brand_kit(info)
        clip = None
        if card is not None:
            backdrop = None
            if self.style == "live":  # the clip's last frame: -update keeps overwriting it
                backdrop = out.with_name(f"{out.stem}-last.jpg")
                ffmpeg.run(["-sseof", "-1", "-i", src, "-update", "1", "-q:v", "2", backdrop],
                           timeout_s=timeout_s)
            clip = card(self.card_props(kit), backdrop)
        if clip is None:
            return self._static(src, info, out, timeout_s=timeout_s, preset=preset)
        graph = (f"[0:v]setsar=1,fps={FPS},format=yuv420p[clip];"
                 f"[1:v]scale={WIDTH}:{HEIGHT},setsar=1,fps={FPS},format=yuv420p,"
                 f"trim=duration={self.duration_s},setpts=PTS-STARTPTS[card];"
                 f"[clip][card]concat=n=2:v=1:a=0,{VIDEO_TAIL}")
        encode(src, info, out, filter_complex=graph, timeout_s=timeout_s, preset=preset,
               extra_inputs=[clip], extend_s=self.duration_s)

    def _static(self, src, info, out, *, timeout_s, preset):
        """The static card (step 050): the fallback when no animated card can be rendered."""
        kit, root = _brand_kit(info)
        font = _brand_font(kit, root)
        _, sy, sw, sh = brand.safe_area(kit)
        colors, cta = kit["colors"], kit["cta"]
        ink, size = colors["light"]["ink"], self.SIZES
        wordmark = root / kit["wordmark_png"]
        _, wordmark_h = _png_size(wordmark)
        text_h = sum(ascent_descent(size["text"], font))
        rows = _wrap(self.text, sw - 2 * TEXT_PAD, size["text"], font) if self.text else []
        blocks = ([("logo", self.LOGO_W)] if self.with_logo else []) + [
            ("wordmark", wordmark_h), ("text", text_h * len(rows)), ("pill", self.PILL_H),
            ("url", sum(ascent_descent(size["url"], font)))]
        blocks = [(k, h) for k, h in blocks if h]
        top, y = {}, sy + (sh - sum(h for _, h in blocks) - self.GAP * (len(blocks) - 1)) / 2
        for k, h in blocks:
            top[k] = y
            y += h + self.GAP

        def baseline(line_top: float, px: int) -> str:
            # drawtext puts the highest glyph of its own text at y: anchor on the baseline
            # instead, so every line sits the same whatever its letters.
            return f"{round(line_top + ascent_descent(px, font)[0])}-max_glyph_a"

        texts = [_text_filter([row], out, f"text{i}", font=font, size=size["text"], color=ink,
                              x="(w-text_w)/2", y=baseline(top["text"] + i * text_h,
                                                           size["text"]))
                 for i, row in enumerate(rows)]
        trial = french_spaces(cta["trial"])
        pw = round((text_width(trial, size["pill"], font) + 2 * self.PILL_PAD) / 2) * 2
        ph, r = self.PILL_H, self.PILL_H / 2
        # ponytail: cap height ~0.72 em (Inter): the pill text's capitals sit centred.
        texts.append(_text_filter([trial], out, "pill", font=font, size=size["pill"],
                                  color="#FFFFFF", x="(w-text_w)/2",
                                  y=f"{round(top['pill'] + r + 0.36 * size['pill'])}"
                                    "-max_glyph_a"))
        texts.append(_text_filter([french_spaces(cta["url"])], out, "url", font=font,
                                  size=size["url"], color=ink, x="(w-text_w)/2",
                                  y=baseline(top["url"], size["url"])))

        dur = self.duration_s
        # The pill: an emerald capsule, alpha = coverage of a rounded rectangle (1 px soft).
        alpha = (f"255*clip({r}+0.5-hypot(max(abs(X+0.5-{pw / 2})-{pw / 2 - r}\\,0)\\,"
                 f"Y+0.5-{r})\\,0\\,1)")
        card = (f"color=c=0x{colors['light']['bg'][1:]}:s={WIDTH}x{HEIGHT}:r={FPS}:d={dur}[bg];"
                f"color=c=0x{colors['brand'][1:]}:s={pw}x{ph}:r={FPS}:d={dur},format=rgba,"
                f"geq=r=r(X\\,Y):g=g(X\\,Y):b=b(X\\,Y):a={alpha}[pill];"
                f"[bg][pill]overlay={(WIDTH - pw) // 2}:{round(top['pill'])}")
        card += f"[bp];[1:v]format=rgba[wm];[bp][wm]overlay=(W-w)/2:{round(top['wordmark'])}"
        extra: List[PathLike] = [wordmark]
        if self.with_logo:
            card += (f"[bw];[2:v]scale={self.LOGO_W}:-2[logo];"
                     f"[bw][logo]overlay=(W-w)/2:{round(top['logo'])}")
            extra.append(root / kit["logo_png"])
        graph = (f"[0:v]setsar=1,fps={FPS},format=yuv420p[clip];"
                 f"{card},{','.join(texts)},setsar=1,format=yuv420p[card];"
                 f"[clip][card]concat=n=2:v=1:a=0,{VIDEO_TAIL}")
        encode(src, info, out, filter_complex=graph, timeout_s=timeout_s, preset=preset,
               extra_inputs=extra, extend_s=self.duration_s)

    def events(self, length):  # appended: starts where the clip ends
        event = {"t": length, "d": self.duration_s, "e": f"end card ({self.style})"}
        return [{**event, "text": self.text} if self.text else event]

    def texts(self):
        return [self.text] if self.text else []


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

    def events(self, length):
        where = ("the clip on top, the owner's reaction below" if self.layout == "split"
                 else f"the owner's reaction in a box, {self.pip_corner.replace('_', ' ')}")
        return [{"t": 0, "d": length, "e": f"reaction {self.layout}: {where}"}]


# --- Timeline (step 110): what happens in the video, second by second, small enough to sit
# in every asset row and in the agent's context: [{"t": start_s, "d": dur_s, "e": line}].
TIMELINE_EVENTS = 40
TIMELINE_BYTES = 2000  # as stored (json.dumps)
EVENT_CHARS = 80


def _window(start: float, end: float, length: float, label: str, text: str
            ) -> List[Dict[str, Any]]:
    """An event shown from `start` to `end`, cut at the clip's end (none if it starts after)."""
    if start >= length:
        return []
    return [{"t": start, "d": min(end, length) - start, "e": label, "text": text}]


def _clip(text: str, chars: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= chars else text[:chars - 1].rstrip() + "…"


def compress_timeline(raw: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Events {t, d, e, text?} -> the stored timeline: t/d rounded to 0.1 s, one line per
    event (`e: 'text'`, about EVENT_CHARS), sorted by t, at most TIMELINE_EVENTS and
    TIMELINE_BYTES; what is cut becomes a last {"e": "+N more"}."""
    events = []
    for r in raw:
        e = _clip(r["e"], EVENT_CHARS)
        if r.get("text"):
            e = f"{e}: '{_clip(r['text'], max(EVENT_CHARS - len(e) - 4, 12))}'"
        events.append({"t": round(r["t"], 1), "d": round(r["d"], 1), "e": e})
    events.sort(key=lambda x: x["t"])

    def cut(k: int) -> List[Dict[str, Any]]:
        return events[:k] + ([{"e": f"+{len(events) - k} more"}] if k < len(events) else [])

    keep = min(len(events), TIMELINE_EVENTS)
    while keep and len(json.dumps(cut(keep))) > TIMELINE_BYTES:
        keep -= 1
    return cut(keep)


def recipe_timeline(recipe: Recipe, duration_s: float,
                    clip: Sequence[Mapping[str, Any]] = ()) -> List[Dict[str, Any]]:
    """The compressed timeline of a render of `recipe` that came out `duration_s` long (the
    final video), in its seconds. Ops without a time window span the clip as it is when they
    run: an end card makes it longer for the ops after it. `clip` is the source clip's own
    timeline (step 119, in its seconds): its events inside the trim come in shifted and
    marked `clip:`, so the clip's beats and our overlays can be told apart."""
    length = duration_s - sum(op.duration_s for op in recipe.ops if isinstance(op, EndCard))
    start = next((op.start_s for op in recipe.ops if isinstance(op, Trim)), 0.0)
    clips: List[Dict[str, Any]] = []
    for ev in clip:
        if "t" in ev and ev["t"] + ev["d"] >= start:  # no t: the "+N more" marker
            clips += _window(max(ev["t"] - start, 0.0), ev["t"] + ev["d"] - start, length,
                             "clip", ev["e"])
    raw: List[Dict[str, Any]] = []
    for op in recipe.ops:
        raw += op.events(length)
        if isinstance(op, EndCard):
            length += op.duration_s
    return compress_timeline(raw + clips)  # stable sort: our overlays first at the same t


def _limiter(ceiling_db: float) -> str:
    """Filter chain: a true-peak limiter at `ceiling_db` (4x oversampled, no auto gain)."""
    return (f"aresample={4 * SAMPLE_RATE},alimiter=limit={10 ** (ceiling_db / 20):.5f}"
            f":attack=1:release=50:level=0:latency=1")


def loudness(path: PathLike, *, timeout_s: float) -> Tuple[Optional[float], Optional[float]]:
    """(integrated loudness LUFS, true peak dBTP) of the audio (ffmpeg ebur128); None for a
    value silence does not have."""
    with tempfile.TemporaryDirectory() as work:
        log = Path(work) / "loudness.log"
        ffmpeg.run(["-i", path, "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"],
                   timeout_s=timeout_s, log_path=log)
        summary = log.read_text(encoding="utf-8").rpartition("Summary:")[2]
    found = [re.search(pattern, summary) for pattern in
             (r"I:\s+(\S+) LUFS", r"True peak:\s+Peak:\s+(\S+) dBFS")]
    values = [float(f.group(1)) if f else math.nan for f in found]
    return tuple(v if math.isfinite(v) and v > -70 else None for v in values)


def dialogue_voice(src: PathLike, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> Path:
    """The voice as every render mixes it (step 161): its peaks limited to VOICE_PEAK_LU over
    its loudness, then brought back to that loudness. The TTS voices peak ~19 dB over their
    loudness, so a -14 LUFS voice would need -1 dBTP + 5 dB: limited in the mix, the
    limiter would ride the bed with every syllable. Written once next to `src`
    (`<stem>.dialogue-<chain hash>.wav`); `src` itself when it is silent."""
    src = Path(src)
    chain = f"volume={{gain:.2f}}dB,{_limiter(VOICE_REF_LUFS + VOICE_PEAK_LU)}"
    out = src.with_name(f"{src.stem}.dialogue-{hashlib.sha256(chain.encode()).hexdigest()[:8]}"
                        ".wav")
    if out.is_file():
        return out
    level = loudness(src, timeout_s=timeout_s)[0]
    if level is None:
        return src
    with tempfile.TemporaryDirectory(dir=src.parent) as work:
        limited, final = Path(work) / "limited.wav", Path(work) / "voice.wav"
        pcm = ["-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le"]
        ffmpeg.run(["-i", src, "-map", "0:a:0", "-af",
                    chain.format(gain=VOICE_REF_LUFS - level), *pcm, limited], timeout_s=timeout_s)
        back = level - loudness(limited, timeout_s=timeout_s)[0]
        ffmpeg.run(["-i", limited, "-af", f"volume={back:.2f}dB", *pcm, final],
                   timeout_s=timeout_s)
        os.replace(final, out)  # atomic: two renders of the same voice write the same file
    return out


def normalize_loudness(src: Path, out: Path, *, timeout_s: float, log_path: Path,
                       voice: Optional[Path] = None, voice_gain_db: float = 0.0) -> None:
    """The finish: to LOUDNESS_*, then the true-peak ceiling (see TRUE_PEAK_MAX), checked on
    the encoded file. The video is copied. The audio is cut back to the source's length
    (loudnorm flushes ~0.1 s more than it was given).

    A voiced mix (`voice`: the voice track, mixed in at `voice_gain_db`) is normalised by its
    dialogue (step 161): one linear gain puts the voice's gated loudness at LOUDNESS_I, then
    the limiter; the gain goes up by what the limiter took off the mix. A dynamic loudnorm
    there squeezed the quiet voice into the bed (7-11 LU over it instead of 14-15).
    Otherwise: two-pass loudnorm, measure, then apply with the measured values (linear gain
    when the true-peak target allows it). Digital silence (integrated loudness -inf) passes
    through unchanged."""
    duration = ffmpeg.probe(src).duration
    spoken = loudness(voice, timeout_s=timeout_s)[0] if voice else None
    mixed = loudness(src, timeout_s=timeout_s)[0] if spoken is not None else None
    if mixed is not None:  # the dialogue's gain, kept to a mix within DIALOGUE_SPREAD of I
        expect = min(max(mixed + LOUDNESS_I - spoken - voice_gain_db,
                         LOUDNESS_I - DIALOGUE_SPREAD), LOUDNESS_I + DIALOGUE_SPREAD)
        af, gain = "anull", expect - mixed
    else:
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
        gain, expect = 0.0, LOUDNESS_I
    ceiling = LIMIT_DB
    for _ in range(LIMIT_TRIES):
        ffmpeg.run(["-i", src, "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af",
                    f"{af},volume={gain:.2f}dB,{_limiter(ceiling)},{AUDIO_FORMAT},"
                    f"{_fit(duration)}", *AUDIO_ARGS, *CONTAINER_ARGS, out], timeout_s=timeout_s)
        lufs, peak = loudness(out, timeout_s=timeout_s)
        over = 0.0 if peak is None else max(peak - TRUE_PEAK_MAX, 0.0)
        short = 0.0 if lufs is None else expect - lufs
        if over == 0 and abs(short) <= LOUDNESS_TOL:
            return
        ceiling, gain = ceiling - (over + 0.2 if over else 0.0), gain + short
    # ponytail: still out after LIMIT_TRIES encodes: kept, the QC's loudness checks flag it


def render(recipe: Recipe, inputs: Mapping[str, PathLike], out: PathLike, *,
           timeout_s: float = DEFAULT_TIMEOUT_S, preset: str = DEFAULT_PRESET,
           end_card: Optional[CardRenderer] = None, voice: Optional[PathLike] = None
           ) -> MediaInfo:
    """Run `recipe` on `inputs["source"]` and write `out`. Other named inputs (music,
    voice-over, reaction) are for the ops that use them; `end_card` renders the animated end
    card clips (none: the static card). Every output gets a final loudness pass
    (LOUDNESS_*), by the voice when there is one: `voice`, the voice the source already
    carries at unity gain (its dialogue_voice()), else the voice_over op's input. Returns the
    output's MediaInfo.
    `timeout_s` applies to each ffmpeg run."""
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
            extra = {"card": end_card} if isinstance(op, EndCard) else {}
            op.apply(current, ffmpeg.probe(current), nxt, inputs=paths, timeout_s=timeout_s,
                     preset=preset, **extra)
            current = nxt
        loud = Path(work) / "loudnorm.mp4"
        over = next((op for op in recipe.ops if isinstance(op, VoiceOver)), None)
        gain = 0.0
        if voice is None and over:
            voice, gain = dialogue_voice(paths[over.input], timeout_s=timeout_s), over.gain_db
        normalize_loudness(current, loud, timeout_s=timeout_s,
                           log_path=Path(work) / "loudnorm.log",
                           voice=Path(voice) if voice else None, voice_gain_db=gain)
        os.replace(loud, out)
    return ffmpeg.probe(out)
