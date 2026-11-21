"""The troupe: MPFB characters (cinematic/cast.json), PS2-ified, lip-synced, acting.

An actor = a cast look + where it stands (a set spot) + an action (cinematic/actions.json): a
library clip retargeted on the MPFB rig, or a hand-keyed move on top of one, played on its own
clock (time warp for fast-forward / slow-mo, a per-actor offset so a crowd never moves in sync),
with a face (ARKit face units) and maybe a hand prop.
"""
import json
import math
import os

import bpy
import kit
import retarget

ACTIONS = json.load(open(os.path.join(kit.ENGINE, "..", "actions.json"), encoding="utf-8"))
LIBRARY = os.path.join(kit.TOOLS, "anim", "Animation Library[Standard]", "Godot",
                       "AnimationLibrary_Godot_Standard.glb")
PHENOTYPE = {"gender": 0.5, "age": 0.5, "muscle": 0.5, "weight": 0.5, "proportions": 0.5,
             "height": 0.5, "cupsize": 0.5, "firmness": 0.5}
RACES = ("caucasian", "asian", "african")
SEAT_FWD = 0.1  # a seated rig sits this far in front of its chair's centre
# Rhubarb mouth shape -> Meta viseme (visemes02 pack)
RHUBARB = {"A": "PP", "B": "kk", "C": "E", "D": "aa", "E": "O", "F": "U", "G": "FF", "H": "nn", "X": "sil"}


# ---------------- looks ----------------

def build(ch, name=None):
    """The MPFB human for a cast.json entry (rig `mixamo`, visemes + face units loaded)."""
    services = kit.mpfb()
    race = {r: ch["phenotype"].get("race", {}).get(r, 0.0) for r in RACES}
    info = {
        "name": name or ch.get("name", "actor"), "phenotype": {**PHENOTYPE, **ch["phenotype"], "race": race},
        "rig": "mixamo", "skin_mhmat": ch["skin"], "skin_material_type": "ENHANCED_SSS",
        "eyes": "low-poly/low-poly.mhclo", "eyes_material_type": "PROCEDURAL_EYES",
        "eyebrows": ch.get("eyebrows", "eyebrow001/eyebrow001.mhclo"),
        "eyelashes": "eyelashes01/eyelashes01.mhclo",
        "teeth": "teeth_base/teeth_base.mhclo", "tongue": "tongue01/tongue01.mhclo",
        "hair": ch["hair"], "clothes": ch["clothes"], "clothes_material_type": "MAKESKIN",
        "targets": [], "alternative_materials": {}, "color_adjustments": {},
    }
    settings = services.HumanService.get_default_deserialization_settings()
    settings["subdiv_levels"] = 0
    body = services.HumanService.deserialize_from_dict(info, settings)
    services.FaceService.load_targets(body, load_microsoft_visemes=False, load_meta_visemes=True,
                                      load_arkit_faceunits=True)
    services.FaceService.interpolate_targets(body)
    return body, body.parent


def decimate(body, rig):
    """Fewer polygons on everything the character wears."""
    for o in rig.children_recursive:
        if o.type == "MESH":
            d = o.modifiers.new("ps2_decimate", "DECIMATE")
            d.ratio = 0.5 if o is body else 0.35
            if "hair" in o.name.lower():
                d.ratio = 0.6


def share_images():
    """One copy of each image file: MPFB loads a skin, hair or outfit again for every actor
    wearing it (dad, uncle and chef share a skin), and each copy would sit in VRAM (177)."""
    first = {}
    for img in list(bpy.data.images):
        if not img.filepath or not img.size[0]:
            continue
        key = (os.path.normcase(bpy.path.abspath(img.filepath)), img.colorspace_settings.name,
               tuple(img.size))
        if key in first:
            img.user_remap(first[key])
            bpy.data.images.remove(img)
        else:
            first[key] = img


