// Macro3D props, script mapping and timings (step 154): a dark photoreal 3D macro explainer.
// Blender renders the plates (cinematic/engine/macro.py: black studio void, rim lights, depth of
// field, a slow macro move per shot, a hard cut every 1-3 s); this template composes the word-by-word
// captions, the presenter (Marco, the macroBody coach), the small honest labels, a counter and
// the end card on top. Imports only zod and pure modules, so `node --test` runs it.
import { z } from "zod";
import { accentSchema, addressSchema, CARD_S, screenText } from "../../endcards/schema.ts";
import { buildTimeline, fitEndCard, LINE_GAP_S, type Timeline, type Timing } from "../../lib/timeline.ts";
import { POSES } from "../../macro3d/poses.ts";
import { LABELS, LOOKS, MOVES, SUBJECTS } from "../../macro3d/subjects.ts";
import { keyIndexes, wordTimes } from "../../macro3d/words.ts";

/** One voice line (TTS, step 036/048): seconds from the start of the video. */
const voiceLine = z.strictObject({ text: z.string(), start_s: z.number().min(0), end_s: z.number().min(0) });

const subject = z.enum(SUBJECTS);

const scene = z.strictObject({
  /** The line, read aloud and captioned word by word as it is said. */
  line: screenText(130),
  /** One word (or a few, in order) of the line boxed by the blue selection frame as it is said. */
  key: screenText(24).optional(),
  /** What the macro camera shows (cinematic/engine/macro.py). */
  subject,
  /** A second subject the scene cuts to halfway (a cut-away: the food, then what it does). */
  cut: subject.optional(),
  /** plain, heat (« Énergie en couleur »), section (egg, stomach cut open). */
  look: z.enum(LOOKS).default("plain"),
  /** The camera moves, one per shot in order; none = picked so no two shots in a row match. */
  moves: z.array(z.enum(MOVES)).min(1).max(3).optional(),
  /** The small label bottom-left; none = what the picture is (magnified, colour, section). */
  label: z.enum([...(Object.keys(LABELS) as (keyof typeof LABELS)[]), "none"]).optional(),
  /** A small uppercase tag with a leader line onto the subject (« PROTÉINES »). */
  callout: screenText(22).optional(),
  /**
   * A number that counts while the scene plays (kcal, g, kg, jours); `decimals` 0-1. `big`: the
   * scene's one big number, glowing white in the middle over the plate (the reference's « 18.2M »);
   * else small, left of the subject.
   */
  counter: z
    .strictObject({ from: z.number(), to: z.number(), unit: screenText(10), decimals: z.number().int().min(0).max(1).default(0), big: z.boolean().default(false) })
    .optional(),
  /** Marco's pose; none = read from the line (question: shrug, number: point, « pas »: stop…). */
  pose: z.enum(POSES).optional(),
});
export type Scene = z.infer<typeof scene>;

export const macro3dSchema = z
  .strictObject({
    /** 4-10 scenes, one spoken line each; the first is the hook (on screen from frame 0). */
    scenes: z.array(scene).min(4).max(10),
    /** The end card's tagline, read aloud as the last line; none = the app's tagline. */
    outro: screenText(70).optional(),
    address: addressSchema.default("tu"),
    /** Macro colour of the topic: the counter and the end card's underline. */
    accent: accentSchema.default("kcal"),
    /** Sources of the stated numbers (GOAL.md §5.6). Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /** Voice track (048b rule): `lines` = one timing per script line: each scene, then the outro. */
    voice: z.strictObject({ audioSrc: z.string().min(1).optional(), lines: z.array(voiceLine).optional() }).optional(),
    /** The Blender plates, all shots end to end (src/studio/macro3d.py fills it at render time): a video, or an image for a still. None = the dark void alone. */
    plate: z.string().min(1).optional(),
    music: z.enum(["music-cutaway-c", "music-cutaway-b", "music-dusk", "music-nocturne", "none"]).default("music-cutaway-c"),
    /** Off by default: the end card closes the video. */
    loop: z.boolean().default(false),
    safeZone: z.boolean().optional(),
  })
  .superRefine((p, ctx) => {
    p.scenes.forEach((s, i) => {
      if (s.key && !keyIndexes(wordTimes(s.line, 0, 1), s.key).length) {
        ctx.addIssue({ code: "custom", path: ["scenes", i, "key"], message: `the key word must be words of the line (« ${s.key} »)` });
      }
      if (s.counter && s.counter.from === s.counter.to) {
        ctx.addIssue({ code: "custom", path: ["scenes", i, "counter"], message: "a counter must move (from ≠ to)" });
      }
    });
    const lines = macro3dScript(p).lines.length;
    if (p.voice?.lines && p.voice.lines.length !== lines) {
      ctx.addIssue({ code: "custom", path: ["voice", "lines"], message: `voice.lines needs one timing per script line: each scene, then the outro (${lines})` });
    }
  });

export type Macro3DProps = z.infer<typeof macro3dSchema>;

/** Script lines: [...scenes, outro?] (048b: the voice reads what the viewer sees); voice timings when given. */
export const macro3dScript = ({ scenes, outro, voice }: Pick<Macro3DProps, "scenes" | "outro" | "voice">) => ({
  lines: [...scenes.map((s) => s.line), ...(outro ? [outro] : [])],
  timings: voice?.lines,
});

/** Reading speed estimated without a voice: the studio voice reads about 20 characters a second (step-154 samples), faster than lib/timeline's caption estimate. */
export const VOICE_CHARS_PER_S = 19;

/** End card hold after the outro line is read (the card itself lasts at least CARD_S.macro3d). */
export const END_HOLD_S = 1.2;

/**
 * Scenes in frames (one per script line, the outro last when there is one) and where the end
 * card starts: at the outro line, else after the last scene.
 */
export const timelineOf = (p: Macro3DProps, fps: number) => {
  const script = macro3dScript(p);
  let t = 0;
  const timings: Timing[] =
    script.timings ??
    script.lines.map((text) => {
      const read = Math.max(1.8, Array.from(text).length / VOICE_CHARS_PER_S);
      const timing = { text, start_s: t, end_s: t + read };
      t += read + LINE_GAP_S;
      return timing;
    });
  const build = (outroSeconds: number) => buildTimeline({ lines: script.lines, timings, fps, hookSeconds: 2, outroSeconds, loop: p.loop });
  const cardStart = (tl: Timeline) => (p.outro ? tl.scenes[tl.scenes.length - 1].startFrame : tl.outroStart);
  const timeline = fitEndCard(build, p.outro ? END_HOLD_S : CARD_S.macro3d, cardStart, CARD_S.macro3d, fps);
  return { timeline, endStart: cardStart(timeline), timings };
};
