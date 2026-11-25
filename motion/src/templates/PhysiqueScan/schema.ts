// PhysiqueScan props and timings (owner order 75, « Physique Scan »): kinetic type on rolling 3D
// bands round a jacked statue, in the look of the owner's reference Reel (a cream drafting grid,
// navy, orange, teal). The AI writes scenes: a set, what the hero does there (training, eating),
// 1-3 bands of macro and calorie text that wrap round his muscles and roll, a measure readout.
// Every cut falls on the bed's beat (BEDS); src/studio/physique.py turns the timed shots below
// into the troupe's blueprint shot list (cinematic/engine/bands.py). No voice: the words are on
// the bands. Imports only zod and pure modules, so `node --test` runs it.
import { z } from "zod";
import { accentSchema, addressSchema, CARD_S, screenText } from "../../endcards/schema.ts";

/** The body parts a band rides (cinematic/engine/bands.py PARTS). */
export const PARTS = ["chest", "abs", "arm_r", "arm_l", "forearm_r", "forearm_l", "thigh_r", "thigh_l"] as const;
/** The statues (cinematic/cast.json, tag physique). */
export const HEROES = ["hero", "hero_b", "hero_f"] as const;
export const CAMERAS = ["orbit", "close", "dolly", "wide"] as const;
export type Camera = (typeof CAMERAS)[number];
export type Part = (typeof PARTS)[number];
/** The beds the cuts are timed to: tempo and first beat (s), measured by src/studio/music.py measure. */
export const BEDS = {
  "music-cutaway-c": { bpm: 112.3, first: 0 },
  "music-cutaway-b": { bpm: 99.4, first: 0.604 },
  "music-cutaway-a": { bpm: 86.1, first: 0 },
} as const;
type Bed = keyof typeof BEDS;
const BED_IDS = Object.keys(BEDS) as [Bed, ...Bed[]];
/** A shot lasts this many beats (a scene's last one may be shorter). */
export const SHOT_BEATS = 2;
/** The hook stays this many beats (one word lands per beat, 5 at most, then one to read), and at least HOOK_MIN_S. */
export const HOOK_BEATS = 6;
export const HOOK_MIN_S = 1.6;

const words = (s: string) => s.trim().split(/\s+/).filter(Boolean).length;

const band = z.strictObject({
  /** The muscle it wraps: chest, abs, arm_r / arm_l (biceps), forearm_r / forearm_l, thigh_r / thigh_l. */
  on: z.enum(PARTS),
  /** What it says (a macro, a calorie count, a word of the hook): repeated all round the band. */
  text: screenText(28),
  /** light: cream band, ink bold caps; dark: ink band, cream italic serif; orange: orange band, cream caps. */
  tone: z.enum(["light", "dark", "orange"]).default("light"),
});

const scene = z.strictObject({
  /** A troupe set (cinematic/sets.json), drawn in the blueprint look: gym, kitchen, dinner, living, restaurant, beach. */
  set: z.string().min(1),
  /** Where the hero stands or sits (a spot of the set); none = picked for the action. */
  at: z.string().min(1).optional(),
  /** What the hero does (cinematic/actions.json): curl, bar_strain (a barbell), fork_up (eating), carry_plate, cheer, Idle_Loop, Jump_Loop... */
  action: z.string().min(1),
  /** 1-3 bands of text round his muscles, rolling. */
  bands: z.array(band).min(1).max(3),
  /** A measure readout that pops in on the scene's first beat (« +180 G », « 2 800 KCAL »). */
  label: screenText(16).optional(),
  /** How long the scene lasts, in beats of the bed (a cut every SHOT_BEATS). */
  beats: z.number().int().min(2).max(8).default(4),
  /** The scene's first camera (the others come round): orbit (round the chest), close (on the first band), dolly (push in), wide. */
  camera: z.enum(CAMERAS).optional(),
});
export type Scene = z.infer<typeof scene>;

export const physiqueSchema = z
  .strictObject({
    /** The hook, 5 words at most: each word slams in on a beat, big, over the opening shot. */
    hook: screenText(40).refine((s) => words(s) <= 5, "the hook is 5 words at most"),
    /** The statue: hero (light skin), hero_b (dark skin), hero_f (a woman, sports top). */
    hero: z.enum(HEROES).default("hero"),
    /** 2-6 scenes (train, eat, train...), each 2-8 beats. */
    scenes: z.array(scene).min(2).max(6),
    /** The end card's tagline; none = the app's tagline. */
    outro: screenText(70).optional(),
    address: addressSchema.default("tu"),
    accent: accentSchema.default("brand"),
    /** Sources of the stated numbers (GOAL.md §5.6). Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /** The bed the cuts fall on. */
    music: z.enum(BED_IDS).default("music-cutaway-c"),
    /** The troupe's shots end to end (src/studio/physique.py fills it at render time): a video, or an image for a still. */
    plate: z.string().min(1).optional(),
    loop: z.boolean().default(false),
    safeZone: z.boolean().optional(),
  });

export type PhysiqueProps = z.infer<typeof physiqueSchema>;

/** One shot on the video's clock: its scene, its camera and the body part it looks at. */
export type Shot = { scene: number; shot: number; start_s: number; end_s: number; camera: Camera; part: Part };

/** After a scene's first camera, the next ones come round in this order. */
const ROUND: Camera[] = ["close", "orbit", "dolly", "close", "wide"];

/** The beat grid of the bed: the s of beat `n` (beat 0 = the video's start). */
export const beatAt = (music: Bed, n: number) => {
  const { bpm, first } = BEDS[music];
  return n === 0 ? 0 : first + (n * 60) / bpm;
};

/**
 * The video on the bed's beat: each scene `beats` long, a cut every SHOT_BEATS (the camera
 * comes round: a close-up looks at the scene's bands in turn, an orbit and a dolly at the
 * chest), then the end card. Returns the shots (what src/studio/physique.py renders, end to
 * end up to the card), each scene's start, when the hook leaves, the card's start and the total.
 */
export const layoutOf = (p: PhysiqueProps) => {
  const shots: Shot[] = [];
  const starts: number[] = [];
  let beat = 0;
  p.scenes.forEach((s, i) => {
    starts.push(beatAt(p.music, beat));
    let close = 0;
    let round = 0;
    let last: Camera | undefined;
    for (let k = 0; k * SHOT_BEATS < s.beats; k++) {
      const from = beat + k * SHOT_BEATS;
      const to = Math.min(beat + s.beats, from + SHOT_BEATS);
      let camera: Camera = k === 0 ? (s.camera ?? (i === 0 ? "orbit" : "close")) : ROUND[round++ % ROUND.length];
      if (camera === last) camera = ROUND[round++ % ROUND.length]; // never the same camera twice in a row
      last = camera;
      const part: Part = camera === "close" ? s.bands[close++ % s.bands.length].on : "chest";
      shots.push({ scene: i, shot: k, start_s: beatAt(p.music, from), end_s: beatAt(p.music, to), camera, part });
    }
    beat += s.beats;
  });
  const cardStart = shots[shots.length - 1].end_s;
  const hookOut = Math.min(cardStart, Math.max(HOOK_MIN_S, beatAt(p.music, HOOK_BEATS)));
  return { shots, starts, hookOut, cardStart, total: cardStart + CARD_S.physique };
};

/** The Reel cover: the hook's words in, over the opening shot (frames). */
export const coverOf = (p: PhysiqueProps, fps: number) => Math.round(Math.min(layoutOf(p).hookOut - 0.2, 1.2) * fps);
