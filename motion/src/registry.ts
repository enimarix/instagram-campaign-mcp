import type { ComponentType } from "react";
import type { z } from "zod";
import { type Event, scriptEvents } from "./lib/events";
import { BossBattle, timelineOf as bossBattleTimeline } from "./templates/BossBattle/BossBattle";
import { bossBattleSchema } from "./templates/BossBattle/schema";
import { DialogStory, timelineOf as dialogStoryTimeline } from "./templates/DialogStory/DialogStory";
import { dialogStorySchema } from "./templates/DialogStory/schema";
import { FactQuest, timelineOf as factQuestTimeline } from "./templates/FactQuest/FactQuest";
import { factQuestSchema } from "./templates/FactQuest/schema";
import { Hello, helloSchema } from "./templates/Hello";
import { PixelSkit, timelineOf as pixelSkitTimeline } from "./templates/PixelSkit/PixelSkit";
import { pixelSkitSchema } from "./templates/PixelSkit/schema";
import { Preview8bit, preview8bitSchema } from "./templates/Preview8bit";
import { QuizChest, timelineOf as quizChestTimeline } from "./templates/QuizChest/QuizChest";
import { quizChestSchema, REVEAL_S } from "./templates/QuizChest/schema";
import { TimelineDemo, timelineDemoSchema, timelineOf } from "./templates/TimelineDemo";

export const WIDTH = 1080;
export const HEIGHT = 1920;
export const FPS = 30;

export type Template<S extends z.ZodType> = {
  component: ComponentType<z.infer<S>>;
  schema: S;
  defaultProps: z.infer<S>;
  durationInFrames: (props: z.infer<S>) => number;
  /** Frame to use as the Reel cover (thumb_offset); script templates use timeline.hookFrame. */
  coverFrame?: (props: z.infer<S>) => number;
  /** What happens when (assets.timeline, step 110); none = the whole video as one event. */
  events?: (props: z.infer<S>) => Event[];
};

/** Key under which Root passes the cover frame out through the resolved props (render.mjs reads it). */
export const COVER_FRAME_PROP = "__coverFrame";

// Ties component, schema and defaults to one schema type per entry.
const template = <S extends z.ZodType>(t: Template<S>) => t;

