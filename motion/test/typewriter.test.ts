// node --test (Node strips the types); the module under test has no imports.
import assert from "node:assert/strict";
import { test } from "node:test";
import { visibleChars, wrap } from "../src/lib/typewriter.ts";

test("visibleChars counts whole characters per frame", () => {
  // 10 chars/s at 30 fps = one character every 3 frames, from frame 6.
  assert.equal(visibleChars(0, 20, 30, 10, 6), 0);
  assert.equal(visibleChars(6, 20, 30, 10, 6), 0);
  assert.equal(visibleChars(8, 20, 30, 10, 6), 0);
  assert.equal(visibleChars(9, 20, 30, 10, 6), 1);
  assert.equal(visibleChars(36, 20, 30, 10, 6), 10);
  assert.equal(visibleChars(999, 20, 30, 10, 6), 20); // clamped
  assert.equal(visibleChars(30, 30, 30, 0.7), 0); // 0.7 chars/s: none in the first second
  assert.equal(visibleChars(43, 30, 30, 0.7), 1); // 43 * 0.7 / 30 = 1.003
  assert.equal(visibleChars(200, 30, 30, 2.55), 17); // 200 * 2.55 / 30 = 16.999… in floats
});

test("visibleChars without speed shows all from the start frame", () => {
  assert.equal(visibleChars(4, 12, 30, undefined, 5), 0);
  assert.equal(visibleChars(5, 12, 30, undefined, 5), 12);
  assert.equal(visibleChars(5, 12, 30, 0, 5), 12);
});

test("wrap breaks at spaces inside the column limit", () => {
  assert.deepEqual(wrap("Café, crème brûlée, ñandú, Straße", 12), ["Café, crème", "brûlée,", "ñandú,", "Straße"]);
  assert.deepEqual(wrap("one two", Infinity), ["one two"]);
  assert.deepEqual(wrap("a  b", 10), ["a b"]);
});

test("wrap keeps forced breaks and cuts long words", () => {
  assert.deepEqual(wrap("hi\n\nyo", 10), ["hi", "", "yo"]);
  assert.deepEqual(wrap("ab abcdefgh", 3), ["ab", "abc", "def", "gh"]);
  assert.deepEqual(wrap("Straße", 3), ["Str", "aße"]); // counts code points, not UTF-16 units
});
