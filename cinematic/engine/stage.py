"""Render settings, light presets (cinematic/sets.json `lights`) and cameras shared by the
cinematic engine's runs (shot.py: the single-character skit, troupe.py: shot lists)."""
import json
import math
import os

import bpy
import kit
from mathutils import Vector

SETS = json.load(open(os.path.join(kit.ENGINE, "..", "sets.json"), encoding="utf-8"))


def reset(cfg):
    bpy.ops.wm.read_homefile(use_empty=True)
    s = bpy.context.scene
    s.render.fps = cfg.get("fps", 24)
    try:
        s.render.engine = "BLENDER_EEVEE"
    except TypeError:
        s.render.engine = "BLENDER_EEVEE_NEXT"
    s.render.resolution_x, s.render.resolution_y = cfg.get("size", [720, 1280])
    s.render.filter_size = 0.8
    e = s.eevee
    # VRAM diet (177: the NVIDIA driver stalled under troupe scenes on the 8 GB laptop): a
    # 256 MB shadow pool (default 512); ray tracing stays at Blender's half resolution; no
    # volumetric settings (no set has a volume: nothing is allocated for them).
    for attr, val in [("taa_render_samples", cfg.get("samples", 64)), ("use_shadows", True), ("shadow_ray_count", 2),
                      ("shadow_step_count", 8), ("shadow_pool_size", "256"), ("use_raytracing", True),
                      ("use_fast_gi", True), ("fast_gi_method", "GLOBAL_ILLUMINATION"), ("fast_gi_distance", 1.5)]:
        if hasattr(e, attr):
            try:
                setattr(e, attr, val)
            except (TypeError, ValueError) as err:
                print("eevee", attr, err)
    s.view_settings.view_transform = "AgX"          # soft filmic highlights like the reference
    for look in ("AgX - Punchy", "None"):
        try:
            s.view_settings.look = look
            break
        except TypeError:
            pass
    s.world = bpy.data.worlds.new("world")
    s.world.use_nodes = True
    ambient(SETS["lights"]["sunset"])
    return s


def ambient(preset):
    """The flat world light (a baked-light feel)."""
    bg = bpy.context.scene.world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (*preset["ambient"], 1)
    bg.inputs[1].default_value = preset["ambient_strength"]


def sun_dir(preset):
    az, el = (math.radians(a) for a in preset["sun_dir"])
    return Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el)))


def lights(sun, preset=None, cfg=None):
    """Key = the low sun (soft shadows), coming from `sun` (unit vector toward it). Fill = warm
    bounce from the camera side. Rim (when the preset has one) = a coloured side / back light.
    Shadow softness is what sells the 'baked light' look."""
    p, cfg = preset or SETS["lights"]["sunset"], cfg or {}
    key = bpy.data.lights.new("key", "SUN")
    key.color, key.energy = p["sun"], cfg.get("sun_energy", p["sun_energy"])
    key.angle = math.radians(5)
    o = bpy.data.objects.new("key", key)
    o.rotation_euler = sun.to_track_quat("Z", "Y").to_euler()   # lamp +Z points at the sun
    bpy.context.collection.objects.link(o)
    fill = bpy.data.lights.new("fill", "AREA")
    fill.color, fill.energy, fill.size = p["fill"], cfg.get("fill_energy", p["fill_energy"]), 2.5
    fill.use_shadow = False
    fo = bpy.data.objects.new("fill", fill)
    fo.location = (0.6, -2.9, 1.7)
    fo.rotation_euler = (math.radians(80), 0, math.radians(10))
    bpy.context.collection.objects.link(fo)
    if p.get("rim"):  # a coloured side light (the sitcom presets, step 164): video-game contrast
        rim = bpy.data.lights.new("rim", "SUN")
        rim.color, rim.energy, rim.angle = p["rim"], p["rim_energy"], math.radians(3)
        ro = bpy.data.objects.new("rim", rim)
        ro.rotation_euler = sun_dir({"sun_dir": p["rim_dir"]}).to_track_quat("Z", "Y").to_euler()
        bpy.context.collection.objects.link(ro)


