"""Physique Scan v2 (owner 2026-11-25): a detailed 3D anatomy object (a muscle belly, its fibres
showing where it is cut open) with many bands of type wrapped round it: rolling, rocking,
whooshing up and down between stops and squeezing it there, each spot its own grip (the flesh
pinched under each band, bulging between them), in a free palette. Standalone: no troupe.

    blender -b -P cinematic/engine/anatomy.py -- <shots.json>

<shots.json>: out, fps, size, samples, shots [{id, frames, stills, palette, bands [{text, tone,
path (its stops, 0..1 along the belly), squeeze (0..1, or one per stop), turns, tilt (degrees),
cinch (pulls tight first), lag (when it leaves, share of the shot)}], camera {kind: orbit | push | glide | top, start (degrees)}, seed}].
"""
import json
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Vector

ENGINE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(ENGINE, "..", "..", "motion", "public", "fonts")
FONT = {"sans": "InterTight-Black.ttf", "serif": "InstrumentSerif-Italic.ttf"}
LIFT = 2 ** 1.3  # flat colours are lifted by this to show true under the scene's exposure

LENGTH = 1.0  # the muscle belly's length (m, scene units), along Z
RADIUS = 0.135  # its widest radius
BELLY = (0.16, 0.86)  # where the belly runs along the length (the rest: tendons)
CUT = 0.80  # the belly is cut open here (its upper end gone: the fibres show)
# palettes: background, muscle (deep, mid, light), tendon, band tones {name: (band, type, face)}
PALETTES = {
    "lab": {"bg": (0.95, 0.92, 0.85), "floor": (0.90, 0.86, 0.78), "muscle": ((0.22, 0.01, 0.03), (0.55, 0.04, 0.06), (0.92, 0.32, 0.28)),
            "tendon": (0.93, 0.90, 0.84),
            "tones": {"light": ((0.97, 0.95, 0.90), (0.11, 0.13, 0.24), "sans"), "dark": ((0.11, 0.13, 0.24), (0.97, 0.95, 0.90), "serif"),
                      "accent": ((0.93, 0.43, 0.24), (0.97, 0.95, 0.90), "sans"), "pop": ((0.40, 0.62, 0.58), (0.97, 0.95, 0.90), "sans")}},
    "neon": {"bg": (0.04, 0.04, 0.09), "floor": (0.06, 0.06, 0.12), "muscle": ((0.20, 0.0, 0.05), (0.62, 0.02, 0.14), (1.0, 0.38, 0.50)),
             "tendon": (0.85, 0.88, 0.95),
             "tones": {"light": ((0.92, 1.0, 0.20), (0.05, 0.05, 0.10), "sans"), "dark": ((0.05, 0.05, 0.10), (0.20, 1.0, 0.85), "serif"),
                       "accent": ((1.0, 0.18, 0.55), (1.0, 1.0, 1.0), "sans"), "pop": ((0.20, 0.55, 1.0), (1.0, 1.0, 1.0), "sans")}},
    "candy": {"bg": (1.0, 0.80, 0.86), "floor": (0.98, 0.74, 0.82), "muscle": ((0.28, 0.01, 0.07), (0.70, 0.08, 0.16), (1.0, 0.48, 0.46)),
              "tendon": (1.0, 0.96, 0.92),
              "tones": {"light": ((1.0, 1.0, 1.0), (0.30, 0.10, 0.60), "sans"), "dark": ((0.30, 0.10, 0.60), (1.0, 0.95, 0.40), "serif"),
                        "accent": ((1.0, 0.85, 0.15), (0.30, 0.10, 0.60), "sans"), "pop": ((0.15, 0.80, 0.70), (1.0, 1.0, 1.0), "sans")}},
}


