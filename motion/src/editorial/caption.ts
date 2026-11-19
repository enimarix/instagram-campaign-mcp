// The anatomy cards' pixel captions (step 144): 142's 5x7 bitmap font (src/cutaway/pixelfont.ts),
// which draws French accents above the capitals (« APRÈS LA SÉANCE »). Pure, so `node --test`
// checks it (test/editorial.test.ts).
import { fitUnit, wrapText } from "../cutaway/pixelfont.ts";
import { frenchSpaces } from "../lib/french.ts";

/** French spacing, and a number kept with the word after it (« 72 h », « 20 minutes »). */
export const glue = (text: string) => frenchSpaces(text).replace(/(\d) (?=\p{L})/gu, "$1 ");

/** A wrapped caption line and the part of it to draw in yellow ([start, end) in the line, or null). */
export type CaptionLine = { text: string; mark: [number, number] | null };

/**
 * The caption at the largest font unit (4..7 px per font pixel) that fits `width` px in at most
 * 4 lines (bold), wrapped, each line with its share of `highlight` (case-insensitive).
 */
export const captionLines = (caption: string, highlight: string | undefined, width: number) => {
  const text = glue(caption);
  const unit = fitUnit(text, width, 4, 7, 4, true);
  const lines = wrapText(text, Math.floor(width / unit), true);
  const at = highlight ? text.toUpperCase().indexOf(glue(highlight).toUpperCase()) : -1;
  const end = at + (highlight ? glue(highlight).length : 0);
  let pos = 0;
  const out: CaptionLine[] = lines.map((line) => {
    const start = text.indexOf(line, pos);
    pos = start + line.length;
    const a = Math.max(at, start);
    const b = Math.min(end, start + line.length);
    return { text: line, mark: at >= 0 && a < b ? [a - start, b - start] : null };
  });
  return { unit, lines: out };
};
