// Animation and camera maths for the voxel stage. Pure functions of the frame (no
// Math.random, no clock), so every render of a frame is the same. `node --test` runs it.

export const clamp01 = (t: number) => Math.min(1, Math.max(0, t));

/** 0..1 progress of `frame` through [start, start + duration]. */
export const span = (frame: number, start: number, duration: number) =>
  duration <= 0 ? (frame >= start ? 1 : 0) : clamp01((frame - start) / duration);

export const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
export const easeOut = (t: number) => 1 - (1 - t) ** 3;
/** Ends at 1 after overshooting by about `overshoot` (0.1 = 10 %). */
export const backOut = (t: number, overshoot = 0.1) => {
  const c = overshoot * 17; // c ≈ 1.70158 gives the classic 10 % overshoot
  return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2;
};

/** Gentle float: y offset in voxels, `period` frames per cycle. */
export const bob = (frame: number, period = 60, amplitude = 0.4, phase = 0) =>
  amplitude * Math.sin(((frame + phase) / period) * 2 * Math.PI);

/** Yaw (radians) of a model turning once every `framesPerTurn`. */
export const turntable = (frame: number, framesPerTurn = 240, offset = 0) => offset + (frame / framesPerTurn) * 2 * Math.PI;

/** Scale for a pop-in: 0 before `start`, overshoots, settles at 1 after `duration`. */
export const popIn = (frame: number, start: number, duration = 12, overshoot = 0.15) =>
  frame < start ? 0 : backOut(span(frame, start, duration), overshoot);

export type Hop = { y: number; scale: [number, number, number] };

/**
 * A hop with squash and stretch: crouch (20 %), air (60 %, a parabola peaking at `height`
 * voxels), landing squash (20 %); continuous throughout. Volume is kept: x/z = 1 / sqrt(y).
 */
export const hop = (frame: number, start: number, duration = 24, height = 4, squash = 0.22): Hop => {
  const t = span(frame, start, duration);
  let y = 0;
  let sy = 1;
  const stretch = squash * 0.6; // fastest (take-off, touch-down): tallest; apex: round
  if (frame >= start && t < 1) {
    if (t < 0.2) {
      const s = t / 0.2;
      sy = 1 - squash * Math.sin(s * Math.PI) + stretch * s * s; // crouch, then spring
    } else if (t < 0.8) {
      const a = (t - 0.2) / 0.6;
      y = height * 4 * a * (1 - a);
      sy = 1 + stretch * (2 * a - 1) ** 2;
    } else {
      const s = (t - 0.8) / 0.2;
      sy = 1 - squash * Math.sin(s * Math.PI) + stretch * (1 - s) ** 2; // land
    }
  }
  const sxz = 1 / Math.sqrt(sy);
  return { y, scale: [sxz, sy, sxz] };
};

/** Where the camera is: angles in degrees around `target`, distance in world units. */
export type Pose = {
  azimuth: number;
  elevation: number;
  distance: number;
  target: [number, number, number];
  /** Orthographic zoom (pixels per world unit) or perspective field of view (degrees). */
  lens: number;
};

/** True isometric angles (azimuth 45°, elevation atan(1/√2) ≈ 35.26°). */
export const ISO = { azimuth: 45, elevation: (Math.atan(1 / Math.SQRT2) * 180) / Math.PI };

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

export const lerpPose = (a: Pose, b: Pose, t: number): Pose => ({
  azimuth: lerp(a.azimuth, b.azimuth, t),
  elevation: lerp(a.elevation, b.elevation, t),
  distance: lerp(a.distance, b.distance, t),
  target: [lerp(a.target[0], b.target[0], t), lerp(a.target[1], b.target[1], t), lerp(a.target[2], b.target[2], t)],
  lens: lerp(a.lens, b.lens, t),
});

/** A camera move from one pose to another over [start, start + duration], eased in and out. */
export type Move = { from: Pose; to: Pose; start: number; duration: number };

export const poseAt = (frame: number, move: Move): Pose =>
  lerpPose(move.from, move.to, easeInOut(span(frame, move.start, move.duration)));

/** Camera position for a pose (y up). */
export const cameraPosition = (p: Pose): [number, number, number] => {
  const az = (p.azimuth * Math.PI) / 180;
  const el = (p.elevation * Math.PI) / 180;
  return [
    p.target[0] + p.distance * Math.cos(el) * Math.sin(az),
    p.target[1] + p.distance * Math.sin(el),
    p.target[2] + p.distance * Math.cos(el) * Math.cos(az),
  ];
};

// Move builders: the end pose of a classic move, starting from `from`.
/** Orbit: swing round the target by `degrees`. */
export const orbit = (from: Pose, degrees: number): Pose => ({ ...from, azimuth: from.azimuth + degrees });
/** Dolly: travel toward (factor < 1) or away from the target; perspective framing changes. */
export const dolly = (from: Pose, factor: number): Pose => ({ ...from, distance: from.distance * factor });
/** Push-in: tighten the framing by `factor` (lens zoom or distance) and drift to a new target. */
export const pushIn = (from: Pose, factor: number, target = from.target, orthographic = true): Pose => ({
  ...from,
  target,
  lens: orthographic ? from.lens * factor : from.lens,
  distance: orthographic ? from.distance : from.distance / factor,
});
