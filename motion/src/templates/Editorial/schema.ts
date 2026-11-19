// Editorial props, script mapping and timings (step 144): black editorial typography (white
// grotesk + a pink italic serif key word), a code-drawn blossom tree that grows with the story,
// cute anatomy characters on deep blue cards, chapter counters and a moving scrubber.
// Imports only zod and pure modules, so `node --test` runs it (test/editorial.test.ts).
import { z } from "zod";
import { accentSchema, addressSchema, CAMEOS, CARD_S, DEFAULT_ADDRESS, screenText } from "../../endcards/schema.ts";
import { buildTimeline, fitEndCard, LINE_GAP_S, READ_CHARS_PER_S, type Timeline, type Timing } from "../../lib/timeline.ts";
import { CHARACTER_IDS, MOODS } from "../../editorial/palette.ts";

/** One voice line (TTS, step 036/048): seconds from the start of the video. */
const voiceLine = z.strictObject({ text: z.string(), start_s: z.number().min(0), end_s: z.number().min(0) });

/** The typographic duo: `lead` in heavy white grotesk, then `key` in the pink italic serif. Read aloud: lead, key. */
const duo = z.strictObject({
  lead: screenText(40),
  key: screenText(30),
  /** A word of `lead` struck through in pink as the key lands (« Ce n'est pas la *faim* »). */
  strike: screenText(20).optional(),
});

/** Social-proof card: a big bold number and its unit in pink italic (kcal, grams, minutes; never a price). */
const stat = z.strictObject({ value: screenText(8), unit: screenText(16), note: screenText(40).optional() });

/** A chapter's header: the white grotesk title and an optional pink italic line under it. Read aloud: title, key. */
const header = { title: screenText(30), key: screenText(34).optional() };

export const TREE_ACTIONS = ["bloom", "wind", "petals", "frame", "loop"] as const;

/**
 * The blossom tree, each action its own shot (layout.ts cameraOf): bloom (crane up as it
 * blooms from → bloom), wind (wide, a gust with anticipation), petals (macro close-up, petals
 * drifting by), frame (viewfinder brackets, then a zoom into them), loop (a ring, dolly out).
 */
const tree = z.strictObject({
  scene: z.literal("tree"),
  ...header,
  action: z.enum(TREE_ACTIONS).default("bloom"),
  /** How full the canopy is at the end of the chapter (0 bare, 1 full bloom). */
  bloom: z.number().min(0).max(1).default(1),
  /** bloom action: how full it starts; default the previous tree chapter's bloom (0.15 for the first). */
  from: z.number().min(0).max(1).optional(),
  /** Up to 3 small chips beside the tree: « ✕ grignotage », « ✓ 8 h de sommeil ». */
  tags: z.array(z.strictObject({ text: screenText(18), mark: z.enum(["no", "yes"]).default("no") })).max(3).default([]),
  stat: stat.optional(),
});

/** Before / after, as two stacked panels: a flat, sparse tree (« sans méthode ») over the rich blossom (« avec méthode »). */
const split = z.strictObject({
  scene: z.literal("split"),
  ...header,
  before: screenText(18).default("sans méthode"),
  after: screenText(18).default("avec méthode"),
});

/** A cute body part on a deep blue card, a pixel caption on top (the line read aloud). */
const anatomy = z.strictObject({
  scene: z.literal("anatomy"),
  character: z.enum(CHARACTER_IDS),
  mood: z.enum(MOODS).default("neutral"),
  /** Mood it turns to halfway through (the reaction), e.g. neutral → surprised. */
  then: z.enum(MOODS).optional(),
  /** Drawn in capitals in the pixel font; may say tu for the humour. */
  caption: screenText(56),
  /** A part of the caption drawn in yellow. */
  highlight: screenText(30).optional(),
  stat: stat.optional(),
});

/** A type-only beat: the title big and kinetic, the key under it, petals drifting by. */
const type = z.strictObject({ scene: z.literal("type"), ...header });

const chapter = z.discriminatedUnion("scene", [tree, split, anatomy, type]);
export type Chapter = z.infer<typeof chapter>;

/** How a chapter is composed; two chapters in a row never share one (owner: nothing repetitive). */
export const compositionOf = (c: Chapter): string => (c.scene === "tree" ? `tree ${c.action}` : c.scene);

