"""Beach at sunset (sets.json `beach`): sand, the sea out to the photo sky (dining.sky), an
umbrella, towels on the towel spots (lie on them), a beach ball."""
import math

import dining
from kit import blob, box, cyl, mat, plane


def build(cfg, spec):
    plane("sand", (60, 60), (0, 10, 0), mat("sand", (0.92, 0.72, 0.48), rough=0.95), rot=(0, 0, 0))
    plane("sea", (400, 200), (0, 106, 0.02), mat("sea", (0.04, 0.32, 0.42), rough=0.1, spec=0.9, emit=0.35),
          rot=(0, 0, 0))
    pole = mat("pole", (0.9, 0.9, 0.85), rough=0.5)
    cyl("umbrella_pole", 0.025, 2.2, (-1.4, 0.9, 1.1), pole, verts=6)
    cyl("umbrella", 0.05, 0.45, (-1.4, 0.9, 2.1), mat("canvas", (0.9, 0.2, 0.15), rough=0.8), verts=8, r2=1.1)
    for name, color in (("towel0", (0.1, 0.45, 0.8)), ("towel1", (0.95, 0.75, 0.1))):
        sp = spec["spots"][name]
        box(name, (1.8, 0.8, 0.02), (*sp["at"], 0.01), mat(name, color, rough=0.9),
            rot=(0, 0, math.radians(sp["facing"] + 90)))
    blob("ball", (0.18, 0.18, 0.18), (1.5, 0.9, 0.18), mat("ball", (1.0, 0.85, 0.2), rough=0.4), sub=2, smooth=True)
    return dining.sky({**cfg, "sun_azimuth": 95})
