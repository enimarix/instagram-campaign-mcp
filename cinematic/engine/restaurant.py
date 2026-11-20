"""Restaurant (sets.json `restaurant`): three tables for two (each between two seat spots)
with cloths, dinner and a candle, warm wall lamps, framed art; a waiter spot by the kitchen
door."""
import math

import dining
from kit import box, cyl, lamp, mat, room


def build(cfg, spec):
    M = dining.materials()
    room(mat("bistro_wall", cg="Wallpaper001A", tile=5.0, px=64, normal=0.8, tint=(0.75, 0.3, 0.2)),
         M["floor"], M["ceiling"], back=1.9, left=-3.0, right=3.0)
    box("door", (0.9, 0.06, 2.1), (2.4, 1.86, 1.05), M["trim"])
    seats = spec["spots"]
    for t in ("t0", "t1", "t2"):
        a, b = seats[t + "a"], seats[t + "b"]
        x, y = (a["at"][0] + b["at"][0]) / 2, (a["at"][1] + b["at"][1]) / 2
        cyl("table", 0.5, 0.04, (x, y, dining.TABLE_Z - 0.02), M["cloth"], verts=12)
        cyl("table_leg", 0.05, dining.TABLE_Z, (x, y, dining.TABLE_Z / 2), M["trim"], verts=6)
        cyl("candle", 0.02, 0.12, (x, y, dining.TABLE_Z + 0.06), mat("wax", (0.95, 0.9, 0.8), emit=0.3), verts=6)
        lamp("candle_light", (x, y, dining.TABLE_Z + 0.2), (1.0, 0.6, 0.3), 25, 0.05)
        for sp in (a, b):
            dining.setting(M, dining.chair(M, *sp["at"], sp["facing"]))
    for x in (-1.5, 1.5):
        lamp("wall_lamp", (x, 1.7, 2.0), energy=70)
        dining.plane("art", (0.7, 0.5), (x, 1.83, 1.6), M["art"], rot=(math.radians(90), 0, 0))
    return None
