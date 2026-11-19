// The editorial style's hero (step 144): a pixel blossom tree, procedural and seeded, so every
// render of a frame is the same. Pure (no React) so `node --test` checks it; Tree.tsx draws it.
// Local units: the trunk's foot at (0, 0), up is -y, the canopy about 700 px tall, 760 wide.
// Fine pixel art: a 4 px grid, five levels of branches, many small blossom clusters in four
// pinks with white highlights on the lit side.
import { seeded } from "../lib/game.ts";

/** Pixel size: everything snaps to this grid, so the tree reads as pixel art while it sways. */
export const PX = 4;

export type Branch = { x0: number; y0: number; cx: number; cy: number; x1: number; y1: number; w0: number; w1: number; o0: number; o1: number; depth: number };
/** shade 1 (deep) .. 5 (lightest); `white` = a white heart pixel (a highlight on the lit side). */
export type Flower = { x: number; y: number; shade: number; u: number; white: boolean };
export type Cluster = { x: number; y: number; r: number };
export type TreeModel = { branches: Branch[]; clusters: Cluster[]; flowers: Flower[]; height: number };

/** Depth of the trunk; tips (depth 0) and their parents carry the blossom clusters. */
const DEPTH = 4;
/** Angle offsets (radians) of a branch's children, by the parent's depth. */
const FORKS = [[], [-0.42, 0.38], [-0.5, 0.45], [-0.55, 0.5], [-0.8, 0.05, 0.75]];

export const makeTree = (seed = 7): TreeModel => {
  let n = 0;
  const rnd = () => seeded(seed, n++);
  const branches: Branch[] = [];
  const clusters: Cluster[] = [];
  const grow = (x: number, y: number, angle: number, len: number, w: number, depth: number, o: number) => {
    const x1 = x + Math.sin(angle) * len;
    const y1 = y - Math.cos(angle) * len;
    const bend = (rnd() - 0.5) * len * 0.4;
    const o1 = o + len / 700;
    branches.push({ x0: x, y0: y, cx: (x + x1) / 2 + Math.cos(angle) * bend, cy: (y + y1) / 2 + Math.sin(angle) * bend, x1, y1, w0: w, w1: w * 0.6, o0: o, o1, depth });
    if (depth <= 1) clusters.push({ x: x1, y: y1, r: depth ? 62 + rnd() * 16 : 40 + rnd() * 22 });
    // Small clusters along the outer branches too, so the crown is many little clumps.
    if (depth === 1 || depth === 2) clusters.push({ x: (x + x1) / 2 + (rnd() - 0.5) * 30, y: (y + y1) / 2 - 10, r: 34 + rnd() * 16 });
    if (depth === 0) return;
    for (const fork of FORKS[depth]) grow(x1, y1, angle * 0.62 + fork + (rnd() - 0.5) * 0.28, len * (0.68 + rnd() * 0.12), w * 0.6, depth - 1, o1);
  };
  grow(0, 0, 0.05, 230, 52, DEPTH, 0);
  // The crown's middle, so it reads as one crown with depth, not separate pompoms.
  clusters.push({ x: -30, y: -500, r: 96 }, { x: 120, y: -470, r: 84 }, { x: -170, y: -440, r: 80 }, { x: 40, y: -600, r: 70 });
  const flowers: Flower[] = [];
  const top = Math.min(...clusters.map((c) => c.y - c.r));
  for (const c of clusters) {
    const count = Math.round((c.r * c.r) / 52);
    // Each clump has its own brightness, and darkens at its lower rim: the crown reads as clumps.
    const own = (rnd() - 0.5) * 1.1;
    for (let i = 0; i < count; i++) {
      const a = rnd() * 2 * Math.PI;
      const d = rnd() ** 0.65 * c.r;
      const dx = Math.cos(a) * d;
      const dy = Math.sin(a) * d * 0.86;
      // Light from the top right; higher in the crown is lighter.
      const rim = (d / c.r) ** 2 * (dy > 0 ? 1.3 : 0.3);
      const lit = ((dx * 0.6 - dy * 0.8) / c.r) * 1.5 + ((c.y - top) / 420) * -0.9 + own - rim + (rnd() - 0.5) * 1.1;
      const shade = Math.max(1, Math.min(5, Math.round(3 + lit)));
      // Blooms open from the tips inwards, with some spread.
      const u = Math.min(0.97, Math.max(0.02, 0.1 + 0.2 * (d / c.r) + rnd() * 0.7));
      flowers.push({ x: c.x + dx, y: c.y + dy, shade, u, white: shade >= 4 && rnd() < (shade === 5 ? 0.45 : 0.12) });
    }
  }
  flowers.sort((a, b) => a.shade - b.shade); // dark (back) first
  return { branches, clusters, flowers, height: -top };
};

