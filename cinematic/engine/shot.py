"""PS2-cutscene shot builder, run inside Blender by src/studio/cinematic.py:

    blender -b -P cinematic/engine/shot.py -- <shot.json>

(the portable Blender in cinematic/tools keeps MPFB enabled in its own prefs, cinematic/setup.py)

<shot.json> (written by cinematic.py): out, fps, frames, size, cues (Rhubarb mouth cues),
character (a cinematic/cast.json preset), cameras [{frame, pos, look_at, lens}] (cuts at those
frames), stills (frames to render as still_<frame>.png, or null for the whole sequence
frames/f_####.png) and the set's sky keys. Builds the MPFB character (seated, lip-synced, a
retargeted CC0 talking clip) in the dining set, crushes textures to PS2 size.
"""
import json
import math
import os
import random
import sys

import bpy
from bl_ext.user_default.mpfb.services import FaceService, HumanService

ENGINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE)
import dining  # noqa: E402
import retarget  # noqa: E402

ARGS = sys.argv[sys.argv.index("--") + 1:]
CFG = json.load(open(ARGS[0], encoding="utf-8"))
OUT = os.path.abspath(CFG["out"])
FPS = CFG.get("fps", 24)

# Rhubarb mouth shape -> Meta viseme (visemes02 pack)
RHUBARB = {"A": "PP", "B": "kk", "C": "E", "D": "aa", "E": "O", "F": "U", "G": "FF", "H": "nn", "X": "sil"}


# ---------------- scene ----------------

def reset():
    bpy.ops.wm.read_homefile(use_empty=True)
    s = bpy.context.scene
    s.render.fps = FPS
    try:
        s.render.engine = "BLENDER_EEVEE"
    except TypeError:
        s.render.engine = "BLENDER_EEVEE_NEXT"
    s.render.resolution_x, s.render.resolution_y = CFG.get("size", [720, 1280])
    s.render.filter_size = 0.8
    e = s.eevee
    for attr, val in [("taa_render_samples", 64), ("use_shadows", True), ("shadow_ray_count", 2),
                      ("shadow_step_count", 8), ("use_raytracing", True), ("use_fast_gi", True),
                      ("fast_gi_method", "GLOBAL_ILLUMINATION"), ("fast_gi_distance", 1.5),
                      ("volumetric_tile_size", "4"), ("volumetric_samples", 64), ("use_volumetric_shadows", True),
                      ("volumetric_end", 8.0)]:
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
    bg = s.world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.55, 0.36, 0.25, 1)
    bg.inputs[1].default_value = 0.25              # warm flat ambient = baked-light feel
    return s


def lights(sun_dir):
    """Key = the low sun, coming in through the window (soft shadows). Fill = warm bounce from the
    camera side. Shadow softness is what sells the 'baked light' look."""
    sun = bpy.data.lights.new("sunset_key", "SUN")
    sun.color, sun.energy = (1.0, 0.56, 0.3), CFG.get("sun_energy", 5.0)
    sun.angle = math.radians(5)
    o = bpy.data.objects.new("sunset_key", sun)
    o.rotation_euler = sun_dir.to_track_quat("Z", "Y").to_euler()   # lamp +Z points at the sun
    bpy.context.collection.objects.link(o)
    fill = bpy.data.lights.new("fill", "AREA")
    fill.color, fill.energy, fill.size = (1.0, 0.78, 0.6), CFG.get("fill_energy", 60), 2.5
    fill.use_shadow = False
    fo = bpy.data.objects.new("fill", fill)
    fo.location = (0.6, -2.9, 1.7)
    fo.rotation_euler = (math.radians(80), 0, math.radians(10))
    bpy.context.collection.objects.link(fo)


def cameras(specs):
    """One camera per spec; a timeline marker at its frame cuts to it."""
    s = bpy.context.scene
    for i, c in enumerate(specs):
        cam = bpy.data.cameras.new(f"cam{i}")
        cam.lens = c.get("lens", 40)
        o = bpy.data.objects.new(f"cam{i}", cam)
        o.location = c["pos"]
        bpy.context.collection.objects.link(o)
        t = bpy.data.objects.new(f"cam{i}_target", None)
        t.location = c["look_at"]
        bpy.context.collection.objects.link(t)
        k = o.constraints.new("TRACK_TO")
        k.target, k.track_axis, k.up_axis = t, "TRACK_NEGATIVE_Z", "UP_Y"
        s.timeline_markers.new(f"cut{i}", frame=c.get("frame", 1)).camera = o
        if i == 0:
            s.camera = o


# ---------------- character ----------------

def build_character(ch):
    info = {
        "name": ch["name"], "phenotype": ch["phenotype"], "rig": "mixamo",
        "skin_mhmat": ch["skin"], "skin_material_type": "ENHANCED_SSS",
        "eyes": "low-poly/low-poly.mhclo", "eyes_material_type": "PROCEDURAL_EYES",
        "eyebrows": ch.get("eyebrows", "eyebrow001/eyebrow001.mhclo"),
        "eyelashes": "eyelashes01/eyelashes01.mhclo",
        "teeth": "teeth_base/teeth_base.mhclo", "tongue": "tongue01/tongue01.mhclo",
        "hair": ch["hair"], "clothes": ch["clothes"], "clothes_material_type": "MAKESKIN",
        "targets": [], "alternative_materials": {}, "color_adjustments": {},
    }
    settings = HumanService.get_default_deserialization_settings()
    settings["subdiv_levels"] = 0
    body = HumanService.deserialize_from_dict(info, settings)
    FaceService.load_targets(body, load_microsoft_visemes=False, load_meta_visemes=True, load_arkit_faceunits=True)
    FaceService.interpolate_targets(body)
    rig = body.parent
    rig.location = ch.get("location", (0, 0, 0))
    return body, rig


