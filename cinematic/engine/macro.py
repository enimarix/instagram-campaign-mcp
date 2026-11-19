"""Macro 3D plates (style `macro3d`, step 154), run inside Blender by src/studio/macro3d.py:

    blender -b -P cinematic/engine/macro.py -- <plates.json>

<plates.json>: out, fps, size, shots [{id, subject, move, look, seed, frames, stills}]. Every shot
is its own scene: a black studio void (a dark floor fading out, a soft top key, two glossy rim
lights, floating dust), one subject (a scanned Poly Haven food or a procedural food / body
piece, real size in metres), a slow macro camera move with a shallow depth of field. Writes
out/<id>/f_####.png (frames 1..frames) or out/<id>/still_<n>.png for each frame in `stills`.

Looks: plain; heat (the subject in false colour, « Énergie en couleur »); section (the subject
cut open where it has an inside: egg, stomach, fat cell, muscle).
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
sys.path.insert(0, ENGINE)
import kit  # noqa: E402

LENS = 60  # mm on a 36 mm sensor fitted to the frame's height (portrait)


# ---------------- scene ----------------

def reset(cfg):
    bpy.ops.wm.read_homefile(use_empty=True)
    s = bpy.context.scene
    s.render.fps = cfg.get("fps", 24)
    try:
        s.render.engine = "BLENDER_EEVEE"
    except TypeError:
        s.render.engine = "BLENDER_EEVEE_NEXT"
    s.render.resolution_x, s.render.resolution_y = cfg.get("size", [720, 1280])
    e = s.eevee
    for attr, val in [("taa_render_samples", cfg.get("samples", 48)), ("use_shadows", True),
                      ("shadow_ray_count", 2), ("shadow_step_count", 8), ("use_raytracing", True),
                      ("use_fast_gi", True), ("fast_gi_method", "GLOBAL_ILLUMINATION")]:
        if hasattr(e, attr):
            try:
                setattr(e, attr, val)
            except (TypeError, ValueError) as err:
                print("eevee", attr, err)
    s.view_settings.view_transform = "AgX"
    for look in ("AgX - Medium High Contrast", "AgX - Punchy", "None"):
        try:
            s.view_settings.look = look
            break
        except TypeError:
            pass
    s.world = bpy.data.worlds.new("void")
    s.world.use_nodes = True
    bg = s.world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.02, 0.022, 0.026, 1)
    bg.inputs[1].default_value = 0.03
    s.render.image_settings.file_format = "PNG"
    s.render.image_settings.color_mode = "RGB"
    return s


def mat(name, color, rough=0.45, sss=0.0, sss_r=(1.0, 0.4, 0.2), sss_scale=0.01, coat=0.0,
        metal=0.0, trans=0.0, ior=1.45, emit=0.0, bump=None, spec=0.5):
    """Principled material. bump: (kind 'noise' | 'wave' | 'voronoi', scale, strength)."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    for key, val in [("Base Color", (*color, 1)), ("Roughness", rough), ("Metallic", metal),
                     ("Subsurface Weight", sss), ("Subsurface Radius", sss_r),
                     ("Subsurface Scale", sss_scale), ("Coat Weight", coat), ("Coat Roughness", 0.08),
                     ("Transmission Weight", trans), ("IOR", ior), ("Specular IOR Level", spec)]:
        p.inputs[key].default_value = val
    if emit:
        p.inputs["Emission Color"].default_value = (*color, 1)
        p.inputs["Emission Strength"].default_value = emit
    if bump:
        kind, scale, strength = bump
        tc = nt.nodes.new("ShaderNodeTexCoord")
        tex = nt.nodes.new({"noise": "ShaderNodeTexNoise", "wave": "ShaderNodeTexWave",
                            "voronoi": "ShaderNodeTexVoronoi"}[kind])
        tex.inputs["Scale"].default_value = scale
        if kind == "noise":
            tex.inputs["Detail"].default_value = 8
        if kind == "wave":
            tex.inputs["Distortion"].default_value = 2.0
            tex.inputs["Detail"].default_value = 3
        nt.links.new(tc.outputs["Object"], tex.inputs["Vector"])
        b = nt.nodes.new("ShaderNodeBump")
        b.inputs["Strength"].default_value = strength
        nt.links.new(tex.outputs["Distance" if kind == "voronoi" else "Fac"], b.inputs["Height"])
        nt.links.new(b.outputs["Normal"], p.inputs["Normal"])
        if coat:
            nt.links.new(b.outputs["Normal"], p.inputs["Coat Normal"])
    if trans:
        for attr, val in (("use_raytrace_refraction", True), ("surface_render_method", "DITHERED")):
            if hasattr(m, attr):
                setattr(m, attr, val)
    return m


