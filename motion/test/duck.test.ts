// Music ducking under the voice (step 148): pure functions of src/lib/duck.ts.
import assert from "node:assert/strict";
import { test } from "node:test";
import { ATTACK_S, DUCK_DB, duckGain, GAP_DB, HOLD_S, pausedLines, RELEASE_S, speechSpans, spokenLines } from "../src/lib/duck.ts";

const dB = (g: number) => 20 * Math.log10(g);
const near = (a: number, b: number, msg?: string) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b} ${msg ?? ""}`);

test("no voice: the bed plays unchanged", () => {
  for (const t of [0, 1.5, 30]) assert.equal(duckGain(speechSpans([]), t), 1);
  assert.equal(spokenLines(undefined), undefined);
  assert.equal(spokenLines({ lines: [{ start_s: 0, end_s: 1 }] }), undefined, "timings without audio: nothing is heard");
  assert.deepEqual(spokenLines({ audioSrc: "v.wav", lines: [{ start_s: 0, end_s: 1 }] }), [{ start_s: 0, end_s: 1 }]);
});

test("ducked while a line is spoken, back up in the gap, smooth ramps", () => {
  const spans = speechSpans([
    { start_s: 1, end_s: 3 },
    { start_s: 5, end_s: 7 },
  ]);
  near(dB(duckGain(spans, 2)), DUCK_DB, "mid-line");
  near(dB(duckGain(spans, 1)), DUCK_DB, "down before the first word");
  near(dB(duckGain(spans, 1 - ATTACK_S)), GAP_DB, "ramp starts ATTACK_S before");
  near(dB(duckGain(spans, 3 + RELEASE_S)), GAP_DB, "back up RELEASE_S after");
  near(dB(duckGain(spans, 4)), GAP_DB, "a 2 s gap");
  near(dB(duckGain(spans, 0)), GAP_DB, "before the voice");
  // Ramps are 150-250 ms and monotonic, in steps no bigger than 2.5 dB per 30 fps frame.
  assert.ok(ATTACK_S >= 0.15 && ATTACK_S <= 0.25 && RELEASE_S >= 0.15 && RELEASE_S <= 0.25);
  let last = dB(duckGain(spans, 3));
  for (let f = 1; f <= 12; f++) {
    const now = dB(duckGain(spans, 3 + f / 30));
    assert.ok(now >= last && now - last <= 2.5, `frame ${f}: ${last} -> ${now}`);
    last = now;
  }
});

test("short gaps between lines stay ducked", () => {
  const spans = speechSpans([
    { start_s: 5, end_s: 7 },
    { start_s: 1, end_s: 3 },
    { start_s: 3 + HOLD_S - 0.1, end_s: 4 },
  ]);
  assert.deepEqual(spans, [
    { start_s: 1, end_s: 4 },
    { start_s: 5, end_s: 7 },
  ]);
  near(dB(duckGain(spans, 3 + HOLD_S / 2)), DUCK_DB);
});

test("paused voices move their timings with the pause", () => {
  // QuizChest: the voice holds 60 frames from frame 90 (3 s at 30 fps).
  const lines = [
    { text: "q", start_s: 1, end_s: 2.5 },
    { text: "a", start_s: 3.2, end_s: 4 },
  ];
  assert.deepEqual(pausedLines(lines, [{ at: 90, frames: 60 }], 30), [
    { text: "q", start_s: 1, end_s: 2.5 },
    { text: "a", start_s: 5.2, end_s: 6 },
  ]);
  assert.deepEqual(pausedLines(lines, [], 30), lines);
});
