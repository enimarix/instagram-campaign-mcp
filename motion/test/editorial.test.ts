// Editorial (step 144): schema, script mapping (048b voice rule), timings, the blossom model.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { CAMEOS, CARD_S } from "../src/endcards/schema.ts";
import { gustOf, makeTree, petalsAt, PX, snap, TREE } from "../src/editorial/blossom.ts";
import { captionLines } from "../src/editorial/caption.ts";
import { CHARACTER_IDS } from "../src/editorial/palette.ts";
import { cameraOf, payoffCamera } from "../src/templates/Editorial/layout.ts";
import { bloomOf, cameoOf, compositionOf, editorialSchema, editorialScript, joinLine, TREE_ACTIONS, timelineOf } from "../src/templates/Editorial/schema.ts";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../props/${name}.json`, import.meta.url), "utf8"));
const NAMES = ["editorial", "editorial-habitudes", "editorial-courbatures"];
const base = {
  hook: { lead: "Ce n'est pas la faim.", key: "C'est le timing." },
  chapters: [
    { scene: "tree", title: "Un" },
    { scene: "anatomy", character: "stomach", caption: "Ton estomac met 20 minutes." },
    { scene: "split", title: "Trois" },
  ],
  payoff: { lead: "Pas de la volonté.", key: "De la méthode." },
  citations: [],
};

test("the three examples parse and run 20-40 s without a voice; defaults: vous, lounge, no loop", () => {
  for (const name of NAMES) {
    const parsed = editorialSchema.safeParse(read(name));
    assert.ok(parsed.success, parsed.success ? "" : `${name}: ${parsed.error.message}`);
    const s = timelineOf(parsed.data, 30).timeline.totalFrames / 30;
    assert.ok(s >= 20 && s <= 40, `${name}: ${s} s`);
  }
  const p = editorialSchema.parse(base);
  assert.deepEqual([p.kicker, p.address, p.music, p.loop, p.accent], ["macroBody", "vous", "music-lounge", false, "brand"]);
  const [tree, anatomy, split] = p.chapters;
  assert.ok(tree.scene === "tree" && tree.action === "bloom" && tree.bloom === 1 && tree.tags.length === 0);
  assert.ok(anatomy.scene === "anatomy" && anatomy.mood === "neutral");
  assert.ok(split.scene === "split" && split.before === "sans méthode" && split.after === "avec méthode");
});

test("bad props fail with clear messages", () => {
  const message = (p: object) => {
    const r = editorialSchema.safeParse(p);
    assert.equal(r.success, false, JSON.stringify(p));
    return r.success ? "" : r.error.issues.map((i) => i.message).join("; ");
  };
  const [tree, anatomy] = base.chapters;
  assert.match(message({ ...base, outro: "Seulement 9,99 € par mois" }), /no price on screen/);
  assert.match(message({ ...base, hook: { ...base.hook, key: "Dès 5 euros" } }), /no price on screen/);
  assert.match(message({ ...base, chapters: [{ ...tree, stat: { value: "4,99", unit: "€" } }, anatomy, tree] }), /no price on screen/);
  assert.match(message({ ...base, hook: { ...base.hook, strike: "soif" } }), /strike must be a word of lead/);
  assert.match(message({ ...base, chapters: [tree, { ...anatomy, highlight: "une heure" }, tree] }), /highlight must be a part of caption/);
  assert.match(message({ ...base, chapters: [{ ...tree, tags: [{ text: "eau" }], stat: { value: "2", unit: "litres" } }, anatomy, tree] }), /tags or a stat, not both/);
  assert.match(message({ ...base, chapters: [tree, anatomy] }), /Too small|at least/);
  assert.match(message({ ...base, voice: { lines: [{ text: "x", start_s: 0, end_s: 1 }] } }), /one timing per script line/);
  message({ ...base, chapters: [tree, { ...anatomy, character: "liver" }, tree] });
  // Variety (owner): never the same composition twice in a row, and no type-only beat right after the type-only hook.
  assert.match(message({ ...base, chapters: [tree, anatomy, anatomy] }), /same composition \(anatomy\)/);
  assert.match(message({ ...base, chapters: [tree, { ...tree, title: "Deux" }, anatomy] }), /same composition \(tree bloom\)/);
  assert.match(message({ ...base, chapters: [{ scene: "type", title: "Un" }, tree, anatomy] }), /start the chapters with a picture/);
  message({ ...base, cameo: "golem" });
  message({ ...base, extra: 1 });
});

test("script lines: hook, each chapter (caption or title + key), payoff, outro (048b)", () => {
  const p = editorialSchema.parse({ ...base, outro: "Prenez le temps." });
  assert.deepEqual(editorialScript(p).lines, [
    "Ce n'est pas la faim. C'est le timing.",
    "Un",
    "Ton estomac met 20 minutes.",
    "Trois",
    "Pas de la volonté. De la méthode.",
    "Prenez le temps.",
  ]);
  assert.equal(joinLine("Le même objectif", "Écoutez"), "Le même objectif. Écoutez");
  assert.equal(joinLine("Ralentissez", "et la satiété suit"), "Ralentissez, et la satiété suit");
  assert.equal(joinLine("Ça prend du temps", "66 jours"), "Ça prend du temps, 66 jours");
  assert.equal(joinLine("Fini.", "Ensuite"), "Fini. Ensuite");
});

test("timings: voice lines drive the scenes; the end card holds its own length", () => {
  const p = editorialSchema.parse({ ...base, outro: "Prenez le temps." });
  const lines = editorialScript(p).lines.map((text, i) => ({ text, start_s: i * 4, end_s: i * 4 + 3.5 }));
  const { timeline, endStart } = timelineOf({ ...p, voice: { lines } }, 30);
  assert.deepEqual(timeline.scenes.map((s) => s.startFrame), [0, 120, 240, 360, 480, 600]);
  assert.equal(endStart, 600); // the card comes in with the outro line
  assert.ok(timeline.totalFrames - endStart >= CARD_S.editorial * 30);
  const noOutro = timelineOf(editorialSchema.parse(base), 30);
  assert.equal(noOutro.endStart, noOutro.timeline.outroStart);
});

test("bloom carries over between tree chapters; the cameo defaults to the first anatomy character", () => {
  const chapters = editorialSchema.parse({
    ...base,
    chapters: [{ scene: "tree", title: "A", bloom: 0.4 }, base.chapters[1], { scene: "tree", title: "B", bloom: 0.9 }, { scene: "tree", title: "C", action: "wind", bloom: 1 }],
  }).chapters;
  assert.deepEqual(bloomOf(chapters, 0), [0.15, 0.4]);
  assert.deepEqual(bloomOf(chapters, 2), [0.4, 0.9]);
  assert.deepEqual(bloomOf(chapters, 3), [1, 1]); // only the bloom action grows
  assert.equal(cameoOf({ chapters }), "stomach");
  assert.equal(cameoOf({ chapters: [chapters[0]] }), "tree");
  assert.equal(cameoOf({ chapters, cameo: "none" }), "none");
  assert.deepEqual(CAMEOS.editorial, ["tree", ...CHARACTER_IDS]);
});

test("the blossom tree is seeded, on the pixel grid, and its petals fall to the ground", () => {
  assert.deepEqual(makeTree(), TREE); // same seed, same tree
  assert.notDeepEqual(makeTree(8).flowers.slice(0, 5), TREE.flowers.slice(0, 5));
  assert.ok(TREE.flowers.length > 800 && TREE.height > 500);
  assert.equal(snap(13) % PX, 0);
  for (const frame of [0, 45, 300]) {
    const petals = petalsAt(frame, 30, 1);
    assert.ok(petals.length > 0 && petals.every((p) => p.y <= 30 && p.o > 0 && p.o <= 1));
  }
  assert.deepEqual(petalsAt(10, 30, 0), []); // a bare tree sheds nothing
  // The gust: still, leans back (anticipation), pushes, settles.
  assert.equal(gustOf(0, 100), 0);
  assert.ok(gustOf(30, 100) < 0 && gustOf(48, 100) > 0.9 && Math.abs(gustOf(100, 100)) < 0.1);
});

test("every example alternates its compositions; every shot has a camera move", () => {
  for (const name of NAMES) {
    const kinds = editorialSchema.parse(read(name)).chapters.map(compositionOf);
    kinds.forEach((k, i) => assert.ok(!i || k !== kinds[i - 1], `${name}: ${kinds.join(" | ")}`));
    assert.ok(new Set(kinds).size >= 3, `${name}: at least 3 different shots`);
  }
  const moved = (a: object, b: object) => JSON.stringify(a) !== JSON.stringify(b);
  for (const action of TREE_ACTIONS) assert.ok(moved(cameraOf(action, 0), cameraOf(action, 1)), action);
  assert.ok(moved(payoffCamera(0), payoffCamera(1)));
  assert.ok(cameraOf("petals", 0.5).z > 2, "petals is a close-up");
  assert.equal(cameraOf("frame", 0.3).z, 1); // wide while the viewfinder closes, then the zoom
  assert.ok(cameraOf("frame", 0.9).z > 1.4);
});

test("pixel captions keep French accents (142's bitmap font) and split the highlight across lines", () => {
  const { unit, lines } = captionLines("Tes courbatures culminent 48 à 72 h après la séance.", "48 à 72 h", 860);
  assert.ok(unit >= 4 && unit <= 7 && lines.length <= 4);
  const all = lines.map((l) => l.text).join(" ");
  assert.match(all, /après la séance\./); // accents kept (drawn above the capitals by the font)
  assert.ok(!lines.some((l) => /\d$/.test(l.text.trim()) && l.text.endsWith(" ")), "a number stays with its unit");
  const marked = lines.flatMap((l) => (l.mark ? [l.text.slice(...l.mark)] : [])).join(" ");
  assert.equal(marked.replace(/\u00a0/g, " "), "48 à 72 h");
  assert.ok(captionLines("Ton estomac met 20 minutes à dire stop.", undefined, 860).lines.every((l) => l.mark === null));
});
