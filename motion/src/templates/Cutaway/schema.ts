// Cutaway props, script mapping and timings (step 142): a pixel-art mechanism explainer (the
// body as a machine). Imports only zod and pure modules, so `node --test` runs it
// (test/cutaway.test.ts).
import { z } from "zod";
import { accentSchema, addressSchema, CAMEOS, CARD_S, DEFAULT_ADDRESS, screenText } from "../../endcards/schema.ts";
import { buildTimeline, fitEndCard, LINE_GAP_S, READ_CHARS_PER_S, type Timeline, type Timing } from "../../lib/timeline.ts";
import { rateOf, type Speed, SPEEDS, VIEW_IDS, VIEWS, type ViewId } from "../../cutaway/views.ts";
import { sceneLine } from "../PaperStory/schema.ts";

const voiceLine = z.strictObject({ text: z.string(), start_s: z.number().min(0), end_s: z.number().min(0) });

/** A boxed label pointing at a named point of the scene's view (VIEWS anchors), e.g. « Myosine » at "tete". */
const callout = z.strictObject({ text: screenText(22), at: z.string() });

const scene = z.strictObject({
  /** The title box, read aloud: « Comment un muscle se contracte ? », « 2. Elle tire ». */
  title: screenText(60),
  /** Its second line, in yellow, read aloud after the title: « La tête de myosine tire l'actine ». */
  sub: screenText(60).optional(),
  /** The mechanism on screen (src/cutaway/views.ts): a new view = a cut to it (zoom through, dither). */
  view: z.enum(VIEW_IDS),
  /** Playback speed on the mode chip: « VITESSE RÉELLE » or « RALENTI 1/84 »; the mechanism runs at it. */
  speed: z.enum(SPEEDS).default("real"),
  /** A « ×2 » badge: twice the speed. */
  x2: z.boolean().default(false),
  /** Camera: zoom (1 = the whole view) and the named point it centres on (none = the view's centre). */
  zoom: z.number().min(0.4).max(4).default(1),
  focus: z.string().optional(),
  /** The view's slow change by the end of the scene, 0..1 (views.ts: contraction, growth, repair...); none = as before. */
  stage: z.number().min(0).max(1).optional(),
  /** Up to 3 labels with leader lines, popping in one after the other. Not read aloud. */
  callouts: z.array(callout).max(3).default([]),
  /** A numbered row under the title (firing-order style); `current` lit, none = it follows the mechanism's cycle. */
  steps: z.strictObject({ items: z.array(screenText(14)).min(2).max(9), current: z.number().int().min(0).optional() }).optional(),
  /** Top-right gauge: « 2 400 kcal », « Force » with a bar `fill` (0..1); kept until a scene sets another. */
  gauge: z.strictObject({ label: screenText(10), value: screenText(8).optional(), fill: z.number().min(0).max(1) }).optional(),
  /** A burst word with a light flash, a third into the scene: « BANG ! », « ATP ! ». Not read aloud. */
  bang: screenText(10).optional(),
  /** dusk (sunset; default for the hook and the payoff) or night (default for the beats). */
  sky: z.enum(["dusk", "night"]).optional(),
});
export type SceneProps = z.infer<typeof scene>;

export const cutawaySchema = z
  .strictObject({
    /** The question, in the big framed box from frame 0 (the Reel cover): « Comment un muscle se contracte ? ». */
    hook: scene,
    /** 4-6 mechanism beats: each one HUD state and one short line. */
    beats: z.array(scene).min(4).max(6),
    /** The closing beat, big box again: « Toujours là, 100 ans plus tard »-style. */
    payoff: scene,
    /** The end card's tagline, read aloud as the last line; none = the app's tagline. */
    outro: screenText(70).optional(),
    address: addressSchema.default(DEFAULT_ADDRESS),
    /** Macro colour of the topic: the end card's button and glow. */
    accent: accentSchema.default("brand"),
    /** Beside the end card's tile: a small running view (default: the payoff's view when it is one). */
    cameo: z.enum([...CAMEOS.cutaway, "none"]).optional(),
    /** Sources of the stated numbers (GOAL.md §5.6). Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /** Voice track (048b rule): one timing per script line: hook, each beat, payoff, then the outro when there is one. */
    voice: z.strictObject({ audioSrc: z.string().min(1).optional(), lines: z.array(voiceLine).optional() }).optional(),
    /** The dusk synth bed, or "none". */
    // a/b/c: the step-148 candidates; the default stays music-dusk until the owner picks.
    music: z.enum(["music-dusk", "music-cutaway-a", "music-cutaway-b", "music-cutaway-c", "none"]).default("music-dusk"),
    /** Off by default: the end card closes the video. */
    loop: z.boolean().default(false),
    safeZone: z.boolean().optional(),
  })
  .superRefine((p, ctx) => {
    const all = [["hook"], ...p.beats.map((_, i) => ["beats", i]), ["payoff"]] as (string | number)[][];
    scenesOf(p).forEach((s, i) => {
      const anchors: readonly string[] = VIEWS[s.view].anchors;
      const where = all[i];
      if (s.focus !== undefined && !anchors.includes(s.focus)) {
        ctx.addIssue({ code: "custom", path: [...where, "focus"], message: `${s.view} points: ${anchors.join(", ")}` });
      }
      s.callouts.forEach((c, k) => {
        if (!anchors.includes(c.at)) ctx.addIssue({ code: "custom", path: [...where, "callouts", k, "at"], message: `${s.view} points: ${anchors.join(", ")}` });
      });
      if (s.steps?.current !== undefined && s.steps.current >= s.steps.items.length) {
        ctx.addIssue({ code: "custom", path: [...where, "steps", "current"], message: "current must be one of the items (from 0)" });
      }
    });
    const lines = cutawayScript(p).lines.length;
    if (p.voice?.lines && p.voice.lines.length !== lines) {
      ctx.addIssue({ code: "custom", path: ["voice", "lines"], message: `voice.lines needs one timing per script line: hook, each beat, payoff, outro (${lines})` });
    }
  });

