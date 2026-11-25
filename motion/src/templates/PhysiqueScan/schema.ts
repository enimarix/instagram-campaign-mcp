// PhysiqueScan props and timings (owner order 75, « Physique Scan »): kinetic type on 3D bands
// round a detailed muscle (its fibres showing where it is cut open), in the spirit of the owner's
// reference Reel. The AI writes scenes: a palette and 2-6 bands of macro and calorie text that
// grip the muscle, rock, whoosh up and down it and squeeze it, a measure readout. Every cut falls
// on the bed's beat (BEDS); src/studio/physique.py turns the timed shots below into the anatomy
// engine's shots (cinematic/engine/anatomy.py). No voice: the words are on the bands. Imports
// only zod and pure modules, so `node --test` runs it.
import { z } from "zod";
import { accentSchema, addressSchema, CARD_S, screenText } from "../../endcards/schema.ts";

/** The palettes (cinematic/engine/anatomy.py PALETTES): lab (cream, navy, orange, teal), neon (night, acid tones), candy (pink, violet, yellow). */
export const PALETTES = ["lab", "neon", "candy"] as const;
/** orbit (round the muscle), push (in on it), top (down into the cut: the fibres inside), glide (along it, close). */
export const CAMERAS = ["orbit", "push", "top", "glide"] as const;
export type Camera = (typeof CAMERAS)[number];
/** The beds the cuts are timed to: tempo and first beat (s), measured by src/studio/music.py measure. */
export const BEDS = {
  "music-cutaway-c": { bpm: 112.3, first: 0 },
  "music-cutaway-b": { bpm: 99.4, first: 0.604 },
  "music-cutaway-a": { bpm: 86.1, first: 0 },
} as const;
type Bed = keyof typeof BEDS;
const BED_IDS = Object.keys(BEDS) as [Bed, ...Bed[]];
/** When the bands whoosh, as a share of their shot (cinematic/engine/anatomy.py state: the first band leaves at 0.28). */
export const WHOOSH = 0.3;
/** A shot lasts this many beats (a scene's last one may be shorter). */
export const SHOT_BEATS = 2;
/** The hook stays this many beats (one word lands per beat, 5 at most, then one to read), and at least HOOK_MIN_S. */
export const HOOK_BEATS = 6;
export const HOOK_MIN_S = 1.6;

const words = (s: string) => s.trim().split(/\s+/).filter(Boolean).length;

const band = z.strictObject({
  /** What it says (a macro, a calorie count, a word of the hook): repeated all round the band. */
  text: screenText(28),
  /** The palette's tones: light (pale band, dark caps), dark (dark band, italic serif), accent and pop (its two bright colours, caps). */
  tone: z.enum(["light", "dark", "accent", "pop"]).default("light"),
  /** How hard it squeezes the muscle (0 rests on it, 1 bites in); each stop varies round it. */
  squeeze: z.number().min(0).max(1).default(0.8),
});

const scene = z.strictObject({
  /** The scene's colours (PALETTES). */
  palette: z.enum(PALETTES).default("lab"),
  /** 2-6 bands of text round the muscle, top to bottom: they pull tight, rock, whoosh up and down, squeeze. */
  bands: z.array(band).min(2).max(6),
  /** A measure readout that pops in on the scene's first beat (« +180 G », « 2 800 KCAL »). */
  label: screenText(16).optional(),
  /** How long the scene lasts, in beats of the bed (a cut every SHOT_BEATS). */
  beats: z.number().int().min(2).max(8).default(4),
  /** The scene's first camera (the others come round). */
  camera: z.enum(CAMERAS).optional(),
});
export type Scene = z.infer<typeof scene>;

export const physiqueSchema = z
  .strictObject({
    /** The hook, 5 words at most: each word slams in on a beat, big, over the opening shot. */
    hook: screenText(40).refine((s) => words(s) <= 5, "the hook is 5 words at most"),
    /** 2-6 scenes (one idea each: the protein, the carbs, the total...), each 2-8 beats. */
    scenes: z.array(scene).min(2).max(6),
    /** The end card's tagline; none = the app's tagline. */
    outro: screenText(70).optional(),
    address: addressSchema.default("tu"),
    accent: accentSchema.default("brand"),
    /** Sources of the stated numbers (GOAL.md §5.6). Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /** The bed the cuts fall on. */
    music: z.enum(BED_IDS).default("music-cutaway-c"),
    /** The muscle's shots end to end (src/studio/physique.py fills it at render time): a video, or an image for a still. */
    plate: z.string().min(1).optional(),
    loop: z.boolean().default(false),
    safeZone: z.boolean().optional(),
  });

export type PhysiqueProps = z.infer<typeof physiqueSchema>;

/** One shot on the video's clock: its scene, its number in the scene, its camera. */
export type Shot = { scene: number; shot: number; start_s: number; end_s: number; camera: Camera };

/** After a scene's first camera, the next ones come round in this order. */
const ROUND: Camera[] = ["top", "push", "glide", "orbit"];

/** The beat grid of the bed: the s of beat `n` (beat 0 = the video's start). */
export const beatAt = (music: Bed, n: number) => {
  const { bpm, first } = BEDS[music];
  return n === 0 ? 0 : first + (n * 60) / bpm;
};

/**
 * The video on the bed's beat: each scene `beats` long, a cut every SHOT_BEATS (the camera
 * comes round, never twice in a row), then the end card. Returns the shots (what src/studio/physique.py renders, end to
 * end up to the card), each scene's start, when the hook leaves, the card's start and the total.
 */
export const layoutOf = (p: PhysiqueProps) => {
  const shots: Shot[] = [];
  const starts: number[] = [];
  let beat = 0;
  p.scenes.forEach((s, i) => {
    starts.push(beatAt(p.music, beat));
    let round = 0;
    let last: Camera | undefined;
    for (let k = 0; k * SHOT_BEATS < s.beats; k++) {
      const from = beat + k * SHOT_BEATS;
      const to = Math.min(beat + s.beats, from + SHOT_BEATS);
      let camera: Camera = k === 0 ? (s.camera ?? (i === 0 ? "orbit" : ROUND[i % ROUND.length])) : ROUND[round++ % ROUND.length];
      if (camera === last) camera = ROUND[round++ % ROUND.length]; // never the same camera twice in a row
      last = camera;
      shots.push({ scene: i, shot: k, start_s: beatAt(p.music, from), end_s: beatAt(p.music, to), camera });
    }
    beat += s.beats;
  });
  const cardStart = shots[shots.length - 1].end_s;
  const hookOut = Math.min(cardStart, Math.max(HOOK_MIN_S, beatAt(p.music, HOOK_BEATS)));
  return { shots, starts, hookOut, cardStart, total: cardStart + CARD_S.physique };
};

/** The Reel cover: the hook's words in, over the opening shot (frames). */
export const coverOf = (p: PhysiqueProps, fps: number) => Math.round(Math.min(layoutOf(p).hookOut - 0.2, 1.2) * fps);
