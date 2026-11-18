// PaperStory props, script mapping and timings (step 131): the owner's paper cut-out house
// style. Imports only zod and pure modules, so `node --test` runs it (test/paperstory.test.ts).
import { z } from "zod";
import { accentSchema, addressSchema, CAMEOS, CARD_S, DEFAULT_ADDRESS, screenText } from "../../endcards/schema.ts";
import { buildTimeline, fitEndCard, LINE_GAP_S, READ_CHARS_PER_S, type Timeline, type Timing } from "../../lib/timeline.ts";
import { CHARACTER_IDS, FOOD_IDS, SHEETS } from "../../paper/palette.ts";

/** One voice line (TTS, step 036/048): seconds from the start of the video. */
const voiceLine = z.strictObject({ text: z.string(), start_s: z.number().min(0), end_s: z.number().min(0) });

export const TONE_IDS = ["cream", "brand", "yellow", "red", "ink", "sky"] as const;
/** Label sizes in px: s, m (default), l (a hero number like « 308 kcal »). */
export const LABEL_SIZE = { s: 50, m: 66, l: 118 } as const;

/** A Fredoka strip: a plain string (cream, size m) or {text, tone, size}. brand = the green highlight bar. */
const label = z.union([
  screenText(34),
  z.strictObject({ text: screenText(34), tone: z.enum(TONE_IDS).default("cream"), size: z.enum(["s", "m", "l"]).default("m") }),
]);
export type LabelProp = z.infer<typeof label>;

const food = z.enum(FOOD_IDS);
const moodSchema = z.enum(["neutral", "worried", "happy", "surprised"]);
const gestureSchema = z.enum(["none", "wave", "phone", "shrug", "cheer"]);

/** What every scene has: its strips (= its voice line), an aside, its sheet, the character's face and gesture. */
const common = {
  /** 1-3 strips stacked under each other (app list beats: one after the other in the same place). Read aloud, in order. */
  labels: z.array(label).min(1).max(3),
  /** Caveat handwriting, not read aloud: « (spoiler : pas une pizza) ». */
  aside: screenText(44).optional(),
  /** The sheet the scene is cut from; default per kind (hook navy, problem sky, app mint / cream, payoff = the hook's). */
  sheet: z.enum(Object.keys(SHEETS) as [keyof typeof SHEETS, ...(keyof typeof SHEETS)[]]).optional(),
  /** The character's face (default per kind) and gesture. */
  mood: moodSchema.optional(),
  gesture: gestureSchema.optional(),
};

/** "21:00": the clock's time. */
const time = z.string().regex(/^([01]?\d|2[0-3]):[0-5]\d$/, "a time like 21:00");

const hook = z.strictObject({
  ...common,
  /** The prop beside the character: a clock at `time` (minute hand ticks to it), the fridge, a plate with `foods`, the phone, or none. */
  prop: z.enum(["clock", "fridge", "plate", "phone", "none"]).default("clock"),
  time: time.default("21:00"),
  foods: z.array(food).max(3).optional(),
});

const option = z.strictObject({
  food,
  /** Its number on a receipt slip: "850 kcal", "4 g". */
  label: screenText(14),
  /** Handwritten over the number; default « environ ». */
  note: screenText(14).default("environ"),
  /** A red cross (too much, too little), a green check (ok) or nothing. */
  verdict: z.enum(["too_much", "too_little", "ok", "none"]).default("none"),
});

const problem = z.strictObject({
  kind: z.literal("problem"),
  ...common,
  /** The prop the options come out of. */
  prop: z.enum(["fridge", "clock", "plate", "none"]).default("fridge"),
  time: time.default("21:00"),
  /** 0-3 foods shown one after the other, each with its number and a verdict. */
  options: z.array(option).max(3).default([]),
});

const row = z.strictObject({
  food,
  name: screenText(16),
  /** Grams before and after the app solves the day; same = left as is. */
  from: z.number().int().min(0).max(2000).optional(),
  to: z.number().int().min(0).max(2000),
  /** A padlock: the owner of the day fixed this one. */
  locked: z.boolean().default(false),
});

const app = z.strictObject({
  kind: z.literal("app"),
  ...common,
  /** Phone screen: the big number in the ring (counts up), its unit, the green button (tapped halfway). */
  value: screenText(10).optional(),
  unit: screenText(18).default("kcal restantes"),
  button: screenText(24).default("Compléter ma journée"),
  /** Instead of the phone: the app's list as paper rows (2-5) whose grams the app solves, then `total`. */
  rows: z.array(row).min(2).max(5).optional(),
  total: screenText(24).optional(),
});

const payoff = z.strictObject({
  kind: z.literal("payoff"),
  ...common,
  /** The big ring's number (counts up to it), e.g. "2 236", and what it is out of, e.g. "/ 2 238 kcal". */
  value: screenText(10).optional(),
  of: screenText(18).optional(),
  /** Stamped down in the accent: « PILE. » */
  stamp: screenText(12).optional(),
  /** On the plate beside the character. */
  foods: z.array(food).max(3).optional(),
});

const beat = z.discriminatedUnion("kind", [problem, app, payoff]);
export type Beat = z.infer<typeof beat>;

