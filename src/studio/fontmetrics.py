"""
Text width in a TrueType font, read straight from its `cmap` and `hmtx` tables (stdlib
only), so the ffmpeg ops can wrap and centre text in the proportional brand font.

Widths are the sum of the glyph advances at `size` px per em, without kerning: drawtext
on ffmpeg 6.1 (CI) does not kern, and later builds only pull pairs a few px closer.
"""

from __future__ import annotations

import struct
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple, Union


@lru_cache(maxsize=8)
def _metrics(path: Path) -> Tuple[int, Dict[int, int], List[int], int, int, int]:
    """(units per em, code point -> glyph id, advance per glyph id, OS/2 win ascent +
    descent, hhea ascender, hhea descender (negative))."""
    data = path.read_bytes()
    tables = {}
    for i in range(struct.unpack_from(">H", data, 4)[0]):
        tag, _, offset, _ = struct.unpack_from(">4sIII", data, 12 + 16 * i)
        tables[tag.decode("latin-1")] = offset
    upem = struct.unpack_from(">H", data, tables["head"] + 18)[0]
    n_metrics = struct.unpack_from(">H", data, tables["hhea"] + 34)[0]
    win = sum(struct.unpack_from(">HH", data, tables["OS/2"] + 74))
    ascender, descender = struct.unpack_from(">hh", data, tables["hhea"] + 4)
    # hmtx: n_metrics (advance, left bearing) pairs; later glyphs reuse the last advance.
    advances = list(struct.unpack_from(">" + "Hh" * n_metrics, data, tables["hmtx"])[0::2])

    cmap: Dict[int, int] = {}
    base, records = tables["cmap"], {}
    for i in range(struct.unpack_from(">H", data, base + 2)[0]):
        platform, encoding, offset = struct.unpack_from(">HHI", data, base + 4 + 8 * i)
        records[(platform, encoding)] = base + offset
    sub = records.get((3, 10)) or records.get((3, 1)) or records.get((0, 3))
    if sub is None:
        raise ValueError(f"{path}: no Unicode cmap")
    fmt = struct.unpack_from(">H", data, sub)[0]
    if fmt == 12:
        for i in range(struct.unpack_from(">I", data, sub + 12)[0]):
            start, end, glyph = struct.unpack_from(">III", data, sub + 16 + 12 * i)
            for code in range(start, end + 1):
                cmap[code] = glyph + code - start
    elif fmt == 4:
        segs = struct.unpack_from(">H", data, sub + 6)[0] // 2
        ends = struct.unpack_from(f">{segs}H", data, sub + 14)
        starts = struct.unpack_from(f">{segs}H", data, sub + 16 + 2 * segs)
        deltas = struct.unpack_from(f">{segs}h", data, sub + 16 + 4 * segs)
        ranges_at = sub + 16 + 6 * segs
        ranges = struct.unpack_from(f">{segs}H", data, ranges_at)
        for i in range(segs):
            for code in range(starts[i], ends[i] + 1):
                if code == 0xFFFF:
                    continue
                if ranges[i]:
                    at = ranges_at + 2 * i + ranges[i] + 2 * (code - starts[i])
                    glyph = struct.unpack_from(">H", data, at)[0]
                    glyph = (glyph + deltas[i]) % 65536 if glyph else 0
                else:
                    glyph = (code + deltas[i]) % 65536
                if glyph:
                    cmap[code] = glyph
    else:
        raise ValueError(f"{path}: cmap format {fmt} not supported")
    return upem, cmap, advances, win, ascender, descender


def text_width(text: str, size: float, font: Union[str, Path]) -> float:
    """Width in px of one line of `text` at `size` px per em (missing glyphs: .notdef)."""
    upem, cmap, advances, *_ = _metrics(Path(font).resolve())
    last = advances[-1]
    units = sum(advances[g] if g < len(advances) else last
                for g in (cmap.get(ord(c), 0) for c in text))
    return units * size / upem


def ass_em(size: float, font: Union[str, Path]) -> float:
    """The em in px that libass draws at style font size `size`: like VSFilter it scales
    the font so its OS/2 win ascent + descent (not the em) is `size` px tall."""
    upem, _, _, win, *_ = _metrics(Path(font).resolve())
    return size * upem / win


def ascent_descent(size: float, font: Union[str, Path]) -> Tuple[float, float]:
    """(ascent, descent) in px at `size` px per em, both positive (the font's hhea line)."""
    upem, *_, ascender, descender = _metrics(Path(font).resolve())
    return ascender * size / upem, -descender * size / upem
