// The window set (step 143): a rainy city at 21 h, one lit kitchen window as the hero.
// Four views (shots cut between them): `block` the city block in the storm, the lit window
// the brightest thing in it, a car's headlights sweeping the wet street; `facade` the window
// filling the frame (lamp, open cupboard, someone reaching in, a steaming mug, curtains
// moving, rain on the glass, drips off the sill, the neon cross glowing green on wet bricks);
// `interior` close through the glass (the face lit by the phone, the lamp swinging);
// `puddle` street level, the window mirrored in a puddle broken by rain rings.
// Pure, so `node --test` runs it.
import {
  AMBER_HOT,
  type AnchorId,
  bricks,
  carAt,
  FLASH_PAPER,
  flashSky,
  headlights,
  INK,
  lit,
  neonCross,
  NEON_GLOW,
  neonGlow,
  nightSky,
  ripples,
  SOLID_INK,
  type View,
} from "./common.ts";
import { bustAt, figureAt, standPose } from "./figure.ts";
import { beamAt, dither, hash, mix, noise, type RGB, ramp, rgb, smooth, toWorld } from "./pixel.ts";

const ROOM = ramp("#5A2412", "#8A3A16", "#B4541E", "#E07B2E", "#FFAE52", "#FFD58A", "#FFF0C8");
const GLASS = ramp("#0A0E26", "#121838", "#1C244C", "#2C3866");
const STREET = ramp("#06071A", "#0A0C22", "#10142E", "#181E40", "#232B55");
const SKYLINE = ramp("#090A20", "#0E102C", "#14173A", "#1B1F48");
const WOOD = ramp("#140C12", "#22141A", "#341E22", "#4A2C2A");
const DROP = rgb("#9AA6E0");
const STEAM = rgb("#F4E6CC");
const JARS = ["#3FBF7F", "#FF6F61", "#F5C242", "#F5F1E8", "#3E8EF7", "#C98A4A"].map(rgb);

const anchors = (a: Record<AnchorId, readonly [number, number, number]>) => () => a;

/** Rain running down a pane: lighter streaks over `c`. */
const onGlass = (c: RGB, wx: number, wy: number, t: number): RGB => {
  const col = Math.floor(wx * 0.6);
  const run = (wy * 0.1 - t * (0.5 + hash(col, 0, 85)) + hash(col, 1, 85) * 9) % 3;
  if (hash(col, 2, 85) > 0.72 && run > 0 && run < 0.25) return mix(c, DROP, 0.45);
  if (hash(Math.floor(wx), Math.floor(wy), 86) > 0.998) return mix(c, DROP, 0.5); // beads
  return c;
};

/** Steam curling up from a mug whose rim is at (x, y). */
const steamAt = (wx: number, wy: number, x: number, y: number, t: number) => {
  const h = y - wy;
  if (h < 0 || h > 26) return 0;
  const cx = x + Math.sin(h * 0.25 - t * 2.2) * (1 + h * 0.12);
  const d = Math.abs(wx - cx);
  const k = smooth(2.2, 0.4, d) * smooth(26, 4, h) * (noise(wx * 0.4, h * 0.3 - t * 1.6, 87) > 0.42 ? 1 : 0);
  return k * 0.75;
};

/** A mug (body 7 x 8 at (x, y) = bottom-left) with its handle; null outside. */
const mugAt = (wx: number, wy: number, x: number, y: number): RGB | null => {
  if (wx >= x && wx < x + 7 && wy >= y - 8 && wy < y) return wy < y - 7 ? rgb("#FFF4DE") : wx < x + 1.5 ? rgb("#E9D8BC") : rgb("#F7EBD2");
  if (Math.abs(Math.hypot(wx - x - 7.5, wy - y + 4) - 2) < 0.7 && wx > x + 6.5) return rgb("#E9D8BC");
  return null;
};

// ----------------------------------------------------------------------------- block (wide)

const HERO = { x0: 68, x1: 132, top: 96 } as const;
const HERO_WIN = { x0: 90, x1: 110, y0: 150, y1: 174 } as const;
const LOTS = [
  [0, 36, 122],
  [36, 68, 162],
  [132, 180, 132],
] as const;
const carX = (t: number, speed: number, span: number, start: number) => start + ((t * speed) % span);

