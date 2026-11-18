// The paper style's constants (step 131), after the owner's paper.js: colours, the sheets a
// scene is cut from, the four named characters and the foods. Pure (no imports) so the
// schema and `node --test` use it directly.

export const INK = "#2B2118";
export const CREAM = "#FFF8EC";
export const KRAFT = "#E9D9BC";
export const YELLOW = "#FFD24D";
export const RED = "#E5484D";
export const BRAND = "#10B981";
export const BRAND_LIGHT = "#34D399";
/** The app's macro colours. */
export const MACRO = { protein: "#FF6F61", carbs: "#3FBF7F", fat: "#F5C242", kcal: "#3E8EF7" } as const;

/** Sheet colours a scene is cut from: navy is the owner's night sheet as rendered in p1-p3 (lighter than the brand navy #2C3A63). */
export const SHEETS = {
  navy: "#3B4C7E",
  sky: "#DCEBF5",
  mint: "#CFEFDF",
  cream: CREAM,
  peach: "#FCE4CF",
} as const;
export type SheetId = keyof typeof SHEETS;
/** Dark sheets: stars and a moon, light handwriting. */
export const DARK_SHEETS: readonly SheetId[] = ["navy"];

export type Character = {
  name: string;
  skin: string;
  hair: string;
  hairStyle: "bun" | "long" | "short" | "curly";
  top: string;
  topStyle: "dress" | "shirt" | "hoodie";
  pants: string;
  /** Pyjama stripes on the shirt (Inès at 21 h). */
  stripes?: boolean;
  beard?: boolean;
};

/** The owner's cast (paper.js STY): skin, hair, top colour. */
export const CHARACTERS = {
  ines: { name: "Inès", skin: "#C98E66", hair: "#1E1410", hairStyle: "long", top: "#9B7BD4", topStyle: "shirt", pants: "#7A5BA6", stripes: true },
  paul: { name: "Paul", skin: "#F1C6A6", hair: "#8A4B22", hairStyle: "short", top: MACRO.kcal, topStyle: "shirt", pants: "#3B3B46", beard: true },
  sam: { name: "Sam", skin: "#8D5A3B", hair: "#141010", hairStyle: "curly", top: BRAND, topStyle: "hoodie", pants: "#2E3A64" },
  lea: { name: "Léa", skin: "#F4C29B", hair: "#3A2418", hairStyle: "bun", top: MACRO.protein, topStyle: "dress", pants: "#2E3A64" },
} as const satisfies Record<string, Character>;
export const CHARACTER_IDS = Object.keys(CHARACTERS) as [keyof typeof CHARACTERS, ...(keyof typeof CHARACTERS)[]];
export type CharacterId = keyof typeof CHARACTERS;

/** Cut-out foods, each with the macro it is mostly about (its number's colour). */
export const FOODS = {
  pizza: { name: "Pizza", macro: "kcal" },
  apple: { name: "Pomme", macro: "carbs" },
  drumstick: { name: "Poulet", macro: "protein" },
  pasta: { name: "Pâtes", macro: "carbs" },
  egg: { name: "Œuf", macro: "protein" },
  avocado: { name: "Avocat", macro: "fat" },
  rice: { name: "Riz", macro: "carbs" },
  cheese: { name: "Fromage", macro: "fat" },
  bread: { name: "Pain", macro: "carbs" },
  yogurt: { name: "Yaourt", macro: "protein" },
} as const satisfies Record<string, { name: string; macro: keyof typeof MACRO }>;
export const FOOD_IDS = Object.keys(FOODS) as [keyof typeof FOODS, ...(keyof typeof FOODS)[]];
export type PaperFoodId = keyof typeof FOODS;

/** Stepped motion: the whole film moves on 12 fps steps, like the owner's stop-motion paper. */
export const STEP_FPS = 12;
/** `frame` snapped down to the last 12 fps step (in frames of `fps`). */
export const stepped = (frame: number, fps: number) => (Math.floor((frame * STEP_FPS) / fps + 1e-6) * fps) / STEP_FPS;

