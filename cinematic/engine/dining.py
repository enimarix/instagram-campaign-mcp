"""Dining room at sunset: long clothed table, roast dinner, chairs, curtained window with a
pixelated photo sky and billboard trees outside. Coordinates: back wall/window at +Y,
camera side at -Y, table centered at (0, -0.5), top at z 0.76. The skit's table seats 5; the
troupe's family dinner (sets.json `dinner`) is a 3 m table with a chair on each seat spot."""
import math

import bpy
from kit import TEX, asset, blob, box, cyl, ellipsoid, empty, folded, mat, plane
from mathutils import Vector

TABLE_Y, TABLE_Z, TABLE_W, TABLE_D = -0.5, 0.76, 2.4, 1.1


def materials():
    return {
        "wall": mat("wallpaper", image=asset("wallpaper.png"), cg="Wallpaper001A", tile=5.0, px=64, normal=0.8, tint=(0.85, 0.8, 0.78)),
        "floor": mat("floor", cg="WoodFloor051", tile=0.6, px=256, tint=(0.75, 0.62, 0.5)),
        "wood": mat("wood", cg="Wood049", tile=1.5, px=256, tint=(0.45, 0.3, 0.22), coat=0.3),
        "trim": mat("trim", (0.2, 0.12, 0.08), rough=0.5, coat=0.2),
        "cloth": mat("tablecloth", cg="Fabric061", tile=3.0, px=128, tint=(0.95, 0.9, 0.78), normal=0.7),
        "curtain": mat("curtain", cg="Fabric061", tile=3.0, px=128, tint=(0.55, 0.18, 0.12), normal=0.7),
        "ceiling": mat("ceiling", (0.82, 0.76, 0.66), rough=0.95),
        "ceramic": mat("ceramic", (0.93, 0.91, 0.86), rough=0.22, coat=0.4),
        "juice": mat("juice", (0.98, 0.58, 0.16), alpha=0.72, rough=0.08, spec=0.9),
        "steel": mat("steel", (0.75, 0.75, 0.75), metal=1.0, rough=0.28),
        "roast": mat("roast", image=asset("roast.png"), tile=12, px=None, rough=0.32, coat=0.5),
        "mash": mat("mash", image=asset("mash.png"), tile=20, px=None, rough=0.7),
        "cran": mat("cranberry", image=asset("cranberry.png"), tile=30, px=None, rough=0.55, tint=(0.7, 0.5, 0.5)),
        "bread": mat("bread", image=asset("bread.png"), tile=25, px=None, rough=0.6),
        "napkin": mat("napkin", (0.62, 0.2, 0.14), rough=0.9),
        "shade": mat("lampshade", (0.9, 0.55, 0.28), emit=0.7, rough=0.9),
        "art": mat("art", image=asset("art.png"), uv=True, px=None),
        "ground": mat("ground", (0.3, 0.18, 0.08), rough=1.0, emit=0.25),
    }


