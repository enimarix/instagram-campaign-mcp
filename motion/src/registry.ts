import type { ComponentType } from "react";
import type { z } from "zod";
import { type Event, scriptEvents } from "./lib/events";
import { Cutaway } from "./templates/Cutaway/Cutaway";
import { cutawaySchema, timelineOf as cutawayTimeline } from "./templates/Cutaway/schema";
import { BossBattle, timelineOf as bossBattleTimeline } from "./templates/BossBattle/BossBattle";
import { bossBattleSchema } from "./templates/BossBattle/schema";
import { DialogStory, timelineOf as dialogStoryTimeline } from "./templates/DialogStory/DialogStory";
import { dialogStorySchema } from "./templates/DialogStory/schema";
import { FactQuest, timelineOf as factQuestTimeline } from "./templates/FactQuest/FactQuest";
import { factQuestSchema } from "./templates/FactQuest/schema";
import { Hello, helloSchema } from "./templates/Hello";
import { PaperStory } from "./templates/PaperStory/PaperStory";
import { coverFrame as paperStoryCover, transitionInto } from "./templates/PaperStory/layout";
import { paperStorySchema, timelineOf as paperStoryTimeline } from "./templates/PaperStory/schema";
import { PixelSkit, timelineOf as pixelSkitTimeline } from "./templates/PixelSkit/PixelSkit";
import { pixelSkitSchema, voiceParts } from "./templates/PixelSkit/schema";
import { Preview8bit, preview8bitSchema } from "./templates/Preview8bit";
import { QuizChest, timelineOf as quizChestTimeline } from "./templates/QuizChest/QuizChest";
import { quizChestSchema, REVEAL_S } from "./templates/QuizChest/schema";
import { TimelineDemo, timelineDemoSchema, timelineOf } from "./templates/TimelineDemo";
import { VoxelQuest } from "./templates/VoxelQuest/VoxelQuest";
import { timelineOf as voxelQuestTimeline, voxelQuestSchema } from "./templates/VoxelQuest/schema";
import { coverFrame as editorialCover, Editorial } from "./templates/Editorial/Editorial";
import { cutsOf as editorialCuts } from "./templates/Editorial/layout";
import { cameoOf as editorialCameo, editorialSchema, timelineOf as editorialTimeline } from "./templates/Editorial/schema";
import { PixelCinema } from "./templates/PixelCinema/PixelCinema";
import { coverOf as pixelCinemaCover, segmentsOf as pixelCinemaShots } from "./templates/PixelCinema/layout";
import { pixelCinemaSchema, timelineOf as pixelCinemaTimeline } from "./templates/PixelCinema/schema";
import { Macro3D } from "./templates/Macro3D/Macro3D";
import { coverOf as macro3dCover, shotsOf as macro3dShots, type Shot } from "./templates/Macro3D/layout";
import { macro3dSchema, timelineOf as macro3dTimeline } from "./templates/Macro3D/schema";

export const WIDTH = 1080;
export const HEIGHT = 1920;
export const FPS = 30;

/** Visual styles, id -> button label (step 138 lists them; a new style = a new entry here). */
export const STYLES = { pixel: "Pixel 8-bit", voxel: "3D 8-bit", paper: "Papier", cutaway: "Pixel explicatif", editorial: "Éditorial", cinema: "Pixel ciné", macro3d: "Macro 3D" } as const;
export type Style = keyof typeof STYLES;

export type Template<S extends z.ZodType> = {
  /** The template's visual style (STYLES). */
  style: Style;
  component: ComponentType<z.infer<S>>;
  schema: S;
  defaultProps: z.infer<S>;
  durationInFrames: (props: z.infer<S>) => number;
  /** Frame to use as the Reel cover (thumb_offset); script templates use timeline.hookFrame. */
  coverFrame?: (props: z.infer<S>) => number;
  /** What happens when (assets.timeline, step 110); none = the whole video as one event. */
  events?: (props: z.infer<S>) => Event[];
  /** Shots another engine renders before the template (Macro3D: the Blender plates, src/studio/macro3d.py). */
  plates?: (props: z.infer<S>) => Shot[];
  /** Where the voice file plays when the template pauses it: from audio_s on it plays at video at_s (the QC listens there, step 158); none = the whole file from 0. */
  voiceParts?: (props: z.infer<S>) => VoicePart[];
};

export type VoicePart = { audio_s: number; at_s: number };

/** What the 8-bit templates' end card shows (step 137), for their timelines. */
const PIXEL_CARD = "end card (pixel): mB tile, macroBody, 7 jours gratuits, macrobody.fr";

