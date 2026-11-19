// The fridge set (step 143): a dark kitchen at night, the fridge's light as the hero. Four
// views: `kitchen` wide (the door opens, its light spills across the floor onto the person,
// rain on the window); `face` close on the face in profile lit by the open fridge; `inside`
// from inside the fridge, shelves in the foreground, the person framed in the doorway
// checking the phone; `window` the rainy window, the city and the storm outside, the fridge's
// glow on the glass. Pure, so `node --test` runs it.
import { type AnchorId, FLASH_PAPER, flashSky, lit, nightSky, SOLID_INK, type View } from "./common.ts";
import { bustAt, figureAt, phonePose, standPose } from "./figure.ts";
import { beamAt, dither, hash, mix, noise, type RGB, ramp, rgb, smooth, toWorld } from "./pixel.ts";

const SKYLINE = ramp("#0B0B22", "#10112E", "#161842");
const WALL = ramp("#07071A", "#0C0D26", "#131636", "#1D2148");
const WOOD = ramp("#0E0A16", "#170F1E", "#221626", "#2E1E2E");
const STEEL = ramp("#161A2E", "#20263E", "#2C3452", "#3C4668");
const FRIDGE_IN = ramp("#B98A4A", "#E6BC78", "#FFE2A8", "#FFF4DA");
const FLOOR = ramp("#08081A", "#0E0F28", "#171A3A");
const GLASS_DIM = ramp("#0A0E26", "#141A3B", "#1E2750");
const BODY = rgb("#0A0712");
const FRIDGE = { x0: 104, x1: 152, y0: 70, y1: 236 } as const;
const PANE = { x0: 16, x1: 74, y0: 58, y1: 138 } as const;
const ITEMS: [x0: number, y0: number, w: number, h: number, col: string][] = [
  [110, 92, 4, 14, "#3FBF7F"],
  [116, 98, 7, 8, "#FF6F61"],
  [128, 100, 10, 6, "#F5F1E8"],
  [140, 96, 6, 10, "#F5C242"],
  [112, 124, 14, 5, "#F5F1E8"],
  [132, 120, 8, 9, "#3E8EF7"],
  [142, 122, 6, 7, "#FF6F61"],
  [114, 148, 9, 8, "#3FBF7F"],
  [128, 150, 16, 6, "#E6BC78"],
];

const anchors = (a: Record<AnchorId, readonly [number, number, number]>) => () => a;

/** Rain-streaked glass over the night outside (world cells of the pane); city lights below `cityY`. */
const nightPane = (kx: number, ky: number, x: number, y: number, t: number, cityY: number): RGB => {
  let c = nightSky(kx * 1.4, ky * 1.4, x, y, t, 81);
  if (ky > cityY + noise(kx * 0.2, 0, 82) * 8) c = dither(SKYLINE, 0.4, x, y);
  if (ky > cityY - 6 && hash(Math.floor(kx), Math.floor(ky), 83) > 0.93) c = rgb(hash(Math.floor(kx), 0, 84) > 0.5 ? "#8A6A3A" : "#3E5A8E");
  const col = Math.floor(kx * 0.7);
  const drop = (ky * 0.12 - t * (0.6 + hash(col, 0, 85)) + hash(col, 1, 85) * 9) % 3;
  if (hash(col, 2, 85) > 0.6 && drop > 0 && drop < 0.35) c = mix(c, rgb("#8E9AD6"), 0.6);
  return c;
};

// ----------------------------------------------------------------------------- kitchen (wide)

/** The kitchen sits this many cells lower on screen than it is drawn: the upper third stays dark wall for the type. */
const LOWER = 34;
/** Drawing cells of camera-space cells (anchors are camera space, the drawing and its beam are not). */
const lower = ([x, y]: [number, number]): [number, number] => [x, y - LOWER];