const block: View = {
  anchors: anchors({ light: [100, 162, 1], subject: [102, 166, 1], sky: [40, 70, 0.2], ground: [100, 286, 1.1] }),
  rain: 1,
  beam: (p) => ({ x: 100, y: 176, angle: 1.95 + p.sweep, spread: 0.46, length: 170, power: p.beam }),
  pixel(sx, sy, p, beam) {
    const { t, flash } = p;
    const [gx, gy] = toWorld(p.cam, sx, sy, 1.1);
    const cx = carX(t, 26, 320, -90);
    const car = headlights(cx, 272, 1, 1);
    // Street: wet asphalt, light streaks under each light, rain rings, a car passing.
    if (gy >= 242) {
      const c0 = carAt(gx, gy, cx, 272, 1);
      if (c0) return flash ? SOLID_INK : { c: c0, solid: true };
      if (flash) return SOLID_INK;
      let c = gy < 250 ? dither(STREET, gy < 243 ? 0.95 : 0.5, sx, sy) : dither(STREET, 0.12 + 0.2 * noise(gx * 0.06, gy * 0.5, 4), sx, sy);
      if (gy >= 250) {
        const wob = Math.sin(gy * 0.9 + t * 3) * 1.4;
        const streak = (x0: number, x1: number) => gx + wob > x0 && gx + wob < x1 && noise(gx * 0.4, gy * 1.6 - t * 2, 5) > 0.45;
        if (streak(HERO_WIN.x0, HERO_WIN.x1)) c = dither(ROOM, 0.35 + 0.4 * smooth(320, 250, gy), sx, sy);
        else if (streak(132, 142)) c = mix(c, NEON_GLOW, 0.8);
        else if (streak(25, 33) || streak(153, 161)) c = mix(c, rgb("#8FA6E8"), 0.5);
        if (ripples(gx, gy, t, 3) > 0.3) c = mix(c, rgb("#7C86C8"), 0.6);
      }
      c = lit(c, beamAt(car, gx, gy) * 1.2, sx, sy, rgb("#FFF6DA"), rgb("#E9DDB0"));
      return { c: lit(c, beamAt(beam, gx, gy) * 0.8, sx, sy), solid: true };
    }
    // Street lamps, foreground.
    const [lx, ly] = toWorld(p.cam, sx, sy, 1.15);
    for (const x of [28, 157]) {
      if (Math.abs(lx - x) < 1 && ly > 200 && ly < 242) return flash ? SOLID_INK : { c: STREET[1], solid: true };
      if (Math.abs(lx - x) < 3 && ly >= 197 && ly < 200) return flash ? SOLID_INK : { c: rgb("#E9F1FF"), solid: true };
    }
    // Buildings.
    const [wx, wy] = toWorld(p.cam, sx, sy, 1);
    if (wx >= HERO.x0 && wx < HERO.x1 && wy >= HERO.top) {
      const win = wx >= HERO_WIN.x0 && wx < HERO_WIN.x1 && wy >= HERO_WIN.y0 && wy < HERO_WIN.y1;
      const bar = Math.abs(wx - 100) < 0.6 || Math.abs(wy - 160) < 0.6;
      if (win && !bar) {
        if (flash) return { c: FLASH_PAPER, solid: false };
        const f = figureAt(standPose(0.8), 104, HERO_WIN.y1, 0.75, wx, wy, -1, 0);
        return { c: f ? (f === 2 ? rgb("#B0602A") : rgb("#2A1410")) : dither(ROOM, 0.55 + smooth(14, 0, Math.hypot(wx - 96, wy - 156)) * 0.45, sx, sy), solid: true };
      }
      // Other windows: dark glass in a grid.
      const gxw = (wx - HERO.x0) % 16;
      const gyw = (wy - HERO.top - 10) % 30;
      const glass = !win && gxw > 4 && gxw < 13 && gyw > 0 && gyw < 18 && wy > HERO.top + 8 && wy < 236;
      if (flash) return glass || win ? { c: FLASH_PAPER, solid: false } : SOLID_INK;
      if (glass) return { c: lit(dither(GLASS, 0.15 + 0.4 * noise(wx * 0.2, wy * 0.1, 7), sx, sy), beamAt(beam, wx, wy) * 0.5, sx, sy), solid: true };
      const warm = smooth(40, 0, Math.hypot(wx - 100, (wy - 162) * 1.2)) * 0.7;
      return { c: lit(bricks(wx, wy, sx, sy, t, warm), beamAt(beam, wx, wy) * 0.6, sx, sy), solid: true };
    }
    for (const [x0, x1, top] of LOTS) {
      if (wx >= x0 && wx < x1 && wy >= top) {
        const nc = neonCross(wx, wy, 136, 178, 5, t);
        if (nc) return flash ? SOLID_INK : { c: nc, solid: true };
        if (flash) return SOLID_INK;
        const lw = (wx - x0) % 11 > 3 && (wx - x0) % 11 < 8 && (wy - top) % 18 > 5 && (wy - top) % 18 < 13;
        let c = lw ? (hash(Math.floor((wx - x0) / 11), Math.floor((wy - top) / 18), x0) > 0.8 ? rgb("#4A3A2A") : GLASS[1]) : dither(SKYLINE, 0.3 + 0.4 * hash(Math.floor(wx / 3), Math.floor(wy / 4), 21), sx, sy);
        const g = neonGlow(wx, wy, 136, 178, 5);
        if (g > 0) c = mix(c, NEON_GLOW, g);
        return { c, solid: true };
      }
    }
    // Far skyline (parallax), then the storm.
    const [fx, fy] = toWorld(p.cam, sx, sy, 0.5);
    const lot = Math.floor(fx / 9);
    if (fy >= 150 + hash(lot, 0, 23) * 40) return flash ? SOLID_INK : { c: dither(SKYLINE, 0.15, sx, sy), solid: true };
    const [kx, ky] = toWorld(p.cam, sx, sy, 0.2);
    if (flash) return { c: flashSky(kx, ky, sx, sy, [130, 160, 3]), solid: false };
    return { c: lit(nightSky(kx, ky, sx, sy, t, 31), beamAt(beam, wx, wy) * 0.85, sx, sy), solid: false };
  },
};

