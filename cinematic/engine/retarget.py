"""Retarget Quaternius Universal Animation Library clips (CC0, rigify DEF- bones) onto the MPFB
mixamo rig. Bones are matched by name, then each target bone is rotated so it points where
the source bone points, which tolerates different rest poses (T-pose vs A-pose)."""
import math

import bpy
from mathutils import Euler, Matrix

MAP = {"DEF-hips": "Hips", "DEF-spine.001": "Spine", "DEF-spine.002": "Spine1", "DEF-spine.003": "Spine2",
       "DEF-neck": "Neck", "DEF-head": "Head"}
for _s, _side in (("L", "Left"), ("R", "Right")):
    MAP.update({f"DEF-shoulder.{_s}": f"{_side}Shoulder", f"DEF-upper_arm.{_s}": f"{_side}Arm",
                f"DEF-forearm.{_s}": f"{_side}ForeArm", f"DEF-hand.{_s}": f"{_side}Hand",
                f"DEF-thigh.{_s}": f"{_side}UpLeg", f"DEF-shin.{_s}": f"{_side}Leg",
                f"DEF-foot.{_s}": f"{_side}Foot", f"DEF-toe.{_s}": f"{_side}ToeBase"})
    for _f in ("index", "middle", "ring", "pinky"):
        for _i in (1, 2, 3):
            MAP[f"DEF-f_{_f}.0{_i}.{_s}"] = f"{_side}Hand{_f.capitalize()}{_i}"
    for _i in (1, 2, 3):
        MAP[f"DEF-thumb.0{_i}.{_s}"] = f"{_side}HandThumb{_i}"


def sample(glb, action, n_frames):
    """Import the library, play `action` (looping) and record world matrices per frame."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb)
    new = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in new if o.type == "ARMATURE")
    act = bpy.data.actions[action]
    arm.animation_data_create()
    arm.animation_data.action = act
    if getattr(act, "slots", None):
        arm.animation_data.action_slot = act.slots[0]
    f0, f1 = (int(x) for x in act.frame_range)
    span = max(1, f1 - f0)                       # loops repeat their first frame at the end
    rest = {b.name: arm.matrix_world @ b.matrix_local for b in arm.data.bones if b.name in MAP}
    frames = []
    sc = bpy.context.scene
    for i in range(n_frames):
        sc.frame_set(f0 + i % span)
        frames.append({n: arm.matrix_world @ arm.pose.bones[n].matrix for n in rest})
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
    return rest, frames


def apply(rig, rest_s, frames, start=1, skip=(), offsets=None):
    """skip: target bones left at rest. offsets: {bone: [x, y, z] degrees} added on top, local space."""
    offsets = {k: Euler([math.radians(v) for v in r]).to_quaternion() for k, r in (offsets or {}).items()}
    mw = rig.matrix_world
    scale = mw.to_scale()
    def short(b):
        return b.name.split(":")[-1]
    src_of = {t: s for s, t in MAP.items() if s in rest_s}
    bones = sorted((b for b in rig.data.bones if short(b) in src_of and short(b) not in skip),
                   key=lambda b: len(b.parent_recursive))

    # face the same way: if the source's left arm is on the other side, spin the source 180 degrees
    fix = Matrix.Identity(4)
    t_left = (mw @ rig.data.bones["mixamorig:LeftArm"].matrix_local).translation.x
    if (rest_s["DEF-upper_arm.L"].translation.x > 0) != (t_left > 0):
        fix = Matrix.Rotation(math.pi, 4, "Z")
    rest_s = {k: fix @ v for k, v in rest_s.items()}

    align = {}
    for b in bones:
        s = src_of[short(b)]
        t_rest, s_rest = mw @ b.matrix_local, rest_s[s]
        c = t_rest.to_3x3().col[1].normalized().rotation_difference(s_rest.to_3x3().col[1].normalized())
        align[b.name] = (s, s_rest.to_quaternion().inverted(), c @ t_rest.to_quaternion())

    hips = rig.data.bones["mixamorig:Hips"]
    ratio = (mw @ hips.matrix_local).translation.z / max(1e-6, rest_s["DEF-hips"].translation.z)
    prev = {}
    for i, fr in enumerate(frames):
        world = {}
        for b in bones:
            s, s_rest_inv, t_virtual = align[b.name]
            s_pose = fix @ fr[s]
            q = s_pose.to_quaternion() @ s_rest_inv @ t_virtual
            parent = b.parent if b.parent and b.parent.name in world else None
            if parent:
                rest_off = parent.matrix_local.inverted() @ b.matrix_local
                loc = (world[parent.name] @ rest_off).translation
            else:
                loc = (mw @ b.matrix_local).translation
                if b == hips:
                    loc = loc + (s_pose.translation - rest_s["DEF-hips"].translation) * ratio
            w = Matrix.LocRotScale(loc, q, scale)
            world[b.name] = w
            arm_space = mw.inverted() @ w
            if parent:
                basis = (parent.matrix_local.inverted() @ b.matrix_local).inverted() @ (mw.inverted() @ world[parent.name]).inverted() @ arm_space
            else:
                basis = b.matrix_local.inverted() @ arm_space
            loc_b, rot_b, _ = basis.decompose()
            if short(b) in offsets:
                rot_b = rot_b @ offsets[short(b)]
            if b.name in prev and prev[b.name].dot(rot_b) < 0:
                rot_b.negate()                   # keep quaternions continuous between keys
            prev[b.name] = rot_b
            pb = rig.pose.bones[b.name]
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = rot_b
            pb.keyframe_insert("rotation_quaternion", frame=start + i)
            if b == hips:
                pb.location = loc_b
                pb.keyframe_insert("location", frame=start + i)