// Template id (= composition id, PascalCase like brand/taxonomy.json templates) -> template.
export const templates = {
  Hello: template({
    component: Hello,
    schema: helloSchema,
    defaultProps: { title: "Hello", subtitle: "8-bit pipeline online", seconds: 3, safeZone: false },
    durationInFrames: (p) => Math.round(p.seconds * FPS),
  }),
  Preview8bit: template({
    component: Preview8bit,
    schema: preview8bitSchema,
    defaultProps: {
      title: "8-BIT KIT",
      text: "Café, crème brûlée, ñandú, Straße",
      name: "Señor Müller",
      dialog: "Où est la crème brûlée? Ça alors, Œdipe l'a mangée!",
      speed: 15,
      seconds: 8,
      safeZone: false,
      hud: true,
      sprites: true,
      crt: true,
      transitions: true,
    },
    durationInFrames: (p) => Math.round(p.seconds * FPS),
  }),
  TimelineDemo: template({
    component: TimelineDemo,
    schema: timelineDemoSchema,
    defaultProps: {
      lines: ["Your gut has more bacteria than you have cells?", "Not quite: about the same number.", "Roughly 38 trillion of them."],
      loop: true,
      safeZone: false,
    },
    durationInFrames: (p) => timelineOf(p, FPS).totalFrames,
    coverFrame: (p) => timelineOf(p, FPS).hookFrame,
  }),
  FactQuest: template({
    component: FactQuest,
    schema: factQuestSchema,
    defaultProps: {
      hook: "Your heart beats 100,000 times a day?",
      facts: [
        { title: "Heart", text: "It beats about 100,000 times a day, without a break." },
        { title: "Bones", text: "An adult has 206 bones; a newborn has nearly 300." },
        { title: "Skin", text: "Skin is the largest organ of the human body." },
      ],
      outro: "Follow for level 2",
      citations: [],
      music: "music-overworld",
      loop: true,
    },
    durationInFrames: (p) => factQuestTimeline(p, FPS).totalFrames,
    coverFrame: (p) => factQuestTimeline(p, FPS).hookFrame,
    events: (p) =>
      scriptEvents(factQuestTimeline(p, FPS), FPS, ["hook card", ...p.facts.map((_, i) => `fact ${i + 1}`), "outro card"], p),
  }),
  BossBattle: template({
    component: BossBattle,
    schema: bossBattleSchema,
    defaultProps: {
      hook: "Cracking your knuckles causes arthritis?",
      left: { name: "MYTH", sprite: "slime" },
      right: { name: "FACT", sprite: "mascot" },
      rounds: [
        { attacker: "left", text: "Grandma said it ruins your joints." },
        { attacker: "right", text: "The pop is just gas bubbles in the joint fluid." },
        { attacker: "right", text: "A doctor cracked one hand for 60 years: no arthritis in either." },
      ],
      verdict: { winner: "right", text: "No link found: crack away, it's harmless." },
      citations: [],
      music: "music-overworld",
      loop: true,
    },
    durationInFrames: (p) => bossBattleTimeline(p, FPS).totalFrames,
    coverFrame: (p) => bossBattleTimeline(p, FPS).hookFrame,
    events: (p) =>
      scriptEvents(
        bossBattleTimeline(p, FPS),
        FPS,
        [
          "hook card",
          ...p.rounds.map((r, i) => `round ${i + 1} (${p[r.attacker].name} hits)`),
          `verdict (${p.verdict.winner === "draw" ? "draw" : `${p[p.verdict.winner].name} wins`})`,
        ],
        p,
      ),
  }),
  QuizChest: template({
    component: QuizChest,
    schema: quizChestSchema,
    defaultProps: {
      hook: "Only 1 in 5 gets this right!",
      question: "How many bones does an adult human have?",
      choices: [
        { label: "A", text: "106" },
        { label: "B", text: "206" },
        { label: "C", text: "306" },
      ],
      answer: 1,
      countdownSeconds: 5,
      explanation: "206: a newborn has nearly 300, and many fuse together as it grows.",
      cta: "Comment your answer!",
      citations: [],
      music: "music-overworld",
      loop: true,
    },
    durationInFrames: (p) => quizChestTimeline(p, FPS).timeline.totalFrames,
    coverFrame: (p) => quizChestTimeline(p, FPS).timeline.hookFrame,
    events: (p) => {
      const { timeline, countdownStart, reveal } = quizChestTimeline(p, FPS);
      const choice = p.choices[p.answer];
      return [
        ...scriptEvents(timeline, FPS, ["hook card", "question + choices", "explanation", "cta card"], p),
        { t: countdownStart / FPS, d: p.countdownSeconds, e: `countdown ${p.countdownSeconds} s` },
        { t: reveal / FPS, d: REVEAL_S, e: "chest opens: the answer", text: `${choice.label}: ${choice.text}` },
      ];
    },
  }),
  DialogStory: template({
    component: DialogStory,
    schema: dialogStorySchema,
    defaultProps: {
      hook: "Bananas are radioactive?!",
      characters: [
        { name: "PIXEL", side: "left" },
        { name: "SLIMY", side: "right" },
      ],
      lines: [
        { speaker: 1, text: "I heard bananas are radioactive!" },
        { speaker: 0, text: "True: they contain a little potassium-40." },
        { speaker: 1, text: "So I should stop eating them?" },
        { speaker: 0, text: "No! The dose from one banana is tiny, far below a single day of natural background." },
      ],
      moral: "Radioactive is not the same as dangerous: the dose makes the poison.",
      citations: [],
      music: "music-overworld",
      loop: true,
    },
    durationInFrames: (p) => dialogStoryTimeline(p, FPS).totalFrames,
    coverFrame: (p) => dialogStoryTimeline(p, FPS).hookFrame,
    events: (p) =>
      scriptEvents(
        dialogStoryTimeline(p, FPS),
        FPS,
        ["hook card", ...p.lines.map((l) => `dialogue ${p.characters[l.speaker].name}`), "moral"],
        p,
      ),
  }),
  PixelSkit: template({
    component: PixelSkit,
    schema: pixelSkitSchema,
    defaultProps: {
      hook: "POV: you open the fridge for the 5th time",
      cast: [{ name: "YOU" }],
      beats: [
        { line: "Still nothing to eat in here.", action: "stare" },
        { line: "Closes it. Opens it again.", action: "shake" },
        { line: "A new snack has not appeared.", action: "facepalm" },
      ],
      tag: false,
      holdBeforePunchline_s: 0.6,
      freezeOnPunchline: true,
      sting: "hit",
      citations: [],
      music: "music-overworld",
      loop: true,
    },
    durationInFrames: (p) => pixelSkitTimeline(p, FPS).timeline.totalFrames,
    coverFrame: (p) => pixelSkitTimeline(p, FPS).timeline.hookFrame,
    events: (p) => {
      const { timeline, punch, land, freezeStart, freezeEnd } = pixelSkitTimeline(p, FPS);
      const beat = (b: (typeof p.beats)[number], i: number) =>
        `${i + 1 === punch ? "punchline" : i + 1 > punch ? "tag" : `beat ${i + 1}`} (${b.action})`;
      return [
        ...scriptEvents(timeline, FPS, ["hook card", ...p.beats.map(beat)], p),
        ...(p.sting !== "none" ? [{ t: land / FPS, d: 0, e: `sting: ${p.sting}` }] : []),
        ...(freezeEnd > freezeStart ? [{ t: freezeStart / FPS, d: (freezeEnd - freezeStart) / FPS, e: "freeze on the punchline" }] : []),
      ];
    },
  }),
};