def room(M, sideboard_y=-0.5):
    # back wall with a 1.8 x 1.4 window opening (x -0.9..0.9, z 0.9..2.3)
    for name, size, loc in [("wall_l", (1.6, 0.12, 2.8), (-1.7, 1.3, 1.4)), ("wall_r", (1.6, 0.12, 2.8), (1.7, 1.3, 1.4)),
                            ("wall_b", (1.8, 0.12, 0.9), (0, 1.3, 0.45)), ("wall_t", (1.8, 0.12, 0.5), (0, 1.3, 2.55))]:
        box(name, size, loc, M["wall"])
    box("wall_side", (0.12, 5, 2.8), (-2.5, -1.2, 1.4), M["wall"])
    box("floor", (8, 8, 0.1), (0, -1, -0.05), M["floor"])
    box("ceiling", (8, 8, 0.1), (0, -1, 2.85), M["ceiling"])
    for name, size, loc in [("base_back", (5, 0.03, 0.12), (0, 1.23, 0.06)), ("base_side", (0.03, 5, 0.12), (-2.43, -1.2, 0.06)),
                            ("crown_back", (5, 0.05, 0.08), (0, 1.22, 2.76))]:
        box(name, size, loc, M["trim"])
    # window frame, mullions, sill
    for name, size, loc in [("frame_l", (0.08, 0.16, 1.48), (-0.92, 1.3, 1.6)), ("frame_r", (0.08, 0.16, 1.48), (0.92, 1.3, 1.6)),
                            ("frame_t", (1.92, 0.16, 0.08), (0, 1.3, 2.32)), ("frame_m", (0.05, 0.1, 1.4), (0, 1.3, 1.6)),
                            ("sill", (2.1, 0.26, 0.06), (0, 1.2, 0.88))]:
        box(name, size, loc, M["trim"])
    # curtains either side of the window, tied open
    for side in (-1, 1):
        x = side * 1.15
        folded(f"curtain_{side}", (x - 0.25, 1.17), (x + 0.25, 1.17), 2.5, 0.25, (0, -1), M["curtain"], folds=5, amp=0.03)
    box("curtain_rod", (2.8, 0.03, 0.03), (0, 1.17, 2.52), M["trim"])
    # side wall: framed picture and a sideboard with a lamp
    plane("art", (0.6, 0.45), (-2.43, -0.3, 1.7), M["art"], rot=(math.radians(90), 0, math.radians(90)))
    box("art_frame", (0.03, 0.68, 0.53), (-2.44, -0.3, 1.7), M["trim"])
    box("sideboard", (0.45, 1.4, 0.82), (-2.2, sideboard_y, 0.41), M["wood"])
    cyl("side_lamp_base", 0.05, 0.3, (-2.2, sideboard_y + 0.3, 0.97), M["ceramic"], verts=8, r2=0.09)
    cyl("side_lamp_shade", 0.1, 0.18, (-2.2, sideboard_y + 0.3, 1.2), M["shade"], verts=8, r2=0.16)


def table(M, width=TABLE_W):
    top_z = TABLE_Z
    x0, x1 = -width / 2, width / 2
    y0, y1 = TABLE_Y - TABLE_D / 2, TABLE_Y + TABLE_D / 2
    box("table_top", (width, TABLE_D, 0.04), (0, TABLE_Y, top_z - 0.02), M["cloth"])
    drop = top_z - 0.38
    folded("skirt_front", (x0, y0), (x1, y0), top_z, drop, (0, -1), M["cloth"], folds=9, amp=0.012, flare=0.04)
    folded("skirt_back", (x1, y1), (x0, y1), top_z, drop, (0, 1), M["cloth"], folds=9, amp=0.012, flare=0.04)
    folded("skirt_left", (x0, y1), (x0, y0), top_z, drop, (-1, 0), M["cloth"], folds=4, amp=0.012, flare=0.04)
    folded("skirt_right", (x1, y0), (x1, y1), top_z, drop, (1, 0), M["cloth"], folds=4, amp=0.012, flare=0.04)
    for x in (x0 + 0.1, x1 - 0.1):
        for y in (y0 + 0.1, y1 - 0.1):
            box("leg", (0.06, 0.06, drop), (x, y, drop / 2), M["wood"])


def chair(M, x, y, facing_deg):
    e = empty("chair", (x, y, 0), math.radians(facing_deg))   # local -Y = front of the chair
    w = M["wood"]
    box("seat", (0.46, 0.44, 0.05), (0, 0, 0.46), w, parent=e)
    for lx in (-0.2, 0.2):
        for ly in (-0.18, 0.18):
            box("leg", (0.04, 0.04, 0.45), (lx, ly, 0.225), w, parent=e)
        box("post", (0.045, 0.045, 0.62), (lx, 0.2, 0.78), w, parent=e)
    box("rail_top", (0.46, 0.04, 0.09), (0, 0.2, 1.05), w, parent=e)
    box("rail_mid", (0.4, 0.03, 0.05), (0, 0.2, 0.82), w, parent=e)
    return e


