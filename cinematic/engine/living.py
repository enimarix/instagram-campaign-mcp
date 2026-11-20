"""Living room (sets.json `living`): a long sofa against the back wall, a rug with a clear
floor spot in front of it (crunches), coffee table, TV corner, bookcase, plants, a warm lamp."""
import math

from kit import asset, box, kenney, lamp, mat, plane, room


def build(cfg, spec):
    room(mat("wall", cg="Wallpaper001A", tile=5.0, px=64, normal=0.8, tint=(0.95, 0.75, 0.55)),
         mat("floor", cg="WoodFloor051", tile=0.6, px=256, tint=(0.75, 0.62, 0.5)),
         mat("ceiling", (0.85, 0.78, 0.68), rough=0.95), back=1.5, left=-2.6)
    kenney("loungeSofa", (0, 1.0), 0)
    art = mat("art", image=asset("art.png"), uv=True, px=None)
    for x in (-0.9, 0.9):
        plane("art", (0.6, 0.45), (x, 1.48, 1.75), art, rot=(math.radians(90), 0, 0))
        box("art_frame", (0.68, 0.02, 0.53), (x, 1.49, 1.75), mat("frame", (0.2, 0.12, 0.08), rough=0.5))
    kenney("rugRectangle", (0.1, -0.9), 90)
    kenney("tableCoffee", (-1.2, 0.2), 0)
    kenney("cabinetTelevision", (-2.3, -0.6), 90)
    kenney("televisionModern", (-2.3, -0.6, 0.55), 90)
    kenney("lampRoundFloor", (1.4, 1.15), 0)
    kenney("bookcaseOpen", (2.1, 1.2), 0)
    kenney("pottedPlant", (-1.6, 1.15), 0)
    kenney("plantSmall2", (1.0, 1.25, 0), 0)
    lamp("floor_lamp", (1.4, 1.1, 1.7), energy=80)
    return None