const kitchen: View = {
  anchors: anchors({ light: [128, 120 + LOWER, 1], subject: [86, 218 + LOWER, 1.1], sky: [45, 90 + LOWER, 0.6], ground: [96, 290, 1.2] }),
  rain: 0,
  beam: (p) => ({ x: 128, y: 160, angle: 2.15 + p.sweep, spread: 0.62 * p.open, length: 190, power: p.beam * p.open }),
  pixel(sx, sy, p, beam) {
    const { t, open, flash } = p;
    // The person in front of the fridge, a step closer to the camera.
    const [px, py] = lower(toWorld(p.cam, sx, sy, 1.1));
    if (px > 70 && px < 104 && py > 212 && py <= 266) {
      const f = figureAt(standPose(open * 0.85, Math.sin(t * 1.5)), 86, 266, 1.75, px, py, 1, 0);
      if (f) return flash ? SOLID_INK : { c: f === 2 ? dither(FRIDGE_IN, 0.3 + open * 0.4, sx, sy) : BODY, solid: true };
    }
    // Floor: perspective tiles, lit by the fridge.
    const [gx, gy] = lower(toWorld(p.cam, sx, sy, 1.2));
    if (gy >= 236) {
      if (flash) return SOLID_INK;
      const u = Math.floor(((gx - 96) / (gy - 150)) * 9);
      const v = Math.floor(900 / (gy - 150));
      return { c: lit(dither(FLOOR, (u + v) % 2 ? 0.25 : 0.7, sx, sy), beamAt(beam, gx, gy) * 1.1, sx, sy), solid: true };
    }
    const [wx, wy] = lower(toWorld(p.cam, sx, sy, 1));
    // The fridge: a steel door that swings open on the right, the lit inside with shelves.
    if (wx >= FRIDGE.x0 && wx < FRIDGE.x1 + 14 * open && wy >= FRIDGE.y0 && wy < FRIDGE.y1) {
      if (wx >= FRIDGE.x1) return flash ? SOLID_INK : { c: dither(STEEL, (wy % 14 < 2 ? 0.9 : 0.5) + 0.1 * open, sx, sy), solid: true };
      const doorEdge = FRIDGE.x0 + (FRIDGE.x1 - FRIDGE.x0) * open;
      const inside = wx < doorEdge && wx >= FRIDGE.x0 + 3 && wx < FRIDGE.x1 - 3 && wy >= FRIDGE.y0 + 4 && wy < FRIDGE.y1 - 6 && Math.abs(wy - 162) > 1.5;
      if (inside) {
        if (flash) return { c: FLASH_PAPER, solid: false };
        for (const [x0, y0, w, h, col] of ITEMS) if (wx >= x0 && wx < x0 + w && wy >= y0 && wy < y0 + h) return { c: mix(rgb(col), FRIDGE_IN[3], wy < y0 + 1 ? 0.4 : 0), solid: false };
        if ([108, 132, 158, 196].some((s) => Math.abs(wy - s) < 0.6)) return { c: FRIDGE_IN[0], solid: false };
        return { c: dither(FRIDGE_IN, 0.45 + smooth(60, 0, Math.hypot(wx - 128, wy - 84)) * 0.55, sx, sy), solid: false };
      }
      if (flash) return SOLID_INK;
      const handle = Math.abs(wx - (FRIDGE.x0 + 4)) < 0.8 && wy > 120 && wy < 150 && open < 0.1;
      return { c: handle ? STEEL[3] : dither(STEEL, 0.25 + (0.15 * (wx - FRIDGE.x0)) / 48 + (Math.abs(wy - 162) < 1 ? -0.2 : 0), sx, sy), solid: true };
    }
    if (flash && !(wx >= PANE.x0 && wx < PANE.x1 && wy >= PANE.y0 && wy < PANE.y1)) return SOLID_INK;
    // Window on the back wall: the rainy night outside, drops on the glass.
    if (wx >= PANE.x0 - 2 && wx < PANE.x1 + 2 && wy >= PANE.y0 - 2 && wy < PANE.y1 + 3) {
      const frame = wx < PANE.x0 || wx >= PANE.x1 || wy < PANE.y0 || wy >= PANE.y1 || Math.abs(wx - 45) < 0.8 || Math.abs(wy - 98) < 0.8;
      if (frame) return flash ? SOLID_INK : { c: dither(WOOD, wy >= PANE.y1 ? 0.8 : 0.4, sx, sy), solid: true };
      const [kx, ky] = lower(toWorld(p.cam, sx, sy, 0.6));
      if (flash) return { c: flashSky(kx, ky, sx, sy, [40, 140, 7]), solid: false };
      return { c: nightPane(kx, ky, sx, sy, t, 118), solid: false };
    }
    // Counter and cabinets (left), upper cabinets (right).
    if (wx < FRIDGE.x0 - 2 && wy >= 168) {
      const glow = smooth(60, 0, Math.abs(wx - FRIDGE.x0)) * open;
      return { c: dither(WOOD, (wy < 171 ? 0.9 : wx % 24 < 1 ? 0 : 0.35) + glow * 0.5, sx, sy), solid: true };
    }
    if (wx >= 80 && wy >= 20 && wy < 62) {
      return { c: dither(WOOD, wy >= 60 ? 0.9 : Math.floor(wx) % 25 < 1 ? 0 : 0.3 + smooth(80, 0, Math.hypot(wx - 128, wy - 70)) * open * 0.6, sx, sy), solid: true };
    }
    // Back wall, lit by the open fridge.
    const glow = smooth(110, 0, Math.hypot(wx - 128, (wy - 150) * 0.8)) * open;
    return { c: lit(dither(WALL, 0.2 + glow * 0.75, sx, sy), beamAt(beam, wx, wy) * 0.5, sx, sy), solid: true };
  },
};

