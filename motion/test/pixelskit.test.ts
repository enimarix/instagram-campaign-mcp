import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { ASSETS } from "../src/assets.ts";
import { buildTimeline } from "../src/lib/timeline.ts";
import {
  ACTION_FRAMES,
  ACTOR_SPRITES,
  actionPose,
  BEAT,
  comicTiming,
  FREEZE_S,
  MUSIC,
  pixelSkitSchema,
  pixelSkitScript,
  punchlineScene,
  SFX,
  voiceParts,
  withPauses,
} from "../src/templates/PixelSkit/schema.ts";

const example = JSON.parse(readFileSync(new URL("../props/pixelskit.json", import.meta.url), "utf8"));
const base = {
  hook: "POV: hook",
  cast: [{ name: "YOU" }, { name: "CAT", sprite: "slime" }],
  beats: [
    { speaker: 0, line: "Setup." },
    { line: "Escalation." },
    { speaker: 1, line: "Punchline!" },
  ],
  citations: [],
};
const timings = (n: number) => Array.from({ length: n }, (_, i) => ({ text: `${i}`, start_s: i * 2, end_s: i * 2 + 1.5 }));
// Same constants as PixelSkit.tsx.
const FPS = 30;
const CPS = 30;
const plain = (p: Parameters<typeof pixelSkitScript>[0] & { loop: boolean }) =>
  buildTimeline({ ...pixelSkitScript(p), fps: FPS, hookSeconds: 1.5, outroSeconds: 0.5, loop: p.loop });
const timing = (p: object) => {
  const props = pixelSkitSchema.parse({ ...base, ...p });
  const t = plain(props);
  return { props, t, ...comicTiming(t, props, CPS, FPS) };
};

test("the example parses and lasts 10–20 s; defaults: loop, music, timing, sting, idle", () => {
  const p = pixelSkitSchema.parse(example);
  const total = comicTiming(plain(p), p, CPS, FPS).timeline.totalFrames / FPS;
  assert.ok(total >= 10 && total <= 20, `${total} s`);
  const d = pixelSkitSchema.parse(base);
  assert.equal(d.loop, true);
  assert.equal(d.music, "music-overworld");
  assert.equal(d.tag, false);
  assert.equal(d.holdBeforePunchline_s, 0.6);
  assert.equal(d.freezeOnPunchline, true);
  assert.equal(d.sting, "hit");
  assert.equal(d.beats[0].action, "idle");
});

test("actor sprites, music and sfx are the right kinds in the asset registry", () => {
  for (const id of ACTOR_SPRITES) assert.ok("frameWidth" in ASSETS[id], id);
  for (const id of MUSIC) if (id !== "none") assert.equal(ASSETS[id].kind, "music", id);
  for (const id of SFX) assert.equal(ASSETS[`sfx-${id}`].kind, "sfx", id);
});

test("schema rejects bad cast, beat counts, speakers, actions, sfx, a short tag, missing citations", () => {
  const bad = (p: object) => assert.equal(pixelSkitSchema.safeParse({ ...base, ...p }).success, false, JSON.stringify(p));
  bad({ extra: 1 });
  bad({ cast: [] });
  bad({ cast: [...base.cast, { name: "THIRD" }] });
  bad({ cast: [{ name: "YOU", sprite: "tiles" }] });
  bad({ beats: base.beats.slice(0, 1) });
  bad({ beats: [...base.beats, ...base.beats.slice(0, 2)] });
  bad({ cast: base.cast.slice(0, 1) }); // beat 3's speaker 1 is not in the cast
  bad({ beats: [...base.beats.slice(0, 2), { speaker: 2, line: "x" }] });
  bad({ beats: [...base.beats.slice(0, 2), { line: "x", action: "moonwalk" }] });
  bad({ beats: [...base.beats.slice(0, 2), { line: "x", sfx: "music-cave" }] });
  bad({ beats: [...base.beats.slice(0, 2), { line: "x".repeat(81) }] });
  bad({ beats: base.beats.slice(0, 2), tag: true });
  bad({ holdBeforePunchline_s: 3 });
  bad({ sting: "boom" });
  bad({ citations: undefined });
  bad({ voice: { lines: timings(3) } });
  // A failed length check does not crash the refines (zod 4 runs them anyway).
  assert.equal(pixelSkitSchema.safeParse({ ...base, beats: undefined, cast: undefined }).success, false);
  assert.ok(pixelSkitSchema.safeParse({ ...base, voice: { lines: timings(4) } }).success);
});

test("beats map to script lines; the punchline is the last beat, or the one before the tag", () => {
  const p = pixelSkitSchema.parse(base);
  assert.deepEqual(pixelSkitScript(p), { lines: ["POV: hook", "Setup.", "Escalation.", "Punchline!"], timings: undefined });
  assert.equal(punchlineScene(p), 3);
  assert.equal(punchlineScene(pixelSkitSchema.parse({ ...base, tag: true })), 2);
});

