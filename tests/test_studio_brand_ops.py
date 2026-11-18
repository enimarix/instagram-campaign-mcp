"""Brand overlay ops (logo, hook_text, credit). Clips are flat grey lavfi video, so a
frame region is unchanged unless an overlay touched it."""

import pytest
from pydantic import ValidationError

from src.studio import ffmpeg, recipe
from src.studio.brand import load_brand, safe_area
from src.studio.recipe import Credit, FitVertical, HookText, Logo, Recipe, render
from tests.test_studio_ffmpeg import H264, needs_ffmpeg
from tests.test_studio_recipe import assert_spec

W, H = recipe.WIDTH, recipe.HEIGHT
SX, SY, SW, SH = safe_area(load_brand())
NEAR = 4  # px: compression softens overlay edges a little
BLEED = 2  # px: codec ringing just outside an overlay edge


def make_flat(path, *, duration, size=f"{W}x{H}"):
    ffmpeg.run(["-f", "lavfi", "-i", f"color=c=0x808080:size={size}:rate=25:duration={duration}",
                "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
                "-c:a", "aac", "-shortest", *H264, path], timeout_s=60)
    return path


def go(tmp_path, op, *, duration=1):
    src = make_flat(tmp_path / "in.mp4", duration=duration)
    out = tmp_path / "out.mp4"
    info = render(Recipe(ops=[op]), {"source": src}, out, timeout_s=120, preset="ultrafast")
    assert_spec(info, duration)
    return src, out


def gray(tmp_path, path, t):
    raw = tmp_path / f"{path.stem}-{t}.gray"
    ffmpeg.run(["-ss", str(t), "-i", path, "-frames:v", "1", "-f", "rawvideo",
                "-pix_fmt", "gray", raw], timeout_s=60)
    data = raw.read_bytes()
    assert len(data) == W * H
    return data


def changed(tmp_path, src, out, t, threshold=24):
    """Bounding box (x0, y0, x1, y1), end exclusive, of the pixels the op changed at `t`;
    None when the frame is unchanged."""
    a, b = gray(tmp_path, src, t), gray(tmp_path, out, t)
    xs, ys = [], []
    for y in range(H):
        row_a, row_b = a[y * W:(y + 1) * W], b[y * W:(y + 1) * W]
        if row_a == row_b:
            continue
        hits = [x for x in range(W) if abs(row_a[x] - row_b[x]) > threshold]
        if hits:
            xs += (hits[0], hits[-1])
            ys.append(y)
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1) if ys else None


def assert_in_safe_area(box):
    x0, y0, x1, y1 = box
    assert SX - BLEED <= x0 and x1 <= SX + SW + BLEED, box
    assert SY - BLEED <= y0 and y1 <= SY + SH + BLEED, box


@needs_ffmpeg
@pytest.mark.parametrize("position", ["top_left", "top_right", "bottom_left", "bottom_right"])
def test_logo_sits_in_its_safe_corner(tmp_path, position):
    src, out = go(tmp_path, Logo(position=position))
    box = changed(tmp_path, src, out, 0.5, threshold=12)  # bar: low contrast on grey
    assert box is not None
    assert_in_safe_area(box)
    x0, y0, x1, y1 = box
    assert x1 - x0 == pytest.approx(130, abs=NEAR)  # 0.12 x 1080, square logo
    assert y1 - y0 == pytest.approx(130, abs=NEAR)
    if position.endswith("left"):
        assert x0 - SX <= NEAR
    else:
        assert SX + SW - x1 <= NEAR
    if position.startswith("top"):
        assert y0 - SY <= NEAR
    else:
        assert SY + SH - y1 <= NEAR


@needs_ffmpeg
def test_hook_text_only_inside_its_window(tmp_path):
    text = "Why do cats always land on their feet? Science has an answer"  # 60 chars
    src, out = go(tmp_path, HookText(text=text, start_s=0.6, end_s=1.2), duration=2)
    assert changed(tmp_path, src, out, 0.3) is None
    assert changed(tmp_path, src, out, 1.6) is None
    box = changed(tmp_path, src, out, 0.9)
    assert box is not None
    assert_in_safe_area(box)
    x0, y0, x1, y1 = box
    assert y0 - SY <= recipe.TEXT_PAD + NEAR  # top of the safe area
    assert abs((x0 + x1) / 2 - (SX + SW / 2)) <= NEAR  # centred
    assert 2 * 48 < y1 - y0 < 4 * 48  # wrapped over 2 lines, no blank line between them


@needs_ffmpeg
def test_hook_text_center(tmp_path):
    src, out = go(tmp_path, HookText(text="Hi", position="center"))
    x0, y0, x1, y1 = changed(tmp_path, src, out, 0.5)
    assert abs((y0 + y1) / 2 - (SY + SH / 2)) <= NEAR


@needs_ffmpeg
def test_credit_bottom_left_whole_video(tmp_path):
    src, out = go(tmp_path, Credit(text="Clip: Jane Doe / Pexels"), duration=2)
    for t in (0.1, 1.9):
        box = changed(tmp_path, src, out, t)
        assert box is not None
        assert_in_safe_area(box)
        x0, y0, x1, y1 = box
        assert x0 - SX <= NEAR and SY + SH - y1 <= NEAR
        assert y1 - y0 < 100  # one line


@needs_ffmpeg
def test_brand_ops_refuse_a_clip_not_yet_vertical(tmp_path):
    src = make_flat(tmp_path / "in.mp4", duration=1, size="640x360")
    with pytest.raises(ValueError, match="fit_vertical first"):
        render(Recipe(ops=[Credit(text="@x")]), {"source": src}, tmp_path / "out.mp4",
               timeout_s=60, preset="ultrafast")
    info = render(Recipe(ops=[FitVertical(), Logo(), Credit(text="@x")]), {"source": src},
                  tmp_path / "out.mp4", timeout_s=120, preset="ultrafast")
    assert_spec(info, 1.0)


def test_field_validation():
    with pytest.raises(ValidationError, match="at most 60"):
        HookText(text="x" * 61)
    for bad in ({"text": "  "}, {"text": "x", "start_s": 3, "end_s": 3},
                {"text": "x", "position": "bottom"}):
        with pytest.raises(ValidationError):
            HookText(**bad)
    with pytest.raises(ValidationError):
        Logo(opacity=1.5)
    with pytest.raises(ValidationError):
        Logo(position="center")
    with pytest.raises(ValidationError):
        Credit(text="")
    assert HookText(text="  Ça marche  ").text == "Ça marche"  # case kept


def test_filter_value_escapes_twice():
    assert recipe._filter_value("C:/x/f.ttf") == r"C\\:/x/f.ttf"
    assert recipe._filter_value("it's") == r"it\\\'s"
    assert recipe._filter_value("between(t,1,2)") == "between(t\\,1\\,2)"
