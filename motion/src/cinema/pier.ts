// The pier set (step 143): dawn on the coast, a runner backlit by the rising sun. Four views:
// `wide` the sea in layered rolling waves, the pier, the runner small against the sun, the
// lighthouse on the headland sweeping its beam; `runner` close, the runner big against the sun
// disc, its shafts fanning up; `waves` low over the water, big waves breaking white on the
// pilings, the lighthouse beam crossing the sky; `horizon` the sun half out of the sea, lit
// clouds, gulls, the glitter path. Pure, so `node --test` runs it.
import { type AnchorId, flashSky, lit, sea, SOLID_INK, type View } from "./common.ts";
import { figureAt, runPose } from "./figure.ts";
import { beamAt, dither, fbm, hash, mix, noise, on, type RGB, ramp, rgb, smooth, toWorld } from "./pixel.ts";

const DAWN = ramp("#141335", "#211E4C", "#352A63", "#563573", "#86427A", "#B8546F", "#E06F5C", "#F59456", "#FCBF6C", "#FFE29E");
const CLOUD = ramp("#2A1E46", "#3D2A55", "#5A3560");
const CLOUD_LIT = ramp("#C9566A", "#F08A5A", "#FFC27A");
const SEA = ramp("#0B1230", "#142048", "#1E3058", "#2C4468", "#3E5A78", "#5C7890");
const FOAM = rgb("#DCE4EE");
const DECK = ramp("#120C18", "#1D1420", "#2A1C28", "#3E2830");
const RIM = rgb("#FF9A55");
const BODY = rgb("#140C16");

const anchors = (a: (t: number) => Record<AnchorId, readonly [number, number, number]>) => a;

/** Dawn sky over a horizon at `hz`, sun at (sunX, sunY) radius `r`: gradient, stratus lit from below, the sun, its rays. */
const dawnSky = (kx: number, ky: number, x: number, y: number, t: number, hz: number, sunX: number, sunY: number, r: number): RGB => {
  const d = Math.hypot(kx - sunX, ky - sunY);
  if (d < r) return rgb(d < r - 3 ? "#FFF6D8" : "#FFDE96");
  const h = Math.min(1, ky / hz);
  let c = dither(DAWN, h * h * 0.92 + smooth(r * 4.5, 0, d) * 0.12, x, y);
  const cu = kx * 0.014 + t * 0.02;
  const cl = fbm(cu, ky * 0.11, 71, 4) * (0.6 + 0.6 * smooth(20, hz * 0.6, ky)) - smooth(hz * 0.75, hz, ky) * 0.3;
  if (cl > 0.5) {
    const under = fbm(cu, (ky + 1.6) * 0.11, 71, 4) * (0.6 + 0.6 * smooth(20, hz * 0.6, ky + 1.6)) < cl - 0.008;
    c = under ? dither(CLOUD_LIT, smooth(10, hz, ky) * 0.6 + smooth(90, 0, d) * 0.4, x, y) : dither(CLOUD, (cl - 0.5) * 3, x, y);
  }
  const ang = Math.atan2(ky - sunY, kx - sunX);
  const ray = smooth(0.55, 0.85, noise(ang * 9, t * 0.05, 72)) * smooth(r * 10, r, d) * 0.6;
  if (on(ray, x, y)) c = mix(c, rgb("#FFD08A"), 0.35);
  return c;
};

/** The sea below `hz` with the sun's glitter path under sunX. */
const dawnSea = (ox: number, oy: number, x: number, y: number, t: number, hz: number, sunX: number): RGB => {
  let c = sea(ox, oy, x, y, t, hz, SEA, FOAM);
  const near = (oy - hz) / (320 - hz);
  const path = 3 + near * 26;
  if (Math.abs(ox - sunX) < path && c !== FOAM && hash(Math.floor(ox), Math.floor(oy), Math.floor(t * 8)) > 0.72 + (Math.abs(ox - sunX) / path) * 0.26) {
    c = rgb(hash(Math.floor(ox), Math.floor(oy), 52) > 0.5 ? "#FFD27A" : "#FF9A55");
  }
  return c;
};