// ------------------------------------------------------------------- facade (the hero window)

const WIN = { x0: 26, x1: 154, y0: 66, y1: 236 } as const;
const CUP = { x0: 104, x1: 140, y0: 96, y1: 140 } as const;

/** The facade is drawn this many cells higher than it sits on screen: the bricks above the window carry the headline. */
const DROP_Y = 30;

const facade: View = {
  anchors: anchors({ light: [72, 104 + DROP_Y, 1], subject: [112, 150 + DROP_Y, 1], sky: [168, 40 + DROP_Y, 1], ground: [90, 240 + DROP_Y, 1] }),
  rain: 1,
  // The window's light spilling out and down into the rain, toward the viewer.
  // In camera space like the anchors (the rain over it is too), so the drawing looks it up DROP_Y lower.
  beam: (p) => ({ x: 90, y: 226 + DROP_Y, angle: Math.PI / 2 + 0.18 + p.sweep, spread: 0.6, length: 200, power: p.beam }),
  pixel(sx, sy, p, beam) {
    const { t, flash } = p;
    const [wx, sy0] = toWorld(p.cam, sx, sy, 1);
    const wy = sy0 - DROP_Y;
    const inWin = wx >= WIN.x0 && wx < WIN.x1 && wy >= WIN.y0 && wy < WIN.y1;
    if (inWin) {
      const frame = wx < WIN.x0 + 4 || wx >= WIN.x1 - 4 || wy < WIN.y0 + 4 || wy >= WIN.y1 - 3 || Math.abs(wx - 90) < 1.6 || Math.abs(wy - 112) < 1.4;
      if (frame) return flash ? SOLID_INK : { c: dither(WOOD, wx < WIN.x0 + 1 || wy < WIN.y0 + 1 ? 0.9 : 0.35, sx, sy), solid: true };
      return { ...roomPixel(wx, wy, sx, sy, t, flash), solid: !flash || !roomIsBack(wx, wy, t) };
    }
    if (flash) return SOLID_INK;
    // Sill: stone, its wet top edge, drips falling from it.
    if (wy >= WIN.y1 && wy < WIN.y1 + 6 && wx >= WIN.x0 - 6 && wx < WIN.x1 + 6) {
      return { c: wy < WIN.y1 + 1 ? rgb("#E8B07A") : wy < WIN.y1 + 2 ? rgb("#9A6A5A") : dither(WOOD, 0.4, sx, sy), solid: true };
    }
    const col = Math.floor(wx / 4);
    if (wy > WIN.y1 + 6 && wx > WIN.x0 && wx < WIN.x1 && hash(col, 0, 88) > 0.7 && Math.abs(wx - col * 4 - 2) < 0.6) {
      const fall = (t * 50 + hash(col, 1, 88) * 80) % 80;
      if (Math.abs(wy - WIN.y1 - 6 - fall) < 1.2) return { c: rgb("#BFD0FF"), solid: true };
    }
    // The neon cross on the right, its green on the wet bricks.
    const nc = neonCross(wx, wy, 168, 40, 9, t);
    if (nc) return { c: nc, solid: true };
    const warm = smooth(70, 0, Math.max(0, Math.max(WIN.x0 - wx, wx - WIN.x1, WIN.y0 - wy, wy - WIN.y1))) * 0.75;
    let c = bricks(wx, wy, sx, sy, t, warm);
    const g = neonGlow(wx, wy, 168, 40, 9);
    if (g > 0) c = mix(c, NEON_GLOW, g);
    return { c: lit(c, beamAt(beam, wx, sy0), sx, sy), solid: true };
  },
};

