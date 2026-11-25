"""Shot lists for the troupe styles (step 163), run inside Blender by src/studio/troupe.py:

    blender -b -P cinematic/engine/troupe.py -- <shots.json>

<shots.json>: out, fps, size, samples, texture_px (the largest image side), shots [{id, set, light, frames, speed, seed, stills,
camera {kind, on, aim: start | end}, cast [{who, look (its cast.json entry), spot {at, facing, seat, z}, facing,
to (a spot to walk to), action, face, face_at, offset}]}], all resolved and checked by
troupe.py. Every shot is its own scene: the set (engine/<sets.json module>.py), the actors
(engine/people.py) and one camera (engine/stage.py). Writes out/<id>/f_####.png (frames
1..frames) or out/<id>/still_<n>.png for each frame in `stills`, and out/<id>/stats.json
(the scene's texture memory, 177).
"""
import importlib
import json
import math
import os
import random
import sys

import bpy

ENGINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE)
import bands  # noqa: E402
import people  # noqa: E402
import retarget  # noqa: E402
import stage  # noqa: E402


def render_shot(cfg, shot):
    # ponytail: every shot rebuilds its set and actors (~10 s an actor); group the shots that
    # share a set and cast into one build if build time ever matters next to render time.
    s = stage.reset(cfg)
    fps, frames = cfg["fps"], shot["frames"]
    spec = stage.SETS["sets"][shot["set"]]
    preset = stage.SETS["lights"][shot.get("light") or spec["light"]]
    # sample every actor's clip while the scene is still empty (frame changes are cheap then)
    moves, clocks = [], []
    for a in shot["cast"]:
        move = people.move_of(a["action"])
        moves.append(move)
        clocks.append(people.clock(frames, fps, shot.get("speed", 1.0), a.get("offset", 0.0), move.get("speed", 1.0)))
    sampled = retarget.sample_many(people.LIBRARY, [
        (m["base"], lambda act, t=t: people.source_frames(act, t, fps)) for m, t in zip(moves, clocks)])
    sun = importlib.import_module(spec["module"]).build(cfg, spec)
    stage.ambient(preset)
    rng = random.Random(shot.get("seed", 0))
    actors, bodies = {}, {}
    for a, move, smp, times in zip(shot["cast"], moves, sampled, clocks):
        body, rig = people.build(a["look"], a["who"])
        people.dress(rig, a["look"], a["who"])
        people.decimate(body, rig)
        people.act(body, rig, move, smp, fps, frames, rng, a.get("face"), a.get("face_at", 0.0), times,
                   a.get("offset", 0.0))
        people.place(rig, a["spot"], a.get("facing"), move.get("lie"))
        if a.get("to"):  # walk there in a straight line over the shot
            rig.keyframe_insert("location", frame=1)
            people.place(rig, a["to"], a.get("facing"))
            rig.keyframe_insert("location", frame=frames)
        if move.get("lie"):
            people.ground(body, rig)
        actors[a["who"]], bodies[a["who"]] = rig, body
    people.crush_textures(cfg.get("texture_px", 1024))
    if shot.get("look") == "blueprint":  # the physique style: the owner's reference look
        for a in shot["cast"]:
            bands.statue(bodies[a["who"]], actors[a["who"]], a["look"])
        bands.restyle({w: (bodies[w], actors[w]) for w in actors})
        for i, b in enumerate(shot.get("bands") or ()):
            bands.band(bodies[b["who"]], actors[b["who"]], b, frames, f"band{i}")
    stage.lights(sun or stage.sun_dir(preset), preset)
    s.frame_start, s.frame_end = 1, frames
    cam = shot["camera"]
    on = actors.get(cam.get("on"))
    s.frame_set(frames if cam.get("aim") == "end" else 1)  # where the actor ends up, or starts
    head, look = people.head(on) if on else (None, None)
    s.frame_set(1)
    if cam["kind"] == "orbit" or cam.get("part") and cam["kind"] in ("close", "dolly"):
        # round the actor's body part (orbit: a wide arc pushing in; close: a slow drift;
        # dolly: a push in)
        c = bands.part_center(on, cam.get("part") or "chest")
        facing = math.degrees(on.rotation_euler.z)
        arc = {"orbit": (-35, 70, 1.7, 0.3), "close": (-6, 12, 1.25, 0.0), "dolly": (-10, 20, 1.7, 0.35)}
        start, sweep, radius, push = arc[cam["kind"]]
        bands.orbit(frames, c, radius, c.z + 0.12, facing + start, sweep, lens=32, push=push)
    else:
        stage.camera(cam["kind"], frames, spec["wide"], spec["center"], head, look, high=cam.get("aim") == "end")
    out = os.path.join(os.path.abspath(cfg["out"]), shot["id"])
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(texture_stats(), f)
    s.render.image_settings.file_format = "PNG"
    if shot.get("stills"):
        for f in shot["stills"]:
            s.frame_set(f)
            s.render.filepath = os.path.join(out, f"still_{f}.png")
            bpy.ops.render.render(write_still=True)
    else:
        s.render.filepath = os.path.join(out, "f_")
        bpy.ops.render.render(animation=True)


def texture_stats():
    """What the scene's images weigh at render time (step 177's VRAM diet): their count, MB
    uncompressed (no mipmaps) and the biggest ones."""
    imgs = [i for i in bpy.data.images if i.users and i.size[0]]
    size = {i.name: i.size[0] * i.size[1] * i.channels * (4 if i.is_float else 1) for i in imgs}
    big = sorted(imgs, key=lambda i: -size[i.name])[:8]
    return {"images": len(imgs), "texture_mb": round(sum(size.values()) / 2**20, 1),
            "largest": [[i.name, *i.size] for i in big]}


def main():
    cfg = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
    for shot in cfg["shots"]:
        render_shot(cfg, shot)


main()
