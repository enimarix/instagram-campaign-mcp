// The cinema style's pixel painter (step 143): a 180 x 320 grid (6 px cells on 1080 x 1920)
// painted per frame in code: seeded value noise, ordered (Bayer) dithering between palette
// ramps, a camera with parallax per depth, and a volumetric beam. Pure (no imports), so
// `node --test` runs it (test/pixelcinema.test.ts).

export const GW = 180;
export const GH = 320;
/** Screen pixels per grid cell. */
export const CELL = 6;

export type RGB = readonly [number, number, number];

export const rgb = (hex: string): RGB => {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
export const ramp = (...hex: string[]): RGB[] => hex.map(rgb);

export const mix = (a: RGB, b: RGB, k: number): RGB => [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
export const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);
export const smooth = (a: number, b: number, v: number) => {
  const t = clamp01((v - a) / (b - a));
  return t * t * (3 - 2 * t);
};

/** Seeded hash of an integer cell: 0..1, same on every machine (integer maths only). */
export const hash = (x: number, y: number, seed = 0): number => {
  let h = (Math.imul(x | 0, 374761393) + Math.imul(y | 0, 668265263) + Math.imul(seed | 0, 2246822519)) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
};

/** Smooth value noise, 0..1. */
export const noise = (x: number, y: number, seed = 0): number => {
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  const fx = x - xi;
  const fy = y - yi;
  const u = fx * fx * (3 - 2 * fx);
  const v = fy * fy * (3 - 2 * fy);
  const a = hash(xi, yi, seed);
  const b = hash(xi + 1, yi, seed);
  const c = hash(xi, yi + 1, seed);
  const d = hash(xi + 1, yi + 1, seed);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
};

/** Fractal noise (octaves of `noise`), 0..1. */
export const fbm = (x: number, y: number, seed = 0, octaves = 4): number => {
  let sum = 0;
  let amp = 0.5;
  let norm = 0;
  for (let o = 0; o < octaves; o++) {
    sum += amp * noise(x, y, seed + o * 17);
    norm += amp;
    x *= 2.03;
    y *= 2.03;
    amp *= 0.5;
  }
  return sum / norm;
};

/** 4 x 4 Bayer thresholds (0..1): the ordered dither of the whole style. */
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map((v) => (v + 0.5) / 16);
export const bayer = (x: number, y: number) => BAYER[((y & 3) << 2) | (x & 3)];

/** `t` (0..1) along a palette ramp, dithered between its two nearest colours at cell (x, y). */
export const dither = (cols: readonly RGB[], t: number, x: number, y: number): RGB => {
  const s = clamp01(t) * (cols.length - 1);
  const i = Math.floor(s);
  if (i >= cols.length - 1) return cols[cols.length - 1];
  return s - i > bayer(x, y) ? cols[i + 1] : cols[i];
};

/** Dithered on / off: true with probability `k` (ordered), for blends between two colours. */
export const on = (k: number, x: number, y: number) => k > bayer(x, y);

/**
 * Camera: a push-in of `zoom` toward the focus cell (fx, fy), plus a drift. A layer at
 * `depth` (0 = the sky at infinity, 1 = the subject, > 1 = foreground) zooms and drifts by
 * that share, so near layers move more (parallax).
 */
export type Camera = { zoom: number; fx: number; fy: number; dx: number; dy: number };
export const STILL: Camera = { zoom: 1, fx: GW / 2, fy: GH / 2, dx: 0, dy: 0 };

/** World cell under screen cell (sx, sy) for a layer at `depth`. */
export const toWorld = (cam: Camera, sx: number, sy: number, depth: number): [number, number] => {
  const z = 1 + (cam.zoom - 1) * depth;
  return [cam.fx + (sx - cam.fx) / z - cam.dx * depth, cam.fy + (sy - cam.fy) / z - cam.dy * depth];
};
/** Screen cell of world cell (wx, wy) at `depth` (the inverse of toWorld). */
export const toScreen = (cam: Camera, wx: number, wy: number, depth: number): [number, number] => {
  const z = 1 + (cam.zoom - 1) * depth;
  return [cam.fx + (wx + cam.dx * depth - cam.fx) * z, cam.fy + (wy + cam.dy * depth - cam.fy) * z];
};

/** A light cone: from (x, y) toward `angle` (radians, 0 = right, π/2 = down), half-width `spread`. */
export type Beam = { x: number; y: number; angle: number; spread: number; length: number; power: number };

/** How lit world cell (wx, wy) is by `beam`, 0..1: bright on the axis, fading out and away. */
export const beamAt = (b: Beam, wx: number, wy: number): number => {
  if (b.power <= 0) return 0;
  const dx = wx - b.x;
  const dy = wy - b.y;
  const d = Math.hypot(dx, dy);
  if (d < 1 || d > b.length) return 0;
  let a = Math.atan2(dy, dx) - b.angle;
  a = Math.atan2(Math.sin(a), Math.cos(a));
  const off = Math.abs(a) / b.spread;
  if (off >= 1) return 0;
  return (1 - off) ** 0.8 * (1 - d / b.length) ** 0.6 * Math.min(1, d / 6) * b.power;
};

/** A sprite: rows of characters, each mapped to a colour by `pal` ('.' or ' ' = empty). */
export type Sprite = readonly string[];

/** The character of `sprite` at its cell (x, y) (top-left = 0, 0), or null outside / empty. */
export const spriteAt = (sprite: Sprite, x: number, y: number): string | null => {
  const yi = Math.floor(y);
  const xi = Math.floor(x);
  if (yi < 0 || yi >= sprite.length || xi < 0) return null;
  const ch = sprite[yi][xi];
  return ch === undefined || ch === "." || ch === " " ? null : ch;
};
