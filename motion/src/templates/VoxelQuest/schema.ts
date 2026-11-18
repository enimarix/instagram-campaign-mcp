// VoxelQuest props, script mapping and timings (step 130). Imports only zod and pure modules,
// so `node --test` runs it directly (test/voxelquest.test.ts).
import { z } from "zod";
import {
  accentSchema,
  addressSchema,
  DEFAULT_ADDRESS,
  END_CARD_MIN_S,
  foodSchema,
  FORM_IDS,
  formSchema,
  screenText,
} from "../../endcards/schema.ts";
import { buildTimeline, LINE_GAP_S, READ_CHARS_PER_S, type Timing } from "../../lib/timeline.ts";

/** One voice line (TTS, step 036/048): seconds from the start of the video. */
const voiceLine = z.strictObject({ text: z.string(), start_s: z.number().min(0), end_s: z.number().min(0) });

const food = z.strictObject({
  /** Voxel prop that pops onto the worktop. */
  prop: foodSchema,
  /** Its number, short: "160 kcal", "31 g". */
  label: screenText(14),
  /** Colour of the label: the macro the number is about. */
  macro: z.enum(["protein", "carbs", "fat", "kcal"]).default("kcal"),
});

const beat = z.strictObject({
  /** problem: the golem at the worktop, foods pop in; app: the phone solves it; payoff: level up. */
  kind: z.enum(["problem", "app", "payoff"]),
  /** The caption (and the voice's line) of this beat. */
  line: screenText(90),
  /** Problem beats only: 1-3 foods with their numbers. */
  foods: z.array(food).min(1).max(3).optional(),
  /** Golem form in this beat (default: fromForm, toForm once levelled up). */
  form: formSchema.optional(),
});

export const voxelQuestSchema = z
  .strictObject({
    /** Script line 0: big on the light background from frame 0 (the Reel cover). */
    hook: screenText(70),
    /** What the golem faces in the hook: standing on a scale, or an empty plate on the worktop. */
    hookProp: z.enum(["scale", "plate"]).default("scale"),
    /** The story: 1-2 problem beats, then 1-2 app beats, then one payoff. */
    beats: z.array(beat).min(3).max(5),
    /** Last line, the end card's tagline (tied to the payoff); none = the app's tagline. */
    outro: screenText(70).optional(),
    /** tu or vous for the default texts; the lines themselves are written in it. */
    address: addressSchema.default(DEFAULT_ADDRESS),
    /** The golem levels up from this form to that one at the payoff (the six app forms). */
    fromForm: formSchema.default("etincelle"),
    toForm: formSchema.default("recrue"),
    /** Macro colour of the topic: numbers in the captions, the end card's ring and underline. */
    accent: accentSchema.default("brand"),
    /** Beside the end card's tile: default the golem in toForm, or one of the story's foods. */
    cameo: z.union([formSchema, foodSchema]).optional(),
    /** Sources of the stated numbers (GOAL.md §5.6). Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /**
     * Voice track (048b rule): `lines` = one timing per script line: hook, each beat line, then
     * the outro when there is one; none = timings from the reading speed.
     */
    voice: z.strictObject({ audioSrc: z.string().min(1).optional(), lines: z.array(voiceLine).optional() }).optional(),
    /** Background bed: the warm marimba loop (src/assets.ts), or "none". */
    music: z.enum(["music-marimba", "none"]).default("music-marimba"),
    /** Fade back into frame 0 at the end; off by default here: the end card closes the video. */
    loop: z.boolean().default(false),
    /** Voxel pixelation, 1 = off (engine default 2). */
    pixelate: z.number().int().min(1).max(4).default(2),
    safeZone: z.boolean().optional(),
  })
  .superRefine((p, ctx) => {
    const kinds = p.beats.map((b) => b.kind).join(" ");
    if (!/^(problem ){1,2}(app ){1,2}payoff$/.test(kinds)) {
      ctx.addIssue({ code: "custom", path: ["beats"], message: `beats must be 1-2 problem, then 1-2 app, then one payoff (got: ${kinds})` });
    }
    p.beats.forEach((b, i) => {
      if (b.foods && b.kind !== "problem") {
        ctx.addIssue({ code: "custom", path: ["beats", i, "foods"], message: "only problem beats show foods" });
      }
    });
    if (FORM_IDS.indexOf(p.toForm) <= FORM_IDS.indexOf(p.fromForm)) {
      ctx.addIssue({ code: "custom", path: ["toForm"], message: `toForm must be a higher form than fromForm (${FORM_IDS.join(" < ")})` });
    }
    const lines = voxelQuestScript(p).lines.length;
    if (p.voice?.lines && p.voice.lines.length !== lines) {
      ctx.addIssue({ code: "custom", path: ["voice", "lines"], message: `voice.lines needs one timing per script line: hook, each beat, outro (${lines})` });
    }
  });

export type VoxelQuestProps = z.infer<typeof voxelQuestSchema>;
type Script = Pick<VoxelQuestProps, "hook" | "beats" | "outro" | "voice">;

/** Script lines: [hook, ...beat lines, outro?]; voice timings when given. */
export const voxelQuestScript = ({ hook, beats, outro, voice }: Script) => ({
  lines: [hook, ...beats.map((b) => b.line), ...(outro ? [outro] : [])],
  timings: voice?.lines,
});

/** Shortest scene per kind without a voice: room for each beat's animation (a change every 2-4 s). */
export const MIN_S = { hook: 2.5, problem: 3.6, app: 4.4, payoff: 3.8, outro: 2 };
/** End card hold after the outro line (or the whole card when there is no outro). */
export const END_HOLD_S = 1.2;

/** Estimated timings from the reading speed, with each kind's shortest scene. */
const estimate = (lines: string[], kinds: (keyof typeof MIN_S)[]): Timing[] => {
  let t = 0;
  return lines.map((text, i) => {
    const read = Math.max(MIN_S[kinds[i]], Array.from(text).length / READ_CHARS_PER_S);
    const timing = { text, start_s: t, end_s: t + read };
    t += read + LINE_GAP_S;
    return timing;
  });
};

/**
 * Scenes in frames (0 = hook, 1..n = beats, n+1 = outro when there is one) and where the end
 * card starts: at the outro line, else after the last beat. The end card lasts at least
 * END_CARD_MIN_S.
 */
export const timelineOf = (p: VoxelQuestProps, fps: number) => {
  const script = voxelQuestScript(p);
  const kinds = ["hook", ...p.beats.map((b) => b.kind), ...(p.outro ? ["outro"] : [])] as (keyof typeof MIN_S)[];
  const timings = script.timings ?? estimate(script.lines, kinds);
  const build = (outroSeconds: number) => buildTimeline({ lines: script.lines, timings, fps, hookSeconds: MIN_S.hook, outroSeconds, loop: p.loop });
  let timeline = build(p.outro ? END_HOLD_S : END_CARD_MIN_S + 0.5);
  const endStart = p.outro ? timeline.scenes[timeline.scenes.length - 1].startFrame : timeline.outroStart;
  const short = Math.ceil(END_CARD_MIN_S * fps) - (timeline.totalFrames - endStart);
  if (short > 0) timeline = build((timeline.totalFrames - timeline.outroStart + short) / fps);
  return { timeline, endStart };
};
