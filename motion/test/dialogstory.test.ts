import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { ASSETS } from "../src/assets.ts";
import { buildTimeline } from "../src/lib/timeline.ts";
import {
  BEAT,
  CHARACTER_SPRITES,
  dialogStorySchema,
  dialogStoryScript,
  MUSIC,
  sceneRoles,
  talkSpan,
} from "../src/templates/DialogStory/schema.ts";

const example = JSON.parse(readFileSync(new URL("../props/dialogstory.json", import.meta.url), "utf8"));
const line = (speaker: 0 | 1, i: number) => ({ speaker, text: `Line ${i}` });
const base = {
  hook: "Hook?",
  characters: [
    { name: "PIXEL", side: "left" },
    { name: "SLIMY", side: "right" },
  ],
  lines: [line(1, 1), line(0, 2), line(1, 3)],
  citations: [],
};
const timings = (n: number) => Array.from({ length: n }, (_, i) => ({ text: `${i}`, start_s: i * 2, end_s: i * 2 + 1.5 }));

test("the example props parse; defaults: loop, overworld music", () => {
  assert.ok(dialogStorySchema.safeParse(example).success);
  const p = dialogStorySchema.parse(base);
  assert.equal(p.loop, true);
  assert.equal(p.music, "music-overworld");
  assert.equal(dialogStorySchema.parse({ ...base, music: "none" }).music, "none");
});

test("portrait sprites and music are the right kinds in the asset registry", () => {
  for (const id of CHARACTER_SPRITES) assert.ok("frameWidth" in ASSETS[id], id);
  for (const id of MUSIC) if (id !== "none") assert.equal(ASSETS[id].kind, "music", id);
});

test("schema rejects unknown keys, bad characters, 2 or 9 lines, bad speakers, missing citations", () => {
  const bad = (p: object) => assert.equal(dialogStorySchema.safeParse(p).success, false, JSON.stringify(p));
  bad({ ...base, extra: 1 });
  bad({ ...base, characters: [base.characters[0]] });
  bad({ ...base, characters: [...base.characters, { name: "THIRD", side: "left" }] });
  bad({ ...base, characters: [{ ...base.characters[0], sprite: "tiles" }, base.characters[1]] });
  bad({ ...base, characters: [{ name: "PIXEL" }, base.characters[1]] });
  bad({ ...base, lines: base.lines.slice(0, 2) });
  bad({ ...base, lines: [1, 2, 3, 4, 5, 6, 7, 8, 9].map((i) => line(i % 2 ? 1 : 0, i)) });
  for (const speaker of [2, -1, 0.5, "0"]) bad({ ...base, lines: [...base.lines, { speaker, text: "x" }] });
  bad({ ...base, lines: [...base.lines, { speaker: 0, text: "x".repeat(101) }] });
  const { citations: _, ...uncited } = base;
  bad(uncited);
  bad({ ...base, citations: [{ url: "javascript:alert(1)" }] });
  bad({ ...base, music: "sfx-coin" });
});

test("speaker validation: one character per side, both characters speak", () => {
  const ok = (p: object) => dialogStorySchema.safeParse({ ...base, ...p }).success;
  assert.ok(ok({ characters: [{ name: "A", side: "right" }, { name: "B", side: "left" }] }));
  assert.equal(ok({ characters: [{ name: "A", side: "left" }, { name: "B", side: "left" }] }), false);
  assert.equal(ok({ lines: [line(0, 1), line(0, 2), line(0, 3)] }), false);
  assert.equal(ok({ lines: [line(1, 1), line(1, 2), line(1, 3)] }), false);
});

test("voice.lines needs one timing per script line: hook, each line, moral when given", () => {
  const ok = (p: object) => dialogStorySchema.safeParse({ ...base, ...p }).success;
  assert.ok(ok({ voice: { lines: timings(4) } }));
  assert.equal(ok({ voice: { lines: timings(5) } }), false);
  assert.ok(ok({ moral: "Moral.", voice: { lines: timings(5) } }));
  assert.equal(ok({ moral: "Moral.", voice: { lines: timings(4) } }), false);
});

test("lines map to script lines and scene roles: hook, each speaker's line, moral", () => {
  const p = dialogStorySchema.parse(base);
  assert.deepEqual(dialogStoryScript(p), { lines: ["Hook?", "Line 1", "Line 2", "Line 3"], timings: undefined });
  assert.deepEqual(sceneRoles(p), [{ kind: "hook" }, { kind: "line", speaker: 1 }, { kind: "line", speaker: 0 }, { kind: "line", speaker: 1 }]);
  const m = dialogStorySchema.parse({ ...base, moral: "Moral.", voice: { lines: timings(5) } });
  assert.deepEqual(dialogStoryScript(m).lines.at(-1), "Moral.");
  assert.deepEqual(dialogStoryScript(m).timings, timings(5));
  assert.deepEqual(sceneRoles(m).at(-1), { kind: "moral" });
  // One scene per role, in order.
  const t = buildTimeline({ ...dialogStoryScript(m), fps: 30, hookSeconds: 1.5, outroSeconds: 0.5, loop: true });
  assert.equal(t.scenes.length, sceneRoles(m).length);
});

test("the speaker talks from the beat until typed or voiced, never past its scene", () => {
  const p = dialogStorySchema.parse({ ...base, lines: [line(1, 1), { speaker: 0, text: "x".repeat(60) }, line(1, 3)] });
  const t = buildTimeline({ ...dialogStoryScript(p), fps: 30, hookSeconds: 1.5, outroSeconds: 0.5, loop: true });
  const s = t.scenes[2];
  // 60 chars at 30 chars/s = 60 frames after the beat.
  assert.deepEqual(talkSpan(t, 2, 30, 30), [s.startFrame + BEAT, s.startFrame + BEAT + 60]);
  // A voice that reads longer keeps it talking, up to the end of the scene.
  const voiceEnd = (s.startFrame + BEAT + 90) / 30;
  assert.deepEqual(talkSpan(t, 2, 30, 30, voiceEnd), [s.startFrame + BEAT, s.startFrame + BEAT + 90]);
  assert.deepEqual(talkSpan(t, 2, 30, 30, 999), [s.startFrame + BEAT, s.endFrame]);
  // A tiny scene never yields a negative span.
  const [a, b] = talkSpan({ ...t, scenes: [{ ...s, endFrame: s.startFrame + 2 }] }, 0, 30, 30);
  assert.equal(a, b);
});
