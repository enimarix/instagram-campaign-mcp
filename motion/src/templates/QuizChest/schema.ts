// QuizChest props, script mapping and countdown maths. Imports only zod and pure modules (and a type), so
// `node --test` runs it directly (test/quizchest.test.ts).
import { z } from "zod";
import { screenText } from "../../endcards/schema.ts";
import type { Timeline } from "../../lib/timeline";

const hex = z.string().regex(/^#[0-9a-fA-F]{6}$/, "a #RRGGBB colour");

/** One voice line (TTS, step 036/048): seconds from the start of the video. */
const voiceLine = z.strictObject({
  text: z.string(),
  start_s: z.number().min(0),
  end_s: z.number().min(0),
});

/** Music loops in the asset registry a quiz can play (042). */
export const MUSIC = ["music-overworld", "music-cave", "none"] as const;

export const quizChestSchema = z
  .strictObject({
    /** Script line 0: big on the hook card from frame 0 (the Reel cover). */
    hook: z.string().min(1).max(120),
    /** Script line 1: shown whole above the choices, through the countdown and the reveal. */
    question: z.string().min(1).max(120),
    /** 2–4 answers, e.g. {label: "A", text: "…"}; 40 chars fit two lines at scale 3. */
    choices: z
      .array(z.strictObject({ label: z.string().min(1).max(3), text: z.string().min(1).max(40) }))
      .min(2)
      .max(4),
    /** Index of the right choice in `choices` (0-based). */
    answer: z.number().int().min(0),
    /** Seconds the countdown runs after the question (one tick + sfx per second). */
    countdownSeconds: z.number().int().min(3).max(10).default(5),
    /** Script line 2: why that answer, typed into the caption band after the reveal. */
    explanation: z.string().min(1).max(120),
    /** Script line 3: end card inviting comments. */
    cta: screenText(40).default("Comment your answer!"),
    /** Sources of the answer (GOAL.md §5.6), carried from the idea. Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /** Small line under the end card when there are citations, e.g. "Sources in caption". */
    sourcesNote: screenText(40).optional(),
    /**
     * Voice track (step 048). `lines` = one timing per script line: hook, question (may read the
     * choices too), explanation, cta; none = timings estimated from the text length. The voice
     * pauses through the countdown and reveal (the template plays it in two parts), so its timings
     * are those of the plain audio file. `audioSrc`: URL or `staticFile()` path.
     */
    voice: z.strictObject({ audioSrc: z.string().min(1).optional(), lines: z.array(voiceLine).optional() }).optional(),
    /** Background loop under everything (src/assets.ts), or "none". */
    music: z.enum(MUSIC).default("music-overworld"),
    /** Fade back into frame 0 at the end so the Reel loops seamlessly. */
    loop: z.boolean().default(true),
    /** Template colours (background, titles, highlight, wipes); the kit components keep the 8-bit defaults (lib/palette.ts). */
    palette: z
      .strictObject({
        primary: hex.optional(),
        secondary: hex.optional(),
        accent: hex.optional(),
        background: hex.optional(),
        text: hex.optional(),
      })
      .optional(),
    safeZone: z.boolean().optional(),
  })
  .refine((p) => p.answer < p.choices.length, {
    message: "answer must be the index of one of the choices",
    path: ["answer"],
  })
  .refine((p) => !p.voice?.lines || p.voice.lines.length === 4, {
    message: "voice.lines needs one timing per script line: hook, question, explanation, cta",
    path: ["voice", "lines"],
  });

export type QuizChestProps = z.infer<typeof quizChestSchema>;

/** Script lines for buildTimeline: [hook, question, explanation, cta]; voice timings when given. */
export const quizChestScript = ({ hook, question, explanation, cta, voice }: QuizChestProps) => ({
  lines: [hook, question, explanation, cta],
  timings: voice?.lines,
});

/** Seconds the opened chest holds before the explanation. */
export const REVEAL_S = 1.5;

/**
 * The script timeline with the countdown and reveal inserted after the question: the question
 * scene (1) grows by them, later scenes and the outro move back. `countdownStart` = the frame the
 * question line ended at (where the voice pauses), `reveal` = the frame the chest opens.
 */
export const withCountdown = (t: Timeline, countdownSeconds: number, fps: number) => {
  const countdownStart = t.scenes[1].endFrame;
  const reveal = countdownStart + countdownSeconds * fps;
  const gap = reveal - countdownStart + Math.round(REVEAL_S * fps);
  const timeline: Timeline = {
    ...t,
    scenes: t.scenes.map((s) =>
      s.index < 1 ? s : s.index === 1 ? { ...s, endFrame: s.endFrame + gap } : { ...s, startFrame: s.startFrame + gap, endFrame: s.endFrame + gap },
    ),
    outroStart: t.outroStart + gap,
    totalFrames: t.totalFrames + gap,
  };
  return { timeline, countdownStart, reveal, gap };
};

/** Frames of the countdown ticks (one per second, each with its sfx). */
export const countdownTicks = (start: number, seconds: number, fps: number) =>
  Array.from({ length: seconds }, (_, i) => start + i * fps);

/** Number on screen at `frame` (seconds..1), none outside the countdown. */
export const countdownAt = (frame: number, start: number, seconds: number, fps: number): number | undefined =>
  frame < start || frame >= start + seconds * fps ? undefined : seconds - Math.floor((frame - start) / fps);
