// A person as a silhouette in the pixel scenes (step 143): capsules (torso, limbs) and a head,
// posed per frame, tested per cell. Side view facing right; `rim` = the cells whose
// neighbour toward the light is outside, so a backlit figure gets its warm edge. Pure.

type Seg = readonly [x1: number, y1: number, x2: number, y2: number, r: number];

export type Pose = { segs: Seg[]; head: readonly [x: number, y: number, r: number] };

const distSeg = (px: number, py: number, [x1, y1, x2, y2]: Seg) => {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const l = dx * dx + dy * dy;
  const k = l ? Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / l)) : 0;
  return Math.hypot(px - x1 - k * dx, py - y1 - k * dy);
};

/** Point `len` along angle `a` from (x, y); angle 0 = straight down, positive = forward (right). */
const limb = (x: number, y: number, a: number, len: number): [number, number] => [x + Math.sin(a) * len, y + Math.cos(a) * len];

/** Running, side view, feet at (0, 0), 30 cells tall: `phase` in radians (one stride = 2π). */
export const runPose = (phase: number): Pose => {
  const bob = -Math.abs(Math.sin(phase)) * 1.2;
  const hip: [number, number] = [0, -14.5 + bob];
  const lean = 0.22;
  const neck: [number, number] = [hip[0] + Math.sin(lean) * 9.5, hip[1] - Math.cos(lean) * 9.5];
  const segs: Seg[] = [[hip[0], hip[1], neck[0], neck[1], 2.1]];
  for (const side of [0, Math.PI]) {
    const p = phase + side;
    const thigh = 0.8 * Math.sin(p);
    const knee = limb(hip[0], hip[1], thigh, 7.2);
    // The leg swinging back folds up under the body; the one in front reaches out.
    const fold = 0.2 + 1.5 * Math.max(0, -Math.cos(p)) * (Math.sin(p) < 0.4 ? 1 : 0.4);
    const foot = limb(knee[0], knee[1], thigh - fold, 7);
    segs.push([hip[0], hip[1], knee[0], knee[1], 1.6], [knee[0], knee[1], foot[0], foot[1], 1.3]);
    const arm = -0.9 * Math.sin(p);
    const elbow = limb(neck[0], neck[1] + 1.2, arm, 5);
    const hand = limb(elbow[0], elbow[1], arm + 1.7, 4.4);
    segs.push([neck[0], neck[1] + 1.2, elbow[0], elbow[1], 1.15], [elbow[0], elbow[1], hand[0], hand[1], 1]);
  }
  return { segs, head: [neck[0] + 0.9, neck[1] - 2.8, 2.5] };
};

/** Standing, side view facing right, feet at (0, 0), 30 cells tall; `reach` 0..1 lifts the front arm forward. */
export const standPose = (reach: number, breathe = 0): Pose => {
  const hip: [number, number] = [0, -14.5];
  const neck: [number, number] = [0.4, -24.2 + breathe * 0.3];
  const shoulder: [number, number] = [neck[0], neck[1] + 1.2];
  const a = 0.15 + reach * 1.25;
  const elbow = limb(shoulder[0], shoulder[1], a, 5);
  const hand = limb(elbow[0], elbow[1], a + reach * 0.35, 4.6);
  return {
    segs: [
      [hip[0], hip[1], neck[0], neck[1], 2.3],
      [hip[0] - 0.6, hip[1], -0.8, -0.6, 1.7],
      [hip[0] + 0.6, hip[1], 1.1, -0.6, 1.7],
      [shoulder[0] - 0.5, shoulder[1], -0.6, -14, 1.2],
      [shoulder[0], shoulder[1], elbow[0], elbow[1], 1.2],
      [elbow[0], elbow[1], hand[0], hand[1], 1.05],
    ],
    head: [neck[0] + 0.5, neck[1] - 2.9, 2.6],
  };
};