export const TREE = makeTree();
/** The crown's box in local units (for framing and camera targets). */
export const CROWN = (() => {
  const xs = TREE.flowers.map((f) => f.x);
  return { left: Math.min(...xs), right: Math.max(...xs), top: -TREE.height, bottom: Math.max(...TREE.flowers.map((f) => f.y)) };
})();

/** Sway of a point `h` px up the tree: idle breathing plus the gust (−1 leans back, +1 full push). */
export const swayAt = (h: number, x: number, frame: number, gust: number, height = TREE.height) => {
  const k = Math.max(0, h / height) ** 1.6;
  return { dx: (gust * 48 + 5 * Math.sin(frame / 34 + x / 140)) * k, dy: Math.abs(gust) * k * k * 10 };
};

/** Snap to the pixel grid. */
export const snap = (v: number) => Math.round(v / PX) * PX;

/** Gust over a chapter of `len` frames at frame `f`: anticipation (leans back), the push, then it settles. */
export const gustOf = (f: number, len: number) => {
  const t = f / len;
  if (t < 0.18) return 0;
  if (t < 0.36) return -0.35 * Math.sin(((t - 0.18) / 0.18) * (Math.PI / 2));
  if (t < 0.5) return -0.35 + 1.35 * Math.sin(((t - 0.36) / 0.14) * (Math.PI / 2));
  // Settle with one overshoot.
  const s = (t - 0.5) / 0.5;
  return Math.cos(s * Math.PI * 2.2) * Math.exp(-3.2 * s);
};
/** When the gust pushes (0..1 of the chapter): the scrubber's cyan range. */
export const GUST_RANGE = [0.36, 0.62] as const;

/** A falling petal; `z` 0 (far: small, dim, slow) .. 1 (near: big, out of focus, fast). */
export type Petal = { x: number; y: number; size: number; flip: number; color: number; o: number; z: number };

/**
 * Falling petals at `frame`: `count` petals on 150-frame cycles, each from a flower of the crown
 * (bloomed by `bloom`), drifting with the wind and fading at the ground. `push` = extra wind.
 * Each has a depth: nearer ones are bigger, fall and drift faster (parallax).
 */
export const petalsAt = (frame: number, count: number, bloom: number, push = 0, seed = 3): Petal[] => {
  const P = 150;
  const open = TREE.flowers.filter((fl) => fl.u <= bloom);
  if (!open.length) return [];
  const out: Petal[] = [];
  for (let i = 0; i < count; i++) {
    const birth = Math.floor(seeded(seed, i) * P);
    const since = frame - birth;
    const age = ((since % P) + P) % P;
    const cycle = Math.floor(since / P);
    const fl = open[Math.floor(seeded(seed + 101 + cycle, i) * open.length)];
    const z = seeded(seed + 13, i);
    const speed = 0.7 + 0.7 * z;
    const fall = (1.9 + seeded(seed + 7, i) * 1.1) * speed;
    const y = fl.y + fall * age;
    if (y > 30) continue; // on the ground
    const drift = (0.6 + seeded(seed + 9, i) * 0.9 + push * 4) * speed;
    const x = fl.x + drift * age + 26 * Math.sin(age / 13 + i);
    out.push({ x, y, size: PX * (1 + Math.round(z * 2)), flip: Math.cos((age + i * 7) / 5), color: 3 + (i % 3), o: (0.55 + 0.45 * z) * (y > 0 ? 1 - y / 30 : 1), z });
  }
  return out;
};