def link(o):
    bpy.context.collection.objects.link(o)
    return o


def mesh_obj(name, bm, m, smooth=True, loc=(0, 0, 0)):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = link(bpy.data.objects.new(name, me))
    o.location = loc
    me.materials.append(m)
    for poly in me.polygons:
        poly.use_smooth = smooth
    return o


def sphere(name, r, loc, m, segs=48, rings=32, scale=(1, 1, 1)):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=r)
    bmesh.ops.scale(bm, vec=scale, verts=bm.verts)
    return mesh_obj(name, bm, m, loc=loc)


def cube(name, size, loc, m, rot=(0, 0, 0), bevel=0.12):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    o = mesh_obj(name, bm, m, smooth=False, loc=loc)
    o.rotation_euler = rot
    bv = o.modifiers.new("bevel", "BEVEL")
    bv.width, bv.segments = bevel * min(size), 3
    o.modifiers.new("ws", "WEIGHTED_NORMAL") if hasattr(bpy.types, "WeightedNormalModifier") else None
    for poly in o.data.polygons:
        poly.use_smooth = True
    return o


def tube(name, pts, m, radius, radii=None, res=24):
    """A smooth tube along points (x, y, z) with a radius per point."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions, cu.bevel_depth, cu.bevel_resolution = "3D", radius, 8
    cu.resolution_u, cu.use_fill_caps = res, True
    sp = cu.splines.new("NURBS")
    sp.points.add(len(pts) - 1)
    for i, p in enumerate(pts):
        sp.points[i].co = (*p, 1)
        sp.points[i].radius = radii[i] if radii else 1.0
    sp.use_endpoint_u, sp.order_u = True, min(4, len(pts))
    o = link(bpy.data.objects.new(name, cu))
    cu.materials.append(m)
    return o


def bisect(o, co, no, fill=True):
    """Cut a mesh object with a plane, keeping the side behind `no`."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
    res = bmesh.ops.bisect_plane(bm, geom=geom, plane_co=co, plane_no=no, clear_outer=True)
    if fill:
        edges = [e for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
        bmesh.ops.edgeloop_fill(bm, edges=edges)
    bm.to_mesh(o.data)
    bm.free()
    return o


def fade(m, near, far):
    """The floor dissolves into the void: black beyond `far` from the subject, as it is at `near`."""
    nt = m.node_tree
    out = nt.nodes["Material Output"]
    shader = out.inputs["Surface"].links[0].from_socket
    tc, length = nt.nodes.new("ShaderNodeTexCoord"), nt.nodes.new("ShaderNodeVectorMath")
    length.operation = "LENGTH"
    rng = nt.nodes.new("ShaderNodeMapRange")
    rng.inputs["From Min"].default_value, rng.inputs["From Max"].default_value = near, far
    rng.inputs["To Min"].default_value, rng.inputs["To Max"].default_value = 0.0, 1.0
    black = nt.nodes.new("ShaderNodeBsdfDiffuse")
    black.inputs["Color"].default_value = (0, 0, 0, 1)
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(tc.outputs["Object"], length.inputs[0])
    nt.links.new(length.outputs["Value"], rng.inputs["Value"])
    nt.links.new(rng.outputs["Result"], mix.inputs["Fac"])
    nt.links.new(shader, mix.inputs[1])
    nt.links.new(black.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])


def rest(o):
    """Move a mesh object so its lowest point touches the floor."""
    bpy.context.view_layer.update()
    o.location.z -= min((o.matrix_world @ v.co).z for v in o.data.vertices)
    return o


