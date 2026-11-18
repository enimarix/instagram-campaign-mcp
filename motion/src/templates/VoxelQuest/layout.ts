// VoxelQuest staging (step 130): where things stand in the kitchen set, and the camera for
// every frame. Pure (no React, no three.js) so `node --test` checks the framing of the
// examples frame by frame (test/voxelquest.test.ts): the golem never leaves the picture.
import type { FormId } from "../../endcards/schema.ts";
import type { Scene } from "../../lib/timeline.ts";
import { easeInOut, easeOut, lerpPose, type Pose, span } from "../../voxel/anim.ts";
import { golem, KITCHEN_SPOT, KITCHEN_WIDE, PROPS } from "../../voxel/models.ts";
import { FORMS } from "../../voxel/palette.ts";
import type { VoxelQuestProps } from "./schema.ts";

export type Vec = [number, number, number];
type Beat = VoxelQuestProps["beats"][number];

export const WORKTOP_Y = 11;
/** Food slots on the worktop for 1, 2 or 3 foods (x), close to the golem's right. */
export const SLOTS: Record<number, number[]> = { 1: [5], 2: [2, 11], 3: [0.5, 8, 15.5] };
export const FOOD_Z = -16;
/** Largest side of a food on the worktop, by how many share it. */
export const FOOD_FIT: Record<number, number> = { 1: 14, 2: 12, 3: 10 };
/** The phone: clear of the golem on its right on screen, in front of the worktop. */
export const PHONE_AT: Vec = [KITCHEN_SPOT[0] + 16.9, 18, KITCHEN_SPOT[2] - 8.5];
export const PHONE_SCALE = 1.1;
/** Height in the phone model of its middle (the model is 36 cubes tall): it sits on PHONE_AT. */
export const PHONE_CENTER = 18;
/** The plate (hookProp plate): on the worktop, just right of the golem. */
export const HOOK_PROP_AT: Vec = [0, WORKTOP_Y, -15];
/** On the scale (hookProp scale) the golem stands this much higher. */
export const SCALE_LIFT = 3;
/** Height above the golem's feet of the level pill's tip. */
export const PILL_Y = 25;

/** Height of each food as a share of its largest side (where its label is pinned). */
export const FOOD_HEIGHT: Record<string, number> = Object.fromEntries(
  Object.entries(PROPS).map(([id, make]) => {
    const v = make().voxels();
    const size = [0, 1, 2].map((a) => Math.max(...v.map((c) => c[a] as number)) - Math.min(...v.map((c) => c[a] as number)) + 1);
    return [id, size[1] / Math.max(...size)];
  }),
);

/** Each golem form's reach from its centre line (any yaw) and its height, in voxels. */
const GOLEM_BOUND: Record<string, { r: number; h: number }> = Object.fromEntries(
  FORMS.map((f, i) => {
    const v = golem(i + 1).voxels();
    const [x0, x1] = [Math.min(...v.map((c) => c[0])), Math.max(...v.map((c) => c[0])) + 1];
    const [z0, z1] = [Math.min(...v.map((c) => c[2])), Math.max(...v.map((c) => c[2])) + 1];
    const r = Math.max(...v.flatMap((c) => [0, 1].flatMap((dx) => [0, 1].map((dz) => Math.hypot(c[0] + dx - (x0 + x1) / 2, c[2] + dz - (z0 + z1) / 2)))));
    return [f.id, { r, h: Math.max(...v.map((c) => c[1])) + 1 }];
  }),
);

/** A ring of points round an upright cylinder: enough to bound a model at any yaw. */
const ring = (at: Vec, r: number, y0: number, y1: number): Vec[] =>
  [0, 1, 2, 3, 4, 5, 6, 7].flatMap((k) => {
    const a = (k * Math.PI) / 4;
    return [y0, y1].map((y): Vec => [at[0] + r * Math.cos(a), y, at[2] + r * Math.sin(a)]);
  });

/** Points bounding the golem in `form` (hop and squash included through `extraTop`). */
export const golemPoints = (form: FormId, lift = 0, extraTop = 1.5): Vec[] => {
  const { r, h } = GOLEM_BOUND[form];
  return ring(KITCHEN_SPOT, r, lift, lift + h * 1.06 + extraTop);
};

/** The form the golem reaches at the payoff. */
export const reached = (p: VoxelQuestProps): FormId => p.beats[p.beats.length - 1].form ?? p.toForm;
/** The form before the payoff's flash: the beat's own, the last app beat's in the payoff, else fromForm. */
export const before = (p: VoxelQuestProps, beat?: Beat): FormId =>
  beat?.kind === "payoff" ? (p.beats[p.beats.length - 2].form ?? p.fromForm) : (beat?.form ?? p.fromForm);

