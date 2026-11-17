// node --test (Node strips the types); the modules under test have no runtime imports.
import assert from "node:assert/strict";
import { test } from "node:test";
import { barCells, flashOpacity, padScore, progress, seeded, sheetSvg, spriteFrame, wipeSpan } from "../src/lib/game.ts";
import * as sprites from "../src/lib/sprites.ts";

test("spriteFrame loops or holds at the sheet rate", () => {
  // 4 frames at 10 frames/s in a 30 fps video: a new sheet frame every 3 video frames, from 6.
  assert.equal(spriteFrame(0, 30, 4, 10, true, 6), 0);
  assert.equal(spriteFrame(8, 30, 4, 10, true, 6), 0);
  assert.equal(spriteFrame(9, 30, 4, 10, true, 6), 1);
  assert.equal(spriteFrame(18, 30, 4, 10, true, 6), 0); // 12 frames later: wrapped
  assert.equal(spriteFrame(18, 30, 4, 10, false, 6), 3); // once: holds the last frame
  assert.equal(spriteFrame(999, 30, 4, 10, false, 6), 3);
  assert.equal(spriteFrame(50, 30, 1, 10), 0); // one frame
  assert.equal(spriteFrame(50, 30, 4, 0), 0); // rate 0 = still
  assert.equal(spriteFrame(10, 30, 4, 3), 1); // 10 * 3 / 30 = 1 despite float noise
});

test("progress and wipeSpan cover, then uncover", () => {
  assert.equal(progress(5, 10, 20), 0);
  assert.equal(progress(20, 10, 20), 0.5);
  assert.equal(progress(40, 10, 20), 1);
  assert.equal(progress(10, 10, 0), 1); // zero duration: done at start
  assert.deepEqual(wipeSpan(0), [0, 0]);
  assert.deepEqual(wipeSpan(0.25), [0, 0.5]);
  assert.deepEqual(wipeSpan(0.5), [0, 1]); // fully covered at the midpoint
  assert.deepEqual(wipeSpan(0.75), [0.5, 1]);
  assert.deepEqual(wipeSpan(1), [1, 1]);
});

test("flashOpacity fades out in hard steps", () => {
  assert.equal(flashOpacity(9, 10, 8), 0);
  assert.equal(flashOpacity(10, 10, 8), 1);
  assert.equal(flashOpacity(13, 10, 8), 0.75); // p = 3/8 -> ceil(2.5)/4
  assert.equal(flashOpacity(17, 10, 8), 0.25);
  assert.equal(flashOpacity(18, 10, 8), 0);
});

test("seeded noise is reproducible and spread over [0, 1)", () => {
  const run = (seed: number) => Array.from({ length: 1000 }, (_, f) => seeded(seed, f));
  const a = run(7);
  assert.deepEqual(run(7), a);
  assert.notDeepEqual(run(8), a);
  assert.ok(a.every((v) => v >= 0 && v < 1));
  const mean = a.reduce((s, v) => s + v, 0) / a.length;
  assert.ok(Math.abs(mean - 0.5) < 0.05, `mean ${mean}`);
  assert.equal(new Set(a).size, a.length);
});

test("padScore and barCells clamp", () => {
  assert.equal(padScore(42, 6), "000042");
  assert.equal(padScore(-5, 3), "000");
  assert.equal(padScore(12345, 3), "999");
  assert.equal(padScore(7.9, 2), "07");
  assert.equal(barCells(0.5, 12), 6);
  assert.equal(barCells(2, 12), 12);
  assert.equal(barCells(-1, 12), 0);
  assert.equal(barCells(Number.NaN, 12), 0);
});

test("code-drawn sprites are rectangular and use known colours", () => {
  for (const [name, art] of Object.entries(sprites)) {
    const h = art.frames[0].length;
    const w = art.frames[0][0].length;
    for (const rows of art.frames) {
      assert.equal(rows.length, h, name);
      for (const row of rows) {
        assert.equal(row.length, w, `${name}: ${row}`);
        for (const c of row) assert.ok(c === "." || c in art.colors, `${name}: ${c}`);
      }
    }
  }
});

test("sheetSvg lays frames side by side with one rect per run", () => {
  const svg = sheetSvg({ colors: { A: 1, B: 2 }, frames: [["AA."], [".BA"]] }, ["#000", "#111", "#222"]);
  assert.match(svg, /width="6" height="1"/);
  assert.match(svg, /<rect x="0" y="0" width="2" height="1" fill="#111"\/>/);
  assert.match(svg, /<rect x="4" y="0" width="1" height="1" fill="#222"\/>/);
  assert.match(svg, /<rect x="5" y="0" width="1" height="1" fill="#111"\/>/);
  assert.equal(svg.match(/<rect/g)?.length, 3);
});