def crush_textures(px=1024):
    """Small textures, nearest filtering, one copy each. Faces and outfits keep up to `px`
    (they came at 2048-4096 and sat whole in VRAM, 177's diet), the rest 512: that contrast
    is the look."""
    share_images()
    for img in bpy.data.images:
        if img.size[0] == 0 or "@" in img.name or img.name.endswith(".hdr"):   # set textures are sized at load
            continue
        n = img.name.lower()
        cap = px if ("skin" in n or "male" in n or "female" in n) else min(px, 512)
        w, h = img.size
        if max(w, h) > cap:
            k = cap / max(w, h)
            img.scale(max(1, int(w * k)), max(1, int(h * k)))
    for m in bpy.data.materials:
        if m.use_nodes:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE":
                    n.interpolation = "Closest"


# ---------------- face ----------------

def lip_sync(body, cues, fps):
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
        f0 = 1 + round(c["start"] * fps)
        want = {names[v]: w for v, w in mix[c["value"]].items() if names.get(v)}
        for n in targets:
            keys[n].value = want.get(n, 0.0)
            keys[n].keyframe_insert("value", frame=f0)


def blinks(body, frames, rng):
    """Blinks every 2-4 s, 4 frames each."""
    keys = body.data.shape_keys.key_blocks
    blink = [k.name for k in keys if "eyeblink" in k.name.lower()]
    f = rng.randint(6, 30)
    while blink and f < frames:
        for n in blink:
            for df, v in [(0, 0), (2, 1), (4, 0)]:
                keys[n].value = v
                keys[n].keyframe_insert("value", frame=f + df)
        f += rng.randint(48, 96)


def face(body, name, frame=1, ease=4):
    """An actions.json face, easing in over `ease` frames up to `frame`."""
    keys = body.data.shape_keys.key_blocks
    for unit, w in ACTIONS["faces"][name].items():
        if unit not in keys:
            print("WARN face unit missing:", unit)
            continue
        for f, v in ((max(1, frame - ease), 0.0), (frame, w)):
            keys[unit].value = v
            keys[unit].keyframe_insert("value", frame=f)


def idle(rig, frames, fps):
    """Subtle idle without a clip: breathing + small head turns, like canned cutscene animation."""
    head, spine = rig.pose.bones["mixamorig:Head"], rig.pose.bones["mixamorig:Spine1"]
    base_h, base_s = head.rotation_euler.copy(), spine.rotation_euler.copy()
    for f in range(1, frames + 1, 6):
        t = f / fps
        head.rotation_euler = (base_h[0] + math.radians(2.5 * math.sin(t * 1.3)),
                               base_h[1] + math.radians(4 * math.sin(t * 0.7 + 1)),
                               base_h[2])
        spine.rotation_euler = (base_s[0] + math.radians(1.2 * math.sin(t * 2.1)), base_s[1], base_s[2])
        head.keyframe_insert("rotation_euler", frame=f)
        spine.keyframe_insert("rotation_euler", frame=f)


# ---------------- actions ----------------

def move_of(action):
    """{base, keys, cycle, speed, prop, lie, face} for a library clip or a hand-keyed move."""
    return ACTIONS["moves"].get(action) or {"base": action}


def clock(frames, fps, speed=1.0, offset=0.0, scale=1.0):
    """The action's own time (s) at each shot frame: speed is a number or a [from, to] ramp (x10
    fast-forward, 0.3 slow-mo), times the move's own `scale`; offset shifts the start."""
    a, b = (speed, speed) if isinstance(speed, (int, float)) else speed
    n = max(1, frames - 1)
    return [offset + scale * (i / fps) * (a + (b - a) * (i / n) / 2) for i in range(frames)]


def source_frames(act, times, fps):
    """Clip frames of the bpy action to sample for `times`: `_Loop` clips wrap, the others
    hold their end."""
    f0, f1 = (int(x) for x in act.frame_range)
    span = max(1, f1 - f0)
    loop = act.name.endswith("_Loop")
    return [f0 + ((t * fps) % span if loop else min(t * fps, span)) for t in times]


def _smooth(keys, x):
    if x <= keys[0][0]:
        return keys[0][1]
    for (x0, v0), (x1, v1) in zip(keys, keys[1:]):
        if x <= x1:
            u = (x - x0) / max(1e-6, x1 - x0)
            u = u * u * (3 - 2 * u)
            return [p + (q - p) * u for p, q in zip(v0, v1)]
    return keys[-1][1]


