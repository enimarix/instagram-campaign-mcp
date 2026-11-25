// PhysiqueScan (owner order 75): schema, the shots on the bed's beat (what src/studio/physique.py
// renders in the blueprint look), the cameras coming round, the hook and the end card.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { CAMEOS, CARD_S, END_CARD_STYLES } from "../src/endcards/schema.ts";
import { BEDS, beatAt, coverOf, HOOK_MIN_S, layoutOf, physiqueSchema, SHOT_BEATS } from "../src/templates/PhysiqueScan/schema.ts";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../props/${name}.json`, import.meta.url), "utf8"));
const EXAMPLE = physiqueSchema.parse(read("physiquescan"));
const ok = (p: object) => physiqueSchema.safeParse(p).success;

test("the example parses: a statue, 2-6 scenes of 1-3 bands, no voice, the card after the shots", () => {
  const { shots, cardStart, total } = layoutOf(EXAMPLE);
  assert.ok(total - cardStart >= CARD_S.physique);
  assert.equal(shots[0].start_s, 0);
  assert.ok(!("voice" in EXAMPLE));
  assert.ok(EXAMPLE.scenes.every((s) => s.bands.length >= 1 && s.bands.length <= 3));
});

test("every cut falls on the bed's beat, shots run end to end, SHOT_BEATS each at most", () => {
  for (const music of Object.keys(BEDS) as (keyof typeof BEDS)[]) {
    const p = physiqueSchema.parse({ ...read("physiquescan"), music });
    const { shots } = layoutOf(p);
    const grid = Array.from({ length: 200 }, (_, n) => beatAt(music, n));
    for (const [i, s] of shots.entries()) {
      assert.ok(grid.some((g) => Math.abs(g - s.start_s) < 1e-9), `${music} shot ${i} starts off the beat`);
      // the opening shot also holds the silence before the bed's first beat
      assert.ok(s.end_s - s.start_s <= (SHOT_BEATS * 60) / BEDS[music].bpm + (i ? 0 : BEDS[music].first) + 1e-9);
      if (i) assert.equal(s.start_s, shots[i - 1].end_s);
    }
  }
});

test("a scene's cameras never repeat back to back, and a close-up looks at one of its bands", () => {
  const p = physiqueSchema.parse({ ...read("physiquescan"), scenes: read("physiquescan").scenes.map((s: object) => ({ ...s, beats: 8, camera: "close" })) });
  const { shots } = layoutOf(p);
  for (const [i, s] of shots.entries()) {
    if (i && shots[i - 1].scene === s.scene) assert.notEqual(s.camera, shots[i - 1].camera);
    if (s.camera === "close") assert.ok(p.scenes[s.scene].bands.some((b) => b.on === s.part));
  }
});

test("the hook is 5 words at most and stays readable; the cover shows it", () => {
  assert.ok(!ok({ ...read("physiquescan"), hook: "un deux trois quatre cinq six" }));
  const { hookOut } = layoutOf(EXAMPLE);
  assert.ok(hookOut >= HOOK_MIN_S);
  assert.ok(coverOf(EXAMPLE, 30) / 30 < hookOut);
});

test("bands ride the statue's parts only, with a short text; scenes 2-6", () => {
  const base = read("physiquescan");
  const scene = base.scenes[0];
  assert.ok(!ok({ ...base, scenes: [{ ...scene, bands: [{ on: "head", text: "x" }] }, scene] }));
  assert.ok(!ok({ ...base, scenes: [{ ...scene, bands: [{ on: "chest", text: "x".repeat(29) }] }, scene] }));
  assert.ok(!ok({ ...base, scenes: [scene] }));
  assert.ok(!ok({ ...base, hero: "dad" }));
});

test("the physique end card is a card style of its own", () => {
  assert.ok(END_CARD_STYLES.includes("physique"));
  assert.deepEqual([...CAMEOS.physique], ["band"]);
  assert.equal(read("physique-endcard").style, "physique");
});
