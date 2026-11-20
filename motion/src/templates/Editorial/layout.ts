// Editorial staging (step 144, round 2): every chapter has its own composition and a camera
// move, so no two chapters in a row look alike (owner: more scene and camera changes, nothing
// repetitive), and a scene longer than 3 s cuts to a new framing (step 162: recut, typeShot).
// Pure, so `node --test` checks it (test/editorial.test.ts).
import { shotCuts, type Timeline } from "../../lib/timeline.ts";
import type { TREE_ACTIONS } from "./schema.ts";

/**
 * The tree chapters' camera at `t` (0..1 of the chapter): zoom `z`, the point of the crown it
 * frames (`u`, `v`: 0..1 across the crown's box), where that point sits on screen (`at`, in
 * px; null = where it is in the wide shot) and a roll in degrees.
 * - bloom: crane up from the trunk to the whole crown, pulling out as it blooms;
 * - wind: wide, panning with the gust;
 * - petals: macro close-up on a corner of the crown, creeping in;
 * - frame: wide while the viewfinder closes, then a zoom into what it frames (reframe);
 * - loop: a slow dolly out with a roll, the ring around it.
 */
export type Camera = { z: number; u: number; v: number; at: [number, number] | null; roll: number };
const smooth = (t: number) => t * t * (3 - 2 * t);
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

export const cameraOf = (action: (typeof TREE_ACTIONS)[number], t: number): Camera => {
  const e = smooth(Math.min(1, Math.max(0, t)));
  switch (action) {
    case "bloom":
      return { z: lerp(1.45, 1, e), u: 0.5, v: lerp(1.25, 0.55, e), at: null, roll: 0 };
    case "wind":
      return { z: 1.1, u: lerp(0.38, 0.62, e), v: 0.5, at: null, roll: lerp(-1, 1, e) };
    case "petals":
      return { z: lerp(1.95, 2.3, e), u: 0.7, v: 0.35, at: [560, 900], roll: lerp(2, -1, e) };
    case "frame": {
      const zoom = smooth(Math.min(1, Math.max(0, (t - 0.45) / 0.4)));
      return { z: lerp(1, 1.55, zoom), u: 0.5, v: 0.45, at: null, roll: 0 };
    }
    case "loop":
      return { z: lerp(1.18, 0.94, e), u: 0.5, v: 0.5, at: null, roll: lerp(-3, 2, e) };
  }
};

/** The payoff's camera: from close on the crown, pulling out to the whole tree. */
export const payoffCamera = (t: number): Camera => {
  const e = smooth(Math.min(1, Math.max(0, t / 0.7)));
  return { z: lerp(1.7, 1, e), u: 0.5, v: lerp(0.35, 0.55, e), at: null, roll: 0 };
};

/**
 * Camera `cam` as shot `k` of its scene frames it (a long scene cuts every MAX_SHOT_S,
 * shotCuts): 0 as it is; odd = a cut in closer on another part of the crown; even = a cut
 * back out a little wider, rolled the other way.
 */
export const recut = (cam: Camera, k: number): Camera => {
  if (!k) return cam;
  if (k % 2) return { ...cam, z: cam.z * 1.3, u: cam.u + (k % 4 === 1 ? 0.18 : -0.18), v: cam.v - 0.1, roll: cam.roll - 2 };
  return { ...cam, z: cam.z * 0.88, roll: cam.roll + 2 };
};

/** A type-only shot's framing after `k` cuts: the block jumps smaller and lower (odd), or back up (even). Never larger: it stays in the safe area. */
export const typeShot = (k: number) => (!k ? { scale: 1, dy: 0 } : k % 2 ? { scale: 0.86, dy: 170 } : { scale: 0.94, dy: -50 });

/** Scene lengths in frames (0 = hook, 1..n = chapters, n+1 = payoff), the last one running to the end card. */
export const sceneLens = (t: Timeline, chapters: number, endStart: number) => {
  const scenes = t.scenes.slice(0, chapters + 2);
  return scenes.map((s, i) => (i + 1 < scenes.length ? scenes[i + 1].startFrame : endStart) - s.startFrame);
};

/** Every cut inside a scene: the frame it lands on and the shot it starts (1 = the scene's second shot). */
export const cutsOf = (t: Timeline, chapters: number, endStart: number, fps: number) =>
  sceneLens(t, chapters, endStart).flatMap((len, i) => shotCuts(len, fps).map((at, k) => ({ frame: t.scenes[i].startFrame + at, shot: k + 1 })));
