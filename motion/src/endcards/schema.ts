// End-card props shared by every style (step 130; 137 adds the other styles). The base is
// fixed (mB tile, wordmark, « 7 jours gratuits » pill, macrobody.fr; never a price) and each
// video adapts it: tagline from its payoff, accent from its topic, cameo from its story.
// Imports only zod and pure modules, so `node --test` runs it (test/voxelquest.test.ts).
import { z } from "zod";
import { NO_PRICE, noPrice } from "../lib/noPrice.ts";
import { FORMS } from "../voxel/palette.ts";

/** Visible text: 1..max characters, never a price (owner rule). */
export const screenText = (max: number) => z.string().trim().min(1).max(max).refine(noPrice, NO_PRICE);

/** Accent name -> colour: the macro colours of the app, emerald = the brand. */
export const ACCENTS = {
  brand: "#10B981",
  protein: "#FF6F61",
  carbs: "#3FBF7F",
  fat: "#F5C242",
  kcal: "#3E8EF7",
} as const;
export const accentSchema = z.enum(["brand", "protein", "carbs", "fat", "kcal"]);
export type Accent = z.infer<typeof accentSchema>;

/** The golem's six forms, by id (src/voxel/palette.ts FORMS). */
export const FORM_IDS = FORMS.map((f) => f.id) as [(typeof FORMS)[number]["id"], ...(typeof FORMS)[number]["id"][]];
export const formSchema = z.enum(FORM_IDS);
export type FormId = z.infer<typeof formSchema>;

/** Food props of the voxel library (src/voxel/models.ts PROPS) a story may show. */
export const FOOD_IDS = ["drumstick", "avocado", "pizza", "egg", "broccoli", "riceBowl"] as const;
export const foodSchema = z.enum(FOOD_IDS);
export type FoodId = z.infer<typeof foodSchema>;

/** brand/brand.json address.default (a test keeps them equal): vous for the brand styles. */
export const DEFAULT_ADDRESS = "vous";
export const addressSchema = z.enum(["vous", "tu"]);

/** The app's tagline, per form of address: the end card's line when a video gives none. */
export const DEFAULT_TAGLINE = {
  vous: "Calculez. Personnalisez. Atteignez vos objectifs.",
  tu: "Calcule. Personnalise. Atteins tes objectifs.",
} as const;

export const END_CARD_STYLES = ["voxel"] as const;

export const endCardSchema = z.strictObject({
  /** Which style's card (one per style: voxel now; paper, clean, pixel, live in step 137). */
  style: z.enum(END_CARD_STYLES).default("voxel"),
  /** One line tied to the video's payoff; none = the app's tagline in the right address. */
  tagline: screenText(70).optional(),
  /** Macro colour of the topic (the rug under the tile, the url underline); default emerald. */
  accent: accentSchema.default("brand"),
  /** Who stands beside the tile: the golem in the form the story reached, or its food prop. */
  cameo: z.union([formSchema, foodSchema]).default("etincelle"),
  address: addressSchema.default(DEFAULT_ADDRESS),
  /** Voxel pixelation (1 = off), as the story around it. */
  pixelate: z.number().int().min(1).max(4).default(2),
});

export type EndCardProps = z.infer<typeof endCardSchema>;

/** Shortest end card (owner: a clean end card of 2 s or more; the reveal needs about 2 s). */
export const END_CARD_MIN_S = 2.5;
