import assert from "node:assert/strict";
import { test } from "node:test";
import { frenchSpaces } from "../src/lib/french.ts";
import { wrap } from "../src/lib/typewriter.ts";

const NBSP = "\u00a0";

test("frenchSpaces binds ? ! : ; » to the word before and « to the word after", () => {
  assert.equal(frenchSpaces("Vrai ? Faux ! Note : oui ; « non »"), `Vrai${NBSP}? Faux${NBSP}! Note${NBSP}: oui${NBSP}; «${NBSP}non${NBSP}»`);
  assert.equal(frenchSpaces("«oui»"), `«${NBSP}oui${NBSP}»`);
  assert.equal(frenchSpaces("Why? 12:30 https://x.fr"), "Why? 12:30 https://x.fr");
});

test("wrapped French text never starts a line with ? ! : ; or »", () => {
  const text = frenchSpaces("Pourquoi tu stagnes en sèche ? La réponse est simple : tu manges moins !");
  // From the longest bound word up: a word wider than the line is cut anywhere.
  for (let cols = 9; cols <= 40; cols++) {
    for (const line of wrap(text, cols)) assert.doesNotMatch(line, /^[?!:;»]/, `cols ${cols}: ${line}`);
  }
});