/** The kitchen behind the facade window's glass: is it back wall (white in the lightning)? */
const roomIsBack = (wx: number, wy: number, t: number) => {
  if (figureAt(standPose(0.9, Math.sin(t * 1.4)), 112, 262, 2.55, wx, wy)) return false;
  if (wx >= CUP.x0 && wx < CUP.x1 + 8 && wy >= CUP.y0 && wy < CUP.y1) return false;
  return wy < 204;
};

/** The kitchen through the facade window: lamp, open cupboard, the person reaching in, mug and steam, curtains, rain on the glass. */
const roomPixel = (wx: number, wy: number, sx: number, sy: number, t: number, flash: boolean): { c: RGB } => {
  const person = figureAt(standPose(0.9, Math.sin(t * 1.4)), 112, 262, 2.55, wx, wy, -1, 0);
  if (flash) return { c: roomIsBack(wx, wy, t) ? FLASH_PAPER : INK };
  // Curtains, swaying a little at their inner edge.
  const sway = Math.sin(t * 0.9 + wy * 0.04) * 2.5;
  const left = wx < WIN.x0 + 18 + sway - (wy - WIN.y0) * 0.04;
  const right = wx > WIN.x1 - 16 + sway + (wy - WIN.y0) * 0.03;
  let c: RGB;
  if (left || right) {
    const fold = Math.sin(wx * 1.1 + Math.sin(wy * 0.05 + t) * 0.6) * 0.5 + 0.5;
    c = dither(ROOM, 0.2 + fold * 0.3, sx, sy);
  } else if (person) {
    c = person === 2 ? rgb("#C46A2A") : rgb("#2A130E");
  } else {
    const lamp = Math.hypot(wx - 72, (wy - 104) * 1.2);
    c = dither(ROOM, 0.32 + smooth(70, 0, lamp) * 0.6, sx, sy);
    // Lamp: cord, shade, bulb.
    if (Math.abs(wx - 72) < 0.6 && wy < 98) c = rgb("#2A1208");
    if (wy >= 98 && wy < 104 && Math.abs(wx - 72) < 7 - (104 - wy)) c = rgb("#3A1A0C");
    if (wy >= 104 && wy < 106 && Math.abs(wx - 72) < 2.5) c = rgb("#FFF8E0");
    // Open cupboard: dark inside, shelves of jars, the door swung open.
    if (wx >= CUP.x0 && wx < CUP.x1 && wy >= CUP.y0 && wy < CUP.y1) {
      c = dither(ROOM, 0.08, sx, sy);
      for (const shelf of [118, 139]) {
        if (Math.abs(wy - shelf) < 0.8) c = dither(ROOM, 0.45, sx, sy);
        const slot = Math.floor((wx - CUP.x0) / 6);
        if (wy < shelf - 0.8 && wy > shelf - 9 + hash(slot, shelf, 3) * 3 && (wx - CUP.x0) % 6 > 1) c = mix(JARS[Math.floor(hash(slot, shelf, 4) * 6)], ROOM[4], 0.25);
      }
    }
    if (wx >= CUP.x1 && wx < CUP.x1 + 8 && wy >= CUP.y0 - 2 && wy < CUP.y1 + 2 - (wx - CUP.x1) * 0.4) c = dither(ROOM, 0.25, sx, sy);
    // Counter, the mug and its steam.
    if (wy >= 204) c = dither(ROOM, wy < 206 ? 0.7 : 0.18, sx, sy);
    const mug = mugAt(wx, wy, 50, 204);
    if (mug) c = mug;
    const st = steamAt(wx, wy, 53.5, 195, t);
    if (st > 0) c = mix(c, STEAM, st);
  }
  return { c: onGlass(c, wx, wy, t) };
};

