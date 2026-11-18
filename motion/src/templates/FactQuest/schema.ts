// FactQuest props and script mapping. Imports only zod and pure modules, so `node --test` runs it directly
// (test/factquest.test.ts).
import { z } from "zod";
import { screenText } from "../../endcards/schema.ts";

const hex = z.string().regex(/^#[0-9a-fA-F]{6}$/, "a #RRGGBB colour");

/** One voice line (TTS, step 036/048): seconds from the start of the video. */
const voiceLine = z.strictObject({
  text: z.string(),
  start_s: z.number().min(0),
  end_s: z.number().min(0),
});

export const factQuestSchema = z
  .strictObject({
    /** Script line 0: big on the hook card from frame 0 (the Reel cover). */
    hook: z.string().min(1).max(120),
    /** One "LEVEL n" scene each. `text` types into the caption band (~120 chars fit at scale 4). */
    facts: z
      .array(z.strictObject({ title: z.string().min(1).max(24).optional(), text: z.string().min(1).max(120) }))
      .min(3)
      .max(5),
    /** The end card's tagline (pixel card, step 137), e.g. "Follow for level 2". Never a price. */
    outro: screenText(60),
    /** Sources of the facts (GOAL.md §5.6), carried from the idea. Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /** Small end-card line shown when there are citations, e.g. "Sources in caption". */
    sourcesNote: screenText(40).optional(),
    /**
     * Voice track (step 048). `lines` = one timing per script line: hook, each fact, outro;
     * none = timings estimated from the text length. `audioSrc`: URL or `staticFile()` path.
     */
    voice: z.strictObject({ audioSrc: z.string().min(1).optional(), lines: z.array(voiceLine).optional() }).optional(),
    /** Background loop under everything (src/assets.ts), or "none". */
    music: z.enum(["music-overworld", "music-cave", "none"]).default("music-overworld"),
    /** Fade back into frame 0 at the end so the Reel loops seamlessly. */
    loop: z.boolean().default(true),
    /** Template colours (background, headings, wipes); the kit components keep the 8-bit defaults (lib/palette.ts). */
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
  .refine((p) => !p.voice?.lines || p.voice.lines.length === p.facts.length + 2, {
    message: "voice.lines needs one timing per script line: hook, each fact, outro",
    path: ["voice", "lines"],
  });

export type FactQuestProps = z.infer<typeof factQuestSchema>;

/** Script lines for buildTimeline: [hook, ...fact texts, outro]; voice timings when given. */
export const factQuestScript = ({ hook, facts, outro, voice }: FactQuestProps) => ({
  lines: [hook, ...facts.map((f) => f.text), outro],
  timings: voice?.lines,
});
