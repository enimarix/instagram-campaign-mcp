// Loads the brand's pixel font once per bundle (@remotion/fonts holds the render until it is in).
import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";
import { brand } from "../brand";

// brand.json lists font files relative to itself; motion serves them from motion/public/.
const PUBLIC = "../motion/public/";
const [file] = brand.fonts.files;
if (!file?.startsWith(PUBLIC)) {
  throw new Error(`brand.json fonts.files[0] must be a file under ${PUBLIC}, got ${file}`);
}

// ponytail: one file, loaded as the display family (= body today); map files to families
// when the brand gets a second font.
export const fontFamily = brand.fonts.display;

void loadFont({ family: fontFamily, url: staticFile(file.slice(PUBLIC.length)) });
