"""captions and end_card ops, and every op keeping the clip's length."""

import json
import subprocess

import pytest
from pydantic import ValidationError

from src.studio import ffmpeg, recipe
from src.studio.recipe import Captions, EndCard, Logo, Recipe, render
from tests.test_studio_brand_ops import (
    NEAR,
    SH,
    SW,
    SX,
    SY,
    W,
    assert_in_safe_area,
    changed,
    gray,
    make_flat,
)
from tests.test_studio_ffmpeg import needs_ffmpeg
from tests.test_studio_recipe import assert_spec

FRAME = 1 / recipe.FPS
AAC_SLACK = 0.025  # one AAC frame (1024 samples at 48 kHz) is ~21 ms


def streams(path):
    """{codec_type: duration} of a file's streams."""
    out = subprocess.run([ffmpeg.find_ffprobe(), "-v", "error", "-show_entries",
                          "stream=codec_type,duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return {s["codec_type"]: float(s["duration"]) for s in json.loads(out)["streams"]}


def run(tmp_path, ops, *, duration):
    src = make_flat(tmp_path / "in.mp4", duration=duration)
    out = tmp_path / "out.mp4"
    info = render(Recipe(ops=ops), {"source": src}, out, timeout_s=120, preset="ultrafast")
    return src, out, info


@needs_ffmpeg
def test_captions_only_in_their_window_and_text_cannot_inject_tags(tmp_path):
    lines = [{"start_s": 0.3, "end_s": 0.9, "text": "{\\an8}Cats land {\\b1}on\\Ntheir feet"},
             {"start_s": 1.2, "end_s": 1.8, "text": "Second line 😀"}]
    src, out, info = run(tmp_path, [Captions(lines=lines)], duration=2)
    assert_spec(info, 2)
    for t in (0.1, 1.0, 1.95):
        assert changed(tmp_path, src, out, t) is None
    for t in (0.6, 1.5):
        box = changed(tmp_path, src, out, t)
        assert box is not None
        assert_in_safe_area(box)
        x0, y0, x1, y1 = box
        assert SY + SH - y1 <= NEAR  # bottom: {\an8} stayed text, not a move to the top
        assert abs((x0 + x1) / 2 - (SX + SW / 2)) <= NEAR


@needs_ffmpeg
def test_captions_center(tmp_path):
    src, out, _ = run(tmp_path, [Captions(lines=[{"start_s": 0, "end_s": 1, "text": "Hi"}],
                                          position="center")], duration=1)
    x0, y0, x1, y1 = changed(tmp_path, src, out, 0.5)
    assert abs((y0 + y1) / 2 - (SY + SH / 2)) <= NEAR


def test_caption_validation():
    ok = {"start_s": 0, "end_s": 1, "text": "x"}
    for bad in ([], [ok, ok],  # overlap
                [{**ok, "start_s": 2, "end_s": 3}, ok],  # not sorted
                [{**ok, "end_s": 0.5, "start_s": 0.5}],
                [{**ok, "text": "x" * 81}],
                [{**ok, "text": " 😀👍🏽 "}]):  # nothing left once emoji are removed
        with pytest.raises(ValidationError):
            Captions(lines=bad)
    with pytest.raises(ValidationError):
        Captions(lines=[ok], position="top")
    touching = Captions(lines=[ok, {**ok, "start_s": 1, "end_s": 2}])  # end == next start
    assert len(touching.lines) == 2
    assert Captions(lines=[{**ok, "text": "  Ça  marche 🎉 © ™ "}]).lines[0].text == "Ça marche ©"
    assert Captions(lines=[{**ok, "text": "x" * 80}]).lines[0].text == "x" * 80


def test_ass_text_escapes_override_braces_and_backslashes():
    assert recipe._ass_text("{\\b1}hi}") == "\\{\\\u2060b1\\}hi\\}"
    assert recipe._ass_text("a\\Nb") == "a\\\u2060Nb"
    assert recipe._ass_time(3725.456) == "1:02:05.46"
    assert recipe._ass_color("#1A1C2C", 0.6) == "&H662C1C1A"


@needs_ffmpeg
def test_end_card_extends_video_with_brand_background_and_continuous_audio(tmp_path):
    src, out, info = run(tmp_path, [EndCard(text="7 jours gratuits sur macrobody.fr")], duration=1)
    assert_spec(info, 3)
    s = streams(out)
    assert s["video"] == pytest.approx(1 + 2.0, abs=FRAME + 0.005)
    assert s["audio"] == pytest.approx(s["video"], abs=FRAME + 0.005)
    clip, card = gray(tmp_path, out, 0.5), gray(tmp_path, out, 2.5)
    assert clip[0] > 100  # the grey clip
    bg = card[0]
    assert bg > 220  # the light brand surface (#F5F7F8)
    for x, y in ((W - 1, 0), (0, recipe.HEIGHT - 1), (W // 2, recipe.HEIGHT - 300)):
        assert abs(card[y * W + x] - bg) <= 4


def test_end_card_validation():
    for bad in ({"text": ""}, {"text": "x", "duration_s": 0.5}, {"text": "x", "duration_s": 5},
                {"text": "x" * 61}):
        with pytest.raises(ValidationError):
            EndCard(**bad)
    assert EndCard(text="x").duration_s == 2.0 and EndCard(text="x").with_logo


@needs_ffmpeg
def test_ops_keep_a_3s_aac_clip_at_3s(tmp_path):
    """Regression: AAC + loudnorm made a 3 s clip 3.1 s through any op."""
    _, out, info = run(tmp_path, [Logo()], duration=3)
    s = streams(out)
    assert info.duration == pytest.approx(3.0, abs=FRAME)
    assert s["video"] == pytest.approx(3.0, abs=FRAME + 0.005)
    assert s["audio"] == pytest.approx(3.0, abs=AAC_SLACK)