def studio(c, r, floor=True, warm=0.0):
    """Floor, key, rims, dust around a subject of radius r centred on c."""
    if floor:
        fm = mat("floor", (0.006, 0.006, 0.007), rough=0.72, spec=0.05, bump=("noise", 260 / r, 0.35))
        fade(fm, 1.2 * r, 6 * r)
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=60 * r)
        mesh_obj("floor", bm, fm, smooth=False)

    def area(name, pos, energy, size, color, spread=70):
        li = bpy.data.lights.new(name, "AREA")
        li.energy, li.size, li.color = energy, size, color
        if hasattr(li, "spread"):
            li.spread = math.radians(spread)
        o = link(bpy.data.objects.new(name, li))
        o.location = c + Vector(pos) * r
        o.rotation_euler = (c - o.location).to_track_quat("-Z", "Y").to_euler()
        return o

    k = r * r  # watts grow with the distance squared: same picture at any size
    area("key", (-1.2, -1.6, 5.0), 700 * k, 4 * r, (1.0, 0.96 - warm * 0.1, 0.92 - warm * 0.2), 45)
    area("rim_l", (-3.6, 3.2, 1.6), 900 * k, 2.2 * r, (0.86, 0.92, 1.0))
    area("rim_r", (3.4, 2.6, 2.4), 700 * k, 2.2 * r, (1.0, 0.95, 0.9))
    area("fill", (2.5, -4.0, 1.0), 40 * k, 5 * r, (0.8, 0.85, 1.0), 50)


def dust(c, r, cam_dist, rng):
    """Specks floating between the camera and the subject (out of focus: small bokeh)."""
    m = mat("dust", (0.5, 0.5, 0.48), rough=0.6, emit=0.05)
    bm = bmesh.new()
    for _ in range(70):  # near the lens: soft out-of-focus specks
        d = rng.uniform(0.18, 0.75) * cam_dist
        p = Vector((rng.uniform(-0.5, 0.5) * d * 0.4, -cam_dist + d, rng.uniform(-0.6, 0.9) * d * 0.6))
        geo = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=rng.uniform(0.0008, 0.0018) * d)
        bmesh.ops.translate(bm, vec=p, verts=geo["verts"])
    o = mesh_obj("dust", bm, m, smooth=True, loc=c)
    return o


# ---------------- subjects (each returns (centre, radius, floor)) ----------------

def scan(name, height, loc=(0, 0, 0), rot_z=0.0):
    root = kit.prop(f"polyhaven/{name}/{name}.gltf", loc, rot_z, height)
    for o in root.children_recursive:
        if o.type == "MESH":
            for poly in o.data.polygons:
                poly.use_smooth = True
    return root


def bounds(objects):
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in objects if o.type in ("MESH", "CURVE") for c in o.bound_box]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    return (lo + hi) / 2, max(hi - lo) / 2


def scanned(name, height, rot=0.6):
    def build(p, rng):
        root = scan(name, height, rot_z=rot + rng.uniform(-0.4, 0.4))
        c, r = bounds(root.children_recursive)
        return c, r * 1.05, True
    return build


def egg_mesh(name, r, m, loc=(0, 0, 0)):
    o = sphere(name, r, loc, m, 64, 40, (1, 1, 1.28))
    for v in o.data.vertices:
        if v.co.z > 0:
            k = 1 - 0.13 * v.co.z / (1.28 * r)
            v.co.x *= k
            v.co.y *= k
    return o


