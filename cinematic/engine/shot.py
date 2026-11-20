"""PS2-cutscene shot builder, run inside Blender by src/studio/cinematic.py:

    blender -b -P cinematic/engine/shot.py -- <shot.json>

<shot.json> (written by cinematic.py): out, fps, frames, size, cues (Rhubarb mouth cues),
character (a cinematic/cast.json preset), cameras [{frame, pos, look_at, lens}] (cuts at those
frames), stills (frames to render as still_<frame>.png, or null for the whole sequence
frames/f_####.png) and the set's sky keys. Builds the MPFB character (seated, lip-synced, a
retargeted CC0 talking clip) in the dining set, crushes textures to PS2 size.
"""
import json
import os
import random
import sys

import bpy

ENGINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE)
import dining  # noqa: E402
import kit  # noqa: E402
import people  # noqa: E402
import retarget  # noqa: E402
import stage  # noqa: E402

ARGS = sys.argv[sys.argv.index("--") + 1:]
CFG = json.load(open(ARGS[0], encoding="utf-8"))
OUT = os.path.abspath(CFG["out"])
FPS = CFG.get("fps", 24)


# ---------------- main ----------------

def main():
    s = stage.reset(CFG)
    cues = CFG.get("cues", [])
    frames = CFG["frames"]
    ch = CFG["character"]
    clip = ch.get("clip")
    # sample the clip while the scene is still empty (frame changes are cheap then)
    sampled = None
    if clip:
        glb = clip["glb"] if os.path.isabs(clip["glb"]) else os.path.join(kit.TOOLS, clip["glb"])
        sampled = retarget.sample(os.path.abspath(glb), clip["action"], frames)
    sun_dir = dining.build(CFG)
    body, rig = people.build(ch)
    people.dress(rig, ch, ch.get("name", "actor"))
    rig.location = ch.get("location", (0, 0, 0))
    people.decimate(body, rig)
    people.crush_textures()
    if sampled:
        retarget.apply(rig, *sampled, skip=clip.get("skip", ()), offsets=clip.get("offsets"))
    stage.lights(sun_dir, cfg=CFG)
    stage.cut_cameras(CFG["cameras"])
    s.frame_start, s.frame_end = 1, frames
    people.lip_sync(body, cues, FPS)
    random.seed(3)
    people.blinks(body, frames, random)
    if not sampled:
        people.idle(rig, frames, FPS)
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