/** Key under which Root passes the cover frame out through the resolved props (render.mjs reads it). */
export const COVER_FRAME_PROP = "__coverFrame";

// Ties component, schema and defaults to one schema type per entry.
const template = <S extends z.ZodType>(t: Template<S>) => t;

// Template id (= composition id, PascalCase like brand/taxonomy.json templates) -> template.
export const templates = {
  Hello: template({
    style: "pixel",
    component: Hello,
    schema: helloSchema,
    defaultProps: { title: "Hello", subtitle: "8-bit pipeline online", seconds: 3, safeZone: false },
    durationInFrames: (p) => Math.round(p.seconds * FPS),
  }),
  Preview8bit: template({
    style: "pixel",
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
    style: "pixel",
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
    style: "pixel",
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
      scriptEvents(factQuestTimeline(p, FPS), FPS, ["hook card", ...p.facts.map((_, i) => `fact ${i + 1}`), PIXEL_CARD], p, "end card hold"),
  }),
  BossBattle: template({
    style: "pixel",
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
        PIXEL_CARD,
      ),
  }),
  QuizChest: template({
    style: "pixel",
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
    voiceParts: (p) => {
      const { countdownStart, gap } = quizChestTimeline(p, FPS);
      return [{ audio_s: 0, at_s: 0 }, { audio_s: countdownStart / FPS, at_s: (countdownStart + gap) / FPS }];
    },
    events: (p) => {
      const { timeline, countdownStart, reveal } = quizChestTimeline(p, FPS);
      const choice = p.choices[p.answer];
      return [
        ...scriptEvents(timeline, FPS, ["hook card", "question + choices", "explanation", PIXEL_CARD], p, "end card hold"),
        { t: countdownStart / FPS, d: p.countdownSeconds, e: `countdown ${p.countdownSeconds} s` },
        { t: reveal / FPS, d: REVEAL_S, e: "chest opens: the answer", text: `${choice.label}: ${choice.text}` },
      ];
    },
  }),
  DialogStory: template({
    style: "pixel",
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
        PIXEL_CARD,
      ),
  }),
  PixelSkit: template({
    style: "pixel",
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
    voiceParts: (p) => voiceParts(pixelSkitTimeline(p, FPS).pauses).map((v) => ({ audio_s: v.trimBefore / FPS, at_s: v.from / FPS })),
    events: (p) => {
      const { timeline, punch, land, freezeStart, freezeEnd } = pixelSkitTimeline(p, FPS);
      const beat = (b: (typeof p.beats)[number], i: number) =>
        `${i + 1 === punch ? "punchline" : i + 1 > punch ? "tag" : `beat ${i + 1}`} (${b.action})`;
      return [
        ...scriptEvents(timeline, FPS, ["hook card", ...p.beats.map(beat)], p, PIXEL_CARD),
        ...(p.sting !== "none" ? [{ t: land / FPS, d: 0, e: `sting: ${p.sting}` }] : []),
        ...(freezeEnd > freezeStart ? [{ t: freezeStart / FPS, d: (freezeEnd - freezeStart) / FPS, e: "freeze on the punchline" }] : []),
      ];
    },
  }),
  VoxelQuest: template({
    style: "voxel",
    component: VoxelQuest,
    schema: voxelQuestSchema,
    defaultProps: {
      hook: "Vous mangez équilibré mais vous ne perdez rien ?",
      hookProp: "scale",
      beats: [
        { kind: "problem", line: "Avocat, noix, huile d'olive : sains, mais très caloriques.", foods: [{ prop: "avocado", label: "160 kcal", macro: "fat" }] },
        { kind: "app", line: "macroBody compte pour vous, au gramme près." },
        { kind: "payoff", line: "Les kilos bougent enfin." },
      ],
      address: "vous",
      fromForm: "etincelle",
      toForm: "recrue",
      accent: "brand",
      citations: [],
      music: "music-marimba",
      loop: false,
      pixelate: 2,
    },
    durationInFrames: (p) => voxelQuestTimeline(p, FPS).timeline.totalFrames,
    coverFrame: (p) => voxelQuestTimeline(p, FPS).timeline.hookFrame,
    events: (p) => {
      const { timeline, endStart } = voxelQuestTimeline(p, FPS);
      const beat = (b: (typeof p.beats)[number]) =>
        `${b.kind}${b.kind === "app" ? " (phone: calorie ring fills)" : b.kind === "payoff" ? ` (golem levels up to ${b.form ?? p.toForm})` : ""}${b.foods ? ` (${b.foods.map((f) => `${f.prop} ${f.label}`).join(", ")})` : ""}`;
      const total = timeline.totalFrames;
      return [
        ...scriptEvents(timeline, FPS, ["hook card", ...p.beats.map(beat), "end card tagline"], p).filter((e) => !e.e.startsWith("end hold")),
        { t: endStart / FPS, d: (total - endStart) / FPS, e: `end card (voxel): mB tile assembles, macroBody, 7 jours gratuits, macrobody.fr; cameo ${p.cameo ?? p.beats[p.beats.length - 1].form ?? p.toForm}` },
      ];
    },
  }),
  PaperStory: template({
    style: "paper",
    component: PaperStory,
    schema: paperStorySchema,
    defaultProps: {
      character: "ines",
      hook: {
        labels: ["21 h. Il vous reste", { text: "308 kcal", tone: "brand", size: "l" }, { text: "Vous mangez quoi ?", tone: "yellow", size: "m" }],
        aside: "(spoiler : pas une pizza)",
        prop: "clock",
        time: "21:00",
      },
      beats: [
        { kind: "problem", labels: ["Une pomme ?", { text: "Pas assez.", tone: "red", size: "m" }], prop: "fridge", time: "21:00", options: [{ food: "apple", label: "≈ 95 kcal", note: "environ", verdict: "too_little" }] },
        { kind: "app", labels: ["Inès ouvre l'app."], value: "308", unit: "kcal restantes", button: "Compléter ma journée" },
        { kind: "payoff", labels: ["Fin de journée :"], value: "2 236", of: "/ 2 238 kcal", stamp: "PILE." },
      ],
      outro: "Terminez la journée pile sur vos objectifs.",
      address: "vous",
      accent: "brand",
      citations: [{ url: "https://fdc.nal.usda.gov/food-details/171688/nutrients", title: "USDA FoodData Central: Apples, raw, with skin (52 kcal / 100 g, a medium apple 182 g = about 95 kcal)" }],
      music: "music-kalimba",
      loop: false,
    },
    durationInFrames: (p) => paperStoryTimeline(p, FPS).timeline.totalFrames,
    coverFrame: (p) => paperStoryCover(p, FPS),
    events: (p) => {
      const { timeline, endStart } = paperStoryTimeline(p, FPS);
      const who = p.character;
      const beat = (b: (typeof p.beats)[number], i: number) => {
        const into = `${transitionInto(i + 1)} in`;
        if (b.kind === "problem") return `problem, ${into} (${b.prop}${b.options.length ? `: ${b.options.map((o) => `${o.food} ${o.label} ${o.verdict}`).join(", ")}` : `, ${who} shrugs`})`;
        if (b.kind === "app") return b.rows ? `app list, ${into} (${b.rows.length} rows solve their grams${b.total ? `, ${b.total}` : ""})` : `app phone, ${into} (ring ${b.value ?? "fills"}, tap « ${b.button} »)`;
        return `payoff, ${into} (${b.value ? `ring ${b.value} ${b.of ?? ""}`.trim() : `${who} cheers`}${b.stamp ? `, stamp ${b.stamp}` : ""})`;
      };
      const total = timeline.totalFrames;
      return [
        ...scriptEvents(timeline, FPS, ["hook card", ...p.beats.map(beat), "end card tagline"], p).filter((e) => !e.e.startsWith("end hold")),
        { t: endStart / FPS, d: (total - endStart) / FPS, e: `end card (paper): kraft cover tears open, mB tile, macroBody, 7 jours gratuits, macrobody.fr; cameo ${p.cameo ?? who}` },
      ];
    },
  }),
  Cutaway: template({
    style: "cutaway",
    component: Cutaway,
    schema: cutawaySchema,
    defaultProps: cutawaySchema.parse({
      hook: { title: "Comment un muscle se contracte ?", sub: "Avec des milliards de petits moteurs.", view: "arm", callouts: [{ text: "Biceps", at: "biceps" }] },
      beats: [
        { title: "On zoome dans le biceps", view: "muscle" },
        { title: "Une fibre, c'est une cellule géante", view: "fibre", speed: "1/10" },
        { title: "Ralenti 84 fois : le sarcomère", view: "sarcomere", speed: "1/84", stage: 0.4 },
        { title: "Les lignes Z se rapprochent", view: "sarcomere", speed: "1/2", stage: 1 },
      ],
      payoff: { title: "Le même moteur, du biceps au cœur.", view: "arm" },
      citations: [],
    }),
    durationInFrames: (p) => cutawayTimeline(p, FPS).timeline.totalFrames,
    coverFrame: (p) => cutawayTimeline(p, FPS).timeline.hookFrame,
    events: (p) => {
      const { timeline, endStart } = cutawayTimeline(p, FPS);
      const scene = (s: (typeof p.beats)[number]) =>
        `${s.view} (${s.speed === "real" ? "real speed" : s.speed.startsWith("x") ? `time-lapse ${s.speed}` : `slow-mo ${s.speed}`}${s.x2 ? " ×2" : ""}${s.zoom !== 1 ? `, zoom ${s.zoom}${s.focus ? ` on ${s.focus}` : ""}` : ""}${s.callouts.length ? `, labels ${s.callouts.map((c) => c.text).join(" / ")}` : ""}${s.bang ? `, burst ${s.bang}` : ""})`;
      const total = timeline.totalFrames;
      return [
        ...scriptEvents(timeline, FPS, [`hook card: ${scene(p.hook)}`, ...p.beats.map((b) => `beat: ${scene(b)}`), `payoff: ${scene(p.payoff)}`, "end card tagline"], p).filter((e) => !e.e.startsWith("end hold")),
        { t: endStart / FPS, d: (total - endStart) / FPS, e: `end card (cutaway): level complete, mB tile dithers in, macroBody, 7 jours gratuits, macrobody.fr; cameo ${p.cameo ?? p.payoff.view}` },
      ];
    },
  }),
  Editorial: template({
    style: "editorial",
    component: Editorial,
    schema: editorialSchema,
    defaultProps: {
      kicker: "macroBody",
      hook: { lead: "Ce n'est pas la faim.", key: "C'est le timing.", strike: "faim" },
      chapters: [
        { scene: "tree", title: "Vous mangez vite", key: "en cinq minutes chrono", action: "wind", bloom: 0.35, tags: [] },
        { scene: "anatomy", character: "stomach", mood: "neutral", then: "surprised", caption: "Ton estomac met 20 minutes à dire stop.", highlight: "20 minutes", stat: { value: "20", unit: "minutes", note: "avant le signal de satiété" } },
        { scene: "tree", title: "Ralentissez", key: "et la satiété suit", action: "bloom", bloom: 1, tags: [] },
      ],
      payoff: { lead: "Ce n'est pas de la volonté.", key: "C'est de la méthode." },
      address: "vous",
      accent: "brand",
      citations: [{ url: "https://www.health.harvard.edu/blog/why-eating-slowly-may-help-you-feel-full-faster-20101019605", title: "Harvard Health: the brain takes about 20 minutes to register fullness" }],
      music: "music-lounge",
      loop: false,
    },
    durationInFrames: (p) => editorialTimeline(p, FPS).timeline.totalFrames,
    coverFrame: (p) => editorialCover(p, FPS),
    events: (p) => {
      const { timeline, endStart } = editorialTimeline(p, FPS);
      const chapter = (c: (typeof p.chapters)[number], i: number) => {
        const n = `chapter ${String(i + 1).padStart(2, "0")}/${String(p.chapters.length).padStart(2, "0")}`;
        if (c.scene === "tree") return `${n} tree ${c.action} shot (bloom ${c.bloom}${c.tags.length ? `, tags ${c.tags.map((t) => t.text).join(", ")}` : ""}${c.stat ? `, stat ${c.stat.value} ${c.stat.unit}` : ""})`;
        if (c.scene === "split") return `${n} before / after split (${c.before} vs ${c.after})`;
        if (c.scene === "type") return `${n} type-only beat`;
        return `${n} anatomy card: ${c.character} ${c.mood}${c.then ? ` -> ${c.then}` : ""}${c.stat ? `, stat ${c.stat.value} ${c.stat.unit}` : ""}`;
      };
      const total = timeline.totalFrames;
      return [
        ...scriptEvents(timeline, FPS, ["hook card", ...p.chapters.map(chapter), "payoff over the tree in full bloom", "end card tagline"], p).filter((e) => !e.e.startsWith("end hold")),
        ...editorialCuts(timeline, p.chapters.length, endStart, FPS).map((c) => ({ t: c.frame / FPS, d: 0, e: `cut: ${c.shot % 2 ? "closer" : "wider"} framing` })),
        { t: endStart / FPS, d: (total - endStart) / FPS, e: `end card (editorial): mB tile, macroBody, 7 jours gratuits, macrobody.fr; cameo ${editorialCameo(p)}` },
      ];
    },
  }),
  PixelCinema: template({
    style: "cinema",
    component: PixelCinema,
    schema: pixelCinemaSchema,
    defaultProps: {
      scene: "window",
      hook: { strike: "C'est pas le régime.", line: "C'est la *méthode*." },
      beats: [
        { kind: "chip", title: "À 21 h, tout se joue *ici* :", text: "la fenêtre de la cuisine", point: "light", flash: false },
        { kind: "chip", text: "ce qu'il reste à manger", point: "subject", flash: false },
        { kind: "chip", text: "le moment de décider", point: "sky", flash: true },
        { kind: "stat", title: "Ce soir, il vous reste", value: "308", unit: "kcal", label: "à placer, pas à deviner" },
      ],
      outro: "Décidez avec vos chiffres, pas au hasard.",
      address: "vous",
      accent: "kcal",
      citations: [],
      music: "music-nocturne",
      loop: false,
    },
    durationInFrames: (p) => pixelCinemaTimeline(p, FPS).timeline.totalFrames,
    coverFrame: (p) => pixelCinemaCover(p, pixelCinemaTimeline(p, FPS).timeline, FPS),
    events: (p) => {
      const { timeline, endStart } = pixelCinemaTimeline(p, FPS);
      let n = 0;
      const beat = (b: (typeof p.beats)[number]) => {
        if (b.kind === "chip") return `chip ${++n}${b.point ? ` → ${b.point}` : ""}${b.flash ? " (lightning: silhouette frame, thunder)" : ""}`;
        return b.kind === "stat" ? `stat ${b.value}${b.unit ? ` ${b.unit}` : ""} counts up over the darkened set` : `app card floats in (ring ${b.value} ${b.unit})`;
      };
      const total = timeline.totalFrames;
      return [
        ...scriptEvents(timeline, FPS, ["hook card", ...p.beats.map(beat), "end card tagline"], p).filter((e) => !e.e.startsWith("end hold")),
        ...pixelCinemaShots(p, timeline, FPS)
          .filter((s) => !timeline.scenes.some((x) => x.startFrame === s.start))
          .map((s) => ({ t: s.start / FPS, d: (s.end - s.start) / FPS, e: `cut: ${s.shot.view} shot` })),
        { t: endStart / FPS, d: (total - endStart) / FPS, e: `end card (cinema): the beam sweeps onto the mB tile over the ${p.scene} set, macroBody, 7 jours gratuits, macrobody.fr` },
      ];
    },
  }),  Macro3D: template({
    style: "macro3d",
    component: Macro3D,
    schema: macro3dSchema,
    defaultProps: {
      scenes: [
        { line: "En déficit, la nourriture n'est pas l'ennemie.", key: "l'ennemie", subject: "plate", look: "plain", pose: "stop" },
        { line: "Les protéines gardent ton muscle.", key: "muscle", subject: "egg", cut: "muscle", look: "section" },
        { line: "Les fibres et l'eau remplissent ton estomac.", key: "remplissent", subject: "fibre", cut: "stomach", look: "plain" },
        { line: "Le déficit vient du total de la journée.", key: "total", subject: "scale", look: "plain", counter: { from: 2400, to: 1900, unit: "kcal", decimals: 0, big: true } },
      ],
      outro: "Mange bien, compte juste.",
      address: "tu",
      accent: "kcal",
      citations: [],
      music: "music-cutaway-c",
      loop: false,
    },
    durationInFrames: (p) => macro3dTimeline(p, FPS).timeline.totalFrames,
    coverFrame: (p) => macro3dCover(p, macro3dTimeline(p, FPS).timings, FPS),
    plates: (p) => {
      const { timeline, endStart } = macro3dTimeline(p, FPS);
      return macro3dShots(p, timeline, endStart, FPS);
    },
    events: (p) => {
      const { timeline, endStart } = macro3dTimeline(p, FPS);
      const scene = (s: (typeof p.scenes)[number], i: number) =>
        i === 0 ? "hook card" : `scene: ${s.subject}${s.cut ? ` then ${s.cut}` : ""}${s.look !== "plain" ? ` (${s.look})` : ""}${s.counter ? `, counter ${s.counter.from} → ${s.counter.to} ${s.counter.unit}` : ""}`;
      const total = timeline.totalFrames;
      return [
        ...scriptEvents(timeline, FPS, [...p.scenes.map(scene), "end card tagline"], p).filter((e) => !e.e.startsWith("end hold")),
        { t: endStart / FPS, d: (total - endStart) / FPS, e: "end card (macro3d): a beam lands on the mB tile, Marco's thumbs-up, macroBody, 7 jours gratuits, macrobody.fr" },
      ];
    },
  }),
};
