"""Physique Scan v2 (owner 2026-11-25): a detailed 3D object (a muscle cut open, a dumbbell, a
kettlebell, a heart, a femur: SUBJECTS) with many bands of type wrapped round it: rolling,
rocking, whooshing up and down between stops and squeezing it there, each spot its own grip
(the flesh pinched under each band, bulging between them), in a free palette. Over it, the
motion design layer: shockwave rings where a band clamps down, halo rings orbiting, floating
specks, motion blur, camera punches and shake, and a compositor (bloom, a lens whose colour
fringes kick on every whoosh, a vignette). Standalone: no troupe.

    blender -b -P cinematic/engine/anatomy.py -- <shots.json>

<shots.json>: out, fps, size, samples, shots [{id, frames, stills, subject, palette, bands [{text,
tone, path (its stops, 0..1 of the subject's span), squeeze (0..1, or one per stop), turns, tilt
(degrees), cinch (pulls tight first)}], camera {kind: orbit | push | glide | top, start
(degrees)}, seed}].
"""
import json
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

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
    s.render.use_motion_blur, s.render.motion_blur_shutter = True, 0.45  # whooshes smear
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
    """The subject's radius at u (0..1 along its height): where the bands ride."""
    return SUBJ["profile"](u)


def muscle_profile(u):
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
            r = muscle_profile(u)
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
            r = muscle_profile(u) * 1.1  # on the outer bundles
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


def plan(i, n, spec):
    """Band i of n: the stops it whooshes between (`path`, 0..1 of the subject's span, up and
    down), how hard it grips at each (`squeeze`, a number or one per stop, times the subject's
    give: flesh gives, iron a little), its tilt (degrees) and size."""
    a, b = SUBJ["span"]
    us = [a + (b - a) * x for x in (spec.get("path") or [spec.get("at", 0.5)])]
    sq = spec.get("squeeze", 0.5)
    sqs = list(sq) if isinstance(sq, (list, tuple)) else [sq]
    sqs = (sqs + [sqs[-1]] * len(us))[:len(us)]
    height = 0.05 + 0.018 * (i % 3)
    return {"us": us, "ds": [0.42 * SUBJ["give"] * x for x in sqs], "height": height,
            "width": height * 0.9, "tilt": spec.get("tilt", 0.0), "j": i, "n": n,
            "cinch": spec.get("cinch", False)}


def ease(t):
    return t * t * (3 - 2 * t)


LEAN = 16.0  # degrees a band leans into its whoosh
LAG = 0.05  # each band leaves this much of a leg after the one ahead of it
W0, FLY = 0.28, 0.26  # a leg: the first band leaves at W0, a whoosh lasts FLY (shares of the leg)


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
        up = us[seg + 1] >= us[seg]
        w0 = W0 + LAG * (p["j"] if up else p["n"] - 1 - p["j"])
        x = min(1.0, max(0.0, (local - w0) / FLY))
        u = us[seg] + (us[seg + 1] - us[seg]) * ease(ease(x))
        loose = math.sin(math.pi * min(1.0, max(0.0, (local - w0 + 0.08) / (FLY + 0.16))))
        d = (ds[seg] if x < 0.5 else ds[seg + 1]) * (1 - 0.8 * loose)
        lean = LEAN * math.sin(math.pi * x) * (1 if us[seg + 1] >= us[seg] else -1)
    if p["cinch"]:  # the scene's first shot: the band pulls tight
        d *= 0.15 + 0.85 * ease(min(1.0, t / 0.15))
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


def arrivals(p, frames):
    """Where and when band plan `p` clamps down (the end of each whoosh, and of the cinch):
    [(u, shot time, frame)]."""
    us, n, out = p["us"], len(p["us"]) - 1, []
    for seg in range(n):
        if abs(us[seg + 1] - us[seg]) < 0.01:
            continue
        up = us[seg + 1] >= us[seg]
        local = W0 + LAG * (p["j"] if up else p["n"] - 1 - p["j"]) + FLY
        out.append((us[seg + 1], (seg + local) / n))
    if p["cinch"]:
        out.append((state(p, 0.15)[0], 0.15))
    return [(u, t, 1 + round(t * (frames - 1))) for u, t in out]


