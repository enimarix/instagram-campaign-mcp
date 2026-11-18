// Voxel palette: colour name -> sRGB hex. Hard-coded here, not read from brand/brand.json
// (step 129 brief: the brand pass 050 changes brand files in parallel). Pure, no imports.

/** Mix two #rrggbb colours: t = 0 gives a, 1 gives b. */
export const mix = (a: string, b: string, t: number): string => {
  const ca = parseInt(a.slice(1), 16);
  const cb = parseInt(b.slice(1), 16);
  let out = 0;
  for (const shift of [16, 8, 0]) {
    const va = (ca >> shift) & 255;
    const vb = (cb >> shift) & 255;
    out |= Math.round(va + (vb - va) * t) << shift;
  }
  return `#${out.toString(16).padStart(6, "0")}`;
};

const INK = "#111827";
const WHITE = "#FFFFFF";

/** The golem's six level forms, in level order (the app's colours). */
export const FORMS = [
  { id: "etincelle", name: "Étincelle", hex: "#6FB4FF" },
  { id: "recrue", name: "Recrue", hex: "#57D9BC" },
  { id: "combattant", name: "Combattant", hex: "#7CE493" },
  { id: "guerrier", name: "Guerrier", hex: "#FFD96E" },
  { id: "champion", name: "Champion", hex: "#FF9A5A" },
  { id: "titan", name: "Titan", hex: "#C593FF" },
] as const;

export type FormId = (typeof FORMS)[number]["id"];

const BASE = {
  // macroBody brand colours.
  emerald: "#10B981",
  emeraldLight: "#34D399",
  kcal: "#3E8EF7",
  protein: "#FF6F61",
  fat: "#F5C242",
  fatDark: "#C99A2A",
  carbs: "#3FBF7F",
  violet: "#A78BFA",
  ink: INK,
  offWhite: "#F5F7F8",
  // Neutrals.
  white: WHITE,
  grey100: "#E5E7EB",
  grey300: "#C4C9D1",
  grey500: "#8B93A1",
  grey700: "#4B5563",
  slate: "#2A3343",
  // Skin, wood, food.
  skin: "#F1C9A5",
  skinShade: "#D9A47E",
  woodLight: "#C8955C",
  wood: "#9C6B3E",
  woodDark: "#6B4527",
  roast: "#B8642B",
  roastLight: "#D98B45",
  roastDark: "#8A4720",
  bone: "#F3E9D2",
  avocadoSkin: "#2F5D2A",
  avocadoFlesh: "#DCEB8C",
  avocadoRim: "#A9D159",
  pit: "#7A4A26",
  broccoli: "#2E8B3E",
  broccoliDark: "#1F6B2E",
  broccoliLight: "#4FAE52",
  stem: "#8BC56A",
  eggWhite: "#FBFBF6",
  yolk: "#FFB21E",
  yolkLight: "#FFCB4D",
  crust: "#D99A4E",
  crustDark: "#B8762F",
  cheese: "#FFD45C",
  cheeseLight: "#FFE38A",
  pepperoni: "#C8402F",
  basil: "#3C8C3A",
  rice: "#FAFAF4",
  riceShade: "#E9E7DA",
  bowl: "#FF6F61",
  bowlDark: "#D9534A",
  glass: "#1B2433",
  screen: "#0E1420",
  crystal: "#8FE3FF",
  crystalDark: "#3FA9D6",
  // Rice bowl (navy glaze, white band: white rice reads against it), scale display.
  navy: "#2C3A63",
  navyLight: "#3D4F82",
  lcd: "#16202E",
  lcdOn: "#7DF0B8",
  glassTop: "#DCE6EE",
  // Kitchen set (step 130): warm floor tiles, subway wall tiles, mint paint, white units.
  floorA: "#EFE4D2",
  floorB: "#E2D3BB",
  plinth: "#B9A285",
  wallTile: "#FBFCFC",
  grout: "#D9DEE2",
  wallPaint: "#D6EEE4",
  wallPaintDark: "#BFE0D3",
  unit: "#FFFFFF",
  unitShade: "#E9EDF0",
  worktop: "#3A4250",
  sky: "#BFE3FF",
  skyLight: "#E3F3FF",
  jarLid: "#E07A5F",
  // Ground tiles.
  grass: "#7CC46A",
  grassDark: "#62AE55",
  dirt: "#A9774A",
  dirtDark: "#8A5E37",
};

const forms: Record<string, string> = {};
for (const f of FORMS) {
  forms[f.id] = f.hex;
  forms[`${f.id}Dark`] = mix(f.hex, INK, 0.3);
  forms[`${f.id}Light`] = mix(f.hex, WHITE, 0.35);
}

/** Every colour a voxel may use, by name. */
export const COLORS: Readonly<Record<string, string>> = { ...BASE, ...forms };

export type ColorName = keyof typeof BASE | `${FormId}` | `${FormId}Dark` | `${FormId}Light`;
