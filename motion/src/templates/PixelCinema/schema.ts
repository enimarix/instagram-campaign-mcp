// PixelCinema props, script mapping and timings (step 143): one atmospheric pixel-art set
// (src/cinema) told as a short film, with clean editorial type over it. Imports only zod and
// pure modules, so `node --test` runs it (test/pixelcinema.test.ts).
import { z } from "zod";
import { ANCHORS, SCENE_IDS } from "../../cinema/scenes.ts";
import { accentSchema, addressSchema, CARD_S, DEFAULT_ADDRESS, screenText } from "../../endcards/schema.ts";
import { buildTimeline, fitEndCard, LINE_GAP_S, READ_CHARS_PER_S, type Timeline, type Timing } from "../../lib/timeline.ts";

/** One voice line (TTS, step 036/048): seconds from the start of the video. */
const voiceLine = z.strictObject({ text: z.string(), start_s: z.number().min(0), end_s: z.number().min(0) });

/** Text with at most one `*key word*`, drawn in amber; the voice reads it without the stars. */
const HIGHLIGHT = /^[^*]*(\*[^*]+\*[^*]*)?$/;
const rich = (max: number) => screenText(max).regex(HIGHLIGHT, "at most one *key word* between two stars");
/** The text as read and as measured: the stars removed. */
export const plain = (text: string) => text.replace(/\*/g, "");
/** [before, key word, after] of a rich text (key word "" when there is none). */
export const splitHighlight = (text: string): [string, string, string] => {
  const m = /^([^*]*)\*([^*]+)\*(.*)$/.exec(text);
  return m ? [m[1], m[2], m[3]] : [text, "", ""];
};

const hook = z.strictObject({
  /** Struck through in red once read (« C'est pas le régime. »), then `line` lands under it. */
  strike: screenText(36).optional(),
  /** The hook's line (« C'est la *méthode*. »): on screen from frame 0 when there is no strike. */
  line: rich(40),
});

const chip = z.strictObject({
  kind: z.literal("chip"),
  /** The heading above the chips (« Ce soir, tout se joue *ici* : »); it stays for the next chips until one gives a new one. Read aloud when it changes. */
  title: rich(44).optional(),
  /** The numbered tag (« où va la lumière »): numbered 1, 2, 3… in order. */
  text: screenText(30),
  /** Where its leader line points in the set. None = no line. */
  point: z.enum(ANCHORS).optional(),
  /** The key moment: lightning, the set as a white / black silhouette (at most one beat). */
  flash: z.boolean().default(false),
});

const stat = z.strictObject({
  kind: z.literal("stat"),
  /** The line above the number (« Ce soir, il vous reste »). */
  title: rich(48),
  /** The big number, counting up (« 308 », « 2 000 »), its unit and a small label under it. */
  value: screenText(8).regex(/\d/, "a number"),
  unit: screenText(8).optional(),
  label: screenText(28).optional(),
});

const app = z.strictObject({
  kind: z.literal("app"),
  /** The line above the app card (« macroBody vous le dit à la calorie près. »). */
  title: rich(48),
  /** The card's ring: the number in it (counts up) and what it is. */
  value: screenText(8).regex(/\d/, "a number"),
  unit: screenText(16).default("kcal restantes"),
});

const beat = z.discriminatedUnion("kind", [chip, stat, app]);
export type Beat = z.infer<typeof beat>;
export type Chip = z.infer<typeof chip>;