export const editorialSchema = z
  .strictObject({
    /** The small caps chip on the hook (« • MACROBODY »). */
    kicker: screenText(24).default("macroBody"),
    /** The hook, type only, on screen from frame 0 (the Reel cover). */
    hook: duo,
    /** Small pink italic line over every chapter title (« La méthode, c'est »); not read aloud. */
    eyebrow: screenText(30).optional(),
    /** 3-5 chapters, counted « 01 / 04 »; no two in a row with the same composition, the first not type-only (the hook is). */
    chapters: z.array(chapter).min(3).max(5),
    /** The last line before the end card, in duo type over the tree in full bloom. */
    payoff: duo,
    /** The end card's tagline, read aloud as the last line; none = the app's tagline. */
    outro: screenText(70).optional(),
    address: addressSchema.default(DEFAULT_ADDRESS),
    /** Macro colour of the topic: the end card's url underline. The style's own accent stays pink. */
    accent: accentSchema.default("brand"),
    /** Beside the end card's tile: default the tree, or the first anatomy character. */
    cameo: z.enum([...CAMEOS.editorial, "none"]).optional(),
    /** Sources of the stated numbers (GOAL.md §5.6). Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /** Voice track (048b rule): one timing per script line: hook, each chapter, payoff, then the outro when there is one. */
    voice: z.strictObject({ audioSrc: z.string().min(1).optional(), lines: z.array(voiceLine).optional() }).optional(),
    music: z.enum(["music-lounge", "none"]).default("music-lounge"),
    /** Off by default: the end card closes the video. */
    loop: z.boolean().default(false),
    safeZone: z.boolean().optional(),
  })
  .superRefine((p, ctx) => {
    const strikes: [string, z.infer<typeof duo>][] = [["hook", p.hook], ["payoff", p.payoff]];
    for (const [path, d] of strikes) {
      if (d.strike && !d.lead.includes(d.strike)) ctx.addIssue({ code: "custom", path: [path, "strike"], message: "strike must be a word of lead" });
    }
    if (p.chapters[0].scene === "type") ctx.addIssue({ code: "custom", path: ["chapters", 0, "scene"], message: "the hook is type only already: start the chapters with a picture" });
    p.chapters.forEach((c, i) => {
      if (i && compositionOf(c) === compositionOf(p.chapters[i - 1])) {
        ctx.addIssue({ code: "custom", path: ["chapters", i, "scene"], message: `two chapters in a row with the same composition (${compositionOf(c)}): vary them` });
      }
      if (c.scene === "anatomy" && c.highlight && !c.caption.toUpperCase().includes(c.highlight.toUpperCase())) {
        ctx.addIssue({ code: "custom", path: ["chapters", i, "highlight"], message: "highlight must be a part of caption" });
      }
      if (c.scene === "tree" && c.stat && c.tags.length) {
        ctx.addIssue({ code: "custom", path: ["chapters", i, "tags"], message: "a tree chapter shows tags or a stat, not both" });
      }
    });
    const lines = editorialScript(p).lines.length;
    if (p.voice?.lines && p.voice.lines.length !== lines) {
      ctx.addIssue({ code: "custom", path: ["voice", "lines"], message: `voice.lines needs one timing per script line: hook, each chapter, payoff, outro (${lines})` });
    }
  });

export type EditorialProps = z.infer<typeof editorialSchema>;
type Script = Pick<EditorialProps, "hook" | "chapters" | "payoff" | "outro" | "voice">;

/**
 * Two texts read as one line: where the first ends without punctuation, a full stop when the
 * second starts a sentence, else a comma (a breath for the voice: « Ça prend du temps, 66
 * jours »). Same rule as src/studio/motion.py `_editorial_line`.
 */
export const joinLine = (a: string, b?: string) =>
  !b ? a : /[.!?…:;,]$/.test(a) ? `${a} ${b}` : /^\p{Lu}/u.test(b) ? `${a}. ${b}` : `${a}, ${b}`;

/** What a chapter's voice reads: its pixel caption (anatomy) or its title and key. */
export const chapterLine = (c: Chapter) => (c.scene === "anatomy" ? c.caption : joinLine(c.title, c.key));

/** Script lines: [hook, ...chapters, payoff, outro?]; voice timings when given. */
export const editorialScript = ({ hook, chapters, payoff, outro, voice }: Script) => ({
  lines: [joinLine(hook.lead, hook.key), ...chapters.map(chapterLine), joinLine(payoff.lead, payoff.key), ...(outro ? [outro] : [])],
  timings: voice?.lines,
});

/** Shortest scene without a voice: room for each scene's animation. */
const minSeconds = (c: Chapter | "hook" | "payoff" | "outro") => {
  if (c === "hook") return 2.5;
  if (c === "payoff") return 3;
  if (c === "outro") return 2;
  return c.scene === "tree" || c.scene === "type" ? 3.2 : 3.6;
};
/** End card hold after the outro line is read (the card itself lasts at least CARD_S.editorial). */
export const END_HOLD_S = 1.2;

/**
 * Scenes in frames (0 = hook, 1..n = chapters, n+1 = payoff, n+2 = outro when there is one)
 * and where the end card starts: at the outro line, else after the payoff.
 */
export const timelineOf = (p: EditorialProps, fps: number) => {
  const script = editorialScript(p);
  const kinds: (Chapter | "hook" | "payoff" | "outro")[] = ["hook", ...p.chapters, "payoff", ...(p.outro ? ["outro" as const] : [])];
  let t = 0;
  const timings: Timing[] =
    script.timings ??
    script.lines.map((text, i) => {
      const read = Math.max(minSeconds(kinds[i]), Array.from(text).length / READ_CHARS_PER_S);
      const timing = { text, start_s: t, end_s: t + read };
      t += read + LINE_GAP_S;
      return timing;
    });
  const build = (outroSeconds: number) => buildTimeline({ lines: script.lines, timings, fps, hookSeconds: 2.5, outroSeconds, loop: p.loop });
  const cardStart = (tl: Timeline) => (p.outro ? tl.scenes[tl.scenes.length - 1].startFrame : tl.outroStart);
  const timeline = fitEndCard(build, p.outro ? END_HOLD_S : CARD_S.editorial, cardStart, CARD_S.editorial, fps);
  return { timeline, endStart: cardStart(timeline) };
};

/** The end card's cameo: the one asked for, else the first anatomy character, else the tree. */
export const cameoOf = (p: Pick<EditorialProps, "cameo" | "chapters">) =>
  p.cameo ?? p.chapters.find((c): c is Extract<Chapter, { scene: "anatomy" }> => c.scene === "anatomy")?.character ?? "tree";

/** Bloom of tree chapter `i` at its start and end: `from` (default the last tree's bloom, 0.15 at first) → `bloom`. */
export const bloomOf = (chapters: Chapter[], i: number): [number, number] => {
  let last = 0.15;
  for (let k = 0; k < i; k++) {
    const c = chapters[k];
    if (c.scene === "tree") last = c.bloom;
  }
  const c = chapters[i];
  if (c.scene !== "tree") return [last, last];
  return [c.action === "bloom" ? (c.from ?? last) : c.bloom, c.bloom];
};
