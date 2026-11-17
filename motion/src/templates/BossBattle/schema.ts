// BossBattle props, script mapping and health maths. Imports only zod, so `node --test` runs
// it directly (test/bossbattle.test.ts).
import { z } from "zod";

const hex = z.string().regex(/^#[0-9a-fA-F]{6}$/, "a #RRGGBB colour");

/** One voice line (TTS, step 036/048): seconds from the start of the video. */
const voiceLine = z.strictObject({
  text: z.string(),
  start_s: z.number().min(0),
  end_s: z.number().min(0),
});

/** Sprite sheets in src/assets.ts a fighter can use. */
export const FIGHTER_SPRITES = ["mascot", "slime", "coin", "heart"] as const;

const side = z.enum(["left", "right"]);
export type Side = z.infer<typeof side>;

/** 16 chars fit half the safe area at scale 3. */
const fighter = z.strictObject({ name: z.string().min(1).max(16), sprite: z.enum(FIGHTER_SPRITES).optional() });

export const bossBattleSchema = z
  .strictObject({
    /** Script line 0: big on the hook card from frame 0 (the Reel cover). */
    hook: z.string().min(1).max(120),
    /** Fighter on the left (default sprite mascot) and on the right (default slime), e.g. myth vs fact. */
    left: fighter,
    right: fighter,
    /** One "ROUND n" scene each: `attacker` lands a hit, `text` (the argument) types into the caption band. */
    rounds: z
      .array(z.strictObject({ attacker: side, text: z.string().min(1).max(120) }))
      .min(2)
      .max(4),
    /** Last scene: the winner knocks the loser out (a draw leaves both standing); `text` types into the band. */
    verdict: z.strictObject({ winner: z.enum(["left", "right", "draw"]), text: z.string().min(1).max(120) }),
    /** Sources of the arguments (GOAL.md §5.6), carried from the idea. Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /** Small line under the verdict when there are citations, e.g. "Sources in caption". */
    sourcesNote: z.string().min(1).max(40).optional(),
    /**
     * Voice track (step 048). `lines` = one timing per script line: hook, each round, verdict;
     * none = timings estimated from the text length. `audioSrc`: URL or `staticFile()` path.
     */
    voice: z.strictObject({ audioSrc: z.string().min(1).optional(), lines: z.array(voiceLine).optional() }).optional(),
    /** Fade back into frame 0 at the end so the Reel loops seamlessly. */
    loop: z.boolean().default(true),
    /** Template colours (background, titles, wipes, flash); the kit components keep the brand's. */
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
  .refine((p) => !p.voice?.lines || p.voice.lines.length === p.rounds.length + 2, {
    message: "voice.lines needs one timing per script line: hook, each round, verdict",
    path: ["voice", "lines"],
  });

export type BossBattleProps = z.infer<typeof bossBattleSchema>;

/** Script lines for buildTimeline: [hook, ...round texts, verdict text]; voice timings when given. */
export const bossBattleScript = ({ hook, rounds, verdict, voice }: BossBattleProps) => ({
  lines: [hook, ...rounds.map((r) => r.text), verdict.text],
  timings: voice?.lines,
});

export type Health = Record<Side, number>;

export const foe = (s: Side): Side => (s === "left" ? "right" : "left");

/**
 * Health (0..1) of both fighters at the start and after each scene's hit: [start, after round
 * 1..N, after the verdict] (index = scene index). A round's hit takes 1/(N+1) from the attacker's
 * foe, so nobody falls before the verdict; the verdict knocks the loser out, a draw changes nothing.
 */
export const healthSteps = ({ rounds, verdict }: Pick<BossBattleProps, "rounds" | "verdict">): Health[] => {
  const hits: Health = { left: 0, right: 0 };
  const at = (): Health => ({
    left: 1 - hits.left / (rounds.length + 1),
    right: 1 - hits.right / (rounds.length + 1),
  });
  const steps = [at()];
  for (const r of rounds) {
    hits[foe(r.attacker)]++;
    steps.push(at());
  }
  const end = at();
  if (verdict.winner !== "draw") end[foe(verdict.winner)] = 0;
  return [...steps, end];
};