def impacts(i, p, plans, color, frames):
    """A shockwave where a band clamps down: a flat ring at its height, flung out and fading."""
    s = bpy.context.scene
    for k, (u, t, f0) in enumerate(arrivals(p, frames)):
        r = profile(u) * (1 - pinch(u, t, plans)) * 1.12 + 0.02
        bm = bmesh.new()
        seg = 64
        circle = [(math.cos(2 * math.pi * a / seg), math.sin(2 * math.pi * a / seg)) for a in range(seg)]
        inner = [bm.verts.new((0.93 * r * x, 0.93 * r * y, 0)) for x, y in circle]
        outer = [bm.verts.new((r * x, r * y, 0)) for x, y in circle]
        for a in range(seg):
            bm.faces.new((inner[a], inner[(a + 1) % seg], outer[(a + 1) % seg], outer[a]))
        me = bpy.data.meshes.new(f"impact{i}_{k}")
        bm.to_mesh(me)
        bm.free()
        o = bpy.data.objects.new(me.name, me)
        s.collection.objects.link(o)
        m = bpy.data.materials.new(me.name)
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        emit = nt.nodes.new("ShaderNodeEmission")
        emit.inputs["Color"].default_value = (*lin(color), 1)
        emit.inputs["Strength"].default_value = LIFT * 1.6
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(nt.nodes.new("ShaderNodeBsdfTransparent").outputs[0], mix.inputs[1])
        nt.links.new(emit.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], nt.nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
        me.materials.append(m)
        o.location = (0, 0, u * LENGTH)
        for f, size, fade in ((f0 - 1, 0.0, 0.0), (f0, 1.0, 1.0), (f0 + 10, 2.8, 0.0), (f0 + 11, 0.0, 0.0)):
            o.scale = (size, size, 1)
            o.keyframe_insert("scale", frame=f)
            mix.inputs[0].default_value = fade
            mix.inputs[0].keyframe_insert("default_value", frame=f)


# ---------------- the other subjects ----------------

def sweep(bm, pts, radii, seg, mat, smooth=True, caps=True, squash=1.0):
    """A tube through `pts` (Vectors) of `radii` (parallel-transported rings: no twist), its
    faces of material `mat`, closed at both ends."""
    rings, n = [], None
    for i, (c, r) in enumerate(zip(pts, radii)):
        t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        if n is None:
            n = t.cross(Vector((1, 0, 0)) if abs(t.x) < 0.9 else Vector((0, 1, 0))).normalized()
        n = (n - t * n.dot(t)).normalized()
        b = t.cross(n)
        rings.append([bm.verts.new(c + r * (n * math.cos(2 * math.pi * k / seg) + squash * b * math.sin(2 * math.pi * k / seg)))
                      for k in range(seg)])
    faces = [bm.faces.new((r0[k], r0[(k + 1) % seg], r1[(k + 1) % seg], r1[k]))
             for r0, r1 in zip(rings, rings[1:]) for k in range(seg)]
    if caps:
        faces += [bm.faces.new(list(reversed(rings[0]))), bm.faces.new(rings[-1])]
    for f in faces:
        f.material_index, f.smooth = mat, smooth


def ball(bm, c, r, mat, squash=(1.0, 1.0, 1.0)):
    res = bmesh.ops.create_uvsphere(bm, u_segments=40, v_segments=20, radius=r,
                                    matrix=Matrix.Translation(c) @ Matrix.Diagonal((*squash, 1.0)))
    for f in {f for v in res["verts"] for f in v.link_faces}:
        f.material_index, f.smooth = mat, True


def line(a, b, n):
    return [a + (b - a) * (k / (n - 1)) for k in range(n)]


