// The font files behind each template family and the characters each file draws (its
// unicode-range): font.ts loads them, test/glyphs.test.ts checks that every character the
// scripts use is drawable in every family (step 162: « → » and « ~ » came out as « ? »).
// Pure (no imports) so `node --test` reads it.

// unicode-range of the Latin and Latin Extended subsets (= the owner's website fonts.css).
export const LATIN =
  "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD";
export const LATIN_EXT =
  "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF";

/** The symbols file (Inter, subset): every family's fallback for the symbols its own files lack. */
export const SYMBOLS_FILE = "fonts/inter-symbols.woff2";

export type Face = { file: string; unicodeRange?: string; weight?: string; style?: string };
export type Family = {
  faces: Face[];
  /**
   * The symbols this family draws from SYMBOLS_FILE: only ones its own faces lack, so which
   * face draws a character never depends on the order the faces finish loading.
   */
  symbols: string;
};

/** Superscripts / subscripts, arrows, ≈ ≠ ≤ ≥: outside the Latin subsets' ranges. */
const LATIN_SYMBOLS = "U+2070-209C, U+2190, U+2192, U+2194-2199, U+2248, U+2260, U+2264-2265";
const subsets = (name: string, weight: string): Face[] => [
  { file: `fonts/${name}-latin.woff2`, unicodeRange: LATIN, weight },
  { file: `fonts/${name}-latin-ext.woff2`, unicodeRange: LATIN_EXT, weight },
];

/** By key of `fonts` (font.ts). */
export const FAMILIES: Record<"display" | "body" | "paper" | "hand" | "serif" | "pixel", Family> = {
  display: { faces: subsets("inter-tight", "100 900"), symbols: LATIN_SYMBOLS },
  body: { faces: subsets("inter", "100 900"), symbols: LATIN_SYMBOLS },
  paper: { faces: subsets("fredoka", "300 700"), symbols: LATIN_SYMBOLS },
  hand: { faces: subsets("caveat", "400 700"), symbols: LATIN_SYMBOLS },
  serif: { faces: [{ file: "fonts/InstrumentSerif-Italic.ttf", style: "italic" }], symbols: "U+00B2-00B3, U+00B9, U+2070-209C, U+2190-2199, U+2248, U+2260, U+2264-2265" },
  pixel: { faces: [{ file: "fonts/PressStart2P-Regular.ttf" }], symbols: "U+2070-2071, U+2075-209C, U+2194-2199, U+2212" },
};
