// What every cinema set shares (step 143): the view contract (a shot's picture, painted cell
// by cell), the night sky, the lightning sky, the beam's light, rich bricks, a layered
// painterly sea, rain rings on wet ground, the neon cross, a car with its headlights.
// Pure (imports ./pixel only), so `node --test` runs it.
import { type Beam, bayer, type Camera, clamp01, dither, fbm, GH, hash, mix, noise, on, type RGB, ramp, rgb, smooth } from "./pixel.ts";

/** Where a chip's leader line can point: the light, the person, the sky, the ground. */
export const ANCHORS = ["light", "subject", "sky", "ground"] as const;
export type AnchorId = (typeof ANCHORS)[number];

export type Paint = {
  /** Seconds since the start of the video (clouds, waves, rain, the run cycle). */
  t: number;
  cam: Camera;
  /** The beam's power, 0..1 (the template turns it up on the hook's twist). */
  beam: number;
  /** Extra beam angle in radians (the template sweeps it on the key beats). */
  sweep: number;
  /** The lightning frame: white sky, black solids. */
  flash: boolean;
  /** 0..1: the set darkens under big text (stat, app card). */
  dim: number;
  /** 0..1: set-specific action (the fridge door opening). */
  open: number;
  /** A second beam over the whole picture, in screen cells (the end card's light on the tile). */
  extra?: Beam;
};

export type Out = { c: RGB; solid: boolean };

/** One framing of a set: its own picture (world cells), light, rain and chip anchors. */
export type View = {
  /** World cells (x, y, depth) of the chip anchors at `t` seconds. */
  anchors: (t: number) => Record<AnchorId, readonly [number, number, number]>;
  /** Rain over the view (Stage draws it at full resolution): 0 = none, 1 = a storm. */
  rain: number;
  /** The wide beam (half the frame) of this view, in world cells. */
  beam: (p: Paint) => Beam;
  pixel: (sx: number, sy: number, p: Paint, beam: Beam) => Out;
};

export const AMBER = rgb("#FFB547");
export const AMBER_HOT = rgb("#FFE2A0");
export const NIGHT = ramp("#0B0C27", "#121443", "#1A1E5E", "#232A78", "#2E378F", "#3C46A3", "#5059B5");
export const FLASH_PAPER = rgb("#ECEAE3");
export const FLASH_CLOUD = rgb("#CFCBD6");
export const FLASH_BOLT = rgb("#7D72B8");
export const INK = rgb("#09090E");
export const DIM = rgb("#070818");
export const SOLID_INK: Out = { c: INK, solid: true };

/** Night clouds: layered fractal noise with lit upper edges, drifting left. */
export const nightSky = (wx: number, wy: number, x: number, y: number, t: number, seed: number, scale = 1): RGB => {
  const u = wx * 0.028 * scale + t * 0.06;
  const v = wy * 0.055 * scale;
  const c = fbm(u, v, seed, 4);
  const above = fbm(u, v - 0.12, seed, 4);
  const grad = 0.42 - (wy / GH) * 0.25;
  let k = grad + smooth(0.38, 0.72, c) * 0.5;
  if (c > 0.48 && c - above > 0.012) k += 0.16; // the lit rim on top of each cloud
  return dither(NIGHT, k, x, y);
};

/** A jagged bolt (x of the bolt at height wy), for the lightning frame. */
const boltX = (wy: number, x0: number, seed: number) =>
  x0 + (noise(wy * 0.06, 0.5, seed) - 0.5) * 46 + (noise(wy * 0.35, 1.5, seed) - 0.5) * 10;

/** The lightning frame's sky: off-white paper, faint clouds, a bolt and a branch. */
export const flashSky = (wx: number, wy: number, x: number, y: number, bolt: readonly [number, number, number]): RGB => {
  const [x0, end, seed] = bolt;
  if (wy < end && Math.abs(wx - boltX(wy, x0, seed)) < 1.3) return FLASH_BOLT;
  if (wy < end * 0.7 && wy > end * 0.3 && Math.abs(wx - boltX(wy, x0, seed) - (wy - end * 0.3) * 0.5) < 0.6) return FLASH_BOLT;
  return on(smooth(0.5, 0.8, fbm(wx * 0.03, wy * 0.05, 9, 3)) * 0.5, x, y) ? FLASH_CLOUD : FLASH_PAPER;
};