def keyed(move, times, offset=0.0):
    """Per-frame extra bone rotations (degrees) of a hand-keyed move: looping keys follow the
    actor's clock, timed ones start with the shot (a raised fork rises on screen)."""
    keys, cycle = move.get("keys") or {}, move.get("cycle")
    return [{bone: _smooth(k, (t % cycle) / cycle if cycle else t - offset) for bone, k in keys.items()}
            for t in times]


def prop(name, rig):
    """A small hand prop parented to the right hand (built from kit primitives)."""
    steel = kit.mat("prop_steel", (0.75, 0.75, 0.75), metal=1.0, rough=0.3)
    if name == "fork":
        o = kit.box("fork", (0.016, 0.02, 0.19), (0, 0, 0), steel)
    elif name == "phone":
        o = kit.box("phone", (0.075, 0.012, 0.15), (0, 0, 0), kit.mat("phone", (0.05, 0.05, 0.06), rough=0.2, coat=0.8))
    elif name == "plate":
        o = kit.cyl("plate", 0.13, 0.02, (0, 0, 0), kit.mat("prop_ceramic", (0.93, 0.91, 0.86), rough=0.22), verts=12, r2=0.09)
        kit.blob("plate_food", (0.07, 0.07, 0.035), (0, 0, 0.03), kit.mat("prop_food", (0.8, 0.45, 0.2), rough=0.6)).parent = o
    elif name == "dumbbell":
        o = kit.cyl("dumbbell", 0.015, 0.3, (0, 0, 0), steel, verts=8)
        o.rotation_euler.x = math.radians(90)
        for s in (-1, 1):
            kit.cyl("weight", 0.06, 0.05, (0, 0, s * 0.12), kit.mat("prop_iron", (0.08, 0.08, 0.09), rough=0.5), verts=8).parent = o
    else:
        raise ValueError(f"unknown prop {name}")
    o.parent, o.parent_type, o.parent_bone = rig, "BONE", "mixamorig:RightHand"
    o.location = (0, -0.05, 0.03) if name != "plate" else (0, -0.06, 0.08)
    return o


def place(rig, spot, facing=None, lie=False):
    """Stand (or sit, or lie) the rig on a sets.json spot."""
    a = math.radians(spot.get("facing", 0) if facing is None else facing)
    x, y = spot["at"]
    if spot.get("seat"):
        x, y = x + math.sin(a) * SEAT_FWD, y - math.cos(a) * SEAT_FWD
    rig.location = (x, y, spot.get("z", 0.0))
    rig.rotation_euler = (math.radians(-90) if lie else 0.0, 0.0, a)


def ground(body, rig):
    """Lower (or raise) the rig so the body's lowest point at frame 1 touches the floor."""
    bpy.context.scene.frame_set(1)
    ev = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    low = min((ev.matrix_world @ v.co).z for v in ev.to_mesh().vertices)
    ev.to_mesh_clear()
    rig.location.z -= low


def act(body, rig, move, sampled, fps, frames, rng, face_name=None, face_at=0.0, times=None, offset=0.0):
    """Play a move on the rig, still upright at the origin (retarget.apply): the retargeted base
    (sampled clip), its keys, the face, blinks, the prop. Then place() it (and ground() a lying one)."""
    seated = ACTIONS["seated"] if move["base"].startswith("Sitting") else {}
    extra = keyed(move, times, offset) if move.get("keys") else None
    retarget.apply(rig, *sampled, skip=seated.get("skip", ()), offsets=seated.get("offsets"), keyed=extra)
    blinks(body, frames, rng)
    name = face_name or move.get("face")
    if name:
        face(body, name, 1 + round(face_at * fps))
    if move.get("prop"):
        prop(move["prop"], rig)


def head(rig):
    """The head's world position and the way the face looks (unit vector), at the current frame."""
    m = rig.matrix_world @ rig.pose.bones["mixamorig:Head"].matrix
    return m.translation + m.to_3x3().col[1] * 0.1, m.to_3x3().col[2].normalized()