// --------------------------------------------------------------------------- face (close)

const face: View = {
  anchors: anchors({ light: [160, 130, 1], subject: [112, 128, 1], sky: [30, 100, 1], ground: [60, 290, 1] }),
  rain: 0,
  // The fridge's light, wide, falling left across the face onto the wall.
  beam: (p) => ({ x: 176, y: 150, angle: Math.PI + 0.12 + p.sweep, spread: 0.55, length: 220, power: p.beam * p.open }),
  pixel(sx, sy, p, beam) {
    const { t, flash, open } = p;
    const [wx, wy] = toWorld(p.cam, sx, sy, 1);
    // The open fridge on the right: its lit inside, shelves, items.
    if (wx > 150) {
      if (flash) return { c: FLASH_PAPER, solid: false };
      if (wx > 176 || [92, 150, 214].some((y) => Math.abs(wy - y) < 1)) return { c: FRIDGE_IN[0], solid: false };
      const item = Math.floor(wy / 22) % 3 === 0 && wx > 158 && wx < 172 && Math.floor(wy) % 22 > 8;
      return { c: item ? mix(rgb(["#3FBF7F", "#FF6F61", "#F5C242"][Math.floor(wy / 66) % 3]), FRIDGE_IN[3], 0.2) : dither(FRIDGE_IN, 0.5 + 0.5 * open, sx, sy), solid: false };
    }
    const f = bustAt(98, 128, 3.6, wx, wy, 1, 0, 0.12 + Math.sin(t * 0.8) * 0.03);
    if (flash) return f ? SOLID_INK : { c: FLASH_PAPER, solid: false };
    if (f === 3) return { c: dither([BODY, rgb("#5A3424"), rgb("#B07A52"), rgb("#F2C894")], smooth(100, 132, wx) * open + 0.05, sx, sy), solid: true };
    if (f === 2) return { c: dither(FRIDGE_IN, 0.6 * open + 0.1, sx, sy), solid: true };
    if (f) return { c: BODY, solid: true };
    // The dark kitchen behind: the wall in the fridge's glow, a window's blue, the counter.
    let c = dither(WALL, 0.15 + smooth(160, 20, Math.hypot(wx - 170, wy - 150)) * 0.6 * open, sx, sy);
    if (wx < 40 && wy > 60 && wy < 140) c = dither(GLASS_DIM, 0.3 + noise(wx * 0.1, wy * 0.1 - t * 0.2, 89) * 0.4, sx, sy);
    if (wy > 250) c = dither(WOOD, wy < 252 ? 0.8 : 0.3, sx, sy);
    return { c: lit(c, beamAt(beam, wx, wy) * 0.3, sx, sy), solid: true };
  },
};

// ---------------------------------------------------------------- inside (from inside the fridge)