def place_setting(M, x, y, face):
    """Plate, fork, knife, glass, napkin. face = +1 diner on the far side, -1 near side."""
    cyl("plate", 0.14, 0.022, (x, y, TABLE_Z + 0.011), M["ceramic"], verts=12, r2=0.1)
    cyl("plate_well", 0.095, 0.004, (x, y, TABLE_Z + 0.02), M["ceramic"], verts=12)
    box("fork", (0.018, 0.17, 0.006), (x - 0.18, y, TABLE_Z + 0.004), M["steel"])
    box("knife", (0.016, 0.19, 0.005), (x + 0.18, y, TABLE_Z + 0.004), M["steel"])
    box("napkin", (0.09, 0.14, 0.012), (x - 0.27, y, TABLE_Z + 0.006), M["napkin"])
    cyl("glass", 0.036, 0.13, (x + 0.2, y - face * 0.14, TABLE_Z + 0.065), M["juice"], verts=10, r2=0.03)
    # food on the plate: slice of roast + mash
    ellipsoid("plate_roast", (0.05, 0.035, 0.025), (x + 0.03, y, TABLE_Z + 0.04), M["roast"], segs=8, rings=5)
    blob("plate_mash", (0.04, 0.04, 0.025), (x - 0.04, y + 0.01, TABLE_Z + 0.035), M["mash"])


def setting(M, chair_empty):
    """A plate of dinner, fork, knife and glass in front of a chair (its local -Y)."""
    def at(x, y, z):
        return (x, y, TABLE_Z + z)
    e = chair_empty
    cyl("plate", 0.14, 0.022, at(0, -0.52, 0.011), M["ceramic"], verts=12, r2=0.1, parent=e)
    cyl("plate_roast", 0.05, 0.03, at(0.03, -0.52, 0.035), M["roast"], verts=8, parent=e)
    cyl("plate_mash", 0.04, 0.035, at(-0.04, -0.5, 0.035), M["mash"], verts=8, r2=0.05, parent=e)
    box("fork", (0.018, 0.17, 0.006), at(-0.18, -0.52, 0.004), M["steel"], parent=e)
    box("knife", (0.016, 0.19, 0.005), at(0.18, -0.52, 0.004), M["steel"], parent=e)
    cyl("glass", 0.036, 0.13, at(0.2, -0.68, 0.065), M["juice"], verts=10, r2=0.03, parent=e)


def dinner(M):
    # roast turkey on a platter, center left
    cx, cy = -0.35, TABLE_Y - 0.02
    cyl("platter", 0.24, 0.025, (cx, cy, TABLE_Z + 0.0125), M["ceramic"], verts=12, r2=0.18)
    ellipsoid("turkey", (0.17, 0.12, 0.1), (cx, cy, TABLE_Z + 0.1), M["roast"], segs=12, rings=8)
    for s in (-1, 1):
        ellipsoid("drumstick", (0.09, 0.035, 0.035), (cx + 0.12, cy + s * 0.09, TABLE_Z + 0.07), M["roast"],
                  segs=8, rings=5, rot=(0, math.radians(-20), math.radians(s * 25)))
        ellipsoid("wing", (0.06, 0.03, 0.04), (cx - 0.04, cy + s * 0.12, TABLE_Z + 0.1), M["roast"], segs=8, rings=5)
    # mashed potatoes, cranberry, bread basket
    cyl("bowl_mash", 0.12, 0.08, (0.35, cy - 0.05, TABLE_Z + 0.04), M["ceramic"], verts=10, r2=0.07)
    blob("mash", (0.105, 0.105, 0.06), (0.35, cy - 0.05, TABLE_Z + 0.08), M["mash"], sub=2)
    cyl("bowl_cran", 0.1, 0.07, (0.75, cy + 0.08, TABLE_Z + 0.035), M["ceramic"], verts=8, r2=0.06)
    cyl("cran", 0.09, 0.01, (0.75, cy + 0.08, TABLE_Z + 0.065), M["cran"], verts=8)
    cyl("basket", 0.13, 0.07, (-0.85, cy + 0.05, TABLE_Z + 0.035), M["wood"], verts=8, r2=0.1)
    for i in range(5):
        a = i * 2 * math.pi / 5
        ellipsoid("roll", (0.045, 0.035, 0.03), (-0.85 + 0.05 * math.cos(a), cy + 0.05 + 0.05 * math.sin(a), TABLE_Z + 0.08),
                  M["bread"], segs=8, rings=5)


