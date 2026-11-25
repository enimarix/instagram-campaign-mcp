"""The physique style (« Physique Scan », owner order 75): the troupe in the look of the owner's
reference Reel, kinetic type on rolling 3D bands. A cream drafting world (a grid floor, no room),
the set drawn in cream with ink edges, the hero a flat navy statue (orange shorts), and bands of
bold type that wrap round his muscles and roll (troupe shots with `look: blueprint`, `bands`).

Every colour is an emission through a toon ramp (Diffuse -> Shader to RGB -> constant ramp), so
the picture keeps the flat print colours under the Standard view transform.
"""
import math
import os

import bpy
import kit
from mathutils import Matrix, Vector

CREAM, CREAM_SHADE = (0.95, 0.92, 0.85), (0.84, 0.80, 0.72)
INK, INK_LIGHT = (0.11, 0.13, 0.24), (0.55, 0.56, 0.62)
ORANGE, ORANGE_SHADE = (0.93, 0.43, 0.24), (0.70, 0.28, 0.16)
TEAL = (0.40, 0.62, 0.58)
# the statue: three tones so the muscles read (shadow, body, the key light's side)
SKIN = ((0.06, 0.07, 0.15), (0.16, 0.20, 0.36), (0.36, 0.52, 0.62))
FONTS = os.path.join(kit.ENGINE, "..", "..", "motion", "public", "fonts")
FONT = {"sans": "InterTight-Black.ttf", "serif": "InstrumentSerif-Italic.ttf"}
# body part -> (the bone the band rides, the vertex groups that give its girth)
PARTS = {
    "chest": ("mixamorig:Spine2", ("mixamorig:Spine2",)),
    "abs": ("mixamorig:Spine", ("mixamorig:Spine", "mixamorig:Spine1")),
    "arm_r": ("mixamorig:RightArm", ("mixamorig:RightArm",)),
    "arm_l": ("mixamorig:LeftArm", ("mixamorig:LeftArm",)),
    "forearm_r": ("mixamorig:RightForeArm", ("mixamorig:RightForeArm",)),
    "forearm_l": ("mixamorig:LeftForeArm", ("mixamorig:LeftForeArm",)),
    "thigh_r": ("mixamorig:RightUpLeg", ("mixamorig:RightUpLeg",)),
    "thigh_l": ("mixamorig:LeftUpLeg", ("mixamorig:LeftUpLeg",)),
}
TONES = {  # band, type
    "light": (CREAM, INK, "sans"),
    "dark": (INK, CREAM, "serif"),
    "orange": (ORANGE, CREAM, "sans"),
}
SLIDE = {"chest": 0.2, "abs": 0.6}  # where a band sits along its bone by default (else 0.5)
GAP = 0.025  # the band rides this far off the skin (m)
LINE = 0.006  # ink edge width (m)


def _lin(c):
    """sRGB -> linear (Blender's colour inputs)."""
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def _ramp(nt, tones):
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = 0.0, (*_lin(tones[0]), 1)
    els[1].position, els[1].color = 0.18, (*_lin(tones[1]), 1)
    for i, c in enumerate(tones[2:]):
        e = els.new(0.55 + 0.2 * i)
        e.color = (*_lin(c), 1)
    return ramp