// --------------------------------------------------------------- interior (close, through the glass)

const interior: View = {
  anchors: anchors({ light: [48, 52, 1], subject: [106, 150, 1], sky: [150, 40, 1], ground: [40, 262, 1] }),
  rain: 0.5,
  // The lamp's cone, swinging with the lamp.
  beam: (p) => ({ x: 48 + Math.sin(p.t * 0.9) * 2, y: 56, angle: Math.PI / 2 - 0.25 + Math.sin(p.t * 0.9) * 0.06 + p.sweep, spread: 0.5, length: 260, power: p.beam * 0.8 }),
  pixel(sx, sy, p, beam) {
    const { t, flash } = p;
    const [fx, fy] = toWorld(p.cam, sx, sy, 1.3);
    // The window frame in the foreground (left bar, sill), wet.
    if (fx < 8 || fy > 296) return flash ? SOLID_INK : { c: dither(WOOD, fx < 1 || (fy > 296 && fy < 297.5) ? 0.95 : 0.3, sx, sy), solid: true };
    const [wx, wy] = toWorld(p.cam, sx, sy, 1);
    const sway = Math.sin(t * 0.9) * 2;
    const face = bustAt(102, 132, 3.4, wx, wy, -1, 0, 0.32, true);
    if (flash) return face ? SOLID_INK : { c: FLASH_PAPER, solid: false };
    let c: RGB;
    if (face === 4) c = rgb("#CFF3FF");
    else if (face === 3) c = dither([rgb("#1E0F0C"), rgb("#3A2630"), rgb("#5A6A8A"), rgb("#9CC4E0")], smooth(46, 6, Math.hypot(wx - 143, wy - 149)), sx, sy); // lit by the phone
    else if (face === 2) c = rgb("#E08A3A");
    else if (face) c = rgb("#1E0F0C");
    else {
      c = dither(ROOM, 0.3 + smooth(110, 0, Math.hypot(wx - 48 - sway, (wy - 60) * 1.1)) * 0.65, sx, sy);
      // Lamp hanging top left.
      const lx = 48 + sway;
      if (Math.abs(wx - lx) < 0.7 && wy < 44) c = rgb("#2A1208");
      if (wy >= 44 && wy < 54 && Math.abs(wx - lx) < 13 - (54 - wy) * 1.1) c = rgb("#3A1A0C");
      if (wy >= 54 && wy < 57 && Math.abs(wx - lx) < 4) c = rgb("#FFF8E0");
      // The open cupboard behind, right.
      if (wx > 140 && wy > 30 && wy < 180) {
        c = dither(ROOM, 0.12, sx, sy);
        for (const shelf of [80, 130, 178]) {
          if (Math.abs(wy - shelf) < 1.2) c = dither(ROOM, 0.5, sx, sy);
          const slot = Math.floor((wx - 140) / 9);
          if (wy < shelf - 1.2 && wy > shelf - 16 + hash(slot, shelf, 5) * 5 && (wx - 140) % 9 > 2) c = mix(JARS[Math.floor(hash(slot, shelf, 6) * 6)], ROOM[3], 0.3);
        }
      }
      // Counter, the mug and its steam.
      if (wy >= 250) c = dither(ROOM, wy < 253 ? 0.75 : 0.15, sx, sy);
      const mug = (() => {
        const u = (wx - 30) / 2;
        const v = (wy - 250) / 2;
        return mugAt(u, v, 0, 0);
      })();
      if (mug) c = mug;
      const st = steamAt((wx - 30) / 2, (wy - 250) / 2, 3.5, -9, t);
      if (st > 0) c = mix(c, STEAM, st);
      c = lit(c, beamAt(beam, wx, wy) * 0.45, sx, sy, AMBER_HOT);
    }
    return { c: onGlass(c, fx, fy, t), solid: true };
  },
};

// ----------------------------------------------------------------------- puddle (street level)

const STREET_Y = 150;
const PW = { x0: 70, x1: 112, y0: 44, y1: 92 } as const;