export const paperStorySchema = z
  .strictObject({
    /** Who the story is about (the end card's cameo too). */
    character: z.enum(CHARACTER_IDS).default("ines"),
    /** The question hook: on screen from frame 0 (the Reel cover), e.g. « 21 h. Il vous reste » « 308 kcal » « Vous mangez quoi ? ». */
    hook,
    /** 1-2 problem beats, then 1-2 app beats, then one payoff. */
    beats: z.array(beat).min(3).max(5),
    /** The end card's tagline (tied to the payoff), read aloud as the last line; none = the app's tagline. */
    outro: screenText(70).optional(),
    address: addressSchema.default(DEFAULT_ADDRESS),
    /** Macro colour of the topic: the payoff ring, the stamp, the end card's underline. */
    accent: accentSchema.default("brand"),
    /** Beside the end card's tile: default the story's character. */
    cameo: z.enum([...CAMEOS.paper, "none"]).optional(),
    /** Sources of the stated numbers (GOAL.md §5.6). Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /** Voice track (048b rule): `lines` = one timing per script line: hook, each beat, then the outro when there is one. */
    voice: z.strictObject({ audioSrc: z.string().min(1).optional(), lines: z.array(voiceLine).optional() }).optional(),
    /** The kalimba / glockenspiel bed, or "none". */
    music: z.enum(["music-kalimba", "none"]).default("music-kalimba"),
    /** Off by default: the end card closes the video. */
    loop: z.boolean().default(false),
    safeZone: z.boolean().optional(),
  })
  .superRefine((p, ctx) => {
    const kinds = p.beats.map((b) => b.kind).join(" ");
    if (!/^(problem ){1,2}(app ){1,2}payoff$/.test(kinds)) {
      ctx.addIssue({ code: "custom", path: ["beats"], message: `beats must be 1-2 problem, then 1-2 app, then one payoff (got: ${kinds})` });
    }
    p.beats.forEach((b, i) => {
      if (b.kind === "app" && b.rows && b.value) {
        ctx.addIssue({ code: "custom", path: ["beats", i, "value"], message: "an app beat shows the phone (value) or the list (rows), not both" });
      }
      if (b.kind === "app" && b.total && !b.rows) {
        ctx.addIssue({ code: "custom", path: ["beats", i, "total"], message: "total goes with rows" });
      }
      if (b.kind === "payoff" && b.of && !b.value) {
        ctx.addIssue({ code: "custom", path: ["beats", i, "of"], message: "of goes with value" });
      }
    });
    const lines = paperStoryScript(p).lines.length;
    if (p.voice?.lines && p.voice.lines.length !== lines) {
      ctx.addIssue({ code: "custom", path: ["voice", "lines"], message: `voice.lines needs one timing per script line: hook, each beat, outro (${lines})` });
    }
  });

export type PaperStoryProps = z.infer<typeof paperStorySchema>;
type Script = Pick<PaperStoryProps, "hook" | "beats" | "outro" | "voice">;

export const labelText = (l: LabelProp) => (typeof l === "string" ? l : l.text);

/**
 * A scene's spoken line: its strips in order, a full stop added where a strip ends without
 * punctuation and the next starts a sentence (« 308 kcal » « Vous mangez quoi ? »). Same rule
 * as src/studio/motion.py SCRIPTS.
 */
export const sceneLine = (labels: LabelProp[]) =>
  labels
    .map(labelText)
    .reduce((line, next) => (line && !/[.!?…:;,]$/.test(line) && /^\p{Lu}/u.test(next) ? `${line}. ${next}` : line ? `${line} ${next}` : next), "");

/** Script lines: [hook, ...beats, outro?]; voice timings when given. */
export const paperStoryScript = ({ hook: h, beats, outro, voice }: Script) => ({
  lines: [sceneLine(h.labels), ...beats.map((b) => sceneLine(b.labels)), ...(outro ? [outro] : [])],
  timings: voice?.lines,
});

/** Shortest scene without a voice: room for each beat's animation (a change every 2-4 s). */
export const minSeconds = (b: Beat | "hook" | "outro") => {
  if (b === "hook") return 2.5;
  if (b === "outro") return 2;
  if (b.kind === "problem") return Math.max(3.2, 0.6 + 1.5 * b.options.length);
  if (b.kind === "app") return b.rows ? 4.2 + 0.35 * b.rows.length : 3.4;
  return 3.8;
};
/** End card hold after the outro line is read (the card itself lasts at least CARD_S.paper). */
export const END_HOLD_S = 1.2;

/**
 * Scenes in frames (0 = hook, 1..n = beats, n+1 = outro when there is one) and where the end
 * card starts: at the outro line, else after the last beat. The card lasts at least
 * CARD_S.paper, so it settles and holds 1 s.
 */
export const timelineOf = (p: PaperStoryProps, fps: number) => {
  const script = paperStoryScript(p);
  const kinds: (Beat | "hook" | "outro")[] = ["hook", ...p.beats, ...(p.outro ? ["outro" as const] : [])];
  let t = 0;
  const timings: Timing[] =
    script.timings ??
    script.lines.map((text, i) => {
      const read = Math.max(minSeconds(kinds[i]), Array.from(text).length / READ_CHARS_PER_S);
      const timing = { text, start_s: t, end_s: t + read };
      t += read + LINE_GAP_S;
      return timing;
    });
  const build = (outroSeconds: number) => buildTimeline({ lines: script.lines, timings, fps, hookSeconds: 2.5, outroSeconds, loop: p.loop });
  const cardStart = (tl: Timeline) => (p.outro ? tl.scenes[tl.scenes.length - 1].startFrame : tl.outroStart);
  const timeline = fitEndCard(build, p.outro ? END_HOLD_S : CARD_S.paper, cardStart, CARD_S.paper, fps);
  return { timeline, endStart: cardStart(timeline) };
};
