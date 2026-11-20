// The cutaway style's pixel type (step 142): a 5x7 capitals bitmap font drawn in code, so
// every letter sits on the same pixel grid as the art and French accents get their own rows
// above the capital (Press Start 2P squeezes É into the 8x8 cell). Regular for the small
// labels, bold (every stroke one pixel wider) for the titles. Lower case is drawn in capitals,
// like a game HUD. Pure, so `node --test` runs it (test/cutaway.test.ts).
import { frenchSpaces } from "../lib/french.ts";

/** Rows of "#" (on) and "." (off), top to bottom; the glyph is as wide as its rows. */
const G: Record<string, string> = {
  A: ".###. #...# #...# ##### #...# #...# #...#",
  B: "####. #...# #...# ####. #...# #...# ####.",
  C: ".###. #...# #.... #.... #.... #...# .###.",
  D: "####. #...# #...# #...# #...# #...# ####.",
  E: "##### #.... #.... ####. #.... #.... #####",
  F: "##### #.... #.... ####. #.... #.... #....",
  G: ".###. #...# #.... #.### #...# #...# .####",
  H: "#...# #...# #...# ##### #...# #...# #...#",
  I: "### .#. .#. .#. .#. .#. ###",
  J: "..### ...#. ...#. ...#. #..#. #..#. .##..",
  K: "#...# #..#. #.#.. ##... #.#.. #..#. #...#",
  L: "#.... #.... #.... #.... #.... #.... #####",
  M: "#...# ##.## #.#.# #.#.# #...# #...# #...#",
  N: "#...# #...# ##..# #.#.# #..## #...# #...#",
  O: ".###. #...# #...# #...# #...# #...# .###.",
  P: "####. #...# #...# ####. #.... #.... #....",
  Q: ".###. #...# #...# #...# #.#.# #..#. .##.#",
  R: "####. #...# #...# ####. #.#.. #..#. #...#",
  S: ".#### #.... #.... .###. ....# ....# ####.",
  T: "##### ..#.. ..#.. ..#.. ..#.. ..#.. ..#..",
  U: "#...# #...# #...# #...# #...# #...# .###.",
  V: "#...# #...# #...# #...# #...# .#.#. ..#..",
  W: "#...# #...# #...# #.#.# #.#.# #.#.# .#.#.",
  X: "#...# #...# .#.#. ..#.. .#.#. #...# #...#",
  Y: "#...# #...# .#.#. ..#.. ..#.. ..#.. ..#..",
  Z: "##### ....# ...#. ..#.. .#... #.... #####",
  "0": ".###. #...# #..## #.#.# ##..# #...# .###.",
  "1": "..#.. .##.. ..#.. ..#.. ..#.. ..#.. .###.",
  "2": ".###. #...# ....# ...#. ..#.. .#... #####",
  "3": "##### ...#. ..#.. ...#. ....# #...# .###.",
  "4": "...#. ..##. .#.#. #..#. ##### ...#. ...#.",
  "5": "##### #.... ####. ....# ....# #...# .###.",
  "6": "..##. .#... #.... ####. #...# #...# .###.",
  "7": "##### ....# ...#. ..#.. .#... .#... .#...",
  "8": ".###. #...# #...# .###. #...# #...# .###.",
  "9": ".###. #...# #...# .#### ....# ...#. .##..",
  " ": "... ... ... ... ... ... ...",
  ".": ". . . . . . #",
  ",": ".. .. .. .. .. .# #.",
  ":": ". # . . . # .",
  ";": ".. .# .. .. .. .# #.",
  "!": "# # # # # . #",
  "?": ".###. #...# ....# ...#. ..#.. ..... ..#..",
  "-": ".... .... .... #### .... .... ....",
  "+": "..... ..#.. ..#.. ##### ..#.. ..#.. .....",
  "=": ".... .... #### .... #### .... ....",
  "/": "....# ....# ...#. ..#.. .#... #.... #....",
  "%": "##..# ##..# ...#. ..#.. .#... #..## #..##",
  "×": "..... #...# .#.#. ..#.. .#.#. #...# .....",
  "(": "..# .#. #.. #.. #.. .#. ..#",
  ")": "#.. .#. ..# ..# ..# .#. #..",
  "'": "# # . . . . .",
  '"': "#.# #.# ... ... ... ... ...",
  "«": "..... ..#.# .#.#. #.#.. .#.#. ..#.# .....",
  "»": "..... #.#.. .#.#. ..#.# .#.#. #.#.. .....",
  "°": ".#. #.# .#. ... ... ... ...",
  "<": ".... ...# ..#. .#.. ..#. ...# ....",
  ">": ".... #... .#.. ..#. .#.. #... ....",
  "▶": "#... ##.. ###. #### ###. ##.. #...",
  "‖": "#.# #.# #.# #.# #.# #.# #.#",
  "₂": "... ... ### ..# ### #.. ###",
  "²": "##. ..# .#. ### ... ... ...",
  "→": "..... ..#.. ...#. ##### ...#. ..#.. .....",
  "←": "..... ..#.. .#... ##### .#... ..#.. .....",
  "~": "..... ..... .#... #.#.# ...#. ..... .....",
  "≈": "..... .#... #.#.# ...#. .#... #.#.# ...#.",
  "€": "..### .#... ####. .#... ####. .#... ..###",
  "÷": "..... ..#.. ..... ##### ..... ..#.. .....",
  "&": ".##.. #..#. #.#.. .#... #.#.# #..#. .##.#",
  "*": "..... #.#.# .###. ##### .###. #.#.# .....",
  "#": ".#.#. .#.#. ##### .#.#. ##### .#.#. .#.#.",
  "@": ".###. #...# #.### #.#.# #.### #.... .####",
  _: "..... ..... ..... ..... ..... ..... #####",
};