def surface(name, color, rough=0.35, metal=0.0, coat=0.4, sss=0.0, bump="noise", scale=30.0,
            strength=0.25, mottle=None):
    """A lit material: `color` (or a noise mottle from `mottle` to `color`), a bump (noise, or
    a knurl's checker), a coat."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt, ln = m.node_tree, m.node_tree.links
    p = nt.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*lin(color), 1)
    p.inputs["Roughness"].default_value, p.inputs["Metallic"].default_value = rough, metal
    p.inputs["Coat Weight"].default_value, p.inputs["Coat Roughness"].default_value = coat, 0.08
    if sss:
        p.inputs["Subsurface Weight"].default_value, p.inputs["Subsurface Scale"].default_value = sss, 0.01
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tex = nt.nodes.new("ShaderNodeTexChecker" if bump == "knurl" else "ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = scale
    if bump != "knurl":
        tex.inputs["Detail"].default_value = 6
    ln.new(tc.outputs["Object"], tex.inputs["Vector"])
    val = tex.outputs["Fac"]
    if mottle:
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[0].color = 0.35, (*lin(mottle), 1)
        ramp.color_ramp.elements[1].position, ramp.color_ramp.elements[1].color = 0.65, (*lin(color), 1)
        ln.new(val, ramp.inputs["Fac"])
        ln.new(ramp.outputs["Color"], p.inputs["Base Color"])
    bmp = nt.nodes.new("ShaderNodeBump")
    bmp.inputs["Strength"].default_value, bmp.inputs["Distance"].default_value = strength, 0.003
    ln.new(val, bmp.inputs["Height"])
    ln.new(bmp.outputs["Normal"], p.inputs["Normal"])
    return m


def finish(bm, name, mats):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    for m in mats:
        me.materials.append(m)
    return o


def steps(u, points):
    """A profile through `points` [(u, r)], joined smoothly, flat beyond its ends."""
    if u <= points[0][0]:
        return points[0][1]
    for (u0, r0), (u1, r1) in zip(points, points[1:]):
        if u <= u1:
            return r0 + (r1 - r0) * ease((u - u0) / (u1 - u0))
    return points[-1][1]


DB_HEAD, DB_COLLAR, DB_BAR = 0.17, 0.058, 0.036


def dumbbell_profile(u):
    return steps(u, [(0.26, DB_HEAD), (0.28, DB_COLLAR), (0.30, DB_COLLAR), (0.32, DB_BAR),
                     (0.68, DB_BAR), (0.70, DB_COLLAR), (0.72, DB_COLLAR), (0.74, DB_HEAD)])


def dumbbell(palette, rng):
    """A hex dumbbell standing up: two rubber hex heads in the palette's accent, chrome end
    plates and collars, a knurled chrome bar."""
    bm = bmesh.new()
    for z0, z1 in ((0.0, 0.27), (0.73, 1.0)):
        zs = [z0] + [z0 + 0.012 + (z1 - z0 - 0.024) * k / 19 for k in range(20)] + [z1]
        sweep(bm, [Vector((0, 0, z)) for z in zs], [DB_HEAD - 0.015] + [DB_HEAD] * 20 + [DB_HEAD - 0.015], 6, 0, smooth=False)
        face = z1 if z0 else z0  # the head's outer face gets a chrome plate
        out = 1 if z0 else -1
        sweep(bm, [Vector((0, 0, face)), Vector((0, 0, face + out * 0.004))], [0.07, 0.07], 32, 1)
    for z0, z1 in ((0.27, 0.30), (0.70, 0.73)):
        sweep(bm, line(Vector((0, 0, z0)), Vector((0, 0, z1)), 6), [DB_COLLAR] * 6, 32, 1)
    sweep(bm, line(Vector((0, 0, 0.30)), Vector((0, 0, 0.70)), 40), [DB_BAR] * 40, 24, 2)
    return finish(bm, "dumbbell", [
        surface("rubber", palette["tones"]["accent"][0], rough=0.45, coat=0.2, scale=60, strength=0.1),
        surface("chrome", (0.9, 0.9, 0.92), rough=0.12, metal=1.0, coat=0.0, scale=80, strength=0.05),
        surface("knurl", (0.85, 0.86, 0.9), rough=0.25, metal=1.0, coat=0.0, bump="knurl", scale=260, strength=0.6)])


KB_C, KB_R, KB_POST, KB_TOP, KB_ARCH, KB_GRIP = 0.27, 0.235, 0.40, 0.64, 0.13, 0.034


def kettlebell_profile(u):
    if u < 0.06:
        return 0.105
    if u <= 0.47:
        return math.sqrt(max(0.0, KB_R ** 2 - (u - KB_C) ** 2))
    if u <= KB_TOP:
        return steps(u, [(0.47, 0.13), (0.52, KB_ARCH + KB_GRIP)])
    return math.sqrt(max(0.0, KB_ARCH ** 2 - (u - KB_TOP) ** 2)) + KB_GRIP


def kettlebell(palette, rng):
    """A powder-coated kettlebell in the palette's dark tone: the round body on its flat foot,
    the arched handle."""
    bm = bmesh.new()
    zs = [0.06 + 0.41 * k / 47 for k in range(48)]
    sweep(bm, [Vector((0, 0, z)) for z in zs], [math.sqrt(KB_R ** 2 - (z - KB_C) ** 2) for z in zs], 56, 0)
    pts = [Vector((-KB_ARCH, 0, KB_POST + (KB_TOP - KB_POST) * k / 7)) for k in range(7)]
    pts += [Vector((KB_ARCH * math.cos(a), 0, KB_TOP + KB_ARCH * math.sin(a)))
            for a in (math.pi - math.pi * k / 23 for k in range(24))]
    pts += [Vector((KB_ARCH, 0, KB_TOP - (KB_TOP - KB_POST) * k / 7)) for k in range(1, 8)]
    sweep(bm, pts, [KB_GRIP] * len(pts), 24, 0)
    return finish(bm, "kettlebell", [surface("cast", palette["tones"]["dark"][0], rough=0.5, metal=0.35,
                                             coat=0.5, scale=90, strength=0.2)])


HEART_TOP = 0.72  # the heart's body ends here; the great vessels rise above


def heart_r(u):
    t = u / HEART_TOP
    if t < 0.6:
        return 0.2 * math.sin(math.pi / 2 * t / 0.6) ** 0.8
    return 0.2 * math.sqrt(max(0.06, 1 - ((t - 0.6) / 0.4) ** 2))


def heart_profile(u):
    return heart_r(u) * 1.12 + 0.03 if u < HEART_TOP else 0.17


def heart(palette, rng):
    """An anatomical heart: lumpy ventricles in the palette's reds, the aorta arching over with
    its three branches, the pulmonary trunk splitting, the vena cava, coronary vessels winding
    down its surface. It beats (life())."""
    deep, mid, light = palette["muscle"]
    vein = palette.get("vein", (0.30, 0.12, 0.45))
    bm = bmesh.new()
    seg, rows = 56, 60
    rings = []
    for j in range(rows + 1):
        u = 0.02 + (HEART_TOP - 0.02) * j / rows
        t = u / HEART_TOP
        cx, r = 0.05 * (1 - t) ** 2, heart_r(u)
        row = []
        for a in (2 * math.pi * k / seg for k in range(seg)):
            lump = 1 + 0.10 * math.cos(a - 0.6) * math.sin(math.pi * t)
            row.append(bm.verts.new((cx + r * (lump + 0.04 * math.sin(3 * a + 5 * t)) * math.cos(a),
                                     0.86 * r * lump * math.sin(a), u)))
        rings.append(row)
    faces = [bm.faces.new((r0[k], r0[(k + 1) % seg], r1[(k + 1) % seg], r1[k]))
             for r0, r1 in zip(rings, rings[1:]) for k in range(seg)]
    faces += [bm.faces.new(list(reversed(rings[0]))), bm.faces.new(rings[-1])]
    for f in faces:
        f.material_index, f.smooth = 0, True
    arch = [Vector((0.02, 0, 0.58 + 0.28 * k / 6)) for k in range(6)]
    arch += [Vector((-0.08 + 0.1 * math.cos(a), 0, 0.86 + 0.1 * math.sin(a))) for a in (math.pi * k / 15 for k in range(16))]
    arch += [Vector((-0.18, 0.01 * k, 0.86 - 0.04 * k)) for k in range(1, 5)]
    sweep(bm, arch, [0.06] * len(arch), 28, 1)
    for x in (-0.04, -0.08, -0.12):
        top = 0.86 + math.sqrt(max(0.0, 0.01 - (x + 0.08) ** 2))
        sweep(bm, line(Vector((x, 0, top - 0.02)), Vector((x + 0.012, 0, top + 0.1)), 6), [0.02] * 6, 14, 1)
    sweep(bm, line(Vector((0.1, -0.07, 0.52)), Vector((0.12, -0.09, 0.74)), 8), [0.05] * 8, 24, 2)
    for end in (Vector((0.22, -0.03, 0.8)), Vector((0.0, -0.13, 0.82))):
        sweep(bm, line(Vector((0.12, -0.09, 0.72)), end, 8), [0.035] * 8, 18, 2)
    sweep(bm, line(Vector((-0.13, 0.07, 0.48)), Vector((-0.14, 0.08, 0.96)), 12), [0.045] * 12, 22, 2)
    for v in range(3):  # coronary vessels winding down the surface
        a0, wind = rng.uniform(0, 2 * math.pi), rng.uniform(-1.4, 1.4)
        pts = []
        for j in range(40):
            u = 0.64 - 0.56 * j / 39
            a = a0 + wind * (0.64 - u) * 2 + 0.2 * math.sin(12 * u + v)
            r = heart_r(u) * 1.04
            pts.append(Vector((0.05 * (1 - u / HEART_TOP) ** 2 + r * math.cos(a), 0.86 * r * math.sin(a), u)))
        sweep(bm, pts, [0.009 * (1 - 0.5 * j / 39) for j in range(40)], 8, 3)
    return finish(bm, "heart", [
        surface("heart", mid, rough=0.3, coat=0.8, sss=0.4, scale=8, strength=0.35, mottle=deep),
        surface("aorta", light, rough=0.3, coat=0.7, sss=0.3, scale=14, strength=0.15),
        surface("veins", vein, rough=0.3, coat=0.7, sss=0.2, scale=14, strength=0.15),
        surface("coronary", light, rough=0.25, coat=0.8, scale=20, strength=0.1)])


def bone_shaft(u):
    return 0.04 + 0.05 * max(0.0, (0.3 - u) / 0.2) ** 2 + 0.05 * max(0.0, (u - 0.7) / 0.18) ** 2


def bone_profile(u):
    return steps(u, [(0.14, 0.15), (0.3, bone_shaft(0.3) + 0.03), (0.7, bone_shaft(0.7) + 0.03), (0.86, 0.15)])


def bone(palette, rng):
    """A femur standing up: a gently bowed shaft flaring into the knee's two condyles below
    and the neck and ball of the hip above, in ivory."""
    bm = bmesh.new()
    us = [0.1 + 0.78 * k / 49 for k in range(50)]
    sweep(bm, [Vector((0.025 * math.sin(math.pi * (u - 0.1) / 0.78), 0, u)) for u in us],
          [bone_shaft(u) for u in us], 36, 0, squash=0.9)
    ball(bm, Vector((-0.05, 0, 0.09)), 0.075, 0, (1.0, 0.9, 0.85))
    ball(bm, Vector((0.055, 0, 0.085)), 0.07, 0, (1.0, 0.9, 0.85))
    ball(bm, Vector((0, 0, 0.12)), 0.07, 0)
    sweep(bm, line(Vector((0.0, 0, 0.85)), Vector((-0.09, 0, 0.95)), 8), [0.045] * 8, 24, 0)
    ball(bm, Vector((-0.11, 0, 0.97)), 0.075, 0)
    ball(bm, Vector((0.06, 0, 0.9)), 0.055, 0, (1.0, 0.9, 1.1))
    ivory = palette["tendon"]
    return finish(bm, "bone", [surface("bone", ivory, rough=0.5, coat=0.2, sss=0.15, scale=18, strength=0.3,
                                       mottle=tuple(c * 0.86 for c in ivory))])


# ---------------- the motion design layer ----------------

def halos(palette, frames, rng):
    """Three thin rings orbiting the subject like an atom's, in the palette's bright tones,
    spinning over the shot (passing in front of it and behind)."""
    mid = sum(SUBJ["span"]) / 2 * LENGTH
    for k, tone in enumerate(("pop", "accent", "light")):
        bpy.ops.mesh.primitive_torus_add(major_radius=(0.36 + 0.1 * k) * SUBJ["dist"], minor_radius=0.0035,
                                         major_segments=160, minor_segments=8, location=(0, 0, mid))
        o = bpy.context.object
        o.data.materials.append(flat(f"halo{k}", palette["tones"][tone][0]))
        o.rotation_euler = (math.radians(rng.uniform(55, 80)), math.radians(rng.uniform(-25, 25)), rng.uniform(0, 6.3))
        o.keyframe_insert("rotation_euler", frame=1)
        o.rotation_euler.z += rng.choice((-1, 1)) * rng.uniform(0.8, 1.4)
        o.keyframe_insert("rotation_euler", frame=frames)


def dust(palette, frames, rng):
    """Specks of the palette's colours floating round the subject, rising and turning (depth
    and parallax when the camera moves, streaks under the motion blur)."""
    bm = bmesh.new()
    tones = ("light", "dark", "accent", "pop")
    for _ in range(90):
        a, r = rng.uniform(0, 2 * math.pi), rng.uniform(0.32, 1.0) * SUBJ["dist"]
        c = Vector((r * math.cos(a), r * math.sin(a), rng.uniform(-0.2, 1.3)))
        res = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=rng.uniform(0.005, 0.015), matrix=Matrix.Translation(c))
        k = rng.randrange(len(tones))
        for f in {f for v in res["verts"] for f in v.link_faces}:
            f.material_index = k
    o = finish(bm, "dust", [flat(f"dust_{t}", palette["tones"][t][0]) for t in tones])
    o.keyframe_insert("location", frame=1)
    o.keyframe_insert("rotation_euler", frame=1)
    o.location.z += 0.14
    o.rotation_euler.z += rng.choice((-1, 1)) * 0.4
    o.keyframe_insert("location", frame=frames)
    o.keyframe_insert("rotation_euler", frame=frames)


def speed(plans, frames):
    """How fast the bands fly at each frame, 0..1 (the whooshes): drives the punches."""
    out = []
    dt = 0.5 / max(1, frames - 1)
    for f in range(1, frames + 1):
        t = (f - 1) / max(1, frames - 1)
        out.append(sum(abs(state(p, min(1.0, t + dt))[0] - state(p, max(0.0, t - dt))[0]) for p in plans) / max(1, len(plans)))
    top = max(out) or 1.0
    return [v / top for v in out]


def _menu(sock, *values):
    for v in values:
        try:
            sock.default_value = v
            return
        except (TypeError, ValueError):
            continue


def post(fast):
    """The compositor over the render: a bloom on the highlights, a lens whose colour fringes
    (dispersion) and bulge kick on every whoosh (`fast`), a soft vignette."""
    s = bpy.context.scene
    ng = bpy.data.node_groups.new("post", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    s.compositing_node_group = ng
    s.render.use_compositing = True
    n, ln = ng.nodes, ng.links
    rl = n.new("CompositorNodeRLayers")
    glare = n.new("CompositorNodeGlare")
    _menu(glare.inputs["Type"], "Bloom", "BLOOM")
    glare.inputs["Threshold"].default_value = 2.3
    glare.inputs["Strength"].default_value = 0.45
    ln.new(rl.outputs["Image"], glare.inputs["Image"])
    lens = n.new("CompositorNodeLensdist")
    ln.new(glare.outputs["Image"], lens.inputs["Image"])
    if "Fit" in lens.inputs:
        lens.inputs["Fit"].default_value = True
    for f, v in enumerate(fast, start=1):
        lens.inputs["Dispersion"].default_value = 0.012 + 0.07 * v
        lens.inputs["Distortion"].default_value = -0.03 * v
        lens.inputs["Dispersion"].keyframe_insert("default_value", frame=f)
        lens.inputs["Distortion"].keyframe_insert("default_value", frame=f)
    last = lens.outputs["Image"]
    try:  # the vignette: darker towards the outside of a soft ellipse
        mask = n.new("CompositorNodeEllipseMask")
        mask.inputs["Size"].default_value = (1.05, 0.9)
        blur = n.new("CompositorNodeBlur")
        blur.inputs["Size"].default_value = (160, 160)
        ln.new(mask.outputs["Mask"], blur.inputs["Image"])
        amount = n.new("ShaderNodeMath")
        amount.operation = "MULTIPLY_ADD"
        amount.inputs[1].default_value, amount.inputs[2].default_value = -0.38, 0.38
        ln.new(blur.outputs["Image"], amount.inputs[0])
        mix = n.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        ln.new(amount.outputs[0], mix.inputs["Factor"])
        ln.new(last, mix.inputs["A"])
        mix.inputs["B"].default_value = (0, 0, 0, 1)
        last = mix.outputs["Result"]
    except (RuntimeError, KeyError, TypeError) as e:
        print("anatomy: no vignette:", e)
    ln.new(last, n.new("NodeGroupOutput").inputs[0])


def life(o, frames, cinch, beats, rng):
    """The subject itself: a slow turn inside its bands, a springy pop-in on a scene's first
    shot, a heartbeat (lub-dub) for the heart."""
    turn = rng.choice((-1, 1)) * rng.uniform(0.35, 0.7)
    fps = bpy.context.scene.render.fps
    for f in range(1, frames + 1):
        t = (f - 1) / max(1, frames - 1)
        k = 1.0
        if cinch:
            k *= 1 - 0.3 * math.exp(-(f - 1) / 3.5) * math.cos((f - 1) * 0.75)
        if beats:
            ph = ((f - 1) / fps * 1.3) % 1.0
            k *= 1 + 0.06 * math.exp(-ph / 0.06) + (0.035 * math.exp(-(ph - 0.18) / 0.06) if ph > 0.18 else 0.0)
        o.scale = (k, k, k)
        o.rotation_euler.z = turn * t
        o.keyframe_insert("scale", frame=f)
        o.keyframe_insert("rotation_euler", frame=f)


# ---------------- camera ----------------

def camera(kind, frames, start, fast, rng):
    """The shot's camera round the subject, punching in (a longer lens) on every whoosh
    (`fast`) and shaking a little (noise on its position)."""
    s = bpy.context.scene
    cam = bpy.data.cameras.new("cam")
    o = bpy.data.objects.new("cam", cam)
    s.collection.objects.link(o)
    t = bpy.data.objects.new("aim", None)
    s.collection.objects.link(t)
    k = o.constraints.new("TRACK_TO")
    k.target, k.track_axis, k.up_axis = t, "TRACK_NEGATIVE_Z", "UP_Y"
    s.camera = o
    cam.dof.use_dof, cam.dof.focus_object, cam.dof.aperture_fstop = True, t, 2.8
    a0, a1 = SUBJ["span"]
    mid, top, dist = (a0 + a1) / 2 * LENGTH, SUBJ["top"] * LENGTH, SUBJ["dist"]
    for f in range(1, frames + 1):
        u = (f - 1) / max(1, frames - 1)
        e = u * u * (3 - 2 * u)
        if kind == "orbit":
            a, d, z = start + 70 * e, 1.2, mid + 0.1
        elif kind == "push":
            a, d, z = start, 1.6 - 0.6 * e, mid + 0.05
        elif kind == "top":  # looking down onto its top (the muscle: into the cut)
            a, d, z = start + 30 * e, 0.9, top + 0.4
        else:  # glide: along it, close
            a, d, z = start + 15 * e, 1.1, a0 * LENGTH + 0.25 + 0.5 * e
        ar = math.radians(a)
        o.location = (math.sin(ar) * d * dist, -math.cos(ar) * d * dist, z)
        t.location = (0, 0, (top - 0.25 if kind == "top" else z - 0.1 if kind == "glide" else mid))
        cam.lens = 50 * (1 + 0.16 * fast[f - 1])
        o.keyframe_insert("location", frame=f)
        t.keyframe_insert("location", frame=f)
        cam.keyframe_insert("lens", frame=f)
    for fc in _curves(o.animation_data.action):
        noise = fc.modifiers.new("NOISE")
        noise.strength, noise.scale, noise.phase = 0.012, 4.0, rng.uniform(0, 100)


# ---------------- a shot ----------------

def render_shot(cfg, shot):
    global SUBJ
    SUBJ = SUBJECTS[shot.get("subject", "muscle")]
    palette = PALETTES[shot.get("palette", "lab")]
    rng = random.Random(shot.get("seed", 0))
    s = reset(cfg, palette)
    frames = shot["frames"]
    studio(palette)
    m = SUBJ["build"](palette, rng)
    n = len(shot["bands"])
    plans = [plan(i, n, b) for i, b in enumerate(shot["bands"])]
    rings = [ring(i, b, p, plans, palette, frames) for i, (b, p) in enumerate(zip(shot["bands"], plans))]
    squeeze(m, rings)
    for i, (b, p) in enumerate(zip(shot["bands"], plans)):
        impacts(i, p, plans, palette["tones"][b.get("tone", "light")][0], frames)
    life(m, frames, any(p["cinch"] for p in plans), SUBJ.get("beats", False), rng)
    halos(palette, frames, rng)
    dust(palette, frames, rng)
    fast = speed(plans, frames)
    cam = shot.get("camera", {})
    camera(cam.get("kind", "orbit"), frames, cam.get("start", -30), fast, rng)
    post(fast)
    s.frame_start, s.frame_end = 1, frames
    out = os.path.join(os.path.abspath(cfg["out"]), shot["id"])
    os.makedirs(out, exist_ok=True)
    if shot.get("stills"):
        for f in shot["stills"]:
            s.frame_set(f)
            s.render.filepath = os.path.join(out, f"still_{f}.png")
            bpy.ops.render.render(write_still=True)
    else:
        s.render.filepath = os.path.join(out, "f_")
        bpy.ops.render.render(animation=True)


# the objects: how each is built, its radius by height (where the bands ride), the span the
# bands move in, its top (the top camera), how much it gives under a band, how far to frame it
SUBJECTS = {
    "muscle": {"build": muscle, "profile": muscle_profile, "span": (0.16, 0.76), "top": CUT, "give": 1.0, "dist": 1.0},
    "dumbbell": {"build": dumbbell, "profile": dumbbell_profile, "span": (0.05, 0.95), "top": 1.0, "give": 0.3, "dist": 1.12},
    "kettlebell": {"build": kettlebell, "profile": kettlebell_profile, "span": (0.1, 0.74), "top": 0.78, "give": 0.35, "dist": 1.25},
    "heart": {"build": heart, "profile": heart_profile, "span": (0.08, 0.64), "top": 0.92, "give": 0.9, "dist": 1.22, "beats": True},
    "bone": {"build": bone, "profile": bone_profile, "span": (0.2, 0.8), "top": 1.0, "give": 0.3, "dist": 1.0},
}
SUBJ = SUBJECTS["muscle"]


def main():
    cfg = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
    for shot in cfg["shots"]:
        render_shot(cfg, shot)


if __name__ == "__main__":
    main()