def lamp(M):
    cyl("lamp_cord", 0.006, 0.55, (0, TABLE_Y, 2.58), M["trim"], verts=4)
    cyl("lamp_shade", 0.16, 0.2, (0, TABLE_Y, 2.2), M["shade"], verts=10, r2=0.28)
    light = bpy.data.lights.new("lamp", "POINT")
    light.color, light.energy, light.shadow_soft_size = (1.0, 0.68, 0.38), 90, 0.2
    o = bpy.data.objects.new("lamp", light)
    o.location = (0, TABLE_Y, 2.05)
    bpy.context.collection.objects.link(o)


def outside(M, cfg):
    """Billboard trees (PS2 foliage cards) on a dark field, in front of the photo sky."""
    import random
    random.seed(11)
    plane("field", (80, 40), (0, 22, 0.0), M["ground"], rot=(0, 0, 0))
    # backlit foliage glows a little (emission) so it reads warm, not as black cut-outs
    cards = [mat(f"tree{i}", image=asset(f"tree{i}.png"), uv=True, px=None, alpha="texture", rough=1.0, emit=0.35)
             for i in range(3)]
    for _ in range(24):
        d = random.uniform(28, 48)
        x = random.uniform(-d * 0.7, d * 0.7)
        h = random.uniform(5, 8)
        o = plane("tree", (h * 0.66, h), (x, 1.3 + d, h / 2 - 1.2), random.choice(cards))
        o.rotation_euler.z = random.uniform(-0.2, 0.2)
    for _ in range(60):                                    # hedges hide the bare field
        d = random.uniform(10, 26)
        h = random.uniform(1.4, 2.6)
        plane("hedge", (h * 1.4, h), (random.uniform(-d, d), 1.3 + d, h / 2 - 0.5), random.choice(cards))
    for _ in range(70):                                    # dense, distant tree line on the horizon
        d = random.uniform(55, 75)
        h = random.uniform(5, 9)
        plane("treeline", (h * 0.66, h), (random.uniform(-d, d), 1.3 + d, h / 2 - 1.5), random.choice(cards))