def cut_cameras(specs):
    """One camera per spec; a timeline marker at its frame cuts to it."""
    s = bpy.context.scene
    for i, c in enumerate(specs):
        o, t = _camera(f"cam{i}", c.get("lens", 40))
        o.location, t.location = c["pos"], c["look_at"]
        s.timeline_markers.new(f"cut{i}", frame=c.get("frame", 1)).camera = o
        if i == 0:
            s.camera = o


def _camera(name, lens):
    cam = bpy.data.cameras.new(name)
    cam.lens = lens
    o = bpy.data.objects.new(name, cam)
    bpy.context.collection.objects.link(o)
    t = bpy.data.objects.new(f"{name}_target", None)
    bpy.context.collection.objects.link(t)
    k = o.constraints.new("TRACK_TO")
    k.target, k.track_axis, k.up_axis = t, "TRACK_NEGATIVE_Z", "UP_Y"
    return o, t


def _ease(u):
    return u * u * (3 - 2 * u)


FLOOR_HEAD = 0.6  # a head lower than this (m) lies on the floor


def camera(kind, frames, wide, center, head=None, look=None, high=False):
    """The shot's camera. wide: the set's establishing camera; center: what `top` looks at;
    head / look: the named actor's head and the way its face looks (close-ups); high: looks
    down on the actor from ~50 degrees (a frozen punchline: over the table, never behind it).
    Kinds: wide, close (reaction close-up), top (top-down), whip (a fast pan landing on the
    actor), crash (crash zoom on the actor), dolly (slow push in on the actor)."""
    s = bpy.context.scene
    o, t = _camera("cam", wide.get("lens", 24))
    s.camera = o
    pos, aim = Vector(wide["pos"]), Vector(wide["look_at"])
    if head is not None:
        if head.z < FLOOR_HEAD or high:  # lying on the floor, or falling: from above (164)
            tilt = 0.35 if head.z < FLOOR_HEAD else 0.75
            face = (Vector((look.x, look.y, 0)).normalized() * tilt + Vector((0, -0.05, 1))).normalized()
        else:
            face = Vector((look.x, look.y, 0)).normalized() if abs(look.z) < 0.8 else look
        near, aim = head + face * 0.85 + Vector((0, 0, 0.04)), head - Vector((0, 0, 0.03))
    if kind == "top":
        c = Vector(center)
        pos, aim, o.data.lens = c + Vector((0, -0.05, 4.3)), c, 20
        # the camera is above the ceiling: what hangs wholly above 2 m (ceiling, pendant lamp)
        # is hidden from the camera only, so the room keeps its shadows
        for ob in s.objects:
            if ob.type == "MESH" and min((ob.matrix_world @ Vector(b)).z for b in ob.bound_box) > 2.0:
                ob.visible_camera = False
    elif kind == "close":
        pos, o.data.lens = near, 50
    elif kind == "dolly":
        o.data.lens = 45
        for f, u in ((1, 0.0), (frames, 1.0)):
            o.location = head + (near - head) * (1.9 - 0.9 * _ease(u))
            o.keyframe_insert("location", frame=f)
    elif kind == "crash":
        pos = head + (near - head) * 1.6
        for f, lens in ((1, 18), (min(frames, 6), 75)):
            o.data.lens = lens
            o.data.keyframe_insert("lens", frame=f)
    elif kind == "whip":
        if head is not None:
            pos, o.data.lens = head + (near - head) * 2.2, 35
        start = aim + (pos - aim).cross(Vector((0, 0, 1))).normalized() * 3.0
        land = min(frames, max(4, frames // 3))
        for f in range(1, land + 1):
            t.location = start.lerp(aim, _ease((f - 1) / max(1, land - 1)))
            t.keyframe_insert("location", frame=f)
        s.render.use_motion_blur, s.render.motion_blur_shutter = True, 1.0
    if kind not in ("dolly",):
        o.location = pos
    if kind != "whip":
        t.location = aim
    return o