def lin(c):
    """sRGB -> linear (Blender's colour inputs)."""
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def flat(name, color):
    """One colour, unlit, true under the exposure."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (*lin(color), 1)
    emit.inputs["Strength"].default_value = LIFT
    nt.links.new(emit.outputs[0], nt.nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    return m


def _curves(action):
    """An action's F-curves (Blender 5 keeps them in layered channelbags)."""
    if hasattr(action, "fcurves"):
        try:
            return list(action.fcurves)
        except (AttributeError, RuntimeError):
            pass
    return [fc for layer in getattr(action, "layers", ()) for strip in layer.strips
            for bag in getattr(strip, "channelbags", ()) for fc in bag.fcurves]


# ---------------- the scene ----------------

def reset(cfg, palette):
    bpy.ops.wm.read_homefile(use_empty=True)
    s = bpy.context.scene
    s.render.fps = cfg.get("fps", 24)
    try:
        s.render.engine = "BLENDER_EEVEE"
    except TypeError:
        s.render.engine = "BLENDER_EEVEE_NEXT"
    s.render.resolution_x, s.render.resolution_y = cfg.get("size", [720, 1280])
    e = s.eevee
    for attr, val in [("taa_render_samples", cfg.get("samples", 64)), ("use_shadows", True),
                      ("shadow_pool_size", "256"), ("use_raytracing", True), ("use_fast_gi", True)]:
        if hasattr(e, attr):
            try:
                setattr(e, attr, val)
            except (TypeError, ValueError):
                pass
    s.view_settings.view_transform, s.view_settings.look = "Standard", "None"  # true palette colours
    s.view_settings.exposure = -1.3
    s.world = bpy.data.worlds.new("world")
    s.world.use_nodes = True
    bg = s.world.node_tree.nodes["Background"]
    bg.inputs[0].default_value, bg.inputs[1].default_value = (*lin(palette["bg"]), 1), 0.35
    s.render.image_settings.file_format = "PNG"
    s.render.image_settings.color_mode = "RGB"
    return s


def studio(palette):
    """A seamless backdrop in the palette's colour (a curved sweep), a soft key, two rims."""
    m = flat("sweep", palette["floor"])  # unlit: the palette's colour exactly
    bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 4, 0))
    o = bpy.context.object
    o.name = "sweep"
    o.data.materials.append(m)
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=40, use_grid_fill=True)
    for v in bm.verts:  # bend the far half up into a wall: no horizon
        if v.co.y > -2:
            t = (v.co.y + 2) / 22
            v.co.z = 26 * t * t
    bm.to_mesh(o.data)
    bm.free()
    for poly in o.data.polygons:
        poly.use_smooth = True
    o.location = (0, 2.5, -0.6)

    def area(name, pos, energy, size, color):
        li = bpy.data.lights.new(name, "AREA")
        li.energy, li.size, li.color = energy, size, color
        lo = bpy.data.objects.new(name, li)
        bpy.context.collection.objects.link(lo)
        lo.location = pos
        lo.rotation_euler = (Vector((0, 0, 0.5)) - Vector(pos)).to_track_quat("-Z", "Y").to_euler()

    area("key", (-2.0, -2.5, 3.5), 900, 3.0, (1.0, 0.96, 0.92))
    area("rim_l", (-3.0, 2.5, 1.5), 700, 1.5, (0.85, 0.92, 1.0))
    area("rim_r", (3.0, 2.0, 2.0), 900, 1.5, (1.0, 0.92, 0.88))
    area("fill", (2.5, -3.0, 0.8), 150, 4.0, (1.0, 1.0, 1.0))


# ---------------- the muscle ----------------

def profile(u):
    """The belly's radius at u (0..1 along the length): a spindle, tendons beyond BELLY."""
    a, b = BELLY
    if u <= a:  # the tendon: a cord widening into the belly
        return 0.028 + 0.012 * (u / a) ** 3
    if u >= b:
        return 0.022
    t = (u - a) / (b - a)
    return 0.022 + (RADIUS - 0.022) * math.sin(math.pi * t) ** 0.75 * (1 + 0.12 * math.sin(2 * math.pi * t))