test("withPauses: the scene ending at a pause grows, later frames move back", () => {
  const t = plain({ ...pixelSkitSchema.parse(base), loop: true });
  const [s0, s1, s2, s3] = t.scenes;
  const inner = s3.startFrame + 10;
  const w = withPauses(t, [
    { at: s3.startFrame, frames: 18 },
    { at: inner, frames: 30 },
  ]);
  assert.deepEqual(w.scenes[0], s0);
  assert.deepEqual(w.scenes[1], s1);
  assert.deepEqual(w.scenes[2], { ...s2, endFrame: s2.endFrame + 18 });
  assert.deepEqual(w.scenes[3], { ...s3, startFrame: s3.startFrame + 18, endFrame: s3.endFrame + 48 });
  assert.equal(w.outroStart, t.outroStart + 48);
  assert.equal(w.totalFrames, t.totalFrames + 48);
});

test("comic timing: hold before the punchline, sting when it is typed, freeze after it", () => {
  const { t, timeline, punch, land, freezeStart, freezeEnd, pauses } = timing({});
  const hold = Math.round(0.6 * FPS);
  const freeze = FREEZE_S * FPS;
  const s = t.scenes[punch];
  const typed = s.startFrame + BEAT + Math.ceil(("Punchline!".length * FPS) / CPS);
  assert.deepEqual(pauses, [
    { at: s.startFrame, frames: hold },
    { at: typed, frames: freeze },
  ]);
  assert.equal(timeline.scenes[punch].startFrame, s.startFrame + hold);
  assert.equal(land, typed + hold);
  assert.deepEqual([freezeStart, freezeEnd], [land, land + freeze]);
  assert.equal(timeline.totalFrames, t.totalFrames + hold + freeze);
  // The punchline's scene still holds the freeze and the rest of its reading time.
  assert.equal(timeline.scenes[punch].endFrame, s.endFrame + hold + freeze);
});

test("comic timing: a longer voice lands later; no hold, no freeze, a tag after the punchline", () => {
  const voiced = timing({ voice: { lines: timings(4) } });
  // Punchline voice line ends at 7.5 s, inside its scene (6 s → end).
  assert.equal(voiced.land, Math.round(7.5 * FPS) + Math.round(0.6 * FPS));
  const flat = timing({ holdBeforePunchline_s: 0, freezeOnPunchline: false });
  assert.deepEqual(flat.pauses, []);
  assert.equal(flat.freezeStart, flat.freezeEnd);
  assert.equal(flat.timeline.totalFrames, flat.t.totalFrames);
  const tagged = timing({ tag: true });
  assert.equal(tagged.punch, 2);
  // The tag scene comes after the freeze.
  assert.ok(tagged.timeline.scenes[3].startFrame >= tagged.freezeEnd);
});

test("the voice plays in parts around the pauses, picking up where it stopped", () => {
  assert.deepEqual(voiceParts([]), [{ from: 0, trimBefore: 0, frames: undefined }]);
  assert.deepEqual(
    voiceParts([
      { at: 100, frames: 18 },
      { at: 150, frames: 30 },
    ]),
    [
      { from: 0, trimBefore: 0, frames: 100 },
      { from: 118, trimBefore: 100, frames: 50 },
      { from: 198, trimBefore: 150, frames: undefined },
    ],
  );
});

test("action poses: walk in from the side, hop, fall outward, stare dots, facepalm hand", () => {
  assert.equal(actionPose("walk_in", 0, "left").dx < 0, true);
  assert.equal(actionPose("walk_in", 0, "right").dx > 0, true);
  // Offsets may be -0: same picture.
  const zero = (x: number) => assert.ok(x === 0, `${x}`);
  zero(actionPose("walk_in", ACTION_FRAMES, "left").dx);
  assert.ok(actionPose("jump", ACTION_FRAMES / 2, "left").dy < 0);
  zero(actionPose("jump", ACTION_FRAMES, "left").dy);
  zero(actionPose("shake", ACTION_FRAMES, "left").dx);
  assert.equal(actionPose("fall", -5, "right").tilt, 0);
  assert.equal(actionPose("fall", ACTION_FRAMES * 3, "right").tilt, 90);
  assert.equal(actionPose("fall", ACTION_FRAMES, "left").tilt, -90);
  assert.equal(actionPose("stare", -1, "left").dots, 0);
  assert.equal(actionPose("stare", 100, "left").dots, 3);
  assert.equal(actionPose("facepalm", 0, "left").hand, false);
  assert.equal(actionPose("facepalm", ACTION_FRAMES, "left").hand, true);
  assert.deepEqual(actionPose("idle", 5, "left"), { dx: 0, dy: 0, tilt: 0, animate: true, dots: 0, hand: false });
});
