// SitcomSkit props, script mapping and timings (step 164): « Sitcom 3D absurde ». The troupe of the
// Blender engine (cinematic/cast.json: 16 characters, 6 sets, actions.json) plays an absurd skit
// under a French voice-over (tu): the AI writes scenes (a set, a cast of 5-8 with roles, beats
// with one action each, the voice-over line, maybe a short character line in its own voice, a
// big number); src/studio/sitcom.py turns the timed parts below into the shot list Blender
// renders (a cut every 1-2 s, 3+ angles a scene, x10 / slow-mo, the punchline frozen, action from
// frame 1). This template draws the bold karaoke captions, the hook, the speech bubbles, the big
// numbers and the end card over the shots. Imports only zod and pure modules, so `node --test` runs it.
import { z } from "zod";
import { accentSchema, addressSchema, CARD_S, screenText } from "../../endcards/schema.ts";
import { LIBRARY_SFX } from "../../lib/duck.ts";
import { LINE_GAP_S } from "../../lib/timeline.ts";
import { keyIndexes, wordTimes } from "../../macro3d/words.ts";

/** One voice line (TTS, step 036/048): seconds in the voice file. */
const voiceLine = z.strictObject({ text: z.string(), start_s: z.number().min(0), end_s: z.number().min(0) });

/** Sounds a beat can start with (cartoon foley, motion/src/assets.ts). */
export const SITCOM_SFX = ["boing", "whoosh", "clatter", "gasp", "hit", "pop"] as const;
export const SFX_FILE = { boing: "sfx-boing", whoosh: "sfx-swish", clatter: "sfx-clatter", gasp: "sfx-gasp", hit: "sfx-hit", pop: "sfx-pop" } as const;

/** How the beat's shots play: x10 fast-forward (repeated gestures: crunches), slow-mo (a ramp into 0.3x: a faint, a crushing bar). */
export const SPEEDS = ["normal", "x10", "slowmo"] as const;

const who = z.string().min(1).describe("A troupe character (cinematic/cast.json): dad, mum, grandma, grandpa, teen, kid_boy, kid_girl, aunt, uncle, cousin, coach, gym_girl, gym_mum, chef, waiter, neighbour");

const member = z.strictObject({
  who,
  /** Who they are in this skit (« le beau-frère », « ta pote de salle »): shown on their speech bubble. */
  role: screenText(24).optional(),
  /** A spot of the set (cinematic/sets.json); none = picked: a seat when they sit, the floor for a crunch, else a standing mark. */
  at: z.string().min(1).optional(),
  /** What they do when not the beat's actor (cinematic/actions.json, e.g. fork_up, Sitting_Idle_Loop, cheer); none = sit or stand idle. */
  action: z.string().min(1).optional(),
});

const beat = z.strictObject({
  /** The voice-over line (tu), captioned word by word as it is said. One beat = one action = one line. */
  line: screenText(120),
  /** A word (or a few, in order) of the line that pops out bigger, in emerald. */
  key: screenText(24).optional(),
  /** The beat's actor: one of the scene's cast. */
  who,
  /** What they do (cinematic/actions.json: crunch, faint, fork_up, phone_photo, cheer, shout, curl, carry_plate, or a library clip like Death01, Hit_Chest, Jump_Loop, Dance_Loop). */
  action: z.string().min(1),
  /** Their face (jaw_drop, outraged, shout, smile, disgust). */
  face: z.string().optional(),
  /** Everyone else's face on this beat; none = a mix of jaw drops and outrage. */
  react: z.string().optional(),
  speed: z.enum(SPEEDS).default("normal"),
  /** A short line a character shouts after the voice-over line (« Allez ! »), in its own voice, in a bubble. */
  say: z
    .strictObject({
      who,
      text: screenText(48),
      /** Filled by the studio (src/studio/sitcom.py): the line's audio and its length. */
      audioSrc: z.string().min(1).optional(),
      seconds: z.number().min(0.2).max(6).optional(),
    })
    .optional(),
  /** The key fact as a big number over the action (counts up from `from` when given). A stated fact needs its source in `citations`. */
  number: z.strictObject({ value: z.number(), from: z.number().optional(), unit: screenText(14).optional(), decimals: z.number().int().min(0).max(1).default(0) }).optional(),
  /** A cartoon sound as the beat starts: a built-in name or a library `ov:<id>` (find_sfx, step 150: a real fork drop, gasp, laugh...). */
  sfx: z.union([z.enum(SITCOM_SFX), z.string().regex(LIBRARY_SFX, "a library sound: ov:<id> from find_sfx")]).optional(),
});