def egg(p, rng):
    r = 0.022
    shell = mat("shell", (0.86, 0.66, 0.46), rough=0.5, sss=0.25, sss_scale=0.004, bump=("noise", 900, 0.08))
    if p["look"] != "section":
        o = egg_mesh("egg", r, shell, (0, 0, 1.28 * r))
        o.rotation_euler = (0, math.radians(8), 0)
        egg_mesh("egg2", r * 0.95, shell, (-2.6 * r, 2.2 * r, 1.22 * r)).rotation_euler = (0, 0, 0.7)
        return Vector((0, 0, 1.3 * r)), 1.4 * r, True
    # cooked, cut lengthwise: the white face up, the yolk in it
    white = mat("white", (0.8, 0.79, 0.75), rough=0.32, sss=0.6, sss_r=(1, 0.9, 0.8), sss_scale=0.006, coat=0.3)
    yolk = mat("yolk", (0.95, 0.42, 0.02), rough=0.45, sss=0.5, sss_r=(1, 0.5, 0.1), sss_scale=0.004,
               bump=("noise", 400, 0.15))
    tilt = (math.radians(125), 0, 0)  # the cut face up and toward the camera
    for k, (x, y) in enumerate(((0, 0), (2.4 * r, 2.2 * r))):
        o = egg_mesh(f"half{k}", r, white)
        bisect(o, (0, 0, 0), (0, 1, 0))
        yk = sphere(f"yolk{k}", r * 0.56, (0, 0, 0), yolk, scale=(1, 0.4, 1.12))  # a dome on the face
        yk.parent = o
        o.rotation_euler, o.location = tilt, (x, y, 0)
        rest(o)
    return Vector((0, 0, r * 0.3)), 1.5 * r, True


def crystals(p, rng, n, s0, s1, m, spread):
    for i in range(n):
        s = rng.uniform(s0, s1)
        a, d = rng.uniform(0, math.tau), spread * math.sqrt(rng.random())
        z = s * 0.5 + max(0.0, (spread - d) * 0.35) * rng.random()
        cube(f"c{i}", (s, s * rng.uniform(0.9, 1.1), s * rng.uniform(0.85, 1.05)),
             (d * math.cos(a), d * math.sin(a), z), m,
             (rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5), rng.uniform(0, math.tau)), 0.1)


def salt(p, rng):
    m = mat("salt", (0.86, 0.88, 0.9), rough=0.12, sss=0.8, sss_r=(1, 1, 1), sss_scale=0.0008, coat=0.6)
    crystals(p, rng, 46, 0.0006, 0.0011, m, 0.0035)
    return Vector((0, 0, 0.0012)), 0.0042, True


def sugar(p, rng):
    m = mat("sugar", (0.95, 0.94, 0.92), rough=0.75, sss=0.35, sss_scale=0.002, bump=("voronoi", 1400, 0.6))
    for i in range(9):
        x, y = (i % 3 - 1) * 0.0165, (i // 3 - 1) * 0.0165
        cube(f"s{i}", (0.016, 0.016, 0.016), (x + rng.uniform(-1, 1) * 0.001, y, 0.008), m,
             (0, 0, rng.uniform(-0.08, 0.08)), 0.05)
    cube("top", (0.016, 0.016, 0.016), (0.004, -0.002, 0.024), m, (0, 0, 0.4), 0.05)
    return Vector((0, 0, 0.014)), 0.032, True


def gel(color, tint, glow):
    def build(p, rng):
        r = 0.03
        m = mat("gel", color, rough=0.05, sss=1.0, sss_r=tint, sss_scale=r * 0.5, coat=1.0, emit=glow)
        c = Vector((0, 0, 1.5 * r))
        sphere("blob", r, c, m, 96, 64)
        for i in range(7):
            a, e = rng.uniform(0, math.tau), rng.uniform(-0.6, 0.9)
            d = r * rng.uniform(1.5, 2.3)
            sphere(f"drop{i}", r * rng.uniform(0.08, 0.2),
                   c + Vector((math.cos(a) * math.cos(e), math.sin(a) * math.cos(e), math.sin(e))) * d, m)
        return c, 1.6 * r, True
    return build


def glycogen(p, rng):
    r = 0.03
    gran = mat("granule", (0.95, 0.83, 0.62), rough=0.3, sss=0.6, sss_scale=0.004, coat=0.6)
    water = mat("water", (0.25, 0.55, 1.0), rough=0.04, sss=1.0, sss_scale=0.004, coat=1.0, emit=0.15)
    c = Vector((0, 0, 1.4 * r))
    pts = []
    while len(pts) < 70:  # a rosette: granules packed in a ball, branching outward
        v = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)))
        v = v.normalized() * r * (rng.random() ** 0.4)
        if all((v - q).length > 0.2 * r for q in pts):
            pts.append(v)
    for i, v in enumerate(pts):
        sphere(f"g{i}", r * rng.uniform(0.11, 0.15), c + v, gran, 24, 16)
    for i in range(34):  # the water it holds
        v = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))).normalized()
        sphere(f"w{i}", r * rng.uniform(0.05, 0.1), c + v * r * rng.uniform(1.15, 1.5), water, 16, 12)
    return c, 1.5 * r, True