export type CutawayProps = z.infer<typeof cutawaySchema>;

/** Every scene in order: hook, beats, payoff. */
export const scenesOf = (p: Pick<CutawayProps, "hook" | "beats" | "payoff">) => [p.hook, ...p.beats, p.payoff];

/** A scene's spoken line: title then sub, joined like PaperStory's strips (= src/studio/motion.py SCRIPTS). */
export const lineOf = (s: Pick<SceneProps, "title" | "sub">) => sceneLine(s.sub ? [s.title, s.sub] : [s.title]);

/** Script lines: [hook, ...beats, payoff, outro?]; voice timings when given. */
export const cutawayScript = (p: Pick<CutawayProps, "hook" | "beats" | "payoff" | "outro" | "voice">) => ({
  lines: [...scenesOf(p).map(lineOf), ...(p.outro ? [p.outro] : [])],
  timings: p.voice?.lines,
});

/** Shortest scene without a voice: room for its callouts and its burst. */
export const minSeconds = (s: SceneProps | "outro") => (s === "outro" ? 2 : 2.8 + 0.4 * s.callouts.length + (s.bang ? 0.6 : 0));
/** End card hold after the outro line is read (the card itself lasts at least CARD_S.cutaway). */
export const END_HOLD_S = 1.2;

/**
 * Scenes in frames (0 = hook, 1..n = beats, n+1 = payoff, n+2 = outro when there is one) and
 * where the end card starts: at the outro line, else after the payoff.
 */
export const timelineOf = (p: CutawayProps, fps: number) => {
  const script = cutawayScript(p);
  const kinds: (SceneProps | "outro")[] = [...scenesOf(p), ...(p.outro ? ["outro" as const] : [])];
  let t = 0;
  const timings: Timing[] =
    script.timings ??
    script.lines.map((text, i) => {
      const read = Math.max(minSeconds(kinds[i]), Array.from(text).length / READ_CHARS_PER_S);
      const timing = { text, start_s: t, end_s: t + read };
      t += read + LINE_GAP_S;
      return timing;
    });
  const build = (outroSeconds: number) => buildTimeline({ lines: script.lines, timings, fps, hookSeconds: 3, outroSeconds, loop: p.loop });
  const cardStart = (tl: Timeline) => (p.outro ? tl.scenes[tl.scenes.length - 1].startFrame : tl.outroStart);
  const timeline = fitEndCard(build, p.outro ? END_HOLD_S : CARD_S.cutaway, cardStart, CARD_S.cutaway, fps);
  return { timeline, endStart: cardStart(timeline) };
};

/** A scene as played: its view, rate, sky and stage resolved from the scenes before it. */
export type Resolved = { view: ViewId; speed: Speed; rate: number; sky: "dusk" | "night"; stageFrom: number; stageTo: number; cut: boolean; gauge?: SceneProps["gauge"]; gaugeFrom?: SceneProps["gauge"] };

export const resolveScenes = (p: CutawayProps): Resolved[] => {
  const all = scenesOf(p);
  const out: Resolved[] = [];
  all.forEach((s, i) => {
    const prev = out[i - 1];
    const sky = s.sky ?? (i === 0 || i === all.length - 1 ? "dusk" : "night");
    const same = !!prev && prev.view === s.view;
    const stageTo = s.stage ?? (same ? prev.stageTo : 0);
    out.push({
      view: s.view,
      speed: s.speed,
      rate: rateOf(s.speed, s.x2),
      sky,
      stageFrom: same ? prev.stageTo : stageTo,
      stageTo,
      cut: i > 0 && (!same || prev.sky !== sky),
      gauge: s.gauge ?? prev?.gauge,
      gaugeFrom: prev?.gauge,
    });
  });
  return out;
};
