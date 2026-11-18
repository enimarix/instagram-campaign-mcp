// Renders the brand kit's PNGs (step 050) in Remotion's headless Chrome, for the ffmpeg ops
// (the local ffmpeg reads neither SVG nor WOFF2): brand/logo.png from brand/logo.svg, and
// brand/wordmark.png, the brand name in the display font with the part from its second
// capital in emerald ("macro" + "Body"), kerned like the owner's own videos draw it.
// Run from motion/ after editing logo.svg, the name, the colours or the fonts:
//   node scripts/brand-images.mjs
import { openBrowser } from "@remotion/renderer";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const brandDir = join(root, "brand");
const brand = JSON.parse(readFileSync(join(brandDir, "brand.json"), "utf8"));

const WORDMARK_PX = 112; // font size; = EndCard wordmark size in src/studio/recipe.py
const LOGO_PX = 512;
const fontData = (file) => readFileSync(join(root, "motion", "public", "fonts", file)).toString("base64");

const browser = await openBrowser("chrome", { logLevel: "error" });
const page = await browser.newPage({
  context: () => null, logLevel: "error", indent: false, pageIndex: 0, onBrowserLog: null, onLog: () => {},
});

const png = (dataUrl) => Buffer.from(dataUrl.split(",")[1], "base64");

const logo = await page.evaluate(async (svg, size) => {
  const img = new Image();
  img.src = `data:image/svg+xml;base64,${btoa(svg)}`;
  await img.decode();
  const c = document.createElement("canvas");
  c.width = c.height = size;
  c.getContext("2d").drawImage(img, 0, 0, size, size);
  return c.toDataURL("image/png");
}, readFileSync(join(brandDir, brand.logo), "utf8"), LOGO_PX);
writeFileSync(join(brandDir, "logo.png"), png(logo));

const name = brand.name;
const cut = [...name].findIndex((c, i) => i > 0 && c !== c.toLowerCase());
const parts = cut > 0 ? [name.slice(0, cut), name.slice(cut)] : [name, ""];
const wordmark = await page.evaluate(
  async (family, weight, fonts, parts, colors, px) => {
    for (const data of fonts) {
      const face = new FontFace(family, `url(data:font/woff2;base64,${data})`, { weight: "100 900" });
      document.fonts.add(await face.load());
    }
    const c = document.createElement("canvas");
    const ctx = c.getContext("2d");
    const font = `${weight} ${px}px "${family}"`;
    ctx.font = font;
    const m = ctx.measureText(parts.join(""));
    const pad = Math.ceil(px * 0.05);
    const asc = Math.ceil(m.fontBoundingBoxAscent), desc = Math.ceil(m.fontBoundingBoxDescent);
    c.width = Math.ceil(m.actualBoundingBoxLeft + m.actualBoundingBoxRight) + 2 * pad;
    c.height = asc + desc;
    ctx.font = font;
    ctx.textBaseline = "alphabetic";
    // The whole name is measured kerned; the second part starts where the first ends in it.
    const x0 = pad + m.actualBoundingBoxLeft;
    ctx.fillStyle = colors[0];
    ctx.fillText(parts[0], x0, asc);
    ctx.fillStyle = colors[1];
    ctx.fillText(parts[1], x0 + ctx.measureText(parts[0]).width, asc);
    return c.toDataURL("image/png");
  },
  brand.fonts.display, brand.fonts.display_weight,
  [fontData("inter-tight-latin.woff2"), fontData("inter-tight-latin-ext.woff2")],
  parts, [brand.colors.light.ink, brand.colors.brand], WORDMARK_PX,
);
writeFileSync(join(brandDir, "wordmark.png"), png(wordmark));
await browser.close({ silent: true });
console.log("wrote brand/logo.png, brand/wordmark.png");