export const beatOf = (p: VoxelQuestProps, scene?: Scene): Beat | undefined =>
  scene && scene.index >= 1 && scene.index <= p.beats.length ? p.beats[scene.index - 1] : undefined;

/** When things happen inside a beat, in frames from its start (scaled down for short beats). */
export const IN_BEAT = { food: 8, foodGap: 9, phone: 4, fill: 16, hop: 10, hopLength: 26 };

/** Frames into the beat, with its in-beat times scaled when the beat is short (a fast voice). */
export const beatClock = (frame: number, scene: Scene, fps: number) => {
  const length = scene.endFrame - scene.startFrame;
  const k = Math.min(1, length / (3.4 * fps));
  return { t: frame - scene.startFrame, k, length };
};

/** Frame of the level-up flash: the top of the payoff's hop. */
export const flashFrame = (payoff: Scene, fps: number) =>
  payoff.startFrame + Math.round(IN_BEAT.hop * beatClock(payoff.startFrame, payoff, fps).k + IN_BEAT.hopLength / 2);

/** Where a subject may sit on screen (px): left of the Reels button rail, under the captions. */
export const SUBJECT_BOX = { left: 95, right: 865, top: 650, bottom: 1236 };
/** Frames of the eased camera move into each beat (and into a long beat's second shot). */
export const MOVE = 16;
/** Frames before the end card when the payoff eases back to the wide shot (the card starts there). */
export const SETTLE = 22;
/** Lens gain of the slow push over a shot; SUBJECT_BOX leaves room for it. */
const DRIFT = 0.03;
/** A beat longer than this (s) changes shot halfway: never more than ~3.5 s without a change. */
export const LONG_BEAT_S = 3.5;

/**
 * The pose at `base`'s angles that frames every point inside `box`: the lens as tight as
 * `maxLens` allows, the target slid in the image plane so the points' box is centred.
 */
export const fitShot = (base: Pose, points: Vec[], box = SUBJECT_BOX, maxLens = 30, width = 1080, height = 1920): Pose => {
  const az = (base.azimuth * Math.PI) / 180;
  const el = (base.elevation * Math.PI) / 180;
  const right: Vec = [Math.cos(az), 0, -Math.sin(az)];
  const up: Vec = [-Math.sin(el) * Math.sin(az), Math.cos(el), -Math.sin(el) * Math.cos(az)];
  const dot = (a: Vec, b: Vec) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const us = points.map((p) => dot(p, right));
  const vs = points.map((p) => dot(p, up));
  const [u0, u1, v0, v1] = [Math.min(...us), Math.max(...us), Math.min(...vs), Math.max(...vs)];
  const zoom = Math.min(maxLens, (box.right - box.left) / (u1 - u0), (box.bottom - box.top) / (v1 - v0));
  const lens = (zoom * 1080) / width;
  const a = (u0 + u1) / 2 - ((box.left + box.right) / 2 - width / 2) / zoom;
  const b = (v0 + v1) / 2 + ((box.top + box.bottom) / 2 - height / 2) / zoom;
  return { ...base, lens, target: [right[0] * a + up[0] * b, up[1] * b, right[2] * a + up[2] * b] };
};

type Shot = { base: Pose; points: Vec[]; maxLens: number };

