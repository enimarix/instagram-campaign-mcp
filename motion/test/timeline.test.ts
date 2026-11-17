// node --test (Node strips the types); the modules under test have no runtime imports.
import assert from "node:assert/strict";
import { test } from "node:test";
import { fitTextScale } from "../src/lib/pixel.ts";
import {
  buildTimeline,
  HOOK_FRAME,
  LINE_GAP_S,
  loopFade,
  MIN_LINE_S,
  MIN_LOOP_S,
  READ_CHARS_PER_S,
  sceneAt,
} from "../src/lib/timeline.ts";
import { wrap } from "../src/lib/typewriter.ts";

const base = { fps: 30, hookSeconds: 1.5, outroSeconds: 0, loop: false };

test("estimated timings follow the text length, with minimums", () => {
  const long = "x".repeat(45); // 3 s at 15 chars/s
  const t = buildTimeline({ ...base, lines: ["hook", "short", long] });
  const frames = (s: number) => Math.round(s * 30);
  // Hook: 4 chars, but at least hookSeconds; "short": MIN_LINE_S; long: 45 / READ_CHARS_PER_S.
  const h = 1.5 + LINE_GAP_S;
  const sh = h + MIN_LINE_S + LINE_GAP_S;
  const end = sh + 45 / READ_CHARS_PER_S + LINE_GAP_S;
  assert.deepEqual(
    t.scenes.map((s) => [s.index, s.startFrame, s.endFrame]),
    [
      [0, 0, frames(h)],
      [1, frames(h), frames(sh)],
      [2, frames(sh), frames(end)],
    ],
  );
  assert.equal(t.totalFrames, frames(end));
  assert.equal(t.outroStart, t.totalFrames);
  // A long hook takes its reading time, not hookSeconds.
  assert.equal(buildTimeline({ ...base, lines: [long] }).scenes[0].endFrame, frames(3 + LINE_GAP_S));
});

test("given timings are kept; the hook starts at 0 and captions hold through pauses", () => {
  const t = buildTimeline({
    ...base,
    outroSeconds: 1,
    lines: ["a", "b", "c"],
    timings: [
      { start_s: 0.2, end_s: 1 },
      { text: "b", start_s: 1.5, end_s: 2 },
      { start_s: 2, end_s: 3.1 },
    ],
  });
  assert.deepEqual(
    t.scenes.map((s) => [s.startFrame, s.endFrame]),
    [
      [0, 45],
      [45, 60],
      [60, 93],
    ],
  );
  assert.equal(t.outroStart, 93);
  assert.equal(t.totalFrames, 123);
});

test("bad timings and empty scripts are refused", () => {
  assert.throws(() => buildTimeline({ ...base, lines: [] }), /at least one line/);
  assert.throws(() => buildTimeline({ ...base, lines: ["a", "b"], timings: [{ start_s: 0, end_s: 1 }] }), /1 timings for 2/);
  const backwards = [{ start_s: 1, end_s: 2 }, { start_s: 0.5, end_s: 3 }];
  assert.throws(() => buildTimeline({ ...base, lines: ["a", "b"], timings: backwards }), /out of order/);
  assert.throws(() => buildTimeline({ ...base, lines: ["a"], timings: [{ start_s: 2, end_s: 1 }] }), /out of order/);
});

test("the hook frame is inside the first second and the hook scene", () => {
  for (const fps of [24, 30, 60, 10]) {
    const t = buildTimeline({ ...base, fps, lines: ["hook", "next"] });
    assert.ok(t.hookFrame < fps, `fps ${fps}`);
    assert.ok(t.hookFrame < t.scenes[0].endFrame);
  }
  assert.equal(buildTimeline({ ...base, lines: ["hook"] }).hookFrame, HOOK_FRAME);
});

test("loop reserves an outro that fades back to frame 0", () => {
  const t = buildTimeline({ ...base, lines: ["hook"], loop: true }); // outroSeconds 0 → MIN_LOOP_S
  const outro = Math.round(MIN_LOOP_S * 30);
  assert.equal(t.totalFrames - t.outroStart, outro);
  assert.equal(sceneAt(t.scenes, t.outroStart), undefined); // no caption in the outro
  assert.equal(sceneAt(t.scenes, 0)?.index, 0);
  assert.equal(loopFade(t.outroStart - 1, t), 0);
  assert.ok(loopFade(t.outroStart + outro / 2, t) > 0);
  assert.equal(loopFade(t.totalFrames - 1, t), 1); // last frame = frame 0's picture
  const fades = Array.from({ length: outro }, (_, i) => loopFade(t.outroStart + i, t));
  assert.deepEqual(fades, [...fades].sort()); // never fades back out
  // Without loop: outroSeconds only, and nothing fades in.
  const plain = buildTimeline({ ...base, lines: ["hook"], outroSeconds: 1 });
  assert.equal(plain.totalFrames - plain.outroStart, 30);
  assert.equal(loopFade(plain.totalFrames - 1, plain), 0);
});

test("fitTextScale picks the largest scale that fits", () => {
  const lines = (text: string) => (cols: number) => wrap(text, cols).length;
  // 8 px font, 12 px lines per scale step. "abcd" in 64 px wide: scale 2 (4 cols of 16 px).
  assert.equal(fitTextScale(lines("abcd"), 64, 24, 8), 2);
  assert.equal(fitTextScale(lines("ab ab"), 64, 96, 8), 4); // two lines of 2 cols at 32 px
  assert.equal(fitTextScale(lines("too long for anything"), 8, 1, 8), 1); // never below 1
});
