import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { CARD_S } from "../src/endcards/schema.ts";
import { openWorldSchema, openWorldScript, pickupFrames, timelineOf } from "../src/templates/OpenWorld/schema.ts";

const sample = () => openWorldSchema.parse(JSON.parse(readFileSync(new URL("../props/openworld.json", import.meta.url), "utf8")));

test("the script reads hook, mission, chase, loot, clear, passed, outro", () => {
  const { lines } = openWorldScript(sample());
  assert.deepEqual(lines, [
    "Votre fringale de 23 h, ce n'est pas la volonté",
    "Sèche sans fringale. Objectif : moins de 1 800 kcal par jour",
    "Une fringale vous traque. 23 h, le snack d'en bas est ouvert.",
    "Au dîner, prenez 30 g de protéines.",
    "Fringale semée. Rien à grignoter à 23 h.",
    "Mission réussie, +30 g de protéines au dîner",
    "Chaque repas, une mission.",
  ]);
});

test("the end card starts at the outro line and gets its whole length", () => {
  const p = sample();
  const { timeline, endStart } = timelineOf(p, 30);
  assert.equal(endStart, timeline.scenes[6].startFrame);
  assert.ok(timeline.totalFrames - endStart >= CARD_S.gta6 * 30);
  const noOutro = timelineOf({ ...p, outro: undefined }, 30);
  assert.equal(noOutro.endStart, noOutro.timeline.outroStart);
});

test("pickups are collected in order inside the loot scene", () => {
  for (const n of [1, 2, 3]) {
    const f = pickupFrames(n, 120);
    assert.equal(f.length, n);
    assert.ok(f.every((x, i) => x > 0 && x < 120 && (i === 0 || x > f[i - 1])));
  }
});

test("a highlight must be a part of its line, and the voice needs one timing per line", () => {
  const p = sample();
  assert.equal(openWorldSchema.safeParse({ ...p, chase: { ...p.chase, highlight: "absent" } }).success, false);
  const lines = [{ text: "x", start_s: 0, end_s: 1 }];
  assert.equal(openWorldSchema.safeParse({ ...p, voice: { lines } }).success, false);
});