/** What a beat frames, and from where. */
const shotOf = (p: VoxelQuestProps, beat: Beat): Shot => {
  const form = before(p, beat);
  if (beat.kind === "problem" && beat.foods) {
    // Swings round to face the worktop: the foods stand in a row, their numbers side by side.
    const n = beat.foods.length;
    const foods = beat.foods.flatMap((f, i) => {
      const top = WORKTOP_Y + FOOD_HEIGHT[f.prop] * FOOD_FIT[n];
      return ring([SLOTS[n][i], 0, FOOD_Z], FOOD_FIT[n] / 2, WORKTOP_Y, top + 4 + (i % 2) * 4);
    });
    return { base: { ...KITCHEN_WIDE, azimuth: 20, elevation: 30 }, points: [...golemPoints(form), ...foods], maxLens: 28 };
  }
  if (beat.kind === "problem") {
    // No foods: close on the golem and the hook's prop (the same reading, nothing changed).
    const scale = p.hookProp === "scale";
    const prop = scale ? ring(KITCHEN_SPOT, 12, 0, 3) : ring(HOOK_PROP_AT, 7.5, WORKTOP_Y, WORKTOP_Y + 3);
    return { base: { ...KITCHEN_WIDE, azimuth: 58 }, points: [...golemPoints(form, scale ? SCALE_LIFT : 0), ...prop], maxLens: 32 };
  }
  if (beat.kind === "app") {
    const phone = ring(PHONE_AT, 9 * PHONE_SCALE, PHONE_AT[1] - 18.5 * PHONE_SCALE, PHONE_AT[1] + 18.5 * PHONE_SCALE);
    return { base: KITCHEN_WIDE, points: [...golemPoints(form), ...phone], maxLens: 30 };
  }
  // Payoff: room for the hop (7 voxels) and the level pill above the new form.
  const top = (f: FormId) => golemPoints(f, 0, 9);
  return { base: KITCHEN_WIDE, points: [...top(form), ...top(reached(p)), ...ring(KITCHEN_SPOT, 4, PILL_Y + 4, PILL_Y + 6)], maxLens: 24 };
};

/** A beat's shots: one, or two when it is long (the second swung round 16° and refitted). */
export const beatShots = (p: VoxelQuestProps, scene: Scene, fps: number): { pose: Pose; start: number; end: number }[] => {
  const s = shotOf(p, p.beats[scene.index - 1]);
  const first = fitShot(s.base, s.points, SUBJECT_BOX, s.maxLens);
  if (scene.endFrame - scene.startFrame <= LONG_BEAT_S * fps) return [{ pose: first, start: scene.startFrame, end: scene.endFrame }];
  const half = scene.startFrame + Math.round((scene.endFrame - scene.startFrame) / 2);
  const second = fitShot({ ...s.base, azimuth: s.base.azimuth + (s.base.azimuth > 40 ? -16 : 16) }, s.points, SUBJECT_BOX, s.maxLens * 1.04);
  return [
    { pose: first, start: scene.startFrame, end: half },
    { pose: second, start: half, end: scene.endFrame },
  ];
};

/** The camera at `frame`. Every move starts from where the camera actually was (drift included). */
export const cameraAt = (frame: number, p: VoxelQuestProps, scenes: Scene[], endStart: number, fps: number): Pose => {
  const settle = endStart - SETTLE;
  // Back to the wide shot before the end card, which starts on it.
  if (frame >= settle) return lerpPose(cameraAt(settle - 1, p, scenes, endStart, fps), KITCHEN_WIDE, easeInOut(span(frame, settle - 1, SETTLE)));
  const scene = scenes.find((s) => frame >= s.startFrame && frame < s.endFrame) ?? scenes[scenes.length - 1];
  if (scene.index === 0) return lerpPose({ ...KITCHEN_WIDE, lens: KITCHEN_WIDE.lens * 0.9 }, KITCHEN_WIDE, easeOut(span(frame, 0, scene.endFrame)));
  const shots = beatShots(p, scene, fps);
  const shot = shots.find((s) => frame < s.end) ?? shots[shots.length - 1];
  const drift = { ...shot.pose, lens: shot.pose.lens * (1 + DRIFT * span(frame, shot.start + MOVE, shot.end - shot.start - MOVE)) };
  return lerpPose(cameraAt(shot.start - 1, p, scenes, endStart, fps), drift, easeInOut(span(frame, shot.start, MOVE)));
};

export { countUp } from "../../lib/countUp.ts";

/** World point of a spot on the phone's model (cell coordinates), as the scene places it. */
export const phonePoint = (pose: Pose, local: Vec, lift = 0): Vec => {
  const tilt = -((pose.elevation * Math.PI) / 180) * 0.6;
  const yaw = (pose.azimuth * Math.PI) / 180;
  // The model stands centred on PHONE_AT (offset PHONE_CENTER), scaled, then turned YXZ: tilt about x, yaw about y.
  const [x, y0, z0] = [local[0] * PHONE_SCALE, (local[1] - PHONE_CENTER) * PHONE_SCALE, local[2] * PHONE_SCALE];
  const y = y0 * Math.cos(tilt) - z0 * Math.sin(tilt);
  const z = y0 * Math.sin(tilt) + z0 * Math.cos(tilt);
  return [PHONE_AT[0] + x * Math.cos(yaw) + z * Math.sin(yaw), PHONE_AT[1] + y + lift, PHONE_AT[2] - x * Math.sin(yaw) + z * Math.cos(yaw)];
};