/** A gull: a small V flapping, centred at (x, y). */
const gullAt = (wx: number, wy: number, x: number, y: number, t: number, seed: number) => {
  const flap = Math.sin(t * 7 + seed) * 1.5;
  const dx = wx - x;
  if (Math.abs(dx) > 4) return false;
  return Math.abs(wy - (y - Math.abs(dx) * 0.5 * (1 + flap * 0.3) + (Math.abs(dx) > 2 ? flap * 0.4 : 0))) < 0.6;
};

const HZ = 196;
const SUN = { x: 122, y: HZ, r: 13 } as const;
const DECK_Y = 246;
/** The runner gains a little ground along the pier (never wraps). */
const runnerX = (t: number) => 40 + Math.min(t, 40) * 1.1;

const wide: View = {
  anchors: anchors((t) => ({ light: [122, 188, 0.3], subject: [runnerX(t) + 2, DECK_Y - 36, 1], sky: [40, 140, 0.2], ground: [150, 280, 0.8] })),
  rain: 0.15,
  beam: (p) => ({ x: 163, y: 160, angle: Math.PI + 0.25 + p.sweep + Math.sin(p.t * 0.45) * 0.3, spread: 0.2, length: 220, power: p.beam * 0.9 }),
  pixel(sx, sy, p, beam) {
    const { t, flash } = p;
    const [rx, ry] = toWorld(p.cam, sx, sy, 1);
    const runX = runnerX(t);
    if (rx > runX - 18 && rx < runX + 18 && ry > DECK_Y - 44 && ry <= DECK_Y) {
      const f = figureAt(runPose(t * 2 * Math.PI * 1.35), runX, DECK_Y, 1.4, rx, ry, 1, -1);
      if (f) return flash ? SOLID_INK : { c: f === 2 ? RIM : BODY, solid: true };
    }
    // The pier: deck (lit edge facing the sun), rail, lamp posts, pilings into the waves.
    if (rx < 150) {
      if (ry >= DECK_Y && ry < DECK_Y + 6) {
        if (flash) return SOLID_INK;
        const sheen = smooth(50, 0, Math.abs(rx - SUN.x)) * (ry < DECK_Y + 1 ? 1 : 0.3);
        return { c: ry < DECK_Y + 1 ? dither(CLOUD_LIT, 0.1 + sheen * 0.6, sx, sy) : dither(DECK, (Math.floor(rx) % 5 ? 0.4 : 0) * (ry < DECK_Y + 3 ? 1 : 0.5), sx, sy), solid: true };
      }
      if (ry >= DECK_Y - 12 && ry < DECK_Y && (Math.floor(rx) % 16 < 2 || Math.abs(ry - (DECK_Y - 11)) < 0.7 || Math.abs(ry - (DECK_Y - 6)) < 0.5)) return flash ? SOLID_INK : { c: DECK[1], solid: true };
      for (const lampX of [24, 104]) {
        if (Math.abs(rx - lampX) < 0.8 && ry >= DECK_Y - 34 && ry < DECK_Y) return flash ? SOLID_INK : { c: DECK[0], solid: true };
        if (Math.abs(rx - lampX) < 1.8 && ry >= DECK_Y - 37 && ry < DECK_Y - 34) return flash ? SOLID_INK : { c: rgb("#FFE9B0"), solid: true };
      }
      if (ry >= DECK_Y + 6 && ry < 300 && Math.floor(rx) % 16 < 2) return flash ? SOLID_INK : { c: dither(DECK, 0.1, sx, sy), solid: true };
    }
    const [ox, oy] = toWorld(p.cam, sx, sy, 0.7);
    if (oy >= HZ) return flash ? SOLID_INK : { c: dawnSea(ox, oy, sx, sy, t, HZ, SUN.x), solid: true };
    // Headland with the lighthouse (right, far).
    const [hx, hy] = toWorld(p.cam, sx, sy, 0.4);
    const ridge = HZ - 6 - 10 * smooth(130, 175, hx) + noise(hx * 0.3, 0, 61) * 3;
    if (hx > 128 && hy >= ridge) return flash ? SOLID_INK : { c: dither(DECK, 0.15, sx, sy), solid: true };
    if (Math.abs(hx - 163) < 2.8 - (166 - hy) * 0.03 && hy >= 158 && hy < 186) {
      if (flash) return SOLID_INK;
      return { c: hy < 163 ? rgb("#FFE9B0") : Math.floor((hy - 163) / 5) % 2 ? rgb("#3A2230") : rgb("#8A4A4A"), solid: true };
    }
    const [kx, ky] = toWorld(p.cam, sx, sy, 0.2);
    if (flash) return { c: flashSky(kx, ky, sx, sy, [40, 170, 5]), solid: false };
    return { c: lit(dawnSky(kx, ky, sx, sy, t, HZ, SUN.x, SUN.y, SUN.r), beamAt(beam, kx, ky) * 0.85, sx, sy), solid: false };
  },
};

