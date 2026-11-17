import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { ASSETS } from "../src/assets.ts";
import { buildTimeline } from "../src/lib/timeline.ts";
import { bossBattleSchema, bossBattleScript, FIGHTER_SPRITES, healthSteps } from "../src/templates/BossBattle/schema.ts";

const example = JSON.parse(readFileSync(new URL("../props/bossbattle.json", import.meta.url), "utf8"));
const round = (attacker: "left" | "right", i: number) => ({ attacker, text: `Round ${i}` });
const base = {
  hook: "Hook?",
  left: { name: "MYTH" },
  right: { name: "FACT" },
  rounds: [round("left", 1), round("right", 2), round("right", 3)],
  verdict: { winner: "right", text: "Fact wins" },
  citations: [],
};

test("the example props parse; loop defaults to true", () => {
  assert.ok(bossBattleSchema.safeParse(example).success);
  assert.equal(bossBattleSchema.parse(base).loop, true);
});

test("schema rejects unknown keys, 1 or 5 rounds, bad sides and sprites, missing citations, bad voice lines", () => {
  const bad = (p: object) => assert.equal(bossBattleSchema.safeParse(p).success, false, JSON.stringify(p));
  bad({ ...base, extra: 1 });
  bad({ ...base, left: { name: "MYTH", hp: 3 } });
  bad({ ...base, left: { name: "MYTH", sprite: "tiles" } });
  bad({ ...base, rounds: [round("left", 1)] });
  bad({ ...base, rounds: [1, 2, 3, 4, 5].map((i) => round("left", i)) });
  bad({ ...base, rounds: [{ attacker: "both", text: "x" }, round("left", 2)] });
  bad({ ...base, verdict: { winner: "nobody", text: "x" } });
  const { citations: _, ...uncited } = base;
  bad(uncited);
  bad({ ...base, citations: [{ url: "javascript:alert(1)" }] });
  bad({ ...base, voice: { lines: [{ text: "Hook?", start_s: 0, end_s: 1 }] } });
  assert.ok(bossBattleSchema.safeParse({ ...base, rounds: [1, 2, 3, 4].map((i) => round("left", i)) }).success);
});

test("fighter sprites are sheets in the asset registry", () => {
  for (const id of FIGHTER_SPRITES) assert.ok(ASSETS[id].frames > 0, id);
});

test("script lines are hook, each round, verdict; voice timings ride along", () => {
  const props = bossBattleSchema.parse(base);
  assert.deepEqual(bossBattleScript(props), {
    lines: ["Hook?", "Round 1", "Round 2", "Round 3", "Fact wins"],
    timings: undefined,
  });
  const lines = bossBattleScript(props).lines.map((text, i) => ({ text, start_s: i * 2, end_s: i * 2 + 1.5 }));
  const voiced = bossBattleSchema.parse({ ...base, voice: { lines } });
  assert.deepEqual(bossBattleScript(voiced).timings, lines);
  const t = buildTimeline({ ...bossBattleScript(voiced), fps: 30, hookSeconds: 1.5, outroSeconds: 0.5, loop: true });
  assert.equal(t.scenes.length, 5);
  assert.equal(t.outroStart, 285);
});

test("health drops a quarter per hit taken over 3 rounds, the verdict knocks the loser out", () => {
  const props = bossBattleSchema.parse(base);
  assert.deepEqual(healthSteps(props), [
    { left: 1, right: 1 },
    { left: 1, right: 0.75 },
    { left: 0.75, right: 0.75 },
    { left: 0.5, right: 0.75 },
    { left: 0, right: 0.75 },
  ]);
});

test("a draw leaves both standing; nobody falls before the verdict", () => {
  const props = bossBattleSchema.parse({
    ...base,
    rounds: [1, 2, 3, 4].map((i) => round("right", i)),
    verdict: { winner: "draw", text: "Both partly right" },
  });
  const steps = healthSteps(props);
  assert.equal(steps.length, 6);
  assert.deepEqual(steps.at(-1), { left: 1 - 4 / 5, right: 1 });
  assert.deepEqual(steps.at(-1), steps.at(-2));
  assert.ok(steps.slice(0, -1).every((h) => h.left > 0 && h.right > 0));
});