def sky(cfg):
    """Photo sky (Poly Haven, CC0), pixelated, warmed, shown only to camera rays; the room
    gets a flat warm ambient instead so interior light stays art-directed. Returns the sun
    direction (unit vector pointing toward the sun) after rotating the sky."""
    s = bpy.context.scene
    w = s.world
    nt, links = w.node_tree, w.node_tree.links
    out = nt.nodes["World Output"]
    bg = nt.nodes["Background"]
    img = bpy.data.images.load(f"{TEX}/{cfg.get('sky', 'belfast_sunset_puresky_1k.hdr')}")
    # find the sun: brightest pixel of the equirect image
    import numpy as np
    px = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    lum = px.reshape(-1, 4)[:, :3].sum(1)
    i = int(lum.argmax())
    u, v = (i % img.size[0] + 0.5) / img.size[0], (i // img.size[0] + 0.5) / img.size[1]
    az_img = 2 * math.pi * (u - 0.5)                    # Blender equirect: u = atan2(y, -x)/2pi + .5
    sun_xy_img = Vector((-math.cos(az_img), math.sin(az_img)))
    want_az = math.radians(cfg.get("sun_azimuth", 112))  # 90 = straight behind the window (+Y)
    rot = math.atan2(sun_xy_img.y, sun_xy_img.x) - want_az
    elev = (v - 0.5) * math.pi
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image, env.interpolation = img, "Closest"       # chunky sky pixels
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value = (0, 0, rot)
    links.new(tc.outputs["Generated"], mp.inputs["Vector"])
    links.new(mp.outputs["Vector"], env.inputs["Vector"])
    # gradient map: keep the photo's clouds and sun glow, recolor along a sunset palette.
    # t = 0.45 + 0.13 * log2(brightness / median sky) + up to 0.15 near the horizon.
    # (log because brightness spans 0.2x..20x around the sun glow)
    upper = lum.reshape(img.size[1], img.size[0])[img.size[1] // 2:] / 3.0
    gain = 1.0 / max(1e-6, float(np.median(upper)))

    def math_node(op, a, b=None):
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = op
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                links.new(v, n.inputs[i])
        return n.outputs[0]

    bw = nt.nodes.new("ShaderNodeRGBToBW")
    links.new(env.outputs["Color"], bw.inputs["Color"])
    rel = math_node("MULTIPLY", bw.outputs["Val"], gain)
    rel = math_node("MAXIMUM", rel, 1e-4)
    t = math_node("MULTIPLY_ADD", math_node("LOGARITHM", rel, 2.0), 0.13)
    t.node.inputs[2].default_value = 0.45
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    hz = nt.nodes.new("ShaderNodeMapRange")                 # z 0 (horizon) -> 0.15, z 0.4 -> 0
    hz.inputs["From Min"].default_value, hz.inputs["From Max"].default_value = 0.0, 0.4
    hz.inputs["To Min"].default_value, hz.inputs["To Max"].default_value = 0.15, 0.0
    links.new(sep.outputs["Z"], hz.inputs["Value"])
    t = math_node("ADD", t, hz.outputs["Result"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    els = ramp.color_ramp.elements
    stops = cfg.get("sky_palette", [[0.0, [0.12, 0.04, 0.08]], [0.3, [0.5, 0.1, 0.06]], [0.55, [0.95, 0.32, 0.05]],
                                    [0.8, [1.0, 0.6, 0.15]], [1.0, [1.0, 0.85, 0.5]]])
    els[0].position, els[0].color = stops[0][0], (*stops[0][1], 1)
    els[1].position, els[1].color = stops[-1][0], (*stops[-1][1], 1)
    for pos, col in stops[1:-1]:
        e = els.new(pos)
        e.color = (*col, 1)
    links.new(t, ramp.inputs["Fac"])
    sky_bg = nt.nodes.new("ShaderNodeBackground")
    sky_bg.inputs["Strength"].default_value = cfg.get("sky_strength", 1.0)
    links.new(ramp.outputs["Color"], sky_bg.inputs["Color"])
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
    links.new(bg.outputs["Background"], mix.inputs[1])
    links.new(sky_bg.outputs["Background"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return Vector((math.cos(want_az) * math.cos(elev), math.sin(want_az) * math.cos(elev), math.sin(elev))).normalized()


def build(cfg, spec=None):
    M = materials()
    if spec:  # the troupe's family dinner
        room(M, sideboard_y=0.55)
        table(M, 3.0)
        for sp in spec["spots"].values():
            if sp.get("seat"):
                setting(M, chair(M, *sp["at"], sp["facing"]))
        dinner(M)
        lamp(M)
        outside(M, cfg)
        return sky(cfg)
    room(M)
    table(M)
    # chairs: three on the far side facing the camera, two on the near side (backs to camera)
    for x in (-0.75, 0.0, 0.75):
        chair(M, x, TABLE_Y + 0.75, 0)
    for x in (-0.75, 0.75):
        chair(M, x, TABLE_Y - 0.78, 180)
    for x in (-0.75, 0.0, 0.75):
        place_setting(M, x, TABLE_Y + 0.3, +1)
    for x in (-0.75, 0.75):
        place_setting(M, x, TABLE_Y - 0.32, -1)
    dinner(M)
    lamp(M)
    outside(M, cfg)
    return sky(cfg)
