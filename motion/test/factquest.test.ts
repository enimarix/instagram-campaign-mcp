import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { buildTimeline } from "../src/lib/timeline.ts";
import { factQuestSchema, factQuestScript } from "../src/templates/FactQuest/schema.ts";

const example = JSON.parse(readFileSync(new URL("../props/factquest.json", import.meta.url), "utf8"));
const fact = (i: number) => ({ text: `Fact ${i}` });
const base = { hook: "Hook?", facts: [1, 2, 3].map(fact), outro: "Follow for level 2", citations: [] };

test("the example props parse; defaults: loop, overworld music", () => {
  assert.ok(factQuestSchema.safeParse(example).success);
  assert.equal(factQuestSchema.parse(base).loop, true);
  assert.equal(factQuestSchema.parse(base).music, "music-overworld");
  assert.equal(factQuestSchema.parse({ ...base, music: "none" }).music, "none");
});

test("schema rejects unknown keys, 2 or 6 facts, missing citations, bad voice lines", () => {
  const bad = (p: object) => assert.equal(factQuestSchema.safeParse(p).success, false, JSON.stringify(p));
  bad({ ...base, extra: 1 });
  bad({ ...base, music: "sfx-coin" });
  bad({ ...base, facts: [{ text: "x", url: "y" }, fact(2), fact(3)] });
  bad({ ...base, facts: [1, 2].map(fact) });
  bad({ ...base, facts: [1, 2, 3, 4, 5, 6].map(fact) });
  bad({ hook: base.hook, facts: base.facts, outro: base.outro });
  bad({ ...base, citations: [{ url: "javascript:alert(1)" }] });
  bad({ ...base, voice: { lines: [{ text: "Hook?", start_s: 0, end_s: 1 }] } });
  assert.ok(factQuestSchema.safeParse({ ...base, facts: [1, 2, 3, 4, 5].map(fact) }).success);
});

test("script lines are hook, each fact, outro; voice timings ride along", () => {
  const props = factQuestSchema.parse(base);
  assert.deepEqual(factQuestScript(props), {
    lines: ["Hook?", "Fact 1", "Fact 2", "Fact 3", "Follow for level 2"],
    timings: undefined,
  });
  const lines = factQuestScript(props).lines.map((text, i) => ({ text, start_s: i * 2, end_s: i * 2 + 1.5 }));
  const voiced = factQuestSchema.parse({ ...base, voice: { lines } });
  assert.deepEqual(factQuestScript(voiced).timings, lines);
  const t = buildTimeline({ ...factQuestScript(voiced), fps: 30, hookSeconds: 1.5, outroSeconds: 0.5, loop: true });
  // One scene per line, ending with the end card; length follows the voice.
  assert.equal(t.scenes.length, 5);
  assert.equal(t.scenes[4].startFrame, 240);
  assert.equal(t.outroStart, 285);
});