const scene = z.strictObject({
  /** A set (cinematic/sets.json): dinner, living, gym, kitchen, restaurant, beach. */
  set: z.string().min(1),
  /** A slate as the scene opens (« 6 MOIS PLUS TARD », « L'ÉTÉ »). */
  label: screenText(28).optional(),
  /** Who is in the scene (1-8). */
  cast: z.array(member).min(1).max(8),
  /** 1-4 beats. */
  beats: z.array(beat).min(1).max(4),
});
export type Scene = z.infer<typeof scene>;

const words = (s: string) => s.trim().split(/\s+/).filter(Boolean).length;

export const sitcomSchema = z
  .strictObject({
    /** The hook, 6 words at most, big over the opening action from frame 0 and read first. */
    hook: screenText(48).refine((s) => words(s) <= 6, "the hook is 6 words at most"),
    /** 1-4 scenes; the last beat of the last scene is the punchline (the picture freezes on it). */
    scenes: z.array(scene).min(1).max(4),
    /** The end card's tagline, read aloud as the last line; none = the app's tagline. */
    outro: screenText(70).optional(),
    address: addressSchema.default("tu"),
    /** Colour of the big numbers and the end card's underline (the topic's macro); emerald = brand. */
    accent: accentSchema.default("brand"),
    /** Sources of the stated numbers (GOAL.md §5.6). Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /** The narrator (048b rule): `lines` = one timing per script line: hook, every beat's line, then the outro. */
    voice: z.strictObject({ audioSrc: z.string().min(1).optional(), lines: z.array(voiceLine).optional() }).optional(),
    /** The troupe's shots end to end (src/studio/sitcom.py fills it at render time): a video, or an image for a still. */
    plate: z.string().min(1).optional(),
    music: z.enum(["music-sitcom", "music-marimba", "music-cutaway-c", "none"]).default("music-sitcom"),
    loop: z.boolean().default(false),
    safeZone: z.boolean().optional(),
  })
  .superRefine((p, ctx) => {
    const cast = new Set<string>();
    p.scenes.forEach((s, i) => {
      const here = s.cast.map((m) => m.who);
      here.forEach((w) => cast.add(w));
      if (new Set(here).size !== here.length) ctx.addIssue({ code: "custom", path: ["scenes", i, "cast"], message: "a character plays once per scene" });
      s.beats.forEach((b, j) => {
        if (!here.includes(b.who)) ctx.addIssue({ code: "custom", path: ["scenes", i, "beats", j, "who"], message: `the beat's actor must be in the scene's cast (${here.join(", ")})` });
        if (b.say && !here.includes(b.say.who)) ctx.addIssue({ code: "custom", path: ["scenes", i, "beats", j, "say", "who"], message: "who says the line must be in the scene's cast" });
        if (b.key && !keyIndexes(wordTimes(b.line, 0, 1), b.key).length) ctx.addIssue({ code: "custom", path: ["scenes", i, "beats", j, "key"], message: `the key word must be words of the line (« ${b.key} »)` });
        if (b.number && b.number.from === b.number.value) ctx.addIssue({ code: "custom", path: ["scenes", i, "beats", j, "number"], message: "a counting number must move (from ≠ value)" });
      });
    });
    if (cast.size < 5 || cast.size > 8) ctx.addIssue({ code: "custom", path: ["scenes"], message: `a sitcom has a troupe of 5-8 characters across its scenes (${cast.size})` });
    const lines = sitcomScript(p).lines.length;
    if (p.voice?.lines && p.voice.lines.length !== lines) {
      ctx.addIssue({ code: "custom", path: ["voice", "lines"], message: `voice.lines needs one timing per script line: hook, each beat, then the outro (${lines})` });
    }
  });

export type SitcomProps = z.infer<typeof sitcomSchema>;
export type Beat = SitcomProps["scenes"][number]["beats"][number];

/** The narrator's script: [hook, ...every beat's line, outro?]; voice timings when given. */
export const sitcomScript = (p: Pick<SitcomProps, "hook" | "scenes" | "outro" | "voice">) => ({
  lines: [p.hook, ...p.scenes.flatMap((s) => s.beats.map((b) => b.line)), ...(p.outro ? [p.outro] : [])],
  timings: p.voice?.lines,
});

