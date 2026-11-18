// Game-kit maths, pure (no imports) so `node --test` runs it directly (test/game.test.ts).

/**
 * Pixel art drawn in code: each frame is a list of equal-length rows, one character per
 * pixel; "." is transparent, any other character is a key of `colors` (an 8-bit palette index, src/lib/palette.ts).
 */
export type PixelArt = { frames: string[][]; colors: Record<string, number> };

/** 0 before `start`, 1 from `start + duration`, linear in between. */
export const progress = (frame: number, start: number, duration: number): number =>
  duration <= 0 ? (frame >= start ? 1 : 0) : Math.min(1, Math.max(0, (frame - start) / duration));

/**
 * Sheet frame shown at `frame` when a `frames`-frame animation plays at `rate` frames/s from
 * `startFrame` (video at `fps`). `loop` wraps around, otherwise it holds the last frame.
 */
export const spriteFrame = (
  frame: number,
  fps: number,
  frames: number,
  rate: number,
  loop = true,
  startFrame = 0,
): number => {
  if (frames <= 1 || !(rate > 0) || frame < startFrame) return 0;
  // Same float guard as typewriter.visibleChars.
  const i = Math.floor(((frame - startFrame) * rate) / fps + 1e-9);
  return loop ? i % frames : Math.min(i, frames - 1);
};

/**
 * The covered part [from, to] (0..1 along the wipe's direction) at wipe progress `p`:
 * the leading edge crosses the screen in the first half, the trailing edge in the second.
 */
export const wipeSpan = (p: number): [number, number] => [Math.max(0, 2 * p - 1), Math.min(1, 2 * p)];

/** Flash opacity: full at `start`, fading to 0 over `duration` in `steps` hard steps (8-bit). */
export const flashOpacity = (frame: number, start: number, duration: number, steps = 4): number => {
  const p = progress(frame, start, duration);
  return frame < start || p >= 1 ? 0 : Math.ceil((1 - p) * steps) / steps;
};

/**
 * Reproducible noise in [0, 1) for (seed, n): a 32-bit integer hash, no state, so frame n
 * gives the same value in every render, on every machine. Inputs are truncated to integers.
 */
export const seeded = (seed: number, n: number): number => {
  let t = (Math.imul(seed | 0, 0x9e3779b1) ^ Math.imul(n | 0, 0x85ebca6b)) >>> 0;
  t = Math.imul(t ^ (t >>> 16), 0x7feb352d);
  t = Math.imul(t ^ (t >>> 15), 0x846ca68b);
  return ((t ^ (t >>> 16)) >>> 0) / 4294967296;
};

/** Score as `digits` digits with leading zeros, clamped to 0..99…9. */
export const padScore = (score: number, digits: number): string =>
  String(Math.min(10 ** digits - 1, Math.max(0, Math.floor(score)))).padStart(digits, "0");

/** Filled cells of a `cells`-cell bar at `level` (0..1, clamped). */
export const barCells = (level: number, cells: number): number =>
  Math.round(Math.min(1, Math.max(0, level || 0)) * cells);

/**
 * An SVG sprite sheet of `art`: frames side by side, one SVG unit per pixel, `palette`
 * resolving the colour indices. Rows of one rect per run of equal pixels.
 */
export const sheetSvg = (art: PixelArt, palette: readonly string[]): string => {
  const h = art.frames[0].length;
  const w = art.frames[0][0].length;
  const rects: string[] = [];
  art.frames.forEach((rows, f) =>
    rows.forEach((row, y) => {
      for (let x = 0; x < row.length; ) {
        const c = row[x];
        let end = x + 1;
        while (row[end] === c) end++;
        if (c !== ".") {
          rects.push(`<rect x="${f * w + x}" y="${y}" width="${end - x}" height="1" fill="${palette[art.colors[c]]}"/>`);
        }
        x = end;
      }
    }),
  );
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w * art.frames.length}" height="${h}" ` +
    `shape-rendering="crispEdges">${rects.join("")}</svg>`
  );
};