def toon(name, tones, cull=False, also=None, where=None):
    """A flat material: the light it gets, stepped into `tones` (dark..light), emitted as is.
    `also`, `where`: other tones where the body's rest height (its `rest_z` attribute, 0 = the
    feet, 1 = the top of the head) lies in one of the `where` [lo, hi] ranges (the statue's
    shorts, a top): a clean edge that stays on the body through any pose."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt, ln = m.node_tree, m.node_tree.links
    nt.nodes.clear()
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    rgb = nt.nodes.new("ShaderNodeShaderToRGB")
    ln.new(diff.outputs[0], rgb.inputs[0])
    ramp = _ramp(nt, tones)
    ln.new(rgb.outputs["Color"], ramp.inputs["Fac"])
    colour = ramp.outputs["Color"]
    if also:
        other = _ramp(nt, also)
        ln.new(rgb.outputs["Color"], other.inputs["Fac"])
        attr = nt.nodes.new("ShaderNodeAttribute")
        attr.attribute_name = "rest_z"
        mask = None
        for lo, hi in where:
            ge = nt.nodes.new("ShaderNodeMath")  # 1 inside [lo, hi], else 0
            ge.operation, ge.inputs[1].default_value = "GREATER_THAN", lo
            le = nt.nodes.new("ShaderNodeMath")
            le.operation, le.inputs[1].default_value = "LESS_THAN", hi
            ln.new(attr.outputs["Fac"], ge.inputs[0])
            ln.new(attr.outputs["Fac"], le.inputs[0])
            both = nt.nodes.new("ShaderNodeMath")
            both.operation = "MULTIPLY"
            ln.new(ge.outputs[0], both.inputs[0])
            ln.new(le.outputs[0], both.inputs[1])
            if mask is None:
                mask = both.outputs[0]
            else:
                mx = nt.nodes.new("ShaderNodeMath")
                mx.operation = "MAXIMUM"
                ln.new(mask, mx.inputs[0])
                ln.new(both.outputs[0], mx.inputs[1])
                mask = mx.outputs[0]
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        ln.new(mask, mix.inputs["Factor"])
        ln.new(ramp.outputs["Color"], mix.inputs["A"])
        ln.new(other.outputs["Color"], mix.inputs["B"])
        colour = mix.outputs["Result"]
    emit = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    ln.new(colour, emit.inputs["Color"])
    ln.new(emit.outputs[0], out.inputs["Surface"])
    m.use_backface_culling = cull
    return m


def flat(name, color):
    """One colour, unlit."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (*_lin(color), 1)
    nt.links.new(emit.outputs[0], nt.nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    return m


def outline(o, width=LINE, color=INK):
    """An ink edge: the inverted hull (a solidify shell drawn on its back faces only)."""
    ink = bpy.data.materials.get("bp_outline") or flat("bp_outline", color)
    ink.use_backface_culling = True
    o.data.materials.append(ink)
    sol = o.modifiers.new("outline", "SOLIDIFY")
    sol.thickness, sol.offset, sol.use_flip_normals = width, 1.0, True
    sol.material_offset = len(o.data.materials) - 1
    sol.use_rim = False


def _grid_floor():
    """A cream drafting floor with ink grid lines (0.5 m, every 4th darker) out to the horizon."""
    m = bpy.data.materials.new("bp_grid")
    m.use_nodes = True
    nt, ln = m.node_tree, m.node_tree.links
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ln.new(tc.outputs["Object"], sep.inputs[0])

    def lines(axis, step, width):
        div = nt.nodes.new("ShaderNodeMath")
        div.operation, div.inputs[1].default_value = "DIVIDE", step
        ln.new(sep.outputs[axis], div.inputs[0])
        fr = nt.nodes.new("ShaderNodeMath")
        fr.operation = "FRACT"
        ln.new(div.outputs[0], fr.inputs[0])
        cen = nt.nodes.new("ShaderNodeMath")
        cen.operation, cen.inputs[1].default_value = "SUBTRACT", 0.5
        ln.new(fr.outputs[0], cen.inputs[0])
        ab = nt.nodes.new("ShaderNodeMath")
        ab.operation = "ABSOLUTE"
        ln.new(cen.outputs[0], ab.inputs[0])
        gt = nt.nodes.new("ShaderNodeMath")
        gt.operation, gt.inputs[1].default_value = "GREATER_THAN", 0.5 - width / step
        ln.new(ab.outputs[0], gt.inputs[0])
        return gt.outputs[0]

    def either(a, b):
        mx = nt.nodes.new("ShaderNodeMath")
        mx.operation = "MAXIMUM"
        ln.new(a, mx.inputs[0])
        ln.new(b, mx.inputs[1])
        return mx.outputs[0]

    fine = either(lines(0, 0.5, 0.006), lines(1, 0.5, 0.006))
    bold = either(lines(0, 2.0, 0.012), lines(1, 2.0, 0.012))
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["A"].default_value = (*_lin(CREAM), 1)
    mix.inputs["B"].default_value = (*_lin((0.78, 0.76, 0.72)), 1)
    ln.new(fine, mix.inputs["Factor"])
    mix2 = nt.nodes.new("ShaderNodeMix")
    mix2.data_type = "RGBA"
    ln.new(mix.outputs["Result"], mix2.inputs["A"])
    mix2.inputs["B"].default_value = (*_lin((0.62, 0.60, 0.60)), 1)
    ln.new(bold, mix2.inputs["Factor"])
    emit = nt.nodes.new("ShaderNodeEmission")
    ln.new(mix2.outputs["Result"], emit.inputs["Color"])
    ln.new(emit.outputs[0], nt.nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    bpy.ops.mesh.primitive_plane_add(size=80, location=(0, 0, 0.002))
    o = bpy.context.object
    o.name = "bp_floor"
    o.data.materials.append(m)
    return o


def _world():
    """The world: cream to the camera, no light on the scene (the key light alone shapes the
    toon ramps, so the muscles read)."""
    nt = bpy.context.scene.world.node_tree
    nt.nodes.clear()
    path = nt.nodes.new("ShaderNodeLightPath")
    seen = nt.nodes.new("ShaderNodeBackground")
    seen.inputs[0].default_value, seen.inputs[1].default_value = (*_lin(CREAM), 1), 1.0
    dark = nt.nodes.new("ShaderNodeBackground")
    dark.inputs[0].default_value, dark.inputs[1].default_value = (0.5, 0.5, 0.5, 1), 0.15
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(path.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(dark.outputs[0], mix.inputs[1])
    nt.links.new(seen.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], nt.nodes.new("ShaderNodeOutputWorld").inputs["Surface"])


def _assign(o, *mats):
    """`o` wears `mats` (object-linked slots too: MPFB links some materials to the object)."""
    o.data.materials.clear()
    for m in mats:
        o.data.materials.append(m)
    for slot, m in zip(o.material_slots, mats):
        slot.link = "DATA"
        slot.material = m


def restyle(actors):
    """The set in the blueprint look: the room (floor, walls, ceiling) gone for a cream
    world and grid floor, every prop cream with ink edges, the lamps off (the toon ramp reads
    the key light alone). `actors`: {who: (body, rig)}: their meshes are left to statue()."""
    s = bpy.context.scene
    s.view_settings.view_transform, s.view_settings.look = "Standard", "None"
    _world()
    mine = {o for body, rig in actors.values() for o in (rig, *rig.children_recursive)}
    room = ("floor", "wall_", "ceiling")
    prop = toon("bp_prop", (CREAM_SHADE, CREAM, CREAM))
    accent = toon("bp_accent", (ORANGE_SHADE, ORANGE, ORANGE))
    for o in list(s.objects):
        if o in mine:
            continue
        if o.type == "LIGHT" and o.data.type == "POINT":
            o.hide_render = True
        if o.type != "MESH":
            continue
        box = [o.matrix_world @ Vector(c) for c in o.bound_box]
        low, high = min(c.z for c in box), max(c.z for c in box)
        if o.name.startswith(room) or o.name in ("stripe", "window") or high - low > 2.3 or low > 1.0:
            bpy.data.objects.remove(o)  # the room and its decor: the drafting world instead
            continue
        names = {(sl.material.name.lower() if sl.material else "") for sl in o.material_slots}
        hot = "mat" in names or any(n.startswith("prop_food") for n in names)
        _assign(o, accent if hot else prop)
        outline(o)
    _grid_floor()
    ring = flat("bp_ring", ORANGE)
    for body, rig in actors.values():  # the reference's orange measuring rings on the floor
        for r, w in ((0.75, 0.012), (1.05, 0.006)):
            bpy.ops.mesh.primitive_torus_add(major_radius=r, minor_radius=w, major_segments=96,
                                             minor_segments=4, location=(*rig.location.xy, 0.004))
            t = bpy.context.object
            t.scale.z = 0.2
            _assign(t, ring)


def statue(body, rig, look):
    """The hero as a flat navy statue: three-tone skin, orange shorts (the hips-to-thigh band
    of the undeformed body) and a sports top on a woman, eyes and hair in ink, brows and lashes
    gone, an ink edge."""
    woman = look["phenotype"].get("gender", 1.0) < 0.5
    where = [(0.36, 0.555)] + ([(0.70, 0.79)] if woman else [])  # shorts (and a sports top)
    skin = toon("bp_skin", SKIN, also=(ORANGE_SHADE, ORANGE, ORANGE), where=where)
    ink = flat("bp_ink", INK)
    for o in rig.children_recursive:
        if o.type != "MESH" or o is body:
            continue
        n = o.name.lower()
        if "brow" in n or "lash" in n or "teeth" in n or "tongue" in n:
            o.hide_render = True
        else:  # hair and eyes
            _assign(o, ink)
    top = max(v.co.z for v in body.data.vertices)  # the rest pose's height
    rest = body.data.attributes.new("rest_z", "FLOAT", "POINT")
    # the rig's bones only (MPFB also weights every vertex 1.0 to Left / Mid / Right / body)
    names = {g.index: g.name for g in body.vertex_groups if g.name.startswith("mixamorig:")}

    def arm(v):  # the hands hang at hip height in the rest pose: never in the shorts (2.0: above
        # every range, so no seam is interpolated where the arm meets the torso)
        g = max((g for g in v.groups if g.group in names), key=lambda g: g.weight, default=None)
        n = names[g.group] if g else ""
        return "Arm" in n or "Hand" in n

    rest.data.foreach_set("value", [2.0 if arm(v) else v.co.z / top for v in body.data.vertices])
    _assign(body, skin)
    outline(body, 0.008)


def _girth(body, groups, head, axis, length):
    """How far the part's skin lies from the bone's axis (m): the 90th percentile of the
    vertices weighted to `groups` that lie along the bone."""
    idx = {body.vertex_groups[g].index for g in groups if g in body.vertex_groups}
    dg = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(dg)
    mesh = ev.to_mesh()
    d = []
    for v in mesh.vertices:  # the evaluated mesh keeps its weights (decimated: other vertices)
        if not any(g.group in idx and g.weight > 0.5 for g in v.groups):
            continue
        p = ev.matrix_world @ v.co - head
        t = p.dot(axis)
        if -0.1 * length <= t <= 1.1 * length:
            d.append((p - axis * t).length)
    ev.to_mesh_clear()
    if not d:
        return 0.08
    d.sort()
    return d[int(0.9 * (len(d) - 1))]


def _text_ring(text, tone, radius, height, name):
    """The band's type: `text` repeated round the band (the local Z axis), letters standing on
    it, facing out and reading left to right from outside: the flat text mesh wrapped onto the
    cylinder of `radius` (x along the line -> the angle, y up -> z, its depth -> outward)."""
    fill, ink, face = TONES[tone]
    font = bpy.data.fonts.load(os.path.join(FONTS, FONT[face]), check_existing=True)
    curve = bpy.data.curves.new(f"{name}_type", "FONT")
    curve.font = font
    curve.size, curve.extrude = height * 0.62, 0.0025
    unit = f"{text.upper() if face == 'sans' else text}   •   "
    flat_o = bpy.data.objects.new(f"{name}_flat", curve)
    bpy.context.collection.objects.link(flat_o)
    curve.body = unit
    bpy.context.view_layer.update()
    loop = 2 * math.pi * radius
    reps = max(1, round(loop / max(flat_o.dimensions.x, 1e-3)))
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
    _assign(o, flat(f"{name}_ink", ink))
    return o, fill


def _strip(radius, height, fill, name):
    """The band itself: an open cylinder round the local Z axis, its fill with ink rims and a
    tape measure's ticks along the top edge."""
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=radius, depth=height, end_fill_type="NOTHING")
    o = bpy.context.object
    o.name = name
    m = bpy.data.materials.new(f"{name}_fill")
    m.use_nodes = True
    nt, ln = m.node_tree, m.node_tree.links
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ln.new(tc.outputs["Object"], sep.inputs[0])
    # rims: |z| near half the height
    ab = nt.nodes.new("ShaderNodeMath")
    ab.operation = "ABSOLUTE"
    ln.new(sep.outputs[2], ab.inputs[0])
    rim = nt.nodes.new("ShaderNodeMath")
    rim.operation, rim.inputs[1].default_value = "GREATER_THAN", height / 2 - 0.004
    ln.new(ab.outputs[0], rim.inputs[0])
    # ticks: every 6 degrees, on the top fifth
    ang = nt.nodes.new("ShaderNodeMath")
    ang.operation = "ARCTAN2"
    ln.new(sep.outputs[1], ang.inputs[0])
    ln.new(sep.outputs[0], ang.inputs[1])
    sc = nt.nodes.new("ShaderNodeMath")
    sc.operation, sc.inputs[1].default_value = "MULTIPLY", 60 / (2 * math.pi)
    ln.new(ang.outputs[0], sc.inputs[0])
    fr = nt.nodes.new("ShaderNodeMath")
    fr.operation = "FRACT"
    ln.new(sc.outputs[0], fr.inputs[0])
    tick = nt.nodes.new("ShaderNodeMath")
    tick.operation, tick.inputs[1].default_value = "LESS_THAN", 0.12
    ln.new(fr.outputs[0], tick.inputs[0])
    top = nt.nodes.new("ShaderNodeMath")
    top.operation, top.inputs[1].default_value = "GREATER_THAN", height * 0.3
    ln.new(sep.outputs[2], top.inputs[0])
    both = nt.nodes.new("ShaderNodeMath")
    both.operation = "MULTIPLY"
    ln.new(tick.outputs[0], both.inputs[0])
    ln.new(top.outputs[0], both.inputs[1])
    any_ = nt.nodes.new("ShaderNodeMath")
    any_.operation = "MAXIMUM"
    ln.new(rim.outputs[0], any_.inputs[0])
    ln.new(both.outputs[0], any_.inputs[1])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["A"].default_value = (*_lin(fill), 1)
    mix.inputs["B"].default_value = (*_lin(INK if fill != INK else CREAM), 1)
    ln.new(any_.outputs[0], mix.inputs["Factor"])
    emit = nt.nodes.new("ShaderNodeEmission")
    ln.new(mix.outputs["Result"], emit.inputs["Color"])
    ln.new(emit.outputs[0], nt.nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    o.data.materials.append(m)
    return o


def band(body, rig, spec, frames, name):
    """A band of type round a body part (spec: on, text, tone, turns, slide [from, to] along the
    bone), riding the bone through the action and rolling `turns` times over the shot."""
    bone_name, groups = PARTS[spec["on"]]
    s = bpy.context.scene
    s.frame_set(1)
    pb = rig.pose.bones[bone_name]
    m = rig.matrix_world @ pb.matrix
    tail = rig.matrix_world @ pb.tail
    head, axis = m.translation, (tail - m.translation).normalized()
    length = (tail - head).length
    radius = _girth(body, groups, head, axis, length) + GAP
    height = min(0.10, max(0.045, radius * 0.45))
    root = bpy.data.objects.new(name, None)
    s.collection.objects.link(root)
    strip = _strip(radius, height, TONES[spec.get("tone", "light")][0], f"{name}_band")
    typ, _ = _text_ring(spec["text"], spec.get("tone", "light"), radius, height, name)
    spin = bpy.data.objects.new(f"{name}_spin", None)
    s.collection.objects.link(spin)
    for o in (strip, typ):
        o.parent = spin
    spin.parent = root
    # the root rides the bone, baked frame by frame in world space (its Z axis on the bone,
    # at `slide` along it): exact whatever the rig's scale or parenting
    a, b = spec.get("slide") or (SLIDE.get(spec["on"], 0.5),) * 2
    step = max(1, frames // 24)
    root.rotation_mode = "QUATERNION"  # no Euler flips between baked keys
    for f in sorted({*range(1, frames + 1, step), frames}):
        s.frame_set(f)
        m = rig.matrix_world @ pb.matrix
        tail = rig.matrix_world @ pb.tail
        u = a + (b - a) * (f - 1) / max(1, frames - 1)
        z = (tail - m.translation).normalized()
        root.matrix_world = Matrix.Translation(m.translation.lerp(tail, u)) @ z.to_track_quat("Z", "Y").to_matrix().to_4x4()
        root.keyframe_insert("location", frame=f)
        root.keyframe_insert("rotation_quaternion", frame=f)
    s.frame_set(1)
    spin.rotation_euler = (0, 0, 0)
    spin.keyframe_insert("rotation_euler", frame=1)
    spin.rotation_euler = (0, 0, 2 * math.pi * spec.get("turns", 0.5))
    spin.keyframe_insert("rotation_euler", frame=frames)
    for o in (root, spin):
        if o.animation_data and o.animation_data.action:
            for fc in _curves(o.animation_data.action):
                for k in fc.keyframe_points:
                    k.interpolation = "LINEAR" if o is spin else "BEZIER"
    return root


def _curves(action):
    """An action's F-curves (Blender 5 keeps them in layered channelbags)."""
    if hasattr(action, "fcurves"):
        try:
            return list(action.fcurves)
        except (AttributeError, RuntimeError):
            pass
    out = []
    for layer in getattr(action, "layers", ()):
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", ()):
                out.extend(bag.fcurves)
    return out


def part_center(rig, part):
    """The middle of a body part's bone, world space, at the current frame."""
    pb = rig.pose.bones[PARTS[part][0]]
    return (rig.matrix_world @ pb.head).lerp(rig.matrix_world @ pb.tail, 0.5)


def orbit(frames, center, radius, z, start_deg, sweep_deg, lens=35, push=0.0):
    """A camera circling `center` (world): from `start_deg` (0 = in front, -Y) through
    `sweep_deg` over the shot, eased, pushing in by `push` of the radius."""
    s = bpy.context.scene
    cam = bpy.data.cameras.new("cam")
    cam.lens = lens
    o = bpy.data.objects.new("cam", cam)
    s.collection.objects.link(o)
    t = bpy.data.objects.new("cam_target", None)
    s.collection.objects.link(t)
    t.location = center
    k = o.constraints.new("TRACK_TO")
    k.target, k.track_axis, k.up_axis = t, "TRACK_NEGATIVE_Z", "UP_Y"
    s.camera = o
    steps = max(2, min(frames, 12))
    for i in range(steps):
        u = i / (steps - 1)
        e = u * u * (3 - 2 * u)
        a = math.radians(start_deg + sweep_deg * e)
        r = radius * (1 - push * e)
        o.location = Vector((center.x + math.sin(a) * r, center.y - math.cos(a) * r, z))
        o.keyframe_insert("location", frame=1 + round(u * (frames - 1)))
    return o