def section(palette):
    """The cut face: bundles (cells) of fibres, each in its pink sheath, white seams between."""
    deep, mid, light = palette["muscle"]
    m = bpy.data.materials.new("section")
    m.use_nodes = True
    nt, ln = m.node_tree, m.node_tree.links
    p = nt.nodes["Principled BSDF"]
    p.inputs["Roughness"].default_value = 0.25
    p.inputs["Coat Weight"].default_value = 0.8
    p.inputs["Subsurface Weight"].default_value = 0.5
    p.inputs["Subsurface Scale"].default_value = 0.01
    tc = nt.nodes.new("ShaderNodeTexCoord")
    big = nt.nodes.new("ShaderNodeTexVoronoi")
    big.feature, big.inputs["Scale"].default_value = "DISTANCE_TO_EDGE", 7.0
    small = nt.nodes.new("ShaderNodeTexVoronoi")
    small.feature, small.inputs["Scale"].default_value = "DISTANCE_TO_EDGE", 60.0
    for v in (big, small):
        ln.new(tc.outputs["Object"], v.inputs["Vector"])
    edge = nt.nodes.new("ShaderNodeMapRange")
    edge.inputs["From Min"].default_value, edge.inputs["From Max"].default_value = 0.0, 0.035
    ln.new(big.outputs["Distance"], edge.inputs["Value"])
    fib = nt.nodes.new("ShaderNodeMapRange")
    fib.inputs["From Min"].default_value, fib.inputs["From Max"].default_value = 0.0, 0.12
    ln.new(small.outputs["Distance"], fib.inputs["Value"])
    inner = nt.nodes.new("ShaderNodeMix")
    inner.data_type = "RGBA"
    inner.inputs["A"].default_value = (*lin(deep), 1)
    inner.inputs["B"].default_value = (*lin(light), 1)
    ln.new(fib.outputs["Result"], inner.inputs["Factor"])
    out = nt.nodes.new("ShaderNodeMix")
    out.data_type = "RGBA"
    out.inputs["A"].default_value = (*lin(palette["tendon"]), 1)
    ln.new(inner.outputs["Result"], out.inputs["B"])
    ln.new(edge.outputs["Result"], out.inputs["Factor"])
    ln.new(out.outputs["Result"], p.inputs["Base Color"])
    add = nt.nodes.new("ShaderNodeMath")
    add.operation = "ADD"
    ln.new(edge.outputs["Result"], add.inputs[0])
    ln.new(fib.outputs["Result"], add.inputs[1])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.6
    bump.inputs["Distance"].default_value = 0.006
    ln.new(add.outputs[0], bump.inputs["Height"])
    ln.new(bump.outputs["Normal"], p.inputs["Normal"])
    return m