def protein(p, rng):
    r = 0.03
    colors = [(1.0, 0.43, 0.38), (0.78, 0.2, 0.18), (1.0, 0.66, 0.55), (0.92, 0.32, 0.28)]
    mats = [mat(f"aa{i}", col, rough=0.25, sss=0.5, sss_scale=0.003, coat=0.8) for i, col in enumerate(colors)]
    bond = mat("bond", (0.75, 0.78, 0.82), rough=0.2, metal=0.6)
    c = Vector((0, 0, 1.4 * r))
    pts = []
    for i in range(30):
        t = i / 29
        a = t * 3.2 * math.pi
        pts.append(c + Vector((math.cos(a) * r * (1 - 0.35 * t) + (t - 0.5) * 0.5 * r,
                               math.sin(a) * r * 0.75, (t - 0.5) * 1.6 * r + 0.15 * r * math.sin(5 * a))))
    for i, q in enumerate(pts):
        sphere(f"b{i}", r * rng.uniform(0.15, 0.2), q, mats[rng.randrange(len(mats))], 32, 20)
    tube("chain", [tuple(q) for q in pts], bond, r * 0.035)
    return c, 1.4 * r, True


def fibre(p, rng):
    r = 0.03
    m = mat("fibre", (0.62, 0.7, 0.38), rough=0.35, sss=0.5, sss_scale=0.003, coat=0.4, bump=("wave", 300, 0.2))
    water = mat("water", (0.3, 0.6, 1.0), rough=0.04, sss=1.0, sss_scale=0.003, coat=1.0, emit=0.12)
    c = Vector((0, 0, 1.3 * r))
    for i in range(16):
        a = rng.uniform(0, math.pi)
        d = Vector((math.cos(a), math.sin(a) * 0.5, rng.uniform(-0.5, 0.5))).normalized()
        off = Vector((rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4), rng.uniform(-0.5, 0.5))) * r
        pts = [tuple(c + off + d * r * 1.8 * (k / 5 - 0.5) * 2 +
                     Vector((0, 0, math.sin(k + i) * 0.12 * r))) for k in range(6)]
        tube(f"f{i}", pts, m, r * rng.uniform(0.025, 0.05))
    for i in range(26):
        v = Vector((rng.uniform(-1, 1), rng.uniform(-0.5, 0.5), rng.uniform(-0.7, 0.7))) * r
        sphere(f"w{i}", r * rng.uniform(0.05, 0.11), c + v, water, 20, 14)
    return c, 1.5 * r, True


def stomach(p, rng):
    r = 0.06
    wall = mat("stomach", (0.82, 0.34, 0.36), rough=0.28, sss=0.7, sss_r=(1, 0.3, 0.25), sss_scale=0.01,
               coat=0.7, bump=("wave", 40, 0.35))
    # esophagus down into the fundus, the body curving right, the pylorus up, the duodenum down
    path = [(-0.5, 1.65, 0.13), (-0.48, 1.2, 0.15), (-0.5, 0.9, 0.42), (-0.48, 0.5, 0.78), (-0.25, 0.05, 0.88),
            (0.2, -0.12, 0.72), (0.55, 0.05, 0.48), (0.72, 0.35, 0.28), (0.9, 0.5, 0.2), (1.05, 0.3, 0.17),
            (1.1, -0.05, 0.16)]
    c = Vector((0, 0, 1.2 * r))
    pts = [tuple(c + Vector((x, 0, z - 0.6)) * r) for x, z, _ in path]
    o = tube("stomach", pts, wall, r, [w for _, _, w in path])
    if p["look"] == "section":
        bpy.context.view_layer.objects.active = o
        o.select_set(True)
        bpy.ops.object.convert(target="MESH")
        bisect(o, c, (0, -1, 0), fill=False)
        sol = o.modifiers.new("wall", "SOLIDIFY")
        sol.thickness = 0.05 * r
        food = [mat(f"food{i}", col, rough=0.5, sss=0.3, sss_scale=0.003) for i, col in
                enumerate([(0.3, 0.55, 0.15), (0.9, 0.5, 0.12), (0.5, 0.28, 0.15), (0.92, 0.82, 0.55)])]
        for i in range(36):  # what was eaten, in the lower body
            x, z, w = path[rng.randrange(3, 7)]
            v = Vector((x + rng.uniform(-0.4, 0.4) * w, rng.uniform(0.15, 0.6) * w, z - 0.6 - rng.uniform(0, 0.55) * w))
            bm = bmesh.new()
            bmesh.ops.create_icosphere(bm, subdivisions=2, radius=r * rng.uniform(0.07, 0.13))
            ob = mesh_obj(f"bit{i}", bm, food[i % 4], loc=c + v * r)
            ob.scale = (1, rng.uniform(0.6, 1), rng.uniform(0.6, 1))
    cc, rr = bounds([o])
    return cc, rr, True


