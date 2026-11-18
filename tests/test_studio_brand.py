import copy
import json
import re

import pytest

from src.config import APP_HOME
from src.studio.brand import DEFAULT_PATH, BrandError, load_brand, safe_area

GOOD = {
    "version": 1,
    "placeholder": False,
    "name": "Test",
    "handle": "@test",
    "logo": "logo.svg",
    "logo_png": "logo.png",
    "colors": {
        "brand": "#10B981",
        "brand_light": "#34d399",
        "macros": {"kcal": "#3E8EF7", "protein": "#FF6F61", "fat": "#F5C242",
                   "carbs": "#3FBF7F", "weight": "#A78BFA"},
        "light": {"bg": "#F5F7F8", "card": "#FFFFFF", "ink": "#111827", "muted": "#6B7280"},
        "dark": {"bg": "#0E1117", "card": "#1C1C1E", "text": "#FFFFFF", "muted": "#98989F"},
    },
    "fonts": {"display": "Sans", "display_weight": 900, "body": "Sans", "files": []},
    "cta": {"trial": "7 jours gratuits", "url": "example.fr", "stores": "Dispo partout",
            "never_show_price": True},
    "address": {"default": "vous", "humour": "tu", "live": "tu"},
    "safe_zone": {
        "width": 1080, "height": 1920, "top": 269, "bottom": 672, "left": 65, "right": 65,
    },
    "_source": {"note": "ignored"},
}


def _write(tmp_path, data):
    (tmp_path / "logo.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(b"png")
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
    assert brand["placeholder"] is False
    assert (brand["name"], brand["handle"]) == ("macroBody", "@macrobody.fr")
    assert (DEFAULT_PATH.parent / brand["logo"]).is_file()
    png = (DEFAULT_PATH.parent / brand["logo_png"]).read_bytes()
    assert png[:4] == b"\x89PNG"
    assert int.from_bytes(png[16:20], "big") == int.from_bytes(png[20:24], "big") == 512
    assert brand["colors"]["brand"] == "#10B981"
    assert (brand["fonts"]["display"], brand["fonts"]["display_weight"]) == ("Inter Tight", 900)
    assert brand["cta"]["never_show_price"] is True
    assert brand["address"] == {"default": "vous", "humour": "tu", "live": "tu"}
    assert brand["safe_zone"]["width"] == 1080 and brand["safe_zone"]["height"] == 1920
    assert "_source" in brand
    assert load_brand() is brand  # cached


def _colours(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if not k.startswith("_"):
                yield from _colours(v)
    else:
        yield value


def test_committed_colours_are_hex_and_fonts_are_licensed():
    brand = load_brand()
    colours = list(_colours(brand["colors"]))
    assert len(colours) == 15
    assert all(re.fullmatch(r"#[0-9A-F]{6}", c) for c in colours), colours
    licences = (APP_HOME / "motion" / "ASSETS_LICENSES.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"`(public/[^`]+)`", licences))
    files = brand["fonts"]["files"]
    assert files[0].endswith(".ttf")  # the ffmpeg ops need a font FreeType reads
    for rel in files:
        path = (DEFAULT_PATH.parent / rel).resolve()
        assert path.is_file(), rel
        assert path.relative_to(APP_HOME / "motion").as_posix() in listed, rel


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
        (_del("logo_png"), "missing key(s): logo_png"),
        (_set("logo_png", value="missing.png"), "'logo_png' file not found"),
        (_set("logo_png", value="logo.svg"), "'logo_png' must be a .png"),
        (_del("colors", "brand_light"), "missing 'brand_light'"),
        (_del("colors", "dark", "text"), "'colors.dark' is missing 'text'"),
        (_set("colors", "macros", value="#3E8EF7"), "'colors.macros' must be an object"),
        (_set("colors", "brand", value="#FFF"), "colour 'brand' must be #RRGGBB"),
        (_set("colors", "light", "ink", value="red"), "colour 'light.ink'"),
        (_set("colors", "extra", value="#12345G"), "colour 'extra'"),
        (_del("fonts", "body"), "'fonts.body'"),
        (_set("fonts", "display_weight", value=950), "'fonts.display_weight'"),
        (_del("cta"), "missing key(s): cta"),
        (_set("cta", "url", value=""), "'cta.url'"),
        (_set("cta", "never_show_price", value="yes"), "'cta.never_show_price'"),
        (_set("address", "humour", value="toi"), "'address.humour'"),
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


def test_brand_voice_skill_matches_the_kit():
    text = (APP_HOME / "agent" / "skills" / "brand-voice" / "SKILL.md").read_text(encoding="utf-8")
    brand = load_brand()
    for value in (brand["handle"], *(brand["cta"][k] for k in ("trial", "url", "stores"))):
        assert value in text, value
    assert "Never show or say a price" in text and "lien en bio" in text
