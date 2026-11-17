// Crisp 8-bit pixels: whole-number scales, whole-pixel positions, no smoothing.
import type { CSSProperties } from "react";

/** Design size of the pixel font: Press Start 2P is drawn on an 8x8 grid. */
export const FONT_PX = 8;

/** Empty font pixels between two text lines. */
export const LINE_GAP = 4;

/** Nearest whole scale, at least 1. */
export const intScale = (scale: number) => Math.max(1, Math.round(scale));

/** Largest whole scale at which `size` still fits in `room` (at least 1). */
export const fitScale = (size: number, room: number) => Math.max(1, Math.floor(room / size));

/** Snap a position or length to a grid of `unit` px (1 = whole pixels). */
export const snap = (v: number, unit = 1) => Math.round(v / unit) * unit;

/** Font size in px: a whole multiple of the font's design size. */
export const fontPx = (scale: number) => FONT_PX * intScale(scale);

/** Line height in px for text at `scale`. */
export const linePx = (scale: number) => (FONT_PX + LINE_GAP) * intScale(scale);

/** No smoothing when a bitmap (sprite, canvas) is scaled up. */
export const crisp: CSSProperties = { imageRendering: "pixelated" };

/**
 * Largest whole scale, at most `max`, at which a text fits `width` x `height`;
 * `lineCount(cols)` says how many lines the text wraps to in `cols` columns.
 */
export const fitTextScale = (lineCount: (cols: number) => number, width: number, height: number, max: number) => {
  for (let s = intScale(max); s > 1; s--) {
    if (lineCount(Math.max(1, Math.floor(width / fontPx(s)))) * linePx(s) <= height) return s;
  }
  return 1;
};