const inside: View = {
  anchors: anchors({ light: [90, 14, 1.3], subject: [90, 150, 1], sky: [40, 90, 1], ground: [100, 290, 1.3] }),
  rain: 0,
  // The fridge light pouring out at the person.
  beam: (p) => ({ x: 90, y: 10, angle: Math.PI / 2 + p.sweep, spread: 0.5, length: 330, power: p.beam * 0.6 * p.open }),
  pixel(sx, sy, p, beam) {
    const { t, flash, open } = p;
    // Foreground: the bottom shelf with big jars and bottles, the lit walls, the bulb above.
    const [fx, fy] = toWorld(p.cam, sx, sy, 1.3);
    if (fy > 262) {
      if (flash) return SOLID_INK;
      if (Math.abs(fy - 300) < 1.5) return { c: FRIDGE_IN[1], solid: true };
      for (const [x0, w, h, col] of [[6, 22, 44, "#F5F1E8"], [34, 18, 30, "#3FBF7F"], [120, 26, 36, "#FF6F61"], [150, 20, 48, "#F5C242"]] as const) {
        if (fx >= x0 && fx < x0 + w && fy > 300 - h && fy < 300) return { c: mix(rgb(col), rgb("#2A1A10"), 0.55 - ((fx - x0) / w) * 0.3), solid: true };
      }
      return { c: dither(FRIDGE_IN, 0.4, sx, sy), solid: true };
    }
    if (fx < 14 || fx > 166 || fy < 18) {
      if (flash) return SOLID_INK;
      const bulb = Math.hypot(fx - 90, fy - 10) < 6;
      return { c: bulb ? rgb("#FFFBEA") : dither(FRIDGE_IN, fy < 18 ? 0.8 : 0.35 + (fx < 14 ? fx / 30 : (180 - fx) / 30), sx, sy), solid: true };
    }
    // Through the open door: the person in the light, looking at the phone.
    const [wx, wy] = toWorld(p.cam, sx, sy, 1);
    const fig = figureAt(phonePose(Math.sin(t * 1.4)), 90, 340, 7.2, wx, wy);
    if (flash) return fig ? SOLID_INK : { c: FLASH_PAPER, solid: false };
    if (fig) {
      const screen = Math.abs(wx - 90) < 6 && wy > 340 - 7.2 * 19.5 && wy < 340 - 7.2 * 18;
      if (screen) return { c: rgb("#CFF3FF"), solid: true };
      const k = smooth(330, 120, wy) * 0.55 * open + 0.06;
      return { c: dither([BODY, rgb("#3A2418"), rgb("#8A5A34"), rgb("#E0A868")], k, sx, sy), solid: true };
    }
    const c = dither(WALL, 0.1 + smooth(200, 0, Math.hypot(wx - 90, wy - 200)) * 0.5 * open, sx, sy);
    return { c: lit(c, beamAt(beam, wx, wy) * 0.6, sx, sy), solid: true };
  },
};

// ----------------------------------------------------------------------- window (the storm outside)

const PANE2 = { x0: 20, x1: 160, y0: 40, y1: 250 } as const;

const window: View = {
  anchors: anchors({ light: [160, 220, 1], subject: [132, 214, 1.2], sky: [60, 100, 0.6], ground: [90, 290, 1.2] }),
  rain: 0,
  // The fridge's glow from the right, raking across the window frame.
  beam: (p) => ({ x: 200, y: 250, angle: Math.PI + 0.35 + p.sweep, spread: 0.5, length: 240, power: p.beam * 0.7 * p.open }),
  pixel(sx, sy, p, beam) {
    const { t, flash, open } = p;
    // A plant on the sill (foreground): pot and leaves.
    const [qx, qy] = toWorld(p.cam, sx, sy, 1.2);
    const leaf = qy > 200 && qy < 236 && Math.abs(qx - 132 - Math.sin((236 - qy) * 0.2) * 6) < 2 + (236 - qy) * 0.06 && noise(qx * 0.4, qy * 0.4, 99) > 0.35;
    if ((qx > 124 && qx < 140 && qy >= 236 && qy < 254) || leaf) return flash ? SOLID_INK : { c: leaf ? rgb("#14261C") : rgb("#3A1A14"), solid: true };
    const [wx, wy] = toWorld(p.cam, sx, sy, 1);
    const inPane = wx >= PANE2.x0 && wx < PANE2.x1 && wy >= PANE2.y0 && wy < PANE2.y1;
    const bar = Math.abs(wx - 90) < 2 || Math.abs(wy - 140) < 2;
    if (inPane && !bar) {
      const [kx, ky] = toWorld(p.cam, sx, sy, 0.6);
      if (flash) return { c: flashSky(kx, ky, sx, sy, [70, 200, 10]), solid: false };
      let c = nightPane(kx, ky, sx, sy, t, 200);
      // The fridge's warm glow reflected on the glass, low right.
      const refl = smooth(90, 10, Math.hypot(wx - 150, wy - 230)) * 0.5 * open;
      if (refl > 0) c = mix(c, FRIDGE_IN[1], refl);
      return { c, solid: false };
    }
    if (flash) return SOLID_INK;
    if (wy >= PANE2.y1 && wy < PANE2.y1 + 8) return { c: dither(WOOD, wy < PANE2.y1 + 1.5 ? 0.95 : 0.5, sx, sy), solid: true };
    const frame = inPane || (wx > PANE2.x0 - 6 && wx < PANE2.x1 + 6 && wy > PANE2.y0 - 6 && wy < PANE2.y1);
    const c = frame ? dither(WOOD, 0.35, sx, sy) : dither(WALL, 0.15 + smooth(140, 0, Math.hypot(wx - 200, wy - 250)) * 0.5 * open, sx, sy);
    return { c: lit(c, beamAt(beam, wx, wy) * 0.9, sx, sy), solid: true };
  },
};

export const FRIDGE_VIEWS = { kitchen, face, inside, window } as const;