/** Standing, front view, looking down at a phone held at chest height (feet at 0, 0; 30 tall). */
export const phonePose = (breathe = 0): Pose => ({
  segs: [
    [0, -14.5, 0, -24 + breathe * 0.3, 2.6],
    [-1.3, -14, -1.6, -0.5, 1.7],
    [1.3, -14, 1.6, -0.5, 1.7],
    [-2.6, -22.5, -3.4, -17, 1.2],
    [-3.4, -17, -0.8, -18.8, 1.05],
    [2.6, -22.5, 3.4, -17, 1.2],
    [3.4, -17, 0.8, -18.8, 1.05],
  ],
  head: [0, -26.8 + breathe * 0.3, 2.7],
});

/**
 * 0 = outside, 1 = body, 2 = rim (body cell whose neighbour toward (lx, ly) is outside).
 * (x, y) = feet in world cells, `s` = scale (height / 30).
 */
export const figureAt = (pose: Pose, x: number, y: number, s: number, wx: number, wy: number, lx = 0, ly = 0): 0 | 1 | 2 => {
  const inside = (px: number, py: number) => {
    const u = (px - x) / s;
    const v = (py - y) / s;
    const [hx, hy, hr] = pose.head;
    if (Math.hypot(u - hx, v - hy) < hr) return true;
    for (const seg of pose.segs) if (distSeg(u, v, seg) < seg[4]) return true;
    return false;
  };
  if (!inside(wx, wy)) return 0;
  return (lx || ly) && !inside(wx + lx, wy + ly) ? 2 : 1;
};

/**
 * Head and shoulders in profile, facing right: the close shots. Head centre at (x, y), `s` =
 * scale (the head is about 19 s tall), `tilt` (radians) bows the head, `phone` raises a hand
 * holding a phone in front of the face. 0 = outside, 1 = body, 2 = rim (neighbour toward
 * (lx, ly) is outside), 3 = the face (front of the head), 4 = the phone's screen.
 */
export const bustAt = (x: number, y: number, s: number, wx: number, wy: number, lx = 0, ly = 0, tilt = 0, phone = false): 0 | 1 | 2 | 3 | 4 => {
  const ct = Math.cos(tilt);
  const st = Math.sin(tilt);
  const part = (px: number, py: number): 0 | 1 | 3 | 4 => {
    const u = (px - x) / s;
    const v = (py - y) / s;
    if (phone) {
      if (u > 10.5 && u < 13.5 && v > 2.5 && v < 9) return u > 11 && u < 13 && v > 3 && v < 8.5 ? 4 : 1;
      if (distSeg(u, v, [3, 19, 11.5, 9.5, 0]) < 2.2 || Math.hypot(u - 12, v - 8.5) < 2.3) return 1;
    }
    // The head turns about the neck when it bows.
    const hu = (u + 1) * ct + (v - 6) * st - 1;
    const hv = -(u + 1) * st + (v - 6) * ct + 6;
    if ((hu / 8) ** 2 + (hv / 9.6) ** 2 < 1) return hu > 1.5 && hv > -5 ? 3 : 1;
    if (Math.hypot(hu - 8.2, hv - 0.6) < 1.7 || Math.hypot(hu - 6.4, hv - 5.6) < 2.4) return 3; // nose, chin
    if ((hu / 8.6) ** 2 + ((hv + 3.5) / 7.4) ** 2 < 1 && hu < 3) return 1; // hair at the back
    if (u > -4 && u < 3.5 && v > 6 && v < 15) return 1; // neck
    if (v > 13 && ((u + 2) / 18) ** 2 + ((v - 26) / 13) ** 2 < 1) return 1; // shoulders
    if (v >= 26 && Math.abs(u + 2) < 18) return 1; // chest, down out of frame
    return 0;
  };
  const p = part(wx, wy);
  if (!p) return 0;
  if (p === 1 && (lx || ly) && !part(wx + lx, wy + ly)) return 2;
  return p;
};
