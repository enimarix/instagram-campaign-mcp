import copy
import json

import pytest

from src.studio.brand import DEFAULT_PATH, BrandError, load_brand, safe_area

GOOD = {
    "version": 1,
    "placeholder": True,
    "name": "Test",
    "handle": "@test",
    "logo": "logo.svg",
    "colors": {
        "primary": "#FFCD75",
        "secondary": "#38b764",
        "accent": "#EF7D57",
        "background": "#1A1C2C",
        "text": "#F4F4F4",
        "palette": ["#000000", "#FFFFFF"],
    },
    "fonts": {"display": "Pixel", "body": "Pixel", "files": []},
    "safe_zone": {
        "width": 1080, "height": 1920, "top": 269, "bottom": 672, "left": 65, "right": 65,
    },
    "_source": {"note": "ignored"},
}


def _write(tmp_path, data):
    (tmp_path / "logo.svg").write_text("<svg/>", encoding="utf-8")
    path = tmp_path / "brand.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def _with(change):
    data = copy.deepcopy(GOOD)
    change(data)
    return data


def test_committed_file_loads():
    brand = load_brand()
    assert DEFAULT_PATH.is_file()
    assert brand["placeholder"] is True
    assert (DEFAULT_PATH.parent / brand["logo"]).is_file()
    assert len(brand["colors"]["palette"]) >= 8
    assert brand["safe_zone"]["width"] == 1080 and brand["safe_zone"]["height"] == 1920
    assert "_source" in brand
    assert load_brand() is brand  # cached


def test_tmp_file_loads(tmp_path):
    assert load_brand(_write(tmp_path, GOOD))["name"] == "Test"


def test_safe_area_maths():
    assert safe_area(GOOD) == (65, 269, 1080 - 130, 1920 - 269 - 672)
    rail = _with(lambda d: d["safe_zone"].update(right_rail=120))
    assert safe_area(rail) == (65, 269, 1080 - 65 - 120, 979)
    narrow_rail = _with(lambda d: d["safe_zone"].update(right_rail=10))
    assert safe_area(narrow_rail) == safe_area(GOOD)


def test_committed_safe_area_honours_rail():
    x, y, w, h = safe_area(load_brand())
    assert (x, y, w, h) == (65, 269, 895, 979)


def _del(*keys):
    def change(d):
        target = d
        for k in keys[:-1]:
            target = target[k]
        del target[keys[-1]]
    return change


def _set(*keys, value):
    def change(d):
        target = d
        for k in keys[:-1]:
            target = target[k]
        target[keys[-1]] = value
    return change


@pytest.mark.parametrize(
    "change, message",
    [
        (_del("handle"), "missing key(s): handle"),
        (_del("safe_zone"), "missing key(s): safe_zone"),
        (_set("version", value=0), "'version'"),
        (_set("placeholder", value="yes"), "'placeholder'"),
        (_set("name", value=" "), "'name'"),
        (_set("logo", value="missing.svg"), "'logo' file not found"),
        (_del("colors", "accent"), "missing 'accent'"),
        (_set("colors", "primary", value="#FFF"), "colour 'primary' must be #RRGGBB"),
        (_set("colors", "text", value="red"), "colour 'text'"),
        (_set("colors", "palette", value=[]), "'colors.palette'"),
        (_set("colors", "palette", value=["#12345G"]), "palette colour #0"),
        (_del("fonts", "body"), "'fonts.body'"),
        (_set("fonts", "files", value=["nope.ttf"]), "font #0 file not found"),
        (_set("safe_zone", "top", value=-1), "'safe_zone.top'"),
        (_set("safe_zone", "left", value=1.5), "'safe_zone.left'"),
        (_set("safe_zone", "width", value=0), "'safe_zone.width'"),
        (_set("safe_zone", "right_rail", value=-5), "'safe_zone.right_rail'"),
        (_set("safe_zone", "bottom", value=1651), "no usable area"),
        (_set("safe_zone", "right_rail", value=1015), "no usable area"),
    ],
)
def test_validation_errors(tmp_path, change, message):
    with pytest.raises(BrandError) as e:
        load_brand(_write(tmp_path, _with(change)))
    assert isinstance(e.value, ValueError)
    assert message in str(e.value)


def test_missing_file_and_bad_json(tmp_path):
    with pytest.raises(BrandError, match="not found"):
        load_brand(tmp_path / "none.json")
    with pytest.raises(BrandError, match="invalid JSON"):
        load_brand(_write(tmp_path, "{"))
    with pytest.raises(BrandError, match="top level"):
        load_brand(_write(tmp_path, "[]"))
