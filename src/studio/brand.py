"""
Brand kit (GOAL.md §3.1): `brand/brand.json`.

Plain JSON so the agent and `motion/` (TypeScript) read the same file. Shape:
`version`, `placeholder`, `name`, `handle`, `logo` (path relative to the JSON file),
`colors` (`#RRGGBB` for primary/secondary/accent/background/text, plus a `palette`
list), `fonts` (`display`/`body` family names, `files` paths relative to the JSON file),
`safe_zone` (pixel insets on a `width` x `height` canvas: top/bottom/left/right and an
optional `right_rail`, the Reels button column). Keys starting with `_` are notes.

The default file is `APP_HOME/brand/brand.json` (see `src.taxonomy` for APP_HOME).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from src.config import APP_HOME

DEFAULT_PATH = APP_HOME / "brand" / "brand.json"

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
NAMED_COLORS = ("primary", "secondary", "accent", "background", "text")
INSETS = ("top", "bottom", "left", "right")


class BrandError(ValueError):
    """A missing or malformed brand kit file."""


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _text(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _check(data: Any, path: Path) -> Dict[str, Any]:
    def fail(msg: str) -> BrandError:
        return BrandError(f"{path}: {msg}")

    if not isinstance(data, dict):
        raise fail("top level must be an object")
    missing = [
        k for k in ("version", "placeholder", "name", "handle", "logo", "colors", "fonts",
                    "safe_zone") if k not in data
    ]
    if missing:
        raise fail(f"missing key(s): {', '.join(missing)}")
    if not _is_int(data["version"]) or data["version"] < 1:
        raise fail("'version' must be a positive integer")
    if not isinstance(data["placeholder"], bool):
        raise fail("'placeholder' must be true or false")
    for key in ("name", "handle"):
        if not _text(data[key]):
            raise fail(f"'{key}' must be a non-empty string")

    def file_exists(rel: Any, what: str) -> None:
        if not _text(rel):
            raise fail(f"{what} must be a non-empty path")
        if not (path.parent / rel).is_file():
            raise fail(f"{what} file not found: {path.parent / rel}")

    file_exists(data["logo"], "'logo'")

    colors = data["colors"]
    if not isinstance(colors, dict):
        raise fail("'colors' must be an object")
    for name in NAMED_COLORS:
        if name not in colors:
            raise fail(f"'colors' is missing '{name}'")
    for name, value in colors.items():
        if name.startswith("_") or name == "palette":
            continue
        if not isinstance(value, str) or not HEX.match(value):
            raise fail(f"colour '{name}' must be #RRGGBB, got {value!r}")
    palette = colors.get("palette")
    if not isinstance(palette, list) or not palette:
        raise fail("'colors.palette' must be a non-empty list")
    for i, value in enumerate(palette):
        if not isinstance(value, str) or not HEX.match(value):
            raise fail(f"palette colour #{i} must be #RRGGBB, got {value!r}")

    fonts = data["fonts"]
    if not isinstance(fonts, dict):
        raise fail("'fonts' must be an object")
    for key in ("display", "body"):
        if not _text(fonts.get(key)):
            raise fail(f"'fonts.{key}' must be a non-empty family name")
    files = fonts.get("files", [])
    if not isinstance(files, list):
        raise fail("'fonts.files' must be a list")
    for i, rel in enumerate(files):
        file_exists(rel, f"font #{i}")

    zone = data["safe_zone"]
    if not isinstance(zone, dict):
        raise fail("'safe_zone' must be an object")
    for key in ("width", "height"):
        if not _is_int(zone.get(key)) or zone[key] <= 0:
            raise fail(f"'safe_zone.{key}' must be a positive integer")
    for key in INSETS + ("right_rail",):
        if key == "right_rail" and key not in zone:
            continue
        if not _is_int(zone.get(key)) or zone[key] < 0:
            raise fail(f"'safe_zone.{key}' must be a non-negative integer")
    _, _, w, h = _area(zone)
    if w <= 0 or h <= 0:
        raise fail(f"'safe_zone' insets leave no usable area ({w}x{h})")
    return data


def _area(zone: Dict[str, Any]) -> Tuple[int, int, int, int]:
    right = max(zone["right"], zone.get("right_rail", 0))
    return (
        zone["left"],
        zone["top"],
        zone["width"] - zone["left"] - right,
        zone["height"] - zone["top"] - zone["bottom"],
    )


@lru_cache(maxsize=None)
def _load(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BrandError(f"brand file not found: {path}") from None
    except json.JSONDecodeError as e:
        raise BrandError(f"{path}: invalid JSON: {e}") from None
    return _check(data, path)


def load_brand(path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Load and validate the brand kit (cached per path). Treat the result as read-only."""
    return _load(Path(path).resolve() if path else DEFAULT_PATH)


def safe_area(brand: Dict[str, Any]) -> Tuple[int, int, int, int]:
    """`(x, y, w, h)` of the region no Reels UI covers; the right inset honours `right_rail`."""
    return _area(brand["safe_zone"])
