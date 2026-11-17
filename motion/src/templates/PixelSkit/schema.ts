// PixelSkit props, script mapping and comic timing (hold, freeze, voice parts, action poses).
// Imports only zod (and types), so `node --test` runs it directly (test/pixelskit.test.ts).
import { z } from "zod";
import type { Timeline, Timing } from "../../lib/timeline";

const hex = z.string().regex(/^#[0-9a-fA-F]{6}$/, "a #RRGGBB colour");

/** One voice line (TTS, step 036/048): seconds from the start of the video. */
const voiceLine = z.strictObject({
  text: z.string(),
  start_s: z.number().min(0),
  end_s: z.number().min(0),
});

/** Sprite sheets in src/assets.ts an actor can be played by. */
export const ACTOR_SPRITES = ["mascot", "slime", "coin", "heart"] as const;

/** Music loops in the asset registry the skit can play (042). */
export const MUSIC = ["music-overworld", "music-cave", "none"] as const;

/** Sound effects a beat or the sting can play: `sfx-<name>` in src/assets.ts. */
export const SFX = ["hit", "jump", "select", "confirm", "coin"] as const;

/**
 * What the beat's actor does, from the moment its box opens:
 * idle (animates in place), walk_in (walks in from its side), jump (one hop), shake (trembles),
 * fall (tips over and stays down), stare (frozen, "..." appears over it), facepalm (frozen, a
 * hand slaps over its face).
 */
export const ACTIONS = ["idle", "walk_in", "jump", "shake", "fall", "stare", "facepalm"] as const;
export type Action = (typeof ACTIONS)[number];

const beat = z.strictObject({
  /** Index in `cast`: the name tag on the box and the actor. None = no tag, `cast[0]` acts. */
  speaker: z.literal([0, 1]).optional(),
  /** 80 chars fit the box in three lines. */
  line: z.string().min(1).max(80),
  action: z.enum(ACTIONS).default("idle"),
  /** Played as the action starts. */
  sfx: z.enum(SFX).optional(),
});

export const pixelSkitSchema = z
  .strictObject({
    /** Script line 0: big on the hook card from frame 0 (the Reel cover), e.g. "POV: …"; the cast under it. */
    hook: z.string().min(1).max(120),
    /** 1–2 actors on stage (default sprites: mascot, slime); the first stands left, the second right. */
    cast: z
      .array(z.strictObject({ name: z.string().min(1).max(16), sprite: z.enum(ACTOR_SPRITES).optional() }))
      .min(1)
      .max(2),
    /**
     * 2–4 beats: setup, escalation…, punchline (the last beat, or the one before it with `tag`).
     * Each beat's line types into a dialog box while its actor plays the action.
     */
    beats: z.array(beat).min(2).max(4),
    /** The last beat is a tag after the punchline (needs 3+ beats). */
    tag: z.boolean().default(false),
    /** Seconds of silence (the previous beat holds) before the punchline. */
    holdBeforePunchline_s: z.number().min(0).max(2).default(0.6),
    /** Freeze the picture for a moment once the punchline has landed (typed, or voiced). */
    freezeOnPunchline: z.boolean().default(true),
    /** Sound when the punchline lands, or "none". */
    sting: z.enum([...SFX, "none"]).default("hit"),
    /** Sources (GOAL.md §5.6), usually empty for humour. Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /** Small line under the last box when there are citations, e.g. "Sources in caption". */
    sourcesNote: z.string().min(1).max(40).optional(),
    /**
     * Voice track (step 048). `lines` = one timing per script line: hook, then one per beat; none =
     * timings estimated from the text length. The voice pauses through the hold and the freeze
     * (the template plays it in parts), so its timings are those of the plain audio file.
     * `audioSrc`: URL or `staticFile()` path.
     */
    voice: z.strictObject({ audioSrc: z.string().min(1).optional(), lines: z.array(voiceLine).optional() }).optional(),
    /** Background loop under everything (src/assets.ts), or "none". */
    music: z.enum(MUSIC).default("music-overworld"),
    /** Fade back into frame 0 at the end so the Reel loops seamlessly. */
    loop: z.boolean().default(true),
    /** Template colours (background, ground, wipes); the kit components keep the brand's. */
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
  // Refines also run after a failed length check (zod 4): read arrays with `?.`.
  .refine((p) => !p.beats?.some((b) => b.speaker !== undefined && b.speaker >= (p.cast?.length ?? 0)), {
    message: "a beat's speaker must be the index of one of the cast",
    path: ["beats"],
  })
  .refine((p) => !p.tag || p.beats?.length >= 3, {
    message: "a tag needs 3+ beats: setup, punchline, tag",
    path: ["tag"],
  })
  .refine((p) => !p.voice?.lines || p.voice.lines.length === (p.beats?.length ?? 0) + 1, {
    message: "voice.lines needs one timing per script line: hook, then one per beat",
    path: ["voice", "lines"],
  });

export type PixelSkitProps = z.infer<typeof pixelSkitSchema>;

/** Script lines for buildTimeline: [hook, ...beat lines]; voice timings when given. */
export const pixelSkitScript = (p: { hook: string; beats: { line: string }[]; voice?: { lines?: Timing[] } }) => ({
  lines: [p.hook, ...p.beats.map((b) => b.line)],
  timings: p.voice?.lines,
});

/** Scene index of the punchline (scene 0 is the hook, beat i is scene i + 1). */
export const punchlineScene = ({ beats, tag }: Pick<PixelSkitProps, "beats" | "tag">) => beats.length - (tag ? 1 : 0);

/** Frames of the beat at the start of each scene (empty box) before the line types and the action starts. */
export const BEAT = 6;

/** Seconds the frozen picture holds on the punchline. */
export const FREEZE_S = 1;

/** A pause inserted at frame `at` of the plain timeline, `frames` long. */
export type Pause = { at: number; frames: number };

/**
 * The plain timeline with `pauses` inserted: every frame x moves back by the pauses at or before
 * it, so the scene that ends at a pause grows by it (the hold keeps the previous beat up; the
 * freeze lengthens the punchline).
 */
export const withPauses = (t: Timeline, pauses: Pause[]): Timeline => {
  const shift = (x: number) => x + pauses.reduce((n, p) => n + (p.at <= x ? p.frames : 0), 0);
  return {
    ...t,
    scenes: t.scenes.map((s) => ({ ...s, startFrame: shift(s.startFrame), endFrame: shift(s.endFrame) })),
    outroStart: shift(t.outroStart),
    totalFrames: t.totalFrames + pauses.reduce((n, p) => n + p.frames, 0),
  };
};

/**
 * Comic timing on the plain script timeline `t`: the hold before the punchline scene, the frame
 * the punchline lands (typed at `cps`, or voiced, whichever is later; never past its scene) and
 * the freeze there. Returns the final timeline, the pauses (plain frames) and, in final frames,
 * `land` (sting) and the freeze span [freezeStart, freezeEnd) (empty without the freeze).
 */
export const comicTiming = (
  t: Timeline,
  p: Pick<PixelSkitProps, "beats" | "tag" | "holdBeforePunchline_s" | "freezeOnPunchline" | "voice">,
  cps: number,
  fps: number,
) => {
  const punch = punchlineScene(p);
  const hold = Math.round(p.holdBeforePunchline_s * fps);
  const freeze = p.freezeOnPunchline ? Math.round(FREEZE_S * fps) : 0;
  // As DialogStory's talkSpan: typed or voiced, whichever is later, never past the scene.
  const s = t.scenes[punch];
  const typed = s.startFrame + BEAT + Math.ceil((Array.from(s.text.normalize("NFC")).length * fps) / cps);
  const voiceEnd = p.voice?.lines?.[punch].end_s;
  const landed = Math.min(s.endFrame, Math.max(typed, voiceEnd === undefined ? 0 : Math.round(voiceEnd * fps)));
  const pauses = [
    { at: s.startFrame, frames: hold },
    { at: landed, frames: freeze },
  ].filter((x) => x.frames > 0);
  const land = landed + hold;
  return { timeline: withPauses(t, pauses), pauses, punch, land, freezeStart: land, freezeEnd: land + freeze };
};

/**
 * The voice file in parts around the pauses: part k plays the plain audio from frame `trimBefore`
 * for `frames` frames (none = to the end) starting at final frame `from`.
 */
export const voiceParts = (pauses: Pause[]) => {
  let gap = 0;
  return [{ at: 0, frames: 0 }, ...pauses].map((p, i, all) => {
    gap += p.frames;
    const next = all[i + 1];
    return { from: p.at + gap, trimBefore: p.at, frames: next ? next.at - p.at : undefined };
  });
};

/** Frames of a walk-in, hop, shake or fall. */
export const ACTION_FRAMES = 12;
/** Hop height and walk-in distance, in sprite pixels. */
const HOP = 6;
const WALK = 24;

/**
 * The actor's pose `f` frames after its action starts (negative = not yet): offset in sprite
 * pixels (dx > 0 = right, dy < 0 = up; a walk-in starts out on the actor's side), tilt in degrees
 * (a fall tips outward in 3 hard steps), whether the sprite animates, the "..." dots (stare) and
 * the hand (facepalm).
 */
export const actionPose = (action: Action, f: number, side: "left" | "right") => {
  const p = Math.min(1, Math.max(0, f / ACTION_FRAMES));
  const out = side === "left" ? -1 : 1;
  const pose = { dx: 0, dy: 0, tilt: 0, animate: true, dots: 0, hand: false };
  switch (action) {
    case "walk_in":
      return { ...pose, dx: Math.round(out * WALK * (1 - p)) };
    case "jump":
      return { ...pose, dy: -Math.round(Math.sin(Math.PI * p) * HOP) };
    case "shake":
      return { ...pose, dx: f >= 0 && f < ACTION_FRAMES ? (Math.floor(f / 2) % 2 ? 1 : -1) : 0 };
    case "fall":
      return { ...pose, tilt: out * 90 * Math.round(p * 3) / 3, animate: false };
    case "stare":
      return { ...pose, animate: false, dots: Math.min(3, Math.max(0, Math.floor(f / 8) + 1)) };
    case "facepalm":
      return { ...pose, animate: false, hand: f >= ACTION_FRAMES / 2 };
    default:
      return pose;
  }
};