const BIG_SUN = { x: 96, y: 196, r: 46 } as const;

const runner: View = {
  anchors: anchors(() => ({ light: [96, 160, 0.3], subject: [96, 150, 1], sky: [40, 70, 0.2], ground: [60, 300, 1] })),
  rain: 0,
  // Sun shafts fanning up and out behind the runner.
  beam: (p) => ({ x: BIG_SUN.x, y: BIG_SUN.y, angle: -Math.PI / 2 - 0.35 + p.sweep + Math.sin(p.t * 0.3) * 0.1, spread: 0.5, length: 230, power: p.beam * 0.55 }),
  pixel(sx, sy, p, beam) {
    const { t, flash } = p;
    const [rx, ry] = toWorld(p.cam, sx, sy, 1);
    // The runner, big, running on the spot (the camera tracks him), rim-lit by the sun behind.
    if (ry > 140 && ry <= 296 && rx > 30 && rx < 160) {
      const f = figureAt(runPose(t * 2 * Math.PI * 1.35), 92, 296, 4.8, rx, ry, 1.5, -1.5);
      if (f) return flash ? SOLID_INK : { c: f === 2 ? RIM : BODY, solid: true };
    }
    // The deck: planks rushing past under him, the sun's sheen on the wet wood.
    if (ry >= 288) {
      if (flash) return SOLID_INK;
      const plank = Math.floor((rx + t * 60) / 12) % 2;
      const sheen = smooth(60, 0, Math.abs(rx - BIG_SUN.x)) * smooth(320, 288, ry);
      return { c: dither(DECK, 0.2 + plank * 0.25 + sheen * 0.6, sx, sy), solid: true };
    }
    if (ry >= 262 && ry < 288 && (Math.floor(rx + t * 60) % 30 < 3 || Math.abs(ry - 264) < 1)) return flash ? SOLID_INK : { c: DECK[1], solid: true };
    const [ox, oy] = toWorld(p.cam, sx, sy, 0.4);
    if (oy >= BIG_SUN.y) return flash ? SOLID_INK : { c: dawnSea(ox, oy, sx, sy, t, BIG_SUN.y, BIG_SUN.x), solid: true };
    const [kx, ky] = toWorld(p.cam, sx, sy, 0.15);
    if (flash) return { c: flashSky(kx, ky, sx, sy, [150, 180, 6]), solid: false };
    return { c: lit(dawnSky(kx, ky, sx, sy, t, BIG_SUN.y, BIG_SUN.x, BIG_SUN.y, BIG_SUN.r), beamAt(beam, kx, ky) * 0.7, sx, sy, rgb("#FFE9B8"), rgb("#FFC27A")), solid: false };
  },
};

const WAVE_HZ = 120;

