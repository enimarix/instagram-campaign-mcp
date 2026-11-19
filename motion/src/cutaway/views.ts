// The cutaway kit's mechanisms ("views", step 142), as data: each one is a cutaway diagram
// drawn in code (src/cutaway/views/*.tsx) that really moves. A new subject is a new view: a
// component, its entry here (anchors its callouts and camera can point at, its speed) and in
// views/index.tsx. Pure (no imports) so `node --test` and the schema use it.

/**
 * View id -> named points (callouts, camera focus), its cycles per second at real speed and
 * its depth (0 = the whole body): a cut to a deeper view zooms in, to a shallower one out.
 * `stage` (0..1, a beat's slow change) means: arm none, muscle growth, fibre none,
 * sarcomere contraction (Z-lines closing), repair micro-tears -> repaired and thicker,
 * fat the droplet emptying, mito none.
 */
export const VIEWS = {
  /** The whole arm in side view, skin cut away: biceps, triceps, bones; it curls a dumbbell. */
  arm: { depth: 0, hz: 0.7, anchors: ["biceps", "triceps", "tendon", "os", "coude", "haltere", "avantbras"] },
  /** A muscle belly cut open: bundles (fascicles) of fibres in the section; a nerve signal runs along it. */
  muscle: { depth: 1, hz: 1.2, anchors: ["muscle", "faisceau", "fibre", "tendon", "nerf"] },
  /** One fibre opened: myofibrils striped with sarcomeres, nuclei on the surface. */
  fibre: { depth: 2, hz: 2, anchors: ["fibre", "myofibrille", "sarcomere", "noyau"] },
  /** One sarcomere: actin pulled in by the myosin heads (attach, pull, release with ATP, recock). */
  sarcomere: { depth: 3, hz: 12, anchors: ["zline", "actine", "myosine", "tete", "mline"] },
  /** A fibre after training: micro-tears, satellite cells come, the tears fill, the fibre thickens. */
  repair: { depth: 2, hz: 0.0005, anchors: ["fibre", "dechirure", "cellule", "proteine"] },
  /** A fat cell: its droplet empties into the blood as fatty acids. */
  fat: { depth: 1, hz: 0.0005, anchors: ["cellule", "goutte", "noyau", "acides", "sang"] },
  /** A mitochondrion: fatty acids and oxygen in, ATP, CO₂ and water out. */
  mito: { depth: 2, hz: 0.9, anchors: ["mitochondrie", "crete", "o2", "co2", "eau", "atp"] },
} as const;

export type ViewId = keyof typeof VIEWS;
export const VIEW_IDS = Object.keys(VIEWS) as [ViewId, ...ViewId[]];
export type Anchor<V extends ViewId = ViewId> = (typeof VIEWS)[V]["anchors"][number];

/**
 * The HUD's playback speeds: real speed, slow motion down to 1/84, and time-lapse up to
 * ×10000 for slow processes (repair over days, a fat cell emptying: their hz is tiny).
 */
export const SPEEDS = ["real", "1/2", "1/5", "1/10", "1/21", "1/42", "1/84", "x10", "x100", "x1000", "x10000"] as const;
export type Speed = (typeof SPEEDS)[number];

/** Playback rate of a speed (1 = real), doubled by a « ×2 » badge. */
export const rateOf = (speed: Speed, x2 = false) =>
  (speed === "real" ? 1 : speed.startsWith("x") ? Number(speed.slice(1)) : 1 / Number(speed.slice(2))) * (x2 ? 2 : 1);

/** Lit dashes (of 6) under the mode chip: 6 at real speed, 1 at 1/84 (log scale). */
export const dashesOf = (rate: number) => Math.max(1, Math.min(6, Math.round(6 + (5 * Math.log(Math.min(1, rate))) / Math.log(84))));

/** The mode chip's text: « ▶ VITESSE RÉELLE », « ‖ RALENTI 1/84 » or « ▶▶ ACCÉLÉRÉ ×1000 ». */
export const chipText = (speed: Speed) =>
  speed === "real" ? "▶ Vitesse réelle" : speed.startsWith("x") ? `▶▶ Accéléré ×${speed.slice(1)}` : `‖ Ralenti ${speed}`;

/**
 * Mechanism clock (in seconds of real-speed time) at every frame: the playback rate of each
 * scene integrated over the frames, easing (on a log scale) from the previous scene's rate
 * over `rampFrames`, so slowing down and speeding up look continuous.
 */
export const mechanismClock = (scenes: { start: number; rate: number }[], total: number, fps: number, rampFrames: number): number[] => {
  const clock = new Array<number>(total + 1).fill(0);
  let s = 0;
  for (let f = 0; f < total; f++) {
    while (s + 1 < scenes.length && f >= scenes[s + 1].start) s++;
    const prev = s ? scenes[s - 1].rate : scenes[0].rate;
    const k = Math.min(1, (f - scenes[s].start) / rampFrames);
    const e = k * k * (3 - 2 * k);
    const rate = Math.exp(Math.log(prev) + (Math.log(scenes[s].rate) - Math.log(prev)) * e);
    clock[f + 1] = clock[f] + rate / fps;
  }
  return clock;
};
