// Macro3D (step 154): schema, script mapping (048b voice rule), timings, the shot list Blender
// renders, word captions, Marco's poses and mouth, and the engine's subject list.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { CAMEOS, CARD_S } from "../src/endcards/schema.ts";
import { POSES, poseFor, reactionTo } from "../src/macro3d/poses.ts";
import { autoLabel, MOVES, SUBJECTS } from "../src/macro3d/subjects.ts";
import { chunksOf, CHUNK_CHARS, keyIndexes, mouthAt, wordTimes } from "../src/macro3d/words.ts";
import { counterText, coverOf, poseAt, SHOT_S, shotAt, shotsOf } from "../src/templates/Macro3D/layout.ts";
import { macro3dSchema, macro3dScript, timelineOf } from "../src/templates/Macro3D/schema.ts";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../props/${name}.json`, import.meta.url), "utf8"));
const NAMES = ["macro3d", "macro3d-sel", "macro3d-gras"];
const EXAMPLES = NAMES.map((n) => macro3dSchema.parse(read(n)));
const scene = (line: string, extra = {}) => ({ line, subject: "apple", ...extra });
const base = { scenes: [scene("Un."), scene("Deux."), scene("Trois."), scene("Quatre.")], citations: [] };
const ok = (p: object) => macro3dSchema.safeParse(p).success;

test("the three examples parse, run 35-55 s, cite their numbers and leave the card its time", () => {
  for (const [i, p] of EXAMPLES.entries()) {
    const { timeline, endStart, timings } = timelineOf(p, 30);
    const s = timeline.totalFrames / 30;
    assert.ok(s >= 35 && s <= 55, `${NAMES[i]}: ${s} s`);
    assert.ok(timeline.totalFrames - endStart >= CARD_S.macro3d * 30, `${NAMES[i]}: the card plays in full`);
    assert.ok(p.citations.length >= 1, `${NAMES[i]}: numbers need a source`);
    assert.ok(coverOf(p, timings, 30) <= 3 * 30, NAMES[i]);
    assert.equal(p.address, "tu");
  }
  const p = macro3dSchema.parse(base);
  assert.deepEqual([p.address, p.music, p.loop, p.accent, p.scenes[0].look], ["tu", "music-cutaway-c", false, "kcal", "plain"]);
});

test("bad props fail: scene count, key not in the line, still counters, unknown subjects, prices", () => {
  assert.equal(ok({ ...base, scenes: base.scenes.slice(0, 3) }), false);
  assert.equal(ok({ ...base, scenes: [scene("Le sel retient l'eau.", { key: "gras" }), ...base.scenes.slice(1)] }), false);
  assert.equal(ok({ ...base, scenes: [scene("Le sel retient l'eau.", { key: "l'eau" }), ...base.scenes.slice(1)] }), true);
  assert.equal(ok({ ...base, scenes: [scene("Un.", { counter: { from: 2, to: 2, unit: "kg" } }), ...base.scenes.slice(1)] }), false);
  assert.equal(ok({ ...base, scenes: [scene("Un.", { subject: "tyre" }), ...base.scenes.slice(1)] }), false);
  assert.equal(ok({ ...base, outro: "Seulement 4,99 € par mois" }), false);
  assert.equal(ok({ ...base, voice: { lines: [{ text: "x", start_s: 0, end_s: 1 }] } }), false);
});

test("the script is each scene's line, then the outro (= SCRIPTS in src/studio/motion.py)", () => {
  assert.deepEqual(macro3dScript({ ...EXAMPLES[0], voice: undefined }).lines.slice(0, 2), [
    "En déficit calorique, la nourriture n'est pas ton ennemie. C'est ton alliée.",
    "Ce qui te fait perdre du poids, c'est le total de ta journée, pas un repas sauté.",
  ]);
  assert.equal(macro3dScript(EXAMPLES[0]).lines.at(-1), "Mange mieux, pas moins : compte juste.");
  assert.equal(macro3dScript({ ...EXAMPLES[0], outro: undefined }).lines.length, EXAMPLES[0].scenes.length);
});

test("shots cover frame 0 to the end card, cut every 1-3 s, cut away halfway and never repeat a move", () => {
  for (const p of EXAMPLES) {
    const { timeline, endStart } = timelineOf(p, 30);
    const shots = shotsOf(p, timeline, endStart, 30);
    assert.equal(shots[0].start, 0);
    assert.equal(shots.at(-1)!.end, endStart);
    shots.forEach((s, i) => {
      if (i) assert.equal(s.start, shots[i - 1].end, "no gap");
      assert.ok(s.end - s.start >= 30 && s.end - s.start <= 3.2 * 30, `${s.end - s.start} frames`);
      assert.ok(SUBJECTS.includes(s.subject) && MOVES.includes(s.move));
    });
    p.scenes.forEach((s, i) => {
      const mine = shots.filter((x) => x.scene === i);
      if (s.cut) assert.equal(mine.at(-1)!.subject, s.cut);
      if (!s.moves) mine.slice(1).forEach((x, k) => assert.notEqual(x.move, mine[k].move));
    });
  }
  // a short scene still gets a shot of its own, a long one up to 3
  const p = macro3dSchema.parse(base);
  const { timeline, endStart } = timelineOf(p, 30);
  assert.ok(shotsOf(p, timeline, endStart, 30).length >= 4);
  assert.ok(SHOT_S * 30 <= 3 * 30);
  // the scale shows the counter's target on its display
  const sel = EXAMPLES[1];
  const t = timelineOf(sel, 30);
  assert.equal(shotsOf(sel, t.timeline, t.endStart, 30)[0].text, "71,0");
});

test("captions: word times fill the line, chunks stay short, the key word is found", () => {
  const words = wordTimes("Sauter des repas ? Souvent, ça finit en fringale le soir.", 1, 4);
  assert.equal(words[0].start, 1);
  assert.ok(Math.abs(words.at(-1)!.end - 4) < 1e-9);
  words.forEach((w, i) => i && assert.ok(Math.abs(w.start - words[i - 1].end) < 1e-9));
  const chunks = chunksOf(words);
  assert.deepEqual(chunks[0], [0, 4]); // ends at the question mark
  for (const [a, b] of chunks) {
    const text = words.slice(a, b).map((w) => w.text).join(" ");
    assert.ok(b - a === 1 || text.length <= CHUNK_CHARS, text);
  }
  assert.equal(chunks.at(-1)![1], words.length);
  assert.deepEqual(keyIndexes(words, "Fringale"), [8]);
  assert.deepEqual(keyIndexes(wordTimes("C'est 1,6 g par kilo.", 0, 1), "1,6 g"), [1, 2]);
  assert.deepEqual(keyIndexes(words, "absent"), []);
  // a no-break space before « ? » keeps it on its word
  assert.equal(wordTimes("Combien ? Assez.", 0, 1).length, 2);
});

test("mouth: closed out of the line, shapes from the letter being said", () => {
  assert.equal(mouthAt("Bonjour", 1, 2, 0.5), "closed");
  assert.equal(mouthAt("Bonjour", 1, 2, 2), "closed");
  assert.equal(mouthAt("aaaa", 0, 1, 0.5), "open");
  assert.equal(mouthAt("oooo", 0, 1, 0.5), "round");
  assert.equal(mouthAt("mmmm", 0, 1, 0.5), "closed");
  assert.equal(mouthAt("éééé", 0, 1, 0.5), "wide");
});

test("poses: read from the line, a different reaction on the second shot, given poses hold", () => {
  assert.equal(poseFor("Tu as pris un kilo ?", 0), "shrug");
  assert.equal(poseFor("Pourquoi autant ?", 0), "think");
  assert.equal(poseFor("Ce n'est pas du gras.", 0), "stop");
  assert.equal(poseFor("C'est presque impossible !", 0), "wow");
  assert.equal(poseFor("Vise 1,6 g.", 0), "point");
  for (const pose of POSES) for (let n = 0; n < 3; n++) assert.notEqual(reactionTo(pose, n), pose === "thumbs" ? "x" : pose);
  const p = EXAMPLES[0];
  const { timeline, endStart } = timelineOf(p, 30);
  const shots = shotsOf(p, timeline, endStart, 30);
  const s1 = shots.filter((s) => s.scene === 1);
  assert.notEqual(poseAt(p, shots, s1[0].start).pose, poseAt(p, shots, s1[1].start).pose);
  const s0 = shots.filter((s) => s.scene === 0);
  assert.equal(poseAt(p, shots, s0[1].start).pose, "stop"); // given: holds the whole scene
  assert.equal(shotAt(shots, 99999), shots.at(-1));
});

test("labels and counters", () => {
  assert.equal(autoLabel("apple", "plain"), "none");
  assert.equal(autoLabel("salt", "plain"), "agrandie");
  assert.equal(autoLabel("apple", "heat"), "couleur");
  assert.equal(autoLabel("egg", "section"), "coupe");
  assert.equal(autoLabel("apple", "section"), "none");
  assert.equal(counterText({ from: 0, to: 1.6, decimals: 1 }, 0.5), "0,8");
  assert.equal(counterText({ from: 2400, to: 1900, decimals: 0 }, 1), "1900");
  assert.deepEqual([...CAMEOS.macro3d], ["marco"]);
});

test("the engine knows every subject and move the template can ask for (cinematic/engine/macro.py)", () => {
  const engine = readFileSync(new URL("../../cinematic/engine/macro.py", import.meta.url), "utf8");
  const block = (name: string) => engine.slice(engine.indexOf(`${name} = {`), engine.indexOf("}\n", engine.indexOf(`${name} = {`)));
  const keys = (src: string) => [...src.matchAll(/"(\w+)":/g)].map((m) => m[1]);
  assert.deepEqual(keys(block("SUBJECTS")).sort(), [...SUBJECTS].sort());
  assert.deepEqual(keys(block("MOVES")).sort(), [...MOVES].sort());
});
