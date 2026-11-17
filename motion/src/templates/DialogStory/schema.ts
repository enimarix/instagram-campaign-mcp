// DialogStory props, script mapping and talk timing. Imports only zod (and a type), so
// `node --test` runs it directly (test/dialogstory.test.ts).
import { z } from "zod";
import type { Timeline, Timing } from "../../lib/timeline";

const hex = z.string().regex(/^#[0-9a-fA-F]{6}$/, "a #RRGGBB colour");

/** One voice line (TTS, step 036/048): seconds from the start of the video. */
const voiceLine = z.strictObject({
  text: z.string(),
  start_s: z.number().min(0),
  end_s: z.number().min(0),
});

/** Sprite sheets in src/assets.ts a character can use as its portrait. */
export const CHARACTER_SPRITES = ["mascot", "slime", "coin", "heart"] as const;

/** Music loops in the asset registry the story can play (042). */
export const MUSIC = ["music-overworld", "music-cave", "none"] as const;

/** 16 chars fit the name tag and half the safe area at scale 3. */
const character = z.strictObject({
  name: z.string().min(1).max(16),
  sprite: z.enum(CHARACTER_SPRITES).optional(),
  side: z.enum(["left", "right"]),
});

export const dialogStorySchema = z
  .strictObject({
    /** Script line 0: big on the hook card from frame 0 (the Reel cover), the cast under it. */
    hook: z.string().min(1).max(120),
    /** The two speakers (default portraits: mascot, slime), one on each side. */
    characters: z.array(character).length(2),
    /**
     * 3–8 dialogue lines, each typed into a dialog box with the speaker's name tag while the
     * speaker's portrait bounces. `speaker` = index in `characters`. 100 chars fit the box.
     */
    lines: z
      .array(z.strictObject({ speaker: z.literal([0, 1]), text: z.string().min(1).max(100) }))
      .min(3)
      .max(8),
    /** Last line, typed into a box without a name tag (the moral of the story). */
    moral: z.string().min(1).max(120).optional(),
    /** Sources of the story's facts (GOAL.md §5.6), carried from the idea. Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /** Small line under the last box when there are citations, e.g. "Sources in caption". */
    sourcesNote: z.string().min(1).max(40).optional(),
    /**
     * Voice track (step 048). `lines` = one timing per script line: hook, each dialogue line,
     * moral (when given); none = timings estimated from the text length. `audioSrc`: URL or
     * `staticFile()` path.
     */
    voice: z.strictObject({ audioSrc: z.string().min(1).optional(), lines: z.array(voiceLine).optional() }).optional(),
    /** Background loop under everything (src/assets.ts), or "none". */
    music: z.enum(MUSIC).default("music-overworld"),
    /** Fade back into frame 0 at the end so the Reel loops seamlessly. */
    loop: z.boolean().default(true),
    /** Template colours (background, portrait frames, wipes); the kit components keep the brand's. */
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
  // Refines also run after a failed length check (zod 4): read characters with `?.`.
  .refine((p) => p.characters[0]?.side !== p.characters[1]?.side, {
    message: "characters need one on each side: left and right",
    path: ["characters"],
  })
  .refine((p) => p.lines.some((l) => l.speaker === 0) && p.lines.some((l) => l.speaker === 1), {
    message: "a dialogue: both characters need at least one line",
    path: ["lines"],
  })
  .refine((p) => !p.voice?.lines || p.voice.lines.length === dialogStoryScript(p).lines.length, {
    message: "voice.lines needs one timing per script line: hook, each dialogue line, moral (when given)",
    path: ["voice", "lines"],
  });

export type DialogStoryProps = z.infer<typeof dialogStorySchema>;

/** Script lines for buildTimeline: [hook, ...dialogue lines, moral?]; voice timings when given. */
// Typed by shape, not DialogStoryProps: the schema's voice refine calls it.
export function dialogStoryScript(p: { hook: string; lines: { text: string }[]; moral?: string; voice?: { lines?: Timing[] } }) {
  return { lines: [p.hook, ...p.lines.map((l) => l.text), ...(p.moral ? [p.moral] : [])], timings: p.voice?.lines };
}

/** What each script scene shows: the hook card, a character's line, or the moral. */
export type Role = { kind: "hook" } | { kind: "line"; speaker: 0 | 1 } | { kind: "moral" };

/** Role of each scene, by scene index (same order as `dialogStoryScript().lines`). */
export const sceneRoles = ({ lines, moral }: Pick<DialogStoryProps, "lines" | "moral">): Role[] => [
  { kind: "hook" },
  ...lines.map((l) => ({ kind: "line" as const, speaker: l.speaker })),
  ...(moral ? [{ kind: "moral" as const }] : []),
];

/** Frames of the beat at the start of each line (empty box, new name tag) before it types. */
export const BEAT = 6;

/**
 * Frames a scene's speaker talks (portrait bounces): from the end of the beat until the text is
 * typed at `cps` or, with a voice, until the voice line ends, whichever is later; never past the
 * scene. Returns [start, end).
 */
export const talkSpan = (t: Timeline, index: number, cps: number, fps: number, voiceEnd_s?: number): [number, number] => {
  const s = t.scenes[index];
  const start = s.startFrame + BEAT;
  const typed = start + Math.ceil((Array.from(s.text.normalize("NFC")).length * fps) / cps);
  const voiced = voiceEnd_s === undefined ? 0 : Math.round(voiceEnd_s * fps);
  // The last scene ends at outroStart but holds through the outro: still stop there.
  return [start, Math.max(start, Math.min(s.endFrame, Math.max(typed, voiced)))];
};
