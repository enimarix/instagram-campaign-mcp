// End cards (steps 130, 137): one per style, the shared props contract, never a price.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { CAMEOS, CARD_S, cardFrames, END_CARD_MIN_S, END_CARD_STYLES, endCardSchema, FOOD_IDS, SETTLE_S } from "../src/endcards/schema.ts";
import { bossBattleSchema } from "../src/templates/BossBattle/schema.ts";
import { dialogStorySchema } from "../src/templates/DialogStory/schema.ts";
import { factQuestSchema } from "../src/templates/FactQuest/schema.ts";
import { pixelSkitSchema } from "../src/templates/PixelSkit/schema.ts";
import { quizChestSchema } from "../src/templates/QuizChest/schema.ts";
import { buildTimeline, fitEndCard, loopFade } from "../src/lib/timeline.ts";
import { PROPS } from "../src/voxel/models.ts";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../props/${name}.json`, import.meta.url), "utf8"));
const ok = (props: object) => endCardSchema.safeParse(props).success;
/** Minimal valid props per style. */
const BASE = { voxel: {}, paper: {}, clean: {}, pixel: {}, live: { backdrop: "public/last-frame.jpg" }, cutaway: {}, editorial: {}, cinema: {} } as const;
const PRICES = ["9,99 €", "29 $ / an", "5 euros par mois", "4.99"];

test("every style parses with its example props and has a card of at least 2.5 s that holds 1 s", () => {
  for (const style of END_CARD_STYLES) {
    assert.ok(ok({ style, ...BASE[style] }), style);
    assert.ok(CARD_S[style] >= END_CARD_MIN_S, style);
    assert.ok(CARD_S[style] - SETTLE_S[style] >= 1, `${style} holds the finished card ≥ 1 s`);
    assert.equal(cardFrames({ style }, 30), Math.round(CARD_S[style] * 30));
  }
  for (const style of ["voxel", "paper", "clean", "pixel", "editorial"]) assert.ok(ok(read(`${style}-endcard`)), style);
  assert.equal(cardFrames({ style: "clean", seconds: 5 }, 30), 150);
  assert.equal(ok({ style: "clean", seconds: 2 }), false); // shorter than END_CARD_MIN_S
});

test("each style's schema refuses a price in any text", () => {
  for (const style of END_CARD_STYLES) {
    for (const price of PRICES) {
      assert.equal(ok({ style, ...BASE[style], tagline: `Dès ${price}` }), false, `${style}: ${price}`);
    }
  }
  assert.equal(ok({ style: "pixel", note: "Dès 9,99 €" }), false);
  assert.ok(ok({ style: "pixel", tagline: "308 kcal de moins à 21 h.", note: "Sources en légende" }));
});

test("cameos, backdrop, font and note belong to their style", () => {
  for (const style of END_CARD_STYLES) {
    for (const cameo of [...CAMEOS[style], "none"]) assert.ok(ok({ style, ...BASE[style], cameo }), `${style} ${cameo}`);
    assert.equal(ok({ style, ...BASE[style], cameo: "dragon" }), false, style);
  }
  assert.equal(ok({ style: "live" }), false); // live needs the last frame
  assert.equal(ok({ style: "clean", backdrop: "x.jpg" }), false);
  assert.ok(ok({ style: "paper", font: "Fredoka" }));
  assert.equal(ok({ style: "paper", font: 'Fredoka"; color: red' }), false); // a CSS family name only
  assert.equal(ok({ style: "clean", font: "Fredoka" }), false);
  assert.equal(ok({ style: "clean", note: "Sources" }), false);
  assert.deepEqual(endCardSchema.parse({}), { style: "voxel", accent: "brand", address: "vous", pixelate: 2 });
  for (const id of FOOD_IDS) assert.ok(id in PROPS, id);
});

test("the 8-bit templates refuse a price in their end card's texts", () => {
  const cases: [typeof factQuestSchema | typeof quizChestSchema | typeof bossBattleSchema | typeof dialogStorySchema | typeof pixelSkitSchema, string, string][] = [
    [factQuestSchema, "factquest", "outro"],
    [factQuestSchema, "factquest", "sourcesNote"],
    [quizChestSchema, "quizchest", "cta"],
    [bossBattleSchema, "bossbattle", "tagline"],
    [dialogStorySchema, "dialogstory", "tagline"],
    [pixelSkitSchema, "pixelskit", "tagline"],
  ];
  for (const [schema, name, key] of cases) {
    const props = read(name);
    assert.ok(schema.safeParse({ ...props, [key]: "Sans engagement" }).success, `${name}.${key}`);
    assert.equal(schema.safeParse({ ...props, [key]: "Dès 4,99 €" }).success, false, `${name}.${key}`);
  }
});

test("fitEndCard lengthens the outro so the card lasts its length, plus the loop fade at the very end", () => {
  const base = { lines: ["Hook", "A line", "Outro"], fps: 30, hookSeconds: 1.5 };
  for (const loop of [false, true]) {
    const build = (outroSeconds: number) => buildTimeline({ ...base, outroSeconds, loop });
    const fromLast = fitEndCard(build, 0.5, (t) => t.scenes[2].startFrame, CARD_S.pixel, 30);
    assert.equal(fromLast.totalFrames - fromLast.scenes[2].startFrame, 120 + (loop ? 15 : 0));
    const after = fitEndCard(build, 0.5, (t) => t.outroStart, CARD_S.pixel, 30);
    assert.equal(after.totalFrames - after.outroStart, 120 + (loop ? 15 : 0));
    // The card holds untouched; only the last loopFrames fade back to the hook.
    assert.equal(loopFade(after.totalFrames - 16, after), 0);
    assert.equal(loopFade(after.totalFrames - 1, after), loop ? 1 : 0);
  }
  // A card that is already long enough is left alone.
  const long = (o: number) => buildTimeline({ ...base, outroSeconds: o, loop: false });
  assert.equal(fitEndCard(long, 6, (t) => t.outroStart, CARD_S.pixel, 30).totalFrames, long(6).totalFrames);
});
