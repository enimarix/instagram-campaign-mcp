import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { buildTimeline } from "../src/lib/timeline.ts";
import { ASSETS } from "../src/assets.ts";
import { countdownAt, countdownTicks, MUSIC, quizChestSchema, quizChestScript, REVEAL_S, withCountdown } from "../src/templates/QuizChest/schema.ts";

const example = JSON.parse(readFileSync(new URL("../props/quizchest.json", import.meta.url), "utf8"));
const base = {
  hook: "Hook?",
  question: "Question?",
  choices: [
    { label: "A", text: "One" },
    { label: "B", text: "Two" },
  ],
  answer: 1,
  explanation: "Because.",
  citations: [],
};

test("the example props parse; defaults: loop, 5 s countdown, cta, overworld music", () => {
  assert.ok(quizChestSchema.safeParse(example).success);
  const p = quizChestSchema.parse(base);
  assert.equal(p.loop, true);
  assert.equal(p.countdownSeconds, 5);
  assert.equal(p.cta, "Comment your answer!");
  assert.equal(p.music, "music-overworld");
  assert.equal(quizChestSchema.parse({ ...base, music: "none" }).music, "none");
});

test("music choices are music loops in the asset registry", () => {
  for (const id of MUSIC) if (id !== "none") assert.equal(ASSETS[id].kind, "music", id);
});

test("schema rejects unknown keys, 1 or 5 choices, a bad countdown, missing citations, bad voice lines", () => {
  const bad = (p: object) => assert.equal(quizChestSchema.safeParse(p).success, false, JSON.stringify(p));
  bad({ ...base, extra: 1 });
  bad({ ...base, choices: [{ label: "A", text: "One", right: true }, base.choices[1]] });
  bad({ ...base, choices: [base.choices[0]], answer: 0 });
  bad({ ...base, choices: [1, 2, 3, 4, 5].map((i) => ({ label: String(i), text: "x" })) });
  for (const countdownSeconds of [2, 11, 4.5]) bad({ ...base, countdownSeconds });
  const { citations: _, ...uncited } = base;
  bad(uncited);
  bad({ ...base, citations: [{ url: "javascript:alert(1)" }] });
  bad({ ...base, voice: { lines: [{ text: "Hook?", start_s: 0, end_s: 1 }] } });
  bad({ ...base, music: "sfx-coin" });
});

test("answer must index one of the choices", () => {
  const ok = (answer: number) => quizChestSchema.safeParse({ ...base, answer }).success;
  assert.ok(ok(0));
  assert.ok(ok(1));
  assert.equal(ok(2), false);
  assert.equal(ok(-1), false);
  assert.equal(ok(0.5), false);
  const four = { ...base, choices: [1, 2, 3, 4].map((i) => ({ label: String(i), text: "x" })) };
  assert.ok(quizChestSchema.safeParse({ ...four, answer: 3 }).success);
});

test("script lines are hook, question, explanation, cta; voice timings ride along", () => {
  const props = quizChestSchema.parse(base);
  assert.deepEqual(quizChestScript(props), {
    lines: ["Hook?", "Question?", "Because.", "Comment your answer!"],
    timings: undefined,
  });
  const lines = quizChestScript(props).lines.map((text, i) => ({ text, start_s: i * 2, end_s: i * 2 + 1.5 }));
  assert.deepEqual(quizChestScript(quizChestSchema.parse({ ...base, voice: { lines } })).timings, lines);
});

test("the countdown and reveal are inserted after the question line", () => {
  const props = quizChestSchema.parse(base);
  const t = buildTimeline({ ...quizChestScript(props), fps: 30, hookSeconds: 1.5, outroSeconds: 0.5, loop: true });
  const { timeline, countdownStart, reveal, gap } = withCountdown(t, 5, 30);
  assert.equal(countdownStart, t.scenes[1].endFrame);
  assert.equal(reveal, countdownStart + 150);
  assert.equal(gap, 150 + REVEAL_S * 30);
  assert.deepEqual(timeline.scenes.slice(0, 1), t.scenes.slice(0, 1));
  assert.equal(timeline.scenes[1].startFrame, t.scenes[1].startFrame);
  assert.equal(timeline.scenes[1].endFrame, timeline.scenes[2].startFrame);
  for (const i of [2, 3]) assert.equal(timeline.scenes[i].startFrame, t.scenes[i].startFrame + gap);
  assert.equal(timeline.outroStart, t.outroStart + gap);
  assert.equal(timeline.totalFrames, t.totalFrames + gap);
  assert.equal(timeline.hookFrame, t.hookFrame);
});

test("countdown ticks once a second from N down to 1, then nothing", () => {
  assert.deepEqual(countdownTicks(100, 3, 30), [100, 130, 160]);
  const at = (f: number) => countdownAt(f, 100, 3, 30);
  assert.equal(at(99), undefined);
  assert.equal(at(100), 3);
  assert.equal(at(129), 3);
  assert.equal(at(130), 2);
  assert.equal(at(189), 1);
  assert.equal(at(190), undefined);
});
