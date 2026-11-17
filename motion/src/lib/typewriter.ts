// Typewriter maths, pure (no imports) so `node --test` runs it directly (test/typewriter.test.ts).

/**
 * Characters shown at `frame` when `total` characters type at `speed` chars/s from `startFrame`.
 * No speed (undefined or 0) shows everything at `startFrame`. Nothing shows before it.
 */
export const visibleChars = (
  frame: number,
  total: number,
  fps: number,
  speed?: number,
  startFrame = 0,
): number => {
  if (frame < startFrame) return 0;
  if (!speed) return total;
  // The epsilon keeps float noise (200 frames at 2.55 chars/s = 16.999…) from dropping a character.
  return Math.min(total, Math.floor(((frame - startFrame) * speed) / fps + 1e-9));
};

/**
 * Wrap `text` into lines of at most `cols` characters (code points), breaking at spaces;
 * a word longer than a line is cut. "\n" forces a break. `cols` = Infinity keeps lines whole.
 */
export const wrap = (text: string, cols: number): string[] => {
  const len = (s: string) => Array.from(s).length;
  const lines: string[] = [];
  for (const para of text.split("\n")) {
    let line = "";
    for (let word of para.split(/ +/)) {
      while (len(word) > cols) {
        if (line) lines.push(line);
        const chars = Array.from(word);
        lines.push(chars.slice(0, cols).join(""));
        word = chars.slice(cols).join("");
        line = "";
      }
      if (!word) continue;
      if (!line) line = word;
      else if (len(line) + 1 + len(word) <= cols) line += ` ${word}`;
      else {
        lines.push(line);
        line = word;
      }
    }
    lines.push(line);
  }
  return lines;
};