const puddle: View = {
  anchors: anchors({ light: [91, 66, 1], subject: [91, 236, 1.1], sky: [150, 20, 1], ground: [60, 280, 1.1] }),
  rain: 1,
  // A car's headlights sweeping over the wet street as it passes.
  beam: (p) => {
    const cx = carX(p.t, 34, 360, -140);
    return { ...headlights(cx, STREET_Y + 2, 0.9, p.beam), angle: 0.42 + p.sweep, spread: 0.42, length: 240 };
  },
  pixel(sx, sy, p, beam) {
    const { t, flash } = p;
    const [gx, gy] = toWorld(p.cam, sx, sy, 1.1);
    if (gy >= STREET_Y) {
      const car = carAt(gx, gy, carX(t, 34, 360, -140), STREET_Y + 2, 0.9);
      if (car) return flash ? SOLID_INK : { c: car, solid: true };
      if (flash) return SOLID_INK;
      const d = gy - STREET_Y;
      // The puddle: the lit window mirrored (rows flipped about the street line), broken by the rain.
      const inPuddle = ((gx - 90) / 72) ** 2 + ((gy - 236) / 52) ** 2 < 1 + (noise(gx * 0.1, gy * 0.1, 91) - 0.5) * 0.3;
      let c = dither(STREET, 0.15 + 0.25 * noise(gx * 0.12, d * 0.3, 92) + (hash(Math.floor(gx), Math.floor(gy), 93) > 0.97 ? 0.4 : 0), sx, sy);
      if (inPuddle) {
        const wob = Math.sin(gy * 0.7 + t * 4) * 0.9 + (noise(gx * 0.3, gy * 0.5 - t * 3, 94) - 0.5) * 2;
        const mx = gx + wob;
        const my = 2 * STREET_Y - 10 - gy; // mirrored: the window's rows 44..92 land at 246..198
        c = dither(STREET, 0.35 + 0.15 * noise(gx * 0.05, gy * 0.05, 95), sx, sy);
        if (mx > PW.x0 && mx < PW.x1 && my > PW.y0 && my < PW.y1) {
          const bar = Math.abs(mx - 91) < 1 || Math.abs(my - 66) < 1;
          c = bar ? STREET[1] : dither(ROOM, 0.45 + 0.25 * noise(mx * 0.2, my * 0.2, 96), sx, sy);
        }
        const nc = neonCross(mx, my, 150, 30, 8, t);
        if (nc) c = mix(nc, STREET[2], 0.35);
        const ring = ripples(gx, gy, t, 2.5);
        if (ring > 0.45) c = mix(c, rgb("#B8C4FF"), 0.35 * ring + 0.1);
      } else if (ripples(gx, gy, t, 2.5, 97) > 0.75) c = mix(c, rgb("#6A74B0"), 0.4);
      return { c: lit(c, beamAt(beam, gx, gy) * 1.1, sx, sy, rgb("#FFF6DA"), rgb("#E9DDB0")), solid: true };
    }
    // Above the street: the building's base rising, the lit window, the neon cross.
    const [wx, wy] = toWorld(p.cam, sx, sy, 1);
    if (wx > PW.x0 && wx < PW.x1 && wy > PW.y0 && wy < PW.y1) {
      const bar = Math.abs(wx - 91) < 1 || Math.abs(wy - 66) < 1;
      if (flash) return bar ? SOLID_INK : { c: FLASH_PAPER, solid: false };
      const f = figureAt(standPose(0.8), 98, PW.y1, 1.2, wx, wy, -1, 0);
      return { c: bar ? WOOD[0] : f ? rgb("#2A1410") : dither(ROOM, 0.5 + smooth(18, 0, Math.hypot(wx - 84, wy - 62)) * 0.45, sx, sy), solid: true };
    }
    const nc = neonCross(wx, wy, 150, 30, 8, t);
    if (nc) return flash ? SOLID_INK : { c: nc, solid: true };
    if (wy > 6) {
      if (flash) return SOLID_INK;
      // A doorway at street level, the wall.
      if (wx > 20 && wx < 44 && wy > 104) return { c: dither(GLASS, 0.1, sx, sy), solid: true };
      let c = bricks(wx, wy, sx, sy, t, smooth(40, 0, Math.max(0, Math.max(PW.x0 - wx, wx - PW.x1, PW.y0 - wy, wy - PW.y1))) * 0.7);
      const g = neonGlow(wx, wy, 150, 30, 8);
      if (g > 0) c = mix(c, NEON_GLOW, g);
      return { c: lit(c, beamAt(beam, wx, wy) * 0.7, sx, sy), solid: true };
    }
    if (flash) return { c: FLASH_PAPER, solid: false };
    return { c: nightSky(wx, wy, sx, sy, t, 33), solid: false };
  },
};

export const WINDOW_VIEWS = { block, facade, interior, puddle } as const;