def muscle(p, rng):
    """Fascicles of fibres, cut at both ends (the classic muscle illustration)."""
    r = 0.025
    shades = [(0.5, 0.05, 0.06), (0.62, 0.09, 0.08), (0.42, 0.04, 0.05), (0.56, 0.12, 0.1)]
    reds = [mat(f"fibre{i}", col, rough=0.3, sss=0.8, sss_r=(1, 0.25, 0.2), sss_scale=0.003, coat=0.7,
                bump=("wave", 1600, 0.35)) for i, col in enumerate(shades)]
    c = Vector((0, 0, 1.3 * r))
    made, step, fr = [], 0.075 * r, 0.3 * r
    centres = [(0, 0)] + [(0.62 * r * math.cos(a), 0.62 * r * math.sin(a)) for a in
                          (k * math.tau / 6 + 0.3 for k in range(6))]
    for n, (cy, cz) in enumerate(centres):
        x0f, x1f = -2.0 * r - rng.uniform(0, 0.5) * r, 2.0 * r + rng.uniform(0, 0.5) * r
        for i in range(-5, 6):
            for j in range(-5, 6):
                y, z = (i + 0.5 * (j % 2)) * step, j * step * 0.87
                if y * y + z * z > fr * fr:
                    continue
                x0, x1 = x0f + rng.uniform(-0.08, 0.08) * r, x1f + rng.uniform(-0.08, 0.08) * r
                pts = [(x0 + (x1 - x0) * t / 5, cy + y + 0.02 * r * math.sin(2 * t + n),
                        cz + z + 0.025 * r * math.sin(2.5 * t + n)) for t in range(6)]
                made.append(tube(f"f{len(made)}", pts, reds[rng.randrange(4)], step * 0.5 * rng.uniform(0.82, 1.0)))
    for o in made:
        o.location += c
        o.rotation_euler.z = math.radians(55)
    return c, 2.0 * r, True  # framed on the bundle's length, not its width


def fatcell(p, rng):
    r = 0.03
    fat = mat("fat", (1.0, 0.7, 0.15), rough=0.18, sss=1.0, sss_r=(1, 0.55, 0.15), sss_scale=0.006, coat=0.7)
    c = Vector((0, 0, 1.3 * r))
    cells = []
    while len(cells) < 16:
        v = Vector((rng.gauss(0, 0.7), rng.gauss(0, 0.6), rng.gauss(0, 0.5))) * r
        s = r * rng.uniform(0.32, 0.48)
        if all((v - q).length > 0.85 * (s + t) for q, t in cells):
            cells.append((v, s))
    for i, (v, s) in enumerate(cells):
        sphere(f"cell{i}", s, c + v, fat, 48, 32)
    return c, 1.5 * r, True


