"""reaction_collage op. Clip and reaction are flat lavfi video in distinct greys: the clip
mid grey, the reaction dark until SWITCH_S of its own time and light after, so a frame
region tells which video it shows and how far into the reaction it is."""

import pytest
from pydantic import ValidationError

from src.studio import ffmpeg, recipe
from src.studio.recipe import ReactionCollage, Recipe, render
from tests.test_studio_audio import mean_db
from tests.test_studio_brand_ops import SH, SW, SX, SY, W, assert_in_safe_area, gray
from tests.test_studio_ffmpeg import H264, needs_ffmpeg
from tests.test_studio_recipe import assert_spec

CLIP, DARK, LIGHT = 0x80, 0x20, 0xE0
SWITCH_S = 0.5
NEAR = 6  # px


def make_video(path, *, size, duration, color, tone=None, switch_to=None):
    vf = f"color=c=0x{color:02x}{color:02x}{color:02x}:size={size}:rate=25:duration={duration}"
    if switch_to is not None:
        vf += (f",drawbox=c=0x{switch_to:02x}{switch_to:02x}{switch_to:02x}:t=fill"
               f":enable='gte(t,{SWITCH_S})'")
    args = ["-f", "lavfi", "-i", vf]
    if tone:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tone}:duration={duration}",
                 "-c:a", "aac", "-shortest"]
    ffmpeg.run([*args, *H264, path], timeout_s=60)
    return path


def go(tmp_path, op, *, reaction_s=1.0, reaction_tone=1000):
    clip = make_video(tmp_path / "clip.mp4", size="320x568", duration=2, color=CLIP, tone=440)
    reaction = make_video(tmp_path / "reaction.mp4", size="640x480", duration=reaction_s,
                          color=DARK, switch_to=LIGHT, tone=reaction_tone)
    out = tmp_path / "out.mp4"
    info = render(Recipe(ops=[op]), {"source": clip, "reaction": reaction}, out, timeout_s=120,
                  preset="ultrafast")
    assert_spec(info, 2)  # the clip's length, a shorter reaction is padded
    return out


def mean(frame, x0, y0, x1, y1):
    rows = [frame[y * W + x0:y * W + x1] for y in range(y0, y1)]
    return sum(map(sum, rows)) / ((x1 - x0) * (y1 - y0))


def box(frame, threshold=24):
    """Bounding box (x0, y0, x1, y1) of the pixels that are not the clip's grey."""
    ys = [y for y in range(len(frame) // W)
          if any(abs(v - CLIP) > threshold for v in frame[y * W:(y + 1) * W])]
    xs = [x for y in (ys[0], ys[-1]) for x in range(W)
          if abs(frame[y * W + x] - CLIP) > threshold]
    return min(xs), ys[0], max(xs) + 1, ys[-1] + 1


@needs_ffmpeg
def test_split_clip_on_top_reaction_below_padded_and_mixed(tmp_path):
    out = go(tmp_path, ReactionCollage(layout="split", split_ratio=0.6))
    top = 1152  # 0.6 x 1920
    early, late = gray(tmp_path, out, 0.25), gray(tmp_path, out, 1.6)
    assert mean(early, 0, 0, W, top - NEAR) == pytest.approx(CLIP, abs=4)
    assert mean(early, 0, top + NEAR, W, 1920) == pytest.approx(DARK, abs=4)
    # after the 1 s reaction ended, its last frame holds
    assert mean(late, 0, top + NEAR, W, 1920) == pytest.approx(LIGHT, abs=4)
    assert mean(late, 0, 0, W, top - NEAR) == pytest.approx(CLIP, abs=4)
    for tone in (440, 1000):  # both voices are in the mix
        assert mean_db(tmp_path, out, 0.1, 0.9, band=tone) > -35


@needs_ffmpeg
def test_pip_in_safe_corner_and_offset_delays_reaction(tmp_path):
    out = go(tmp_path, ReactionCollage(layout="pip", offset_s=1.0))
    before, start, later = (gray(tmp_path, out, t) for t in (0.5, 1.25, 1.8))
    x0, y0, x1, y1 = box(before)  # the reaction's first frame holds until it starts
    assert_in_safe_area((x0, y0, x1, y1))
    assert (x1 - x0, y1 - y0) == (pytest.approx(324, abs=NEAR), pytest.approx(576, abs=NEAR))
    assert SX + SW - x1 <= NEAR and SY + SH - y1 <= NEAR  # bottom right
    inner = (x0 + NEAR, y0 + NEAR, x1 - NEAR, y1 - NEAR)
    assert mean(before, *inner) == pytest.approx(DARK, abs=4)
    assert mean(start, *inner) == pytest.approx(DARK, abs=4)  # 0.25 s into the reaction
    assert mean(later, *inner) == pytest.approx(LIGHT, abs=4)  # 0.8 s into it
    assert mean(later, 0, 0, W, SY) == pytest.approx(CLIP, abs=4)  # the clip fills the rest
    quiet, loud = mean_db(tmp_path, out, 0.1, 0.9, 1000), mean_db(tmp_path, out, 1.1, 1.9, 1000)
    assert loud - quiet > 20  # the reaction's mic starts with it
    assert mean_db(tmp_path, out, 0.1, 0.9, 440) > -35


@needs_ffmpeg
def test_reaction_without_audio_keeps_the_clip_sound(tmp_path):
    out = go(tmp_path, ReactionCollage(layout="pip", pip_corner="top_left", offset_s=-0.6),
             reaction_tone=None)
    x0, y0, _, _ = box(gray(tmp_path, out, 0.1))
    assert (x0, y0) == (pytest.approx(SX, abs=NEAR), pytest.approx(SY, abs=NEAR))
    # negative offset: the reaction's first 0.6 s are skipped, so it is already light
    assert mean(gray(tmp_path, out, 0.1), x0 + NEAR, y0 + NEAR, x0 + 300, y0 + 500) == \
        pytest.approx(LIGHT, abs=4)
    assert mean_db(tmp_path, out, 0.1, 1.9, 440) > -35


def test_missing_reaction_input_is_a_clear_error(tmp_path):
    with pytest.raises(ValueError, match="needs input.*reaction"):
        render(Recipe(ops=[ReactionCollage(layout="split")]), {"source": tmp_path / "in.mp4"},
               tmp_path / "o.mp4")


def test_validation_and_round_trip():
    assert "reaction_collage" in recipe.OPS
    data = {"version": 1, "ops": [{"op": "reaction_collage", "layout": "pip",
                                   "reaction_input": "take", "offset_s": 1.5,
                                   "split_ratio": 0.5, "pip_corner": "top_right",
                                   "pip_scale": 0.3, "reaction_gain_db": 0.0,
                                   "clip_gain_db": -6.0}]}
    assert Recipe.model_validate(data).model_dump() == data
    for bad in ({}, {"layout": "grid"}, {"layout": "split", "split_ratio": 0.3},
                {"layout": "pip", "pip_scale": 0.6}, {"layout": "pip", "pip_corner": "center"},
                {"layout": "split", "clip_gain_db": 3}):
        with pytest.raises(ValidationError):
            ReactionCollage(**bad)