export const pixelCinemaSchema = z
  .strictObject({
    /** The set: window (rainy city, 21 h), pier (dawn run), fridge (kitchen at night). */
    scene: z.enum(SCENE_IDS).default("window"),
    /** The twist hook: struck-through belief, then the real line. */
    hook,
    /** 2-4 chips (one may be the lightning), then 1-2 of stat / app. */
    beats: z.array(beat).min(3).max(6),
    /** A small tag at the bottom of the frame during the chips (« Source : Ciqual 2020 »). Not read aloud. */
    tag: screenText(44).optional(),
    /** The end card's tagline (tied to the payoff), read aloud as the last line; none = the app's tagline. */
    outro: screenText(70).optional(),
    address: addressSchema.default(DEFAULT_ADDRESS),
    /** Macro colour of the topic: the app card's ring and the end card's underline. */
    accent: accentSchema.default("kcal"),
    /** Sources of the stated numbers (GOAL.md §5.6). Not shown, kept with the asset. */
    citations: z.array(z.strictObject({ url: z.url({ protocol: /^https?$/ }), title: z.string().optional() })),
    /** Voice track (048b rule): `lines` = one timing per script line: hook, each beat, then the outro when there is one. */
    voice: z.strictObject({ audioSrc: z.string().min(1).optional(), lines: z.array(voiceLine).optional() }).optional(),
    /** The night score in the rain, or "none". */
    music: z.enum(["music-nocturne", "none"]).default("music-nocturne"),
    /** Off by default: the end card closes the video. */
    loop: z.boolean().default(false),
    safeZone: z.boolean().optional(),
  })
  .superRefine((p, ctx) => {
    const kinds = p.beats.map((b) => (b.kind === "chip" ? "chip" : "end")).join(" ");
    if (!/^(chip ){2,4}end( end)?$/.test(kinds)) {
      ctx.addIssue({ code: "custom", path: ["beats"], message: `beats must be 2-4 chips, then 1-2 of stat / app (got: ${p.beats.map((b) => b.kind).join(" ")})` });
    }
    if (p.beats.filter((b) => b.kind === "chip" && b.flash).length > 1) {
      ctx.addIssue({ code: "custom", path: ["beats"], message: "one lightning beat at most: it is the one big moment" });
    }
    if (p.beats[0]?.kind === "chip" && !p.beats[0].title) {
      ctx.addIssue({ code: "custom", path: ["beats", 0, "title"], message: "the first chip needs the heading it hangs under" });
    }
    const lines = pixelCinemaScript(p).lines.length;
    if (p.voice?.lines && p.voice.lines.length !== lines) {
      ctx.addIssue({ code: "custom", path: ["voice", "lines"], message: `voice.lines needs one timing per script line: hook, each beat, outro (${lines})` });
    }
  });

export type PixelCinemaProps = z.infer<typeof pixelCinemaSchema>;
type Script = Pick<PixelCinemaProps, "hook" | "beats" | "outro" | "voice">;

/**
 * Parts read as one line (stars removed): a full stop added where a part ends without punctuation and the
 * next starts a sentence (= sceneLine in PaperStory; src/studio/motion.py `_paper_line`).
 */
export const joinParts = (parts: string[]) =>
  parts.map(plain).reduce((line, next) => (line && !/[.!?…:;,]$/.test(line) && /^\p{Lu}/u.test(next) ? `${line}. ${next}` : line ? `${line} ${next}` : next), "");

/** The heading over chip `i` (its own, else the last one given before it). */
export const titleOf = (beats: Beat[], i: number): string | undefined => {
  for (let k = i; k >= 0; k--) {
    const b = beats[k];
    if (b.kind === "chip" && b.title) return b.title;
  }
  return undefined;
};

/** What a beat's voice line says: what its scene shows (048b rule), stars removed. */
export const beatLine = (b: Beat): string => {
  if (b.kind === "chip") return joinParts([...(b.title ? [b.title] : []), b.text]);
  if (b.kind === "stat") return joinParts([b.title, [b.value, b.unit].filter(Boolean).join(" "), ...(b.label ? [b.label] : [])]);
  return plain(b.title);
};

/** Script lines: [hook, ...beats, outro?]; voice timings when given. */
export const pixelCinemaScript = ({ hook: h, beats, outro, voice }: Script) => ({
  lines: [joinParts([...(h.strike ? [h.strike] : []), h.line]), ...beats.map(beatLine), ...(outro ? [outro] : [])],
  timings: voice?.lines,
});

/** Shortest scene without a voice: room for each beat's moves (a change every 2-4 s). */
export const minSeconds = (b: Beat | "hook" | "outro") => {
  if (b === "hook") return 3;
  if (b === "outro") return 2;
  if (b.kind === "chip") return b.flash ? 3.2 : 2.6;
  return 3.4;
};
/** End card hold after the outro line is read (the card itself lasts at least CARD_S.cinema). */
export const END_HOLD_S = 1.2;

/**
 * Scenes in frames (0 = hook, 1..n = beats, n+1 = outro when there is one) and where the end
 * card starts: at the outro line, else after the last beat.
 */
export const timelineOf = (p: PixelCinemaProps, fps: number) => {
  const script = pixelCinemaScript(p);
  const kinds: (Beat | "hook" | "outro")[] = ["hook", ...p.beats, ...(p.outro ? ["outro" as const] : [])];
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
  const timeline = fitEndCard(build, p.outro ? END_HOLD_S : CARD_S.cinema, cardStart, CARD_S.cinema, fps);
  return { timeline, endStart: cardStart(timeline) };
};