def scale(p, rng):
    glass = mat("glass", (0.01, 0.011, 0.012), rough=0.18, coat=0.5, spec=0.3)
    body = mat("body", (0.85, 0.86, 0.87), rough=0.35, coat=0.3)
    lcd = mat("lcd", (0.45, 0.8, 1.0), rough=0.3, emit=3.0)
    cube("base", (0.3, 0.3, 0.028), (0, 0, 0.014), body, bevel=0.7)
    cube("top", (0.28, 0.28, 0.006), (0, 0, 0.029), glass, bevel=0.5)
    cube("screen", (0.08, 0.032, 0.001), (0, -0.098, 0.0325), mat("screen", (0.0, 0.02, 0.04), rough=0.2), bevel=0.2)
    if p.get("text"):
        cu = bpy.data.curves.new("digits", "FONT")
        cu.body, cu.size, cu.align_x, cu.align_y = p["text"], 0.022, "CENTER", "CENTER"
        t = link(bpy.data.objects.new("digits", cu))
        t.location = (0, -0.098, 0.0332)
        cu.materials.append(lcd)
    return Vector((0, 0, 0.02)), 0.17, True


def plate(p, rng):
    ceramic = mat("plate", (0.92, 0.91, 0.88), rough=0.22, coat=0.6, sss=0.1, sss_scale=0.002)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=128, radius1=0.075, radius2=0.11, depth=0.014)
    o = mesh_obj("plate", bm, ceramic, loc=(0, 0, 0.007))
    bv = o.modifiers.new("bevel", "BEVEL")
    bv.width, bv.segments = 0.004, 4
    scan("food_avocado_01", 0.07, (-0.035, 0.03, 0.014), 0.8)
    scan("food_apple_01", 0.08, (0.04, 0.03, 0.014), 0.2)
    scan("food_lime_01", 0.05, (0.02, -0.05, 0.014), 1.2)
    shell = mat("shell", (0.88, 0.7, 0.5), rough=0.5, sss=0.25, sss_scale=0.004)
    for k, (x, y) in enumerate(((-0.045, -0.035), (-0.02, -0.065))):
        o = egg_mesh(f"egg{k}", 0.022, shell, (x, y, 0.035))
        o.rotation_euler = (math.radians(90), 0, 0.9 + k)
        rest(o).location.z += 0.014
    return Vector((0, 0, 0.035)), 0.1, True


SUBJECTS = {
    "apple": scanned("food_apple_01", 0.08), "avocado": scanned("food_avocado_01", 0.1),
    "banana": scanned("bananas", 0.06), "lemon": scanned("lemon", 0.065),
    "lime": scanned("food_lime_01", 0.05), "onion": scanned("yellow_onion", 0.08),
    "sweet_potato": scanned("sweet_potato", 0.06), "croissant": scanned("croissant", 0.05),
    "buns": scanned("hamburger_buns", 0.07), "cake": scanned("carrot_cake", 0.09),
    "egg": egg, "salt": salt, "sugar": sugar, "water": gel((0.12, 0.42, 1.0), (0.3, 0.6, 1.0), 0.04),
    "oil": gel((0.95, 0.5, 0.02), (1.0, 0.45, 0.08), 0.03), "glycogen": glycogen, "protein": protein, "fibre": fibre,
    "stomach": stomach, "muscle": muscle, "fatcell": fatcell, "scale": scale, "plate": plate,
}


