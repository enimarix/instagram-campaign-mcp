// Loads every font in public/fonts once per bundle (@remotion/fonts holds the render until
// they are in; the files per family: faces.ts). Templates choose: the brand's display/body
// families or the 8-bit pixel font.
import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";
import { brand } from "../brand";
import { FAMILIES, SYMBOLS_FILE } from "./faces";

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
  /** The editorial style's key words (step 144): Instrument Serif Italic. */
  serif: "Instrument Serif",
};

for (const [key, { faces, symbols }] of Object.entries(FAMILIES)) {
  const family = fonts[key as keyof typeof FAMILIES];
  const { weight, style } = faces[0];
  for (const f of [...faces, { file: SYMBOLS_FILE, unicodeRange: symbols, weight, style }]) {
    void loadFont({ family, url: staticFile(f.file), weight: f.weight, style: f.style, unicodeRange: f.unicodeRange });
  }
}