/** Without a voice: the narrator's estimated pace (the energetic voice is quick). */
export const VOICE_CHARS_PER_S = 17;
/** A character line's estimated length without audio. */
export const sayEstimate = (text: string) => Math.max(0.8, Array.from(text).length / 13 + 0.3);
/** Silence around a character line, and the frozen punchline. */
export const SAY_GAP_S = 0.2;
export const FREEZE_S = 0.9;
/** The hook stays at least this long (the opening action reads under it). */
export const HOOK_MIN_S = 1.6;
/** After the outro is read the card holds this long (the card lasts at least CARD_S.sitcom). */
export const END_HOLD_S = 1.2;

/** One stretch of the video: the hook, a beat's line, a character's line, the frozen punchline. Seconds on the video's clock. */
export type Part = { scene: number; beat: number; part: "hook" | "line" | "say" | "freeze"; start_s: number; end_s: number };
/** A line said on the video's clock: the narrator's (`line` = its script index) or a character's (`say`). */
export type Spoken = { start_s: number; end_s: number; text: string; line?: number; say?: { scene: number; beat: number } };

/**
 * The skit on the video's clock. The narrator's voice file plays in parts (`voiceParts`: from
 * audio_s it plays at video at_s): it pauses for each character line and for the frozen
 * punchline. Returns the parts (what src/studio/sitcom.py shoots, end to end up to the card),
 * every spoken line, where the end card starts and the total length in seconds.
 */
export const layoutOf = (p: SitcomProps) => {
  const script = sitcomScript(p);
  let est = 0;
  const timings =
    script.timings ??
    script.lines.map((text, i) => {
      const read = Math.max(i ? 1.2 : HOOK_MIN_S, Array.from(text).length / VOICE_CHARS_PER_S);
      const t = { start_s: est, end_s: est + read };
      est += read + LINE_GAP_S;
      return t;
    });
  const beats = p.scenes.flatMap((s, scene) => s.beats.map((b, beat) => ({ b, scene, beat })));
  const parts: Part[] = [];
  const spoken: Spoken[] = [];
  const voiceParts = [{ audio_s: 0, at_s: 0 }];
  let shift = 0; // video time - voice-file time
  // The voice file stops at `audio_s` and resumes `seconds` later.
  const pause = (audio_s: number, seconds: number) => {
    shift += seconds;
    voiceParts.push({ audio_s, at_s: audio_s + shift });
  };
  // Line 0 is the hook (over the first beat's action), line i the beat i - 1.
  for (let i = 0; i <= beats.length; i++) {
    const t = timings[i];
    const next = i + 1 < timings.length ? timings[i + 1].start_s : t.end_s + LINE_GAP_S;
    const { scene, beat, b } = beats[Math.max(0, i - 1)];
    const start = i ? t.start_s + shift : 0;
    spoken.push({ start_s: t.start_s + shift, end_s: t.end_s + shift, text: script.lines[i], line: i });
    if (i && b.say) {
      const at = t.end_s + shift;
      const say = b.say.seconds ?? sayEstimate(b.say.text);
      parts.push({ scene, beat, part: "line", start_s: start, end_s: at });
      pause(t.end_s, say + 2 * SAY_GAP_S);
      spoken.push({ start_s: at + SAY_GAP_S, end_s: at + SAY_GAP_S + say, text: b.say.text, say: { scene, beat } });
      parts.push({ scene, beat, part: "say", start_s: at, end_s: next + shift });
    } else {
      parts.push({ scene, beat, part: i ? "line" : "hook", start_s: start, end_s: next + shift });
    }
    if (i === beats.length) {
      // the punchline: the picture freezes once its lines are said
      const at = next + shift;
      pause(next, FREEZE_S);
      parts.push({ scene, beat, part: "freeze", start_s: at, end_s: at + FREEZE_S });
    }
  }
  const cardStart = parts[parts.length - 1].end_s;
  if (p.outro) {
    const o = timings[timings.length - 1];
    spoken.push({ start_s: o.start_s + shift, end_s: o.end_s + shift, text: p.outro, line: timings.length - 1 });
  }
  const outroEnd = p.outro ? spoken[spoken.length - 1].end_s + END_HOLD_S : cardStart;
  return { parts: parts.filter((x) => x.end_s - x.start_s > 1e-6), spoken, voiceParts, cardStart, total: Math.max(cardStart + CARD_S.sitcom, outroEnd) };
};

/** The Reel cover: the hook fully in, over the opening action (frames). */
export const coverOf = (fps: number) => Math.round(0.7 * fps);