def heat(objects, c, r):
    """False colour: every subject surface glows from cold blue to hot yellow (bottom to top + noise)."""
    m = bpy.data.materials.new("heat")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    out = nt.nodes["Material Output"]
    tc, sep = nt.nodes.new("ShaderNodeNewGeometry"), nt.nodes.new("ShaderNodeSeparateXYZ")
    norm = nt.nodes.new("ShaderNodeMapRange")
    norm.inputs["From Min"].default_value, norm.inputs["From Max"].default_value = c.z - r, c.z + r
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 3.0
    mix = nt.nodes.new("ShaderNodeMath")
    mix.operation = "MULTIPLY_ADD"
    mix.inputs[1].default_value = 0.35
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = 0.15, (0.02, 0.02, 0.2, 1)
    els[1].position, els[1].color = 0.95, (1.0, 0.85, 0.15, 1)
    for pos, col in ((0.35, (0.35, 0.03, 0.5, 1)), (0.55, (0.9, 0.08, 0.1, 1)), (0.75, (1.0, 0.5, 0.0, 1))):
        e = els.new(pos)
        e.color = col
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 0.45
    noise.inputs["Scale"].default_value = 1.5 / r
    nt.links.new(tc.outputs["Position"], sep.inputs[0])
    nt.links.new(tc.outputs["Position"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], mix.inputs[0])
    nt.links.new(sep.outputs["Z"], norm.inputs["Value"])
    nt.links.new(norm.outputs["Result"], mix.inputs[2])
    nt.links.new(mix.outputs[0], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    for o in objects:
        if o.type in ("MESH", "CURVE"):
            o.data.materials.clear()
            o.data.materials.append(m)


# ---------------- camera ----------------

def ease(t):
    return t * t * (3 - 2 * t)


MOVES = {
    # t (0..1) -> (azimuth deg, elevation deg, distance x, focus shift toward the camera x r)
    "push": lambda t: (4 * t, 9, 1.22 - 0.4 * t, 0.0),
    "pull": lambda t: (-4 * t, 12, 0.85 + 0.35 * t, 0.0),
    "orbit": lambda t: (-22 + 44 * t, 14, 1.0, 0.0),
    "rise": lambda t: (8 * t, 2 + 26 * ease(t), 1.05 - 0.1 * t, 0.0),
    "slide": lambda t: (-38 + 76 * t, 6, 0.6, 0.7),
    "top": lambda t: (20 * t, 72, 1.0, 0.0),
    "whip": lambda t: (-70 + 140 * ease(t), 10, 0.9, 0.0),
}


def camera(c, r, move, seed, frames, rng):
    s = bpy.context.scene
    cam = bpy.data.cameras.new("cam")
    cam.lens, cam.sensor_width, cam.sensor_fit = LENS, 36, "AUTO"
    cam.clip_start, cam.clip_end = r * 0.05, r * 400
    o = link(bpy.data.objects.new("cam", cam))
    s.camera = o
    w, h = s.render.resolution_x, s.render.resolution_y
    half = math.atan(18 * min(w, h) / max(w, h) / LENS)  # half the narrow (horizontal) field
    d0 = r / (0.9 * math.tan(half))  # the subject fills about 90 % of the width
    a0 = rng.uniform(-40, 40)
    target = link(bpy.data.objects.new("target", None))
    k = o.constraints.new("TRACK_TO")
    k.target, k.track_axis, k.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
    cam.dof.use_dof = True
    cam.dof.focus_object = target
    for f in range(1, frames + 1):
        t = (f - 1) / max(1, frames - 1)
        az, el, dist, near = MOVES[move](t)
        az, el = math.radians(a0 + az), math.radians(el)
        out = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
        o.location = c + out * d0 * dist
        # aimed a little below the centre: the subject sits in the upper middle, above Marco
        target.location = c + out * r * near - Vector((0, 0, 0.35 * r * math.cos(el)))
        o.keyframe_insert("location", frame=f)
        target.keyframe_insert("location", frame=f)
    # depth of field: about half the subject sharp at its distance (a real macro lens)
    d = d0 * MOVES[move](0.5)[2]
    f_m = LENS / 1000
    cam.dof.aperture_fstop = max(1.4, min(22.0, 0.55 * r * f_m * f_m / (2 * 0.00003 * d * d)))
    if move == "whip":
        s.render.use_motion_blur = True
        s.render.motion_blur_shutter = 0.8
    return d0


# ---------------- main ----------------

def render_shot(cfg, shot):
    s = reset(cfg)
    rng = random.Random(shot.get("seed", 0))
    before = set(bpy.data.objects)
    c, r, floor = SUBJECTS[shot["subject"]](shot, rng)
    subject = [o for o in bpy.data.objects if o not in before]
    if shot["look"] == "heat":
        heat([x for o in subject for x in (o, *o.children_recursive)], c, r)
    studio(c, r, floor, warm=0.5 if shot["subject"] in ("apple", "croissant", "buns", "cake") else 0)
    frames = shot["frames"]
    d0 = camera(c, r, shot["move"], shot.get("seed", 0), frames, rng)
    dust(c, r, d0, rng)
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


def main():
    cfg = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
    for shot in cfg["shots"]:
        render_shot(cfg, shot)


main()
