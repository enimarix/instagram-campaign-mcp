// End-card props shared by every style (step 130, all styles in step 137). The base is fixed
// (mB tile, wordmark, « 7 jours gratuits » pill, macrobody.fr; never a price) and each video
// adapts it: tagline from its payoff, accent from its topic, cameo from its story, backdrop
// from its set (live: the video's last frame).
// Imports only zod and pure modules, so `node --test` runs it (test/endcards.test.ts).
import { z } from "zod";
import { NO_PRICE, noPrice } from "../lib/noPrice.ts";
import { type SfxId, sfxVolume, VOICE_LUFS } from "../lib/duck.ts";
import { VIEW_IDS } from "../cutaway/views.ts";
import { FORMS } from "../voxel/palette.ts";
import { SCENE_IDS } from "../cinema/scenes.ts";
import { CHARACTER_IDS as EDITORIAL_CHARACTERS } from "../editorial/palette.ts";

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
/** Accent colours dark enough for text on a light surface (fat and carbs darkened). */
export const TEXT_ACCENT = { ...ACCENTS, fat: "#B7862A", carbs: "#2E9E66" } as const;
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

/** One card per style; a template ends on its style's card. */
export const END_CARD_STYLES = ["voxel", "paper", "clean", "pixel", "live", "cutaway", "editorial", "cinema", "macro3d"] as const;
export type EndCardStyle = (typeof END_CARD_STYLES)[number];

/**
 * Who or what stands beside the tile, per style (first = default; "none" works everywhere):
 * voxel the golem in a form or a food prop, paper a cut-out character or food, clean an app
 * card (the calorie ring), pixel a sprite of src/assets.ts, live nothing (the footage is the set),
 * cutaway a small running mechanism (src/cutaway/views.ts), editorial the blossom tree or an
 * anatomy character,
 * cinema the pixel set the card's beam and rain play over (src/cinema/scenes.ts),
 * macro3d Marco, the coach of the Macro 3D videos (src/macro3d/Presenter.tsx).
 */
export const CAMEOS = {
  voxel: [...FORM_IDS, ...FOOD_IDS],
  paper: ["ines", "paul", "sam", "lea", "avocado"],
  clean: ["ring"],
  pixel: ["mascot", "slime", "coin", "heart"],
  live: [],
  cutaway: VIEW_IDS,
  editorial: ["tree", ...EDITORIAL_CHARACTERS],
  cinema: SCENE_IDS,
  macro3d: ["marco"],
} as const satisfies Record<EndCardStyle, readonly string[]>;

/** The cameo a card shows: the one asked for, else its style's first. */
export const cameoOf = (style: EndCardStyle, cameo?: string): string => cameo ?? CAMEOS[style][0] ?? "none";

/**
 * Each card's own length (a standalone clip, e.g. Track A recipes) and when its choreography
 * has settled: every card then holds at least 1 s on the finished picture.
 */
export const CARD_S = { voxel: 3.5, paper: 3.5, clean: 3.5, pixel: 4, live: 4, cutaway: 4, editorial: 3.5, cinema: 3.5, macro3d: 3.5 } as const satisfies Record<EndCardStyle, number>;
export const SETTLE_S = { voxel: 2.3, paper: 2.3, clean: 2.1, pixel: 2.8, live: 2.6, cutaway: 2.8, editorial: 2.3, cinema: 2.3, macro3d: 2.4 } as const satisfies Record<EndCardStyle, number>;

export { SFX_PEAK_LUFS } from "../lib/duck.ts";
/**
 * End-card sounds sit at the voice's level (step 158): the coin and the confirm at volume 0.5
 * peaked 9 LU over the speech once the studio's -14 LUFS finish lifted the quiet voice. A card
 * sound peaks at this level in the template's mix (lib/duck.ts VOICE_LUFS, the quietest approved
 * voice's own); a louder voice leaves the card further under it.
 */
export const CARD_PEAK_LUFS = VOICE_LUFS;
/** Volume that puts sound `id` at CARD_PEAK_LUFS (`db` lower for a quieter accent). */
export const cardVolume = (id: SfxId, db = 0) => sfxVolume(id, db);

/** Shortest end card (owner: a clean end card of 2 s or more; the reveal needs about 2 s). */
export const END_CARD_MIN_S = 2.5;

/** A CSS font family name (the paper card's display font): letters, digits and spaces only. */
const fontFamily = z.string().regex(/^[A-Za-z0-9 ]{1,40}$/, "a font family name (letters, digits, spaces)");

export const endCardSchema = z
  .strictObject({
    /** Which style's card. */
    style: z.enum(END_CARD_STYLES).default("voxel"),
    /** One line tied to the video's payoff; none = the app's tagline in the right address. */
    tagline: screenText(70).optional(),
    /** Macro colour of the topic (rings, underlines, glows); default emerald. */
    accent: accentSchema.default("brand"),
    /** Style-specific (CAMEOS); none = the style's default, "none" = nobody. */
    cameo: z.string().optional(),
    address: addressSchema.default(DEFAULT_ADDRESS),
    /** live only, required: the picture the card animates over (the video's last frame), a URL or bundle path. */
    backdrop: z.string().min(1).optional(),
    /** paper only: the display font (Fredoka once step 131 adds it); falls back to Inter Tight. */
    font: fontFamily.optional(),
    /** pixel only: a small line under the card, e.g. the sources note. */
    note: screenText(40).optional(),
    /** Voxel pixelation (1 = off), as the story around it. */
    pixelate: z.number().int().min(1).max(4).default(2),
    /** Length of the standalone card clip (EndCard composition); none = CARD_S of the style. */
    seconds: z.number().min(END_CARD_MIN_S).max(8).optional(),
  })
  .superRefine((p, ctx) => {
    const cameos: readonly string[] = CAMEOS[p.style];
    if (p.cameo !== undefined && p.cameo !== "none" && !cameos.includes(p.cameo)) {
      ctx.addIssue({ code: "custom", path: ["cameo"], message: `${p.style} cameos: ${[...cameos, "none"].join(", ")}` });
    }
    if ((p.style === "live") !== (p.backdrop !== undefined)) {
      ctx.addIssue({ code: "custom", path: ["backdrop"], message: "live needs a backdrop (the last frame); other styles take none" });
    }
    if (p.font !== undefined && p.style !== "paper") {
      ctx.addIssue({ code: "custom", path: ["font"], message: "only the paper card takes a font" });
    }
    if (p.note !== undefined && p.style !== "pixel") {
      ctx.addIssue({ code: "custom", path: ["note"], message: "only the pixel card shows a note" });
    }
  });

export type EndCardProps = z.infer<typeof endCardSchema>;
/** What one style's card component gets. */
export type CardProps = Omit<EndCardProps, "style" | "seconds">;

/** Frames of the standalone card clip. */
export const cardFrames = (p: Pick<EndCardProps, "style" | "seconds">, fps: number) => Math.round((p.seconds ?? CARD_S[p.style]) * fps);