def ps2ify(body, rig, ch):
    # fewer polygons: decimate everything the character wears
    for o in rig.children_recursive:
        if o.type == "MESH":
            d = o.modifiers.new("ps2_decimate", "DECIMATE")
            d.ratio = 0.5 if o is body else 0.35
            if "hair" in o.name.lower():
                d.ratio = 0.6
    # small textures, nearest filtering. Faces keep a bit more detail: that contrast is the look.
    for img in bpy.data.images:
        if img.size[0] == 0 or "@" in img.name or img.name.endswith(".hdr"):   # set textures are sized at load
            continue
        n = img.name.lower()
        cap = 4096 if ("skin" in n or "male" in n or "female" in n) else 512
        w, h = img.size
        if max(w, h) > cap:
            k = cap / max(w, h)
            img.scale(max(1, int(w * k)), max(1, int(h * k)))
    for m in bpy.data.materials:
        if m.use_nodes:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE":
                    n.interpolation = "Closest"


def pose_seated(rig, ch):
    pb = rig.pose.bones
    for name, rot in ch.get("pose", {}).items():
        b = pb["mixamorig:" + name]
        b.rotation_mode = "XYZ"
        b.rotation_euler = [math.radians(a) for a in rot]


def animate(body, rig, cues, frames, idle=True):
    random.seed(3)
    keys = body.data.shape_keys.key_blocks
    names = {v: next((k.name for k in keys if k.name.lower().endswith("viseme_" + v.lower())), None) for v in RHUBARB.values()}
    missing = [v for v, n in names.items() if n is None]
    if missing:
        print("WARN visemes missing:", missing, "available sample:", [k.name for k in keys][:12])
    targets = [n for n in names.values() if n]
    # each Rhubarb shape = a viseme mix; a bit of "aa" opens the jaw so speech reads on a phone
    mix = {"A": {"PP": 1.0}, "B": {"kk": 1.0, "aa": 0.2}, "C": {"E": 1.0, "aa": 0.35},
           "D": {"aa": 1.0}, "E": {"O": 1.0, "aa": 0.3}, "F": {"U": 1.0}, "G": {"FF": 1.0},
           "H": {"nn": 1.0, "aa": 0.25}, "X": {}}
    for c in cues:
        f0 = 1 + round(c["start"] * FPS)
        want = {names[v]: w for v, w in mix[c["value"]].items() if names.get(v)}
        for n in targets:
            keys[n].value = want.get(n, 0.0)
            keys[n].keyframe_insert("value", frame=f0)
    # blinks every 2-4 s, 4 frames each
    blink = [k.name for k in keys if "eyeblink" in k.name.lower()]
    f = 12
    while blink and f < frames:
        for n in blink:
            for df, v in [(0, 0), (2, 1), (4, 0)]:
                keys[n].value = v
                keys[n].keyframe_insert("value", frame=f + df)
        f += random.randint(48, 96)
    if not idle:
        return
    # subtle idle: breathing + small head turns, like canned cutscene animation
    head, spine = rig.pose.bones["mixamorig:Head"], rig.pose.bones["mixamorig:Spine1"]
    base_h, base_s = head.rotation_euler.copy(), spine.rotation_euler.copy()
    for f in range(1, frames + 1, 6):
        t = f / FPS
        head.rotation_euler = (base_h[0] + math.radians(2.5 * math.sin(t * 1.3)),
                               base_h[1] + math.radians(4 * math.sin(t * 0.7 + 1)),
                               base_h[2])
        spine.rotation_euler = (base_s[0] + math.radians(1.2 * math.sin(t * 2.1)), base_s[1], base_s[2])
        head.keyframe_insert("rotation_euler", frame=f)
        spine.keyframe_insert("rotation_euler", frame=f)


# ---------------- main ----------------

def main():
    s = reset()
    cues = CFG.get("cues", [])
    frames = CFG["frames"]
    ch = CFG["character"]
    clip = ch.get("clip")
    # sample the clip while the scene is still empty (frame changes are cheap then)
    sampled = None
    if clip:
        glb = clip["glb"] if os.path.isabs(clip["glb"]) else os.path.join(ENGINE, "..", "tools", clip["glb"])
        sampled = retarget.sample(os.path.abspath(glb), clip["action"], frames)
    sun_dir = dining.build(CFG)
    body, rig = build_character(ch)
    ps2ify(body, rig, ch)
    if sampled:
        retarget.apply(rig, *sampled, skip=clip.get("skip", ()), offsets=clip.get("offsets"))
    pose_seated(rig, ch)
    lights(sun_dir)
    cameras(CFG["cameras"])
    s.frame_start, s.frame_end = 1, frames
    animate(body, rig, cues, frames, idle=not sampled)
    os.makedirs(OUT, exist_ok=True)
    if CFG.get("save_blend"):
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "shot.blend"))
    s.render.image_settings.file_format = "PNG"
    if CFG.get("stills"):
        for f in CFG["stills"]:
            s.frame_set(f)
            s.render.filepath = os.path.join(OUT, f"still_{f}.png")
            bpy.ops.render.render(write_still=True)
    else:
        s.render.filepath = os.path.join(OUT, "frames", "f_")
        bpy.ops.render.render(animation=True)


main()
