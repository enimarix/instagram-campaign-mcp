// Loads every font in public/fonts once per bundle (@remotion/fonts holds the render until
// they are in). Templates choose: the brand's display/body families or the 8-bit pixel font.
import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";
import { brand } from "../brand";

// unicode-range of the Latin and Latin Extended subsets (= the owner's website fonts.css).
const LATIN =
  "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD";
const LATIN_EXT =
  "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF";

export const fonts = {
  /** Brand headlines: Inter Tight, use at `displayWeight` (900) with tight tracking. */
  display: brand.fonts.display,
  displayWeight: brand.fonts.display_weight,
  /** Brand body text: Inter (variable, 100-900). */
  body: brand.fonts.body,
  /** The 8-bit templates' pixel font. Design size 8 px: use whole multiples. */
  pixel: "Press Start 2P",
  /** The paper style (step 131, the owner's house style): Fredoka labels (variable, 300-700). */
  paper: "Fredoka",
  /** The paper style's handwriting for asides: Caveat (variable, 400-700). */
  hand: "Caveat",
};

const FACES = [
  { family: fonts.display, file: "fonts/inter-tight-latin.woff2", unicodeRange: LATIN, weight: "100 900" },
  { family: fonts.display, file: "fonts/inter-tight-latin-ext.woff2", unicodeRange: LATIN_EXT, weight: "100 900" },
  { family: fonts.body, file: "fonts/inter-latin.woff2", unicodeRange: LATIN, weight: "100 900" },
  { family: fonts.body, file: "fonts/inter-latin-ext.woff2", unicodeRange: LATIN_EXT, weight: "100 900" },
  { family: fonts.paper, file: "fonts/fredoka-latin.woff2", unicodeRange: LATIN, weight: "300 700" },
  { family: fonts.paper, file: "fonts/fredoka-latin-ext.woff2", unicodeRange: LATIN_EXT, weight: "300 700" },
  { family: fonts.hand, file: "fonts/caveat-latin.woff2", unicodeRange: LATIN, weight: "400 700" },
  { family: fonts.hand, file: "fonts/caveat-latin-ext.woff2", unicodeRange: LATIN_EXT, weight: "400 700" },
];

for (const f of FACES) {
  void loadFont({ family: f.family, url: staticFile(f.file), weight: f.weight, unicodeRange: f.unicodeRange });
}
void loadFont({ family: fonts.pixel, url: staticFile("fonts/PressStart2P-Regular.ttf") });