const waves: View = {
  anchors: anchors(() => ({ light: [150, 104, 0.3], subject: [40, 250, 1.2], sky: [60, 50, 0.2], ground: [100, 290, 1.2] })),
  rain: 0.15,
  // The lighthouse's beam, wide, crossing the dawn sky.
  beam: (p) => ({ x: 152, y: 104, angle: Math.PI + 0.12 + p.sweep + Math.sin(p.t * 0.5) * 0.35, spread: 0.24, length: 260, power: p.beam }),
  pixel(sx, sy, p, beam) {
    const { t, flash } = p;
    // Pilings in the foreground, waves breaking white on them.
    const [px, py] = toWorld(p.cam, sx, sy, 1.3);
    for (const [x, w] of [[22, 9], [62, 7], [96, 5]] as const) {
      if (Math.abs(px - x) < w / 2 && py > 140) {
        if (flash) return SOLID_INK;
        const wet = py > 230 ? 0.1 : 0.35;
        return { c: dither(DECK, wet + (px - x > w / 4 ? 0.3 : 0), sx, sy), solid: true };
      }
      // A wave hits the piling every few seconds: a burst of spray up its side.
      const hit = Math.sin(t * 1.6 + x * 0.13);
      const spray = hit > 0.2 && Math.abs(px - x) < w / 2 + 2 + hit * 5 && py > 236 - hit * 26 && py < 246;
      if (spray && hash(Math.floor(px), Math.floor(py), Math.floor(t * 12)) > 0.55) return flash ? SOLID_INK : { c: FOAM, solid: true };
    }
    if (py > 128 && py < 136 && px < 110) return flash ? SOLID_INK : { c: dither(DECK, Math.abs(py - 128) < 1 ? 0.8 : 0.3, sx, sy), solid: true }; // deck above
    const [ox, oy] = toWorld(p.cam, sx, sy, 0.9);
    if (oy >= WAVE_HZ) return flash ? SOLID_INK : { c: lit(dawnSea(ox, oy, sx, sy, t, WAVE_HZ, 120), beamAt(beam, ox, oy) * 0.4, sx, sy), solid: true };
    // The lighthouse far right on its rock.
    const [hx, hy] = toWorld(p.cam, sx, sy, 0.4);
    if (hx > 136 && hy > WAVE_HZ - 6 + noise(hx * 0.3, 1, 62) * 3) return flash ? SOLID_INK : { c: dither(DECK, 0.1, sx, sy), solid: true };
    if (Math.abs(hx - 152) < 3.4 - (hy - 100) * 0.02 && hy >= 98 && hy < 118) {
      if (flash) return SOLID_INK;
      return { c: hy < 104 ? rgb("#FFE9B0") : Math.floor((hy - 104) / 4) % 2 ? rgb("#3A2230") : rgb("#9A4A4A"), solid: true };
    }
    const [kx, ky] = toWorld(p.cam, sx, sy, 0.2);
    if (flash) return { c: flashSky(kx, ky, sx, sy, [60, 110, 8]), solid: false };
    return { c: lit(dawnSky(kx, ky, sx, sy, t, WAVE_HZ, 110, WAVE_HZ, 9), beamAt(beam, kx, ky), sx, sy), solid: false };
  },
};

const H_SUN = { x: 90, y: 214, r: 34 } as const;

const horizon: View = {
  anchors: anchors(() => ({ light: [90, 196, 0.3], subject: [60, 120, 0.5], sky: [140, 80, 0.2], ground: [90, 280, 0.8] })),
  rain: 0,
  beam: (p) => ({ x: H_SUN.x, y: H_SUN.y, angle: -Math.PI / 2 + 0.3 + p.sweep + Math.sin(p.t * 0.25) * 0.15, spread: 0.45, length: 220, power: p.beam * 0.5 }),
  pixel(sx, sy, p, beam) {
    const { t, flash } = p;
    const [ox, oy] = toWorld(p.cam, sx, sy, 0.6);
    if (oy >= H_SUN.y) return flash ? SOLID_INK : { c: dawnSea(ox, oy, sx, sy, t, H_SUN.y, H_SUN.x), solid: true };
    const [gx, gy] = toWorld(p.cam, sx, sy, 0.8);
    for (let i = 0; i < 5; i++) {
      const x = ((hash(i, 0, 73) * 200 + t * (8 + hash(i, 1, 73) * 6)) % 220) - 20;
      if (gullAt(gx, gy, x, 90 + hash(i, 2, 73) * 70, t, i)) return flash ? SOLID_INK : { c: rgb("#1A1226"), solid: true };
    }
    const [kx, ky] = toWorld(p.cam, sx, sy, 0.2);
    if (flash) return { c: flashSky(kx, ky, sx, sy, [130, 200, 9]), solid: false };
    return { c: lit(dawnSky(kx, ky, sx, sy, t, H_SUN.y, H_SUN.x, H_SUN.y, H_SUN.r), beamAt(beam, kx, ky) * 0.7, sx, sy, rgb("#FFE9B8"), rgb("#FFC27A")), solid: false };
  },
};

export const PIER_VIEWS = { wide, runner, waves, horizon } as const;