/** Marks of decomposed letters (NFD): rows drawn above the capital (cedilla: below). */
const MARKS: Record<string, string> = {
  "́": "...#. ..#..", // acute
  "̀": ".#... ..#..", // grave
  "̂": "..#.. .#.#.", // circumflex
  "̈": "..... .#.#.", // diaeresis
  "̃": ".##.# #.##.", // tilde
};
const CEDILLA = "..#.. .##..";

/** Letters spelled out (no glyph of their own). */
const SPELL: Record<string, string> = { Œ: "OE", Æ: "AE", "’": "'", "‘": "'", "“": '"', "”": '"', "−": "-", "…": "...", " ": " ", " ": " ", "–": "-", "—": "-", "·": "." };

const rows = (s: string) => s.split(" ");

/** Glyph rows by character, -3..8 (0..6 = the capital, -3..-2 accent, 7..8 cedilla). */
type Bitmap = { width: number; on: [x: number, y: number][] };
const cache = new Map<string, Bitmap>();

const bitmapOf = (ch: string): Bitmap => {
  const hit = cache.get(ch);
  if (hit) return hit;
  const [base, ...marks] = Array.from(ch.normalize("NFD"));
  const glyph = rows(G[base] ?? G["?"]);
  const width = glyph[0].length;
  const on: [number, number][] = [];
  glyph.forEach((r, y) => Array.from(r).forEach((c, x) => c === "#" && on.push([x, y])));
  for (const m of marks) {
    const mark = m === "̧" ? rows(CEDILLA) : MARKS[m] ? rows(MARKS[m]) : null;
    if (!mark) continue;
    const dx = Math.floor((width - 5) / 2);
    const top = m === "̧" ? 7 : -3;
    mark.forEach((r, y) => Array.from(r).forEach((c, x) => c === "#" && on.push([x + dx, y + top])));
  }
  const b = { width, on };
  cache.set(ch, b);
  return b;
};

/** The characters of `text` this font has no glyph for (they would draw as « ? »); [] = all drawable. */
export const missingGlyphs = (text: string) =>
  [...new Set(glyphText(text))].filter((c) => {
    const [base, ...marks] = Array.from(c.normalize("NFD"));
    return !G[base] || marks.some((m) => m !== "̧" && !MARKS[m]);
  });

/** The characters actually drawn: capitals, spelled-out ligatures, unknown -> "?". */
export const glyphText = (text: string) =>
  Array.from(text.normalize("NFC").toUpperCase())
    .map((c) => SPELL[c] ?? c)
    .join("");

/** Width in font pixels of one line (1 pixel between letters; bold letters are 1 wider). */
export const lineWidth = (line: string, bold = false) => {
  const chars = Array.from(glyphText(line));
  return chars.reduce((w, c) => w + bitmapOf(c).width + (bold ? 1 : 0), 0) + Math.max(0, chars.length - 1);
};

/** Capital height, and the pitch from one line to the next, in font pixels. */
export const CAP = 7;
export const LINE_PITCH = 11;

/**
 * Greedy word wrap of `text` into lines at most `maxWidth` font pixels wide ("\n" forces a
 * break). French spacing first, so « ? » never starts a line alone.
 */
export const wrapText = (text: string, maxWidth: number, bold = false): string[] =>
  frenchSpaces(text).split("\n").flatMap((para) => {
    const lines: string[] = [];
    let line = "";
    for (const word of para.split(/ +/).filter(Boolean)) {
      const next = line ? `${line} ${word}` : word;
      if (line && lineWidth(next, bold) > maxWidth) {
        lines.push(line);
        line = word;
      } else line = next;
    }
    return [...lines, line];
  });

/**
 * SVG path of `line` with its top-left capital corner at (x, y), `unit` px per font pixel:
 * one rectangle per horizontal run of lit pixels.
 */
export const linePath = (line: string, x: number, y: number, unit: number, bold = false): string => {
  const lit = new Set<string>();
  let cx = 0;
  for (const c of Array.from(glyphText(line))) {
    const b = bitmapOf(c);
    for (const [gx, gy] of b.on) {
      lit.add(`${cx + gx},${gy}`);
      if (bold) lit.add(`${cx + gx + 1},${gy}`);
    }
    cx += b.width + (bold ? 1 : 0) + 1;
  }
  const byRow = new Map<number, number[]>();
  for (const k of lit) {
    const [px, py] = k.split(",").map(Number);
    byRow.set(py, [...(byRow.get(py) ?? []), px]);
  }
  let d = "";
  for (const [py, xs] of byRow) {
    xs.sort((a, b) => a - b);
    for (let i = 0; i < xs.length; ) {
      let j = i;
      while (j + 1 < xs.length && xs[j + 1] === xs[j] + 1) j++;
      d += `M${x + xs[i] * unit} ${y + py * unit}h${(j - i + 1) * unit}v${unit}h${-(j - i + 1) * unit}z`;
      i = j + 1;
    }
  }
  return d;
};

/** Largest unit in [min, max] at which `text` wraps into at most `maxLines` lines of `width` px. */
export const fitUnit = (text: string, width: number, maxLines: number, max: number, min: number, bold = false) => {
  for (let u = max; u > min; u--) if (wrapText(text, Math.floor(width / u), bold).length <= maxLines) return u;
  return min;
};