/** A beam's light on cell (x, y): three dithered steps of amber, the reference's checkered shaft. */
export const lit = (c: RGB, k: number, x: number, y: number, hot: RGB = AMBER_HOT, warm: RGB = AMBER): RGB => {
  if (k <= 0) return c;
  const level = Math.floor(clamp01(k) * 3 + bayer(x, y)) / 3;
  return level <= 0 ? c : mix(c, level > 0.9 ? hot : warm, Math.min(0.85, level * 0.72));
};

const BRICK = ramp("#140D1C", "#1E1427", "#2A1B32", "#3A2640", "#4E3350");
const BRICK_WARM = ramp("#3A1A1A", "#5A2A22", "#7E3E28", "#A65A32");

/**
 * Wet bricks at world cell (wx, wy): courses 4 cells tall, bricks 9 wide (offset every other
 * course), each its own shade, lit top edge, dark bottom edge and mortar, rain runs
 * glistening down them; `warm` 0..1 = how much a window's light falls on them.
 */
export const bricks = (wx: number, wy: number, x: number, y: number, t: number, warm = 0): RGB => {
  const course = Math.floor(wy / 4);
  const off = (course % 2) * 4.5;
  const bx = Math.floor((wx + off) / 9);
  const inY = wy - course * 4;
  const inX = (wx + off) - bx * 9;
  if (inY < 0.8 || inX < 0.8) return dither(BRICK, 0.02 + warm * 0.25, x, y); // mortar
  let k = 0.3 + 0.35 * hash(bx, course, 11) + (inY < 1.8 ? 0.22 : inY > 3.2 ? -0.12 : 0);
  // Rain runs: thin vertical streaks of sheen sliding down.
  const run = noise(wx * 0.9, wy * 0.04 - t * 0.5, 13);
  if (run > 0.78) k += 0.25;
  const c = dither(BRICK, k, x, y);
  return warm > 0.02 ? mix(c, dither(BRICK_WARM, k, x, y), clamp01(warm)) : c;
};

/**
 * The painterly sea of the reference: stacked rolling wave bands (thinner toward the horizon),
 * each with a lit crest, a body and a dark trough, foam streaks along the crests.
 * `horizon` = world row of the horizon, `pal` dark → light.
 */
export const sea = (wx: number, wy: number, x: number, y: number, t: number, horizon: number, pal: readonly RGB[], foam: RGB, seed = 51): RGB => {
  const d = Math.max(0, wy - horizon);
  // Bands about (d + 3) / 10 cells tall: hair-thin at the horizon, ~12 cells at the bottom.
  const base = 10 * Math.log(d + 3);
  const k0 = Math.floor(base);
  const roll = Math.sin(wx * (9 / (d + 3)) + t * 1.1 + k0 * 1.7) * 0.32 + (noise(wx * (3 / (d + 3)), k0 * 0.7, seed) - 0.5) * 0.5;
  const band = base + roll - t * 0.35;
  const frac = band - Math.floor(band); // 0 = crest, 1 = trough
  const near = clamp01(d / (GH - horizon));
  const crest = frac < 0.14;
  const k = (crest ? 0.92 - frac * 2 : 0.62 - frac * 0.55) * (0.6 + near * 0.4) + 0.08 + near * 0.08;
  // Foam: broken white along the crests, more of it near the viewer.
  if (frac < 0.05 + near * 0.1 && noise(wx * 0.3, Math.floor(band) * 1.3, seed + 1) > 0.6 - near * 0.25) return foam;
  if (crest && hash(Math.floor(wx), Math.floor(wy), Math.floor(t * 6) + seed) > 0.99) return foam;
  return dither(pal, k, x, y);
};

