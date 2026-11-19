// Cutaway HUD layout (step 142): where the title box, its lines and the steps row go, and the
// gauge's number easing from one value to the next. Pure, so `node --test` runs it.
import { CAP, fitUnit, LINE_PITCH, lineWidth, wrapText } from "../../cutaway/pixelfont.ts";
import type { SceneProps } from "./schema.ts";

/** Top of the title box (under the mode chip, inside the safe area). */
export const TITLE_Y = 360;
/** Widest text in the title box, px. */
const TEXT_W = 800;

export type TitleLine = { text: string; unit: number; y: number; color: "white" | "yellow" };
export type BoxLayout = { x: number; y: number; w: number; h: number; lines: TitleLine[] };

/**
 * The framed title: `big` (hook, payoff) = up to 3 lines of large type, white and yellow in
 * turn, with the sub in a small box of its own under it; a beat = a smaller title and its sub
 * (yellow) in one box. Returns the boxes and the y under the last one.
 */
export const titleLayout = (s: Pick<SceneProps, "title" | "sub">, big: boolean) => {
  const unit = big ? fitUnit(s.title, TEXT_W, 3, 8, 5, true) : fitUnit(s.title, TEXT_W, 2, 6, 4, true);
  const subUnit = s.sub ? fitUnit(s.sub, TEXT_W, 2, 4, 3, true) : 0;
  const titleLines = wrapText(s.title, Math.floor(TEXT_W / unit), true);
  const subLines = s.sub ? wrapText(s.sub, Math.floor(TEXT_W / subUnit), true) : [];
  const pad = 22;
  const lines: TitleLine[] = [];
  let y = TITLE_Y + pad;
  titleLines.forEach((text, i) => {
    lines.push({ text, unit, y, color: big && i % 2 ? "yellow" : "white" });
    y += (i + 1 < titleLines.length ? LINE_PITCH : CAP) * unit;
  });
  const widest = (ls: string[], u: number) => Math.max(0, ...ls.map((l) => lineWidth(l, true) * u));
  const boxes: BoxLayout[] = [];
  if (big || !subLines.length) {
    const w = widest(titleLines, unit) + 2 * pad + 8;
    boxes.push({ x: 540 - w / 2, y: TITLE_Y, w, h: y + pad - TITLE_Y, lines });
    if (subLines.length) {
      const top = y + pad + 18;
      const sub: TitleLine[] = subLines.map((text, i) => ({ text, unit: subUnit, y: top + 14 + i * LINE_PITCH * subUnit, color: "yellow" }));
      const sw = widest(subLines, subUnit) + 36;
      boxes.push({ x: 540 - sw / 2, y: top, w: sw, h: 28 + ((subLines.length - 1) * LINE_PITCH + CAP) * subUnit, lines: sub });
    }
  } else {
    y += 16;
    subLines.forEach((text, i) => {
      lines.push({ text, unit: subUnit, y, color: "yellow" });
      y += (i + 1 < subLines.length ? LINE_PITCH : CAP) * subUnit;
    });
    const w = Math.max(widest(titleLines, unit), widest(subLines, subUnit)) + 2 * pad + 8;
    boxes.push({ x: 540 - w / 2, y: TITLE_Y, w, h: y + pad - TITLE_Y, lines });
  }
  const last = boxes[boxes.length - 1];
  return { boxes, bottom: last.y + last.h };
};

/** The steps row: unit and item widths that fit 860 px. */
export const stepsLayout = (items: string[]) => {
  const width = (u: number) => items.reduce((w, t) => w + lineWidth(t, true) * u + 4 * u + 8, 0) + (items.length - 1) * 12;
  const unit = width(3) <= 860 ? 3 : 2;
  return { unit, width: width(unit), item: (t: string) => lineWidth(t, true) * unit + 4 * unit + 8 };
};

const NUM = /\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?/;
const parse = (s: string) => {
  const m = NUM.exec(s);
  if (!m) return null;
  const dec = /[.,](\d+)$/.exec(m[0]);
  const whole = dec ? m[0].slice(0, dec.index) : m[0];
  return { m, value: Number(whole.replace(/\D/g, "") + (dec ? `.${dec[1]}` : "")), decimals: dec ? dec[1].length : 0, mark: dec ? m[0][dec.index] : "," };
};

/**
 * `to` with its first number eased from `from`'s at `t` (0..1), with `to`'s decimals, French
 * grouping from 1 000: the gauge counting « 2 400 » down to « 28,6 ».
 */
export const lerpText = (from: string | undefined, to: string, t: number) => {
  const a = from === undefined ? null : parse(from);
  const b = parse(to);
  if (!a || !b || t >= 1) return to;
  const v = a.value + (b.value - a.value) * Math.max(0, t);
  const [i, d] = v.toFixed(b.decimals).split(".");
  const grouped = i.replace(/\B(?=(\d{3})+$)/g, " ");
  return to.slice(0, b.m.index) + (d ? `${grouped}${b.mark}${d}` : grouped) + to.slice(b.m.index + b.m[0].length);
};
