// « GTA 6 » props, script and timings (owner 2026-11-25): an open-world crime-game mission at
// sunset. Hook = a loading-screen collage (beach, the night city's neon `sign`, Muscle Beach)
// under the hook text; then the letterboxed mission card at Muscle Beach, the chase (a craving
// as a wanted level, him shocked under the neon), the loot (protein pickups, kcal counter and
// protein bar on the neon grid), the clear (the stars go grey), « MISSION RÉUSSIE » with the
// reward, the GTA 6 end card. One voice line per scene.
// Imports only zod and pure modules, so `node --test` runs it (test/openworld.test.ts).
import { z } from "zod";
import { accentSchema, addressSchema, CARD_S, DEFAULT_ADDRESS, screenText } from "../../endcards/schema.ts";
import { buildTimeline, fitEndCard, LINE_GAP_S, READ_CHARS_PER_S, type Timeline, type Timing } from "../../lib/timeline.ts";

const voiceLine = z.strictObject({ text: z.string(), start_s: z.number().min(0), end_s: z.number().min(0) });

/** A line drawn in the objective font; `highlight` (a part of it) in yellow. Read aloud as is. */
const objective = z.strictObject({ line: screenText(80), highlight: screenText(30).optional() });

export const ITEM_IDS = ["egg", "skyr", "chicken", "shaker", "bowl"] as const;

export const openWorldSchema = z
  .strictObject({
    /** The hook on the loading-screen collage, from frame 0 (the cover): `lead` in white, `key` in the sunset gradient. Read: lead, key. */
    hook: z.strictObject({ lead: screenText(30), key: screenText(30) }),
    /** The big neon on the night city (a time, a number: « 23:00 »), and the small one (the temptation: « SNACK »). */
    sign: screenText(6).default("23:00"),
    side: screenText(8).default("SNACK"),
    /** The letterboxed card at Muscle Beach: « MISSION », the title, the objective. Read: title, objective. */
    mission: z.strictObject({ title: screenText(26), objective: screenText(50) }),
    /** The chase: what hunts you as a wanted level (`label` under the stars) and its line. */
    chase: objective.extend({ label: screenText(16).default("Fringale"), stars: z.number().int().min(1).max(5).default(3) }),
    /** The loot on the neon grid: 1-3 pickups, each adding `grams` to the bar and taking `kcal` off the counter. */
    loot: objective.extend({
      items: z.array(z.strictObject({ item: z.enum(ITEM_IDS), grams: z.number().int().min(1).max(99), kcal: z.number().int().min(0).max(999) })).min(1).max(3),
      /** The bar's goal and name (« Protéines », g). */
      goal: z.number().int().min(1).max(300),
      bar: screenText(14).default("Protéines"),
      /** The kcal counter before the first pickup (what is left for the day). */
      kcal: z.number().int().min(0).max(5000),
    }),
    /** The stars go grey: the chase is shaken off. `label` replaces the stars' label (« Fringale semée »). */
    clear: objective.extend({ label: screenText(20).default("Fringale semée") }),
    /** « MISSION RÉUSSIE » slammed in, then the reward lines. Read: title, reward. */
    passed: z.strictObject({ title: screenText(20).default("Mission réussie"), reward: screenText(36), detail: screenText(40).optional() }),
    /** The end card's tagline, read aloud as the last line; none = the app's tagline. */
    outro: screenText(70).optional(),
    address: addressSchema.default(DEFAULT_ADDRESS),
    accent: accentSchema.default("brand"),
    /** Sources of the stated numbers (GOAL.md §5.6). Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /** One timing per script line: hook, mission, chase, loot, clear, passed, then the outro when there is one. */
    voice: z.strictObject({ audioSrc: z.string().min(1).optional(), lines: z.array(voiceLine).optional() }).optional(),
    /** No bed of its own (owner: the synthesized one was bad): an Instagram track rides along (music_audio_id). */
    music: z.enum(["none"]).default("none"),
    safeZone: z.boolean().optional(),
  })
  .superRefine((p, ctx) => {
    for (const k of ["chase", "loot", "clear"] as const) {
      const o = p[k];
      if (o.highlight && !o.line.includes(o.highlight)) ctx.addIssue({ code: "custom", path: [k, "highlight"], message: "highlight must be a part of line" });
    }
    const lines = openWorldScript(p).lines.length;
    if (p.voice?.lines && p.voice.lines.length !== lines) {
      ctx.addIssue({ code: "custom", path: ["voice", "lines"], message: `voice.lines needs one timing per script line: hook, mission, chase, loot, clear, passed, outro (${lines})` });
    }
  });

export type OpenWorldProps = z.infer<typeof openWorldSchema>;
type Script = Pick<OpenWorldProps, "hook" | "mission" | "chase" | "loot" | "clear" | "passed" | "outro" | "voice">;

/** Two texts read as one line (same rule as Editorial's joinLine and src/studio/motion.py `_editorial_line`). */
export const joinLine = (a: string, b?: string) =>
  !b ? a : /[.!?…:;,]$/.test(a) ? `${a} ${b}` : /^\p{Lu}/u.test(b) ? `${a}. ${b}` : `${a}, ${b}`;

/** Script lines: [hook, mission, chase, loot, clear, passed, outro?]. */
export const openWorldScript = ({ hook, mission, chase, loot, clear, passed, outro, voice }: Script) => ({
  lines: [joinLine(hook.lead, hook.key), joinLine(mission.title, mission.objective), chase.line, loot.line, clear.line, joinLine(passed.title, passed.reward), ...(outro ? [outro] : [])],
  timings: voice?.lines,
});

/** Scene kinds in script order. */
export const KINDS = ["hook", "mission", "chase", "loot", "clear", "passed", "outro"] as const;
/** Shortest scene without a voice: room for its animation (the loot: one pickup a second). */
const MIN_S = { hook: 3, mission: 3, chase: 2.8, loot: 3, clear: 2.2, passed: 3.2, outro: 2 } as const;
const END_HOLD_S = 1.2;

/**
 * Scenes in frames (0 hook .. 5 passed, 6 outro when there is one) and where the end card
 * starts: at the outro line, else after « mission réussie ».
 */
export const timelineOf = (p: OpenWorldProps, fps: number) => {
  const script = openWorldScript(p);
  let t = 0;
  const timings: Timing[] =
    script.timings ??
    script.lines.map((text, i) => {
      const min = KINDS[i] === "loot" ? Math.max(MIN_S.loot, p.loot.items.length + 1) : MIN_S[KINDS[i]];
      const read = Math.max(min, Array.from(text).length / READ_CHARS_PER_S);
      const timing = { text, start_s: t, end_s: t + read };
      t += read + LINE_GAP_S;
      return timing;
    });
  const build = (outroSeconds: number) => buildTimeline({ lines: script.lines, timings, fps, hookSeconds: MIN_S.hook, outroSeconds, loop: false });
  const cardStart = (tl: Timeline) => (p.outro ? tl.scenes[tl.scenes.length - 1].startFrame : tl.outroStart);
  const timeline = fitEndCard(build, p.outro ? END_HOLD_S : CARD_S.gta6, cardStart, CARD_S.gta6, fps);
  return { timeline, endStart: cardStart(timeline) };
};

/** Frames (from the loot scene's start) where each pickup is collected: evenly through the scene. */
export const pickupFrames = (n: number, len: number) => Array.from({ length: n }, (_, k) => Math.round((len * (k + 0.8)) / (n + 0.6)));

/** The hook's cover frame: the text has punched in. */
export const COVER_FRAME = 14;