/** Rain rings on wet ground (world cells, flattened by perspective `squash`): 0..1 on a ring. */
export const ripples = (wx: number, wy: number, t: number, squash = 3, seed = 61): number => {
  const cx = Math.floor(wx / 10);
  const cy = Math.floor(wy / 6);
  let best = 0;
  for (let dx = -1; dx <= 1; dx++) {
    for (let dy = -1; dy <= 1; dy++) {
      const gx = cx + dx;
      const gy = cy + dy;
      const period = 0.9 + hash(gx, gy, seed) * 0.8;
      const age = (t + hash(gx, gy, seed + 1) * period) % period;
      const px = gx * 10 + hash(gx, gy, seed + 2) * 10;
      const py = gy * 6 + hash(gx, gy, seed + 3) * 6;
      const r = 1 + age * 9;
      const dist = Math.hypot(wx - px, (wy - py) * squash);
      if (Math.abs(dist - r) < 0.7) best = Math.max(best, 1 - age / period);
    }
  }
  return best;
};

const NEON = rgb("#34F5A4");
const NEON_CORE = rgb("#D8FFEE");

/**
 * A French pharmacy's green neon cross centred at (cx, cy), arm half-length `s`, flickering;
 * returns the cell's colour, or null outside (the glow is `neonGlow`).
 */
export const neonCross = (wx: number, wy: number, cx: number, cy: number, s: number, t: number): RGB | null => {
  const dx = Math.abs(wx - cx);
  const dy = Math.abs(wy - cy);
  const w = s * 0.36;
  if (!((dx < w && dy < s) || (dy < w && dx < s))) return null;
  const flick = hash(Math.floor(t * 9), 0, 71) > 0.93 ? 0.4 : 1;
  const edge = dx > w - 1 && dy > w - 1 ? 0 : dx > w - 1 || dy > w - 1 ? 0.5 : 1;
  return mix(NEON, NEON_CORE, edge * 0.6 * flick);
};
/** Green glow of the neon cross on what is around it: 0..1. */
export const neonGlow = (wx: number, wy: number, cx: number, cy: number, s: number) => smooth(s * 4, s * 0.8, Math.hypot(wx - cx, wy - cy)) * 0.55;
export const NEON_GLOW = rgb("#1F8A66");

const CAR = rgb("#0B0B14");
const CAR_EDGE = rgb("#3A4060");

/**
 * A car seen from the side at (x, y) = its rear wheel's ground point, `s` = scale (length
 * 34 s), driving right: body, windows, wheels, a red tail light. 0 = outside.
 */
export const carAt = (wx: number, wy: number, x: number, y: number, s: number): RGB | null => {
  const u = (wx - x) / s;
  const v = (y - wy) / s;
  if (u < -4 || u > 30 || v < 0 || v > 11) return null;
  const wheel = (cx: number) => Math.hypot(u - cx, v - 2.6) < 2.6;
  if (wheel(2) || wheel(22)) return rgb("#050508");
  const body = v < 6 && u > -3 && u < 29;
  const cabin = v >= 6 && v < 10.5 && u > 4 + (v - 6) * 0.9 && u < 21 - (v - 6) * 1.2;
  if (!body && !cabin) return null;
  if (u < -2 && v > 3 && v < 5) return rgb("#E2333A"); // tail light
  if (cabin && v > 6.8 && v < 9.6 && u > 6 + (v - 6) * 0.9 && u < 19.5 - (v - 6) * 1.2 && Math.abs(u - 12.5) > 0.6) return rgb("#1B2240");
  return v > 5.4 && v < 6.2 ? CAR_EDGE : CAR;
};
/** The headlights' beam of a car at (x, y) scale `s`: a wide cone ahead of it, slightly down. */
export const headlights = (x: number, y: number, s: number, power: number): Beam => ({ x: x + 29 * s, y: y - 4 * s, angle: 0.12, spread: 0.32, length: 120 * s, power });