def bundle_mat(palette, i, rng):
    """One fascicle: wet subsurface red (a shade of its own), fine fibres along its length (UV u
    along, v around), whitening into tendon at its lower end."""
    deep, mid, light = palette["muscle"]
    m = bpy.data.materials.new(f"bundle{i}")
    m.use_nodes = True
    nt, ln = m.node_tree, m.node_tree.links
    p = nt.nodes["Principled BSDF"]
    p.inputs["Roughness"].default_value = 0.28
    p.inputs["Subsurface Weight"].default_value = 0.55
    p.inputs["Subsurface Radius"].default_value = (1.0, 0.2, 0.15)
    p.inputs["Subsurface Scale"].default_value = 0.01
    p.inputs["Coat Weight"].default_value = 0.8
    p.inputs["Coat Roughness"].default_value = 0.06
    uv = nt.nodes.new("ShaderNodeUVMap")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ln.new(uv.outputs[0], sep.inputs[0])
    # fibres: fine stripes round the bundle (v), a little wavy
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type, wave.bands_direction = "BANDS", "Y"
    wave.inputs["Scale"].default_value = 16.0
    wave.inputs["Distortion"].default_value = 3.0
    wave.inputs["Detail"].default_value = 3
    ln.new(uv.outputs[0], wave.inputs["Vector"])
    k = rng.uniform(-0.12, 0.12)
    shade = [tuple(max(0, min(1, x * (1 + k))) for x in c) for c in (deep, mid, light)]
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*lin(shade[0]), 1)
    ramp.color_ramp.elements[1].position, ramp.color_ramp.elements[1].color = 0.25, (*lin(shade[1]), 1)
    e = ramp.color_ramp.elements.new(0.97)
    e.color = (*lin(shade[2]), 1)
    ln.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    # tendon at the lower end: u < the belly's start (as a share of the bundle)
    tend = nt.nodes.new("ShaderNodeMapRange")
    a = BELLY[0] / CUT
    tend.inputs["From Min"].default_value, tend.inputs["From Max"].default_value = a + 0.04, a - 0.02
    ln.new(sep.outputs[0], tend.inputs["Value"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    ln.new(tend.outputs["Result"], mix.inputs["Factor"])
    ln.new(ramp.outputs["Color"], mix.inputs["A"])
    mix.inputs["B"].default_value = (*lin(palette["tendon"]), 1)
    ln.new(mix.outputs["Result"], p.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    bump.inputs["Distance"].default_value = 0.002
    ln.new(wave.outputs["Fac"], bump.inputs["Height"])
    ln.new(bump.outputs["Normal"], p.inputs["Normal"])
    return m


def muscle(palette, rng, seg=14, rows=150):
    """The belly as ~50 fascicles (the anatomy-book muscle): each a tube from the tendon up to
    the cut at CUT, its centre at a fixed place of the cross-section scaled by `profile`, a
    little twisted, its own shade; their ends at the cut show the inside. One mesh object."""
    places = [(0.0, 0.0)]
    for ring_r, n in ((0.32, 7), (0.6, 13), (0.85, 19)):
        off = rng.uniform(0, 1)
        places += [(ring_r * math.cos(2 * math.pi * (k + off) / n), ring_r * math.sin(2 * math.pi * (k + off) / n))
                   for k in range(n)]
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    mats = []
    for b, (px, py) in enumerate(places):
        rr = 0.24 if (px or py) else 0.3  # its share of the radius: neighbours overlap a little
        rr *= rng.uniform(0.9, 1.1)
        twist = rng.uniform(0.15, 0.35)
        ring_list = []
        for j in range(rows + 1):
            u = CUT * j / rows
            r = profile(u)
            a = twist * u * math.pi
            cx = (px * math.cos(a) - py * math.sin(a)) * r
            flat_ = 0.82 if u >= BELLY[0] else 0.82 - 0.5 * min(1, (BELLY[0] - u) / 0.06)  # a flat tendon
            cy = (px * math.sin(a) + py * math.cos(a)) * r * flat_
            br = rr * r * (1 + 0.06 * math.sin(7 * u + b))
            row = [bm.verts.new((cx + br * math.cos(2 * math.pi * i / seg),
                                 cy + 0.82 * br * math.sin(2 * math.pi * i / seg), u * LENGTH))
                   for i in range(seg)]
            ring_list.append(row)
        mats.append(bundle_mat(palette, b, rng))
        for j in range(rows):
            for i in range(seg):
                f = bm.faces.new((ring_list[j][i], ring_list[j][(i + 1) % seg],
                                  ring_list[j + 1][(i + 1) % seg], ring_list[j + 1][i]))
                f.material_index, f.smooth = b, True
                for loop, (du, dv) in zip(f.loops, ((0, 0), (0, 1), (1, 1), (1, 0))):
                    loop[uvl].uv = ((j + du) / rows, (i + dv) / seg)
        cap = bm.faces.new(ring_list[-1])  # its cut end: the inside
        cap.material_index = len(places)
        cap.smooth = True
        low = bm.faces.new(list(reversed(ring_list[0])))
        low.material_index = b
    vein = len(places) + 1  # its material index (after the bundles and the cut face)
    for v in range(3):  # veins winding up the belly, on its surface
        a0, wind, vr = rng.uniform(0, 2 * math.pi), rng.uniform(-1.2, 1.2), rng.uniform(0.006, 0.009)
        rows_v = []
        for j in range(rows + 1):
            u = BELLY[0] + (CUT - 0.02 - BELLY[0]) * j / rows
            a = a0 + wind * (u - BELLY[0]) * 3 + 0.25 * math.sin(14 * u + v)
            r = profile(u) * 1.1  # on the outer bundles
            c = Vector((r * math.cos(a), 0.82 * r * math.sin(a), u * LENGTH))
            nrm = Vector((math.cos(a), math.sin(a), 0))
            side = nrm.cross(Vector((0, 0, 1)))
            rows_v.append([bm.verts.new(c + vr * (nrm * math.cos(2 * math.pi * i / 8) + side * math.sin(2 * math.pi * i / 8)))
                           for i in range(8)])
        for j in range(rows):
            for i in range(8):
                f = bm.faces.new((rows_v[j][i], rows_v[j][(i + 1) % 8], rows_v[j + 1][(i + 1) % 8], rows_v[j + 1][i]))
                f.material_index, f.smooth = vein, True
    me = bpy.data.meshes.new("muscle")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("muscle", me)
    bpy.context.collection.objects.link(o)
    for m in mats:
        me.materials.append(m)
    me.materials.append(section(palette))
    vm = bpy.data.materials.new("vein")
    vm.use_nodes = True
    vp = vm.node_tree.nodes["Principled BSDF"]
    vp.inputs["Base Color"].default_value = (*lin(palette.get("vein", (0.30, 0.12, 0.45))), 1)
    vp.inputs["Roughness"].default_value, vp.inputs["Coat Weight"].default_value = 0.25, 0.8
    me.materials.append(vm)
    return o


def squeeze(o, rings):
    """A Geometry Nodes Set Position that pinches the mesh round its Z axis under each band
    (`rings`: [(empty, grip, width)]: the band's height is its empty's Z, its depth its grip
    empty's X, both animated) and lets it bulge a little
    between them: r *= 1 - sum(depth * (g(dz/w) - 0.45 g(dz/2.4w)))."""
    ng = bpy.data.node_groups.new("squeeze", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n, ln = ng.nodes, ng.links
    gin, gout = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    setp = n.new("GeometryNodeSetPosition")
    pos = n.new("GeometryNodeInputPosition")
    sep = n.new("ShaderNodeSeparateXYZ")
    ln.new(pos.outputs[0], sep.inputs[0])

    def math_(op, a, b=None, val=None):
        m = n.new("ShaderNodeMath")
        m.operation = op
        ln.new(a, m.inputs[0]) if not isinstance(a, (int, float)) else setattr(m.inputs[0], "default_value", a)
        if b is not None:
            ln.new(b, m.inputs[1]) if not isinstance(b, (int, float)) else setattr(m.inputs[1], "default_value", b)
        return m.outputs[0]

    total = None
    for empty, grip, width in rings:
        info = n.new("GeometryNodeObjectInfo")
        info.inputs["Object"].default_value = empty
        info.transform_space = "RELATIVE"
        held = n.new("GeometryNodeObjectInfo")  # the band's grip: its depth, animated
        held.inputs["Object"].default_value = grip
        held.transform_space = "ORIGINAL"
        hx = n.new("ShaderNodeSeparateXYZ")
        ln.new(held.outputs["Location"], hx.inputs[0])
        depth = hx.outputs[0]
        z = n.new("ShaderNodeSeparateXYZ")
        ln.new(info.outputs["Location"], z.inputs[0])
        dz = math_("SUBTRACT", sep.outputs[2], z.outputs[2])
        g1 = math_("EXPONENT", math_("MULTIPLY", -1.0, math_("POWER", math_("DIVIDE", dz, width), 2.0)))
        g2 = math_("EXPONENT", math_("MULTIPLY", -1.0, math_("POWER", math_("DIVIDE", dz, width * 2.4), 2.0)))
        term = math_("MULTIPLY", math_("SUBTRACT", g1, math_("MULTIPLY", g2, 0.45)), depth)
        total = term if total is None else math_("ADD", total, term)
    scale = math_("SUBTRACT", 1.0, total)
    k = math_("SUBTRACT", scale, 1.0)  # offset = (x, y, 0) * (scale - 1)
    off = n.new("ShaderNodeCombineXYZ")
    ln.new(math_("MULTIPLY", sep.outputs[0], k), off.inputs[0])
    ln.new(math_("MULTIPLY", sep.outputs[1], k), off.inputs[1])
    ln.new(gin.outputs[0], setp.inputs["Geometry"])
    ln.new(off.outputs[0], setp.inputs["Offset"])
    ln.new(setp.outputs[0], gout.inputs[0])
    mod = o.modifiers.new("squeeze", "NODES")
    mod.node_group = ng
    return mod


# ---------------- the bands ----------------

def _text_ring(text, ink, face, radius, height, name):
    """The band's type: `text` repeated round the local Z axis, letters standing on the band,
    facing out, reading left to right from outside (the flat text mesh wrapped onto the
    cylinder: x along the line -> the angle, y up -> z, its depth -> outward)."""
    font = bpy.data.fonts.load(os.path.join(FONTS, FONT[face]), check_existing=True)
    curve = bpy.data.curves.new(f"{name}_type", "FONT")
    curve.font = font
    curve.size, curve.extrude = height * 0.62, 0.0025
    unit = f"{text.upper() if face == 'sans' else text}   •   "
    flat_o = bpy.data.objects.new(f"{name}_flat", curve)
    bpy.context.collection.objects.link(flat_o)
    curve.body = unit
    bpy.context.view_layer.update()
    reps = max(1, round(2 * math.pi * radius / max(flat_o.dimensions.x, 1e-3)))
    curve.body = unit * reps
    bpy.context.view_layer.update()
    mesh = bpy.data.meshes.new_from_object(flat_o.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(flat_o)
    xs = [v.co.x for v in mesh.vertices] or [0.0]
    ys = [v.co.y for v in mesh.vertices] or [0.0]
    x0, span = min(xs), max(max(xs) - min(xs), 1e-3)
    mid = (min(ys) + max(ys)) / 2
    for v in mesh.vertices:
        a = (v.co.x - x0) / span * 2 * math.pi  # the whole line once round
        r = radius + 0.003 + v.co.z
        v.co = (r * math.sin(a), -r * math.cos(a), v.co.y - mid)
    o = bpy.data.objects.new(f"{name}_type", mesh)
    bpy.context.collection.objects.link(o)
    o.data.materials.append(flat(f"{name}_ink", ink))
    return o


def _strip(radius, height, fill, ink, name):
    """The band itself: an open cylinder round the local Z axis in `fill`, with `ink` rims and
    a tape measure's ticks along its top edge."""
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=radius, depth=height, end_fill_type="NOTHING")
    o = bpy.context.object
    o.name = name
    m = bpy.data.materials.new(f"{name}_fill")
    m.use_nodes = True
    nt, ln = m.node_tree, m.node_tree.links
    nt.nodes.clear()

    def op(kind, a, b):
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = kind
        for k, v in enumerate((a, b)):
            if v is None:
                continue
            ln.new(v, n.inputs[k]) if not isinstance(v, (int, float)) else setattr(n.inputs[k], "default_value", v)
        return n.outputs[0]

    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ln.new(nt.nodes.new("ShaderNodeTexCoord").outputs["Object"], sep.inputs[0])
    rim = op("GREATER_THAN", op("ABSOLUTE", sep.outputs[2], None), height / 2 - 0.004)
    turn = op("FRACT", op("MULTIPLY", op("ARCTAN2", sep.outputs[1], sep.outputs[0]), 60 / (2 * math.pi)), None)
    tick = op("MULTIPLY", op("LESS_THAN", turn, 0.12), op("GREATER_THAN", sep.outputs[2], height * 0.3))
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["A"].default_value = (*lin(fill), 1)
    mix.inputs["B"].default_value = (*lin(ink), 1)
    ln.new(op("MAXIMUM", rim, tick), mix.inputs["Factor"])
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = LIFT
    ln.new(mix.outputs["Result"], emit.inputs["Color"])
    ln.new(emit.outputs[0], nt.nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    o.data.materials.append(m)
    return o


def plan(i, spec):
    """A band's moves: the stops it whooshes between (`path`, 0..1 of the belly, up and down),
    how hard it grips at each (`squeeze`, a number or one per stop), its tilt (degrees) and size."""
    a, b = BELLY
    us = [min(a + (b - a) * x, CUT - 0.04) for x in (spec.get("path") or [spec.get("at", 0.5)])]
    sq = spec.get("squeeze", 0.5)
    sqs = list(sq) if isinstance(sq, (list, tuple)) else [sq]
    sqs = (sqs + [sqs[-1]] * len(us))[:len(us)]
    height = 0.05 + 0.018 * (i % 3)
    return {"us": us, "ds": [0.42 * x for x in sqs], "height": height, "width": height * 0.9,
            "tilt": spec.get("tilt", 0.0), "lag": spec.get("lag", 0.07 * (i % 4)), "cinch": spec.get("cinch", False)}


def ease(t):
    return t * t * (3 - 2 * t)


LEAN = 16.0  # degrees a band leans into its whoosh


def state(p, t):
    """Band plan `p` at shot time t (0..1): (u along the muscle, grip depth, tilt degrees).
    Each leg between two stops: it holds, grips hard, lets go, whooshes (a sharp ease, the
    bands one after another: `lag`), clamps down at the next stop; it rocks from +tilt to
    -tilt over the shot and leans into each whoosh."""
    us, ds, n = p["us"], p["ds"], len(p["us"]) - 1
    tilt = p["tilt"] * math.cos(math.pi * t)
    if n == 0:
        u, d, lean = us[0], ds[0], 0.0
    else:
        seg = min(n - 1, int(t * n))
        local = t * n - seg
        w0 = 0.28 + p["lag"]
        x = min(1.0, max(0.0, (local - w0) / 0.26))
        u = us[seg] + (us[seg + 1] - us[seg]) * ease(ease(x))
        loose = math.sin(math.pi * min(1.0, max(0.0, (local - w0 + 0.08) / 0.42)))
        d = (ds[seg] if x < 0.5 else ds[seg + 1]) * (1 - 0.8 * loose)
        lean = LEAN * math.sin(math.pi * x) * (1 if us[seg + 1] >= us[seg] else -1)
    if p["cinch"]:  # the scene's first shot: the band pulls tight
        d *= 0.15 + 0.85 * ease(min(1.0, t / 0.3))
    return u, d, tilt + lean


def pinch(u, t, plans):
    """The flesh's share squeezed at u (the Geometry Nodes formula, squeeze())."""
    total = 0.0
    for p in plans:
        bu, d, _ = state(p, t)
        dz = (u - bu) * LENGTH
        total += d * (math.exp(-(dz / p["width"]) ** 2) - 0.45 * math.exp(-(dz / (2.4 * p["width"])) ** 2))
    return total


def ring(i, spec, p, plans, palette, frames):
    """A band round the muscle along its plan, rolling `turns` times, its radius riding the
    pinched flesh frame by frame. Returns (the empty whose Z is its height, its grip, width)."""
    band, ink, face = palette["tones"][spec.get("tone", "light")]
    s = bpy.context.scene
    room = math.sin(math.radians(abs(p["tilt"]) + LEAN)) * p["height"]  # a tilted band needs room

    def radius(u, t):  # on the pinched flesh's outer bundles
        return profile(u) * (1 - pinch(u, t, plans)) * 1.12 + 0.008 + room

    r0 = radius(state(p, 0.0)[0], 0.0)
    root = bpy.data.objects.new(f"ring{i}", None)
    s.collection.objects.link(root)
    spin = bpy.data.objects.new(f"ring{i}_spin", None)
    s.collection.objects.link(spin)
    spin.parent = root
    strip = _strip(r0, p["height"], band, ink, f"ring{i}_band")
    typ = _text_ring(spec["text"], ink, face, r0, p["height"], f"ring{i}")
    for o in (strip, typ):
        o.parent = spin
    grip = bpy.data.objects.new(f"ring{i}_grip", None)
    s.collection.objects.link(grip)
    for f in range(1, frames + 1):  # every frame: a whoosh is a few frames long
        t = (f - 1) / max(1, frames - 1)
        u, d, tilt = state(p, t)
        grip.location.x = d
        k = radius(u, t) / r0
        root.location = (0, 0, u * LENGTH)
        root.scale = (k, 0.86 * k, 1.0)  # the belly is a little flat: so is the band
        root.rotation_euler = (math.radians(tilt), math.radians(tilt * 0.4), 0)
        for o, what in ((grip, "location"), (root, "location"), (root, "scale"), (root, "rotation_euler")):
            o.keyframe_insert(what, frame=f)
    spin.keyframe_insert("rotation_euler", frame=1)
    spin.rotation_euler.z = 2 * math.pi * spec.get("turns", 0.4)
    spin.keyframe_insert("rotation_euler", frame=frames)
    for fc in _curves(spin.animation_data.action):
        for k in fc.keyframe_points:
            k.interpolation = "LINEAR"
    return root, grip, p["width"]


# ---------------- camera ----------------

def camera(kind, frames, start):
    s = bpy.context.scene
    cam = bpy.data.cameras.new("cam")
    cam.lens = 50
    o = bpy.data.objects.new("cam", cam)
    s.collection.objects.link(o)
    t = bpy.data.objects.new("aim", None)
    s.collection.objects.link(t)
    k = o.constraints.new("TRACK_TO")
    k.target, k.track_axis, k.up_axis = t, "TRACK_NEGATIVE_Z", "UP_Y"
    s.camera = o
    cam.dof.use_dof, cam.dof.focus_object, cam.dof.aperture_fstop = True, t, 2.8
    mid = (BELLY[0] + CUT) / 2 * LENGTH
    for f in sorted({*range(1, frames + 1, max(1, frames // 12)), frames}):
        u = (f - 1) / max(1, frames - 1)
        e = u * u * (3 - 2 * u)
        if kind == "orbit":
            a, d, z = start + 70 * e, 1.2, mid + 0.1
        elif kind == "push":
            a, d, z = start, 1.6 - 0.6 * e, mid + 0.05
        elif kind == "top":  # looking down into the cut: the fibres inside
            a, d, z = start + 30 * e, 0.9, CUT * LENGTH + 0.4
        else:  # glide: along the muscle, close
            a, d, z = start + 15 * e, 1.1, BELLY[0] * LENGTH + 0.25 + 0.5 * e
        ar = math.radians(a)
        o.location = (math.sin(ar) * d, -math.cos(ar) * d, z)
        t.location = (0, 0, (CUT * LENGTH - 0.25 if kind == "top" else z - 0.1 if kind == "glide" else mid))
        o.keyframe_insert("location", frame=f)
        t.keyframe_insert("location", frame=f)


# ---------------- a shot ----------------

def render_shot(cfg, shot):
    palette = PALETTES[shot.get("palette", "lab")]
    s = reset(cfg, palette)
    frames = shot["frames"]
    studio(palette)
    m = muscle(palette, random.Random(shot.get("seed", 0)))
    plans = [plan(i, b) for i, b in enumerate(shot["bands"])]
    rings = [ring(i, b, p, plans, palette, frames) for i, (b, p) in enumerate(zip(shot["bands"], plans))]
    squeeze(m, rings)
    cam = shot.get("camera", {})
    camera(cam.get("kind", "orbit"), frames, cam.get("start", -30))
    s.frame_start, s.frame_end = 1, frames
    out = os.path.join(os.path.abspath(cfg["out"]), shot["id"])
    os.makedirs(out, exist_ok=True)
    random.seed(shot.get("seed", 0))
    if shot.get("stills"):
        for f in shot["stills"]:
            s.frame_set(f)
            s.render.filepath = os.path.join(out, f"still_{f}.png")
            bpy.ops.render.render(write_still=True)
    else:
        s.render.filepath = os.path.join(out, "f_")
        bpy.ops.render.render(animation=True)


def main():
    cfg = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
    for shot in cfg["shots"]:
        render_shot(cfg, shot)


if __name__ == "__main__":
    main()
