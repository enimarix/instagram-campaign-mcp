"""Night kitchen (sets.json `kitchen`): counters, sink and stove under a dark window, a big
fridge glowing cold, two bar stools in front of the counters, a warm pendant. Moonlight comes
from the `night` preset."""
from kit import box, kenney, lamp, mat, room


def build(cfg, spec):
    room(mat("tiles", cg="Wallpaper001A", tile=8.0, px=64, normal=0.6, tint=(0.75, 0.8, 0.85)),
         mat("floor", cg="WoodFloor051", tile=0.6, px=256, tint=(0.55, 0.45, 0.4)),
         mat("ceiling", (0.6, 0.58, 0.55), rough=0.95), back=1.5, left=-2.6)
    box("window", (1.2, 0.02, 0.8), (-0.95, 1.49, 1.75), mat("night_sky", (0.03, 0.06, 0.22), emit=0.6))
    frame = mat("window_frame", (0.9, 0.88, 0.82), rough=0.5)
    for size, loc in (((1.3, 0.05, 0.06), (-0.95, 1.47, 2.17)), ((1.3, 0.05, 0.06), (-0.95, 1.47, 1.33)),
                      ((0.05, 0.05, 0.9), (-0.95, 1.47, 1.75))):
        box("window_frame", size, loc, frame)
    for i, name in enumerate(("kitchenCabinet", "kitchenSink", "kitchenCabinetDrawer", "kitchenStove", "kitchenCabinet")):
        kenney(name, (-1.9 + i * 0.95, 1.15), 0)
    kenney("kitchenFridgeLarge", (2.1, 1.0), 0)
    for x in (-0.45, 0.45):
        kenney("stoolBar", (x, 0.3), 0)
    kenney("kitchenMicrowave", (0.95, 1.2, 0.9), 0)
    lamp("fridge_glow", (1.8, 0.6, 1.2), (0.7, 0.85, 1.0), 120, 0.5)
    lamp("pendant", (0, 0.2, 2.1), energy=60)
    return None
