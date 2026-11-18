// VoxelQuest (step 130): schema, script mapping (048b voice rule), timings, end card props.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { DEFAULT_ADDRESS, END_CARD_MIN_S } from "../src/endcards/schema.ts";
import { beatOf, beatShots, before, cameraAt, countUp, flashFrame, golemPoints, LONG_BEAT_S, reached, SCALE_LIFT, SETTLE } from "../src/templates/VoxelQuest/layout.ts";
import { timelineOf, voxelQuestSchema, voxelQuestScript } from "../src/templates/VoxelQuest/schema.ts";
import { projectIso } from "../src/voxel/anim.ts";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../props/${name}.json`, import.meta.url), "utf8"));
const brandJson = JSON.parse(readFileSync(new URL("../../brand/brand.json", import.meta.url), "utf8"));
const EXAMPLES = ["voxelquest", "voxelquest-21h", "voxelquest-proteines"].map(read);
const base = {
  hook: "Hook ?",
  beats: [
    { kind: "problem", line: "Problem", foods: [{ prop: "egg", label: "90 kcal" }] },
    { kind: "app", line: "App" },
    { kind: "payoff", line: "Payoff" },
  ],
  citations: [],
};

test("the three examples parse and run 20-30 s; defaults: vous, marimba, no loop, pixelate 2", () => {
  for (const p of EXAMPLES) {
    const parsed = voxelQuestSchema.safeParse(p);
    assert.ok(parsed.success, parsed.success ? "" : parsed.error.message);
    const s = timelineOf(parsed.data, 30).timeline.totalFrames / 30;
    assert.ok(s >= 20 && s <= 30, `${p.hook}: ${s} s`);
  }
  const p = voxelQuestSchema.parse(base);
  assert.deepEqual([p.address, p.music, p.loop, p.pixelate, p.fromForm, p.toForm, p.accent], ["vous", "music-marimba", false, 2, "etincelle", "recrue", "brand"]);
  assert.equal(p.beats[0].foods?.[0].macro, "kcal");
  assert.equal(DEFAULT_ADDRESS, brandJson.address.default);
});

test("bad props fail with clear messages", () => {
  const message = (p: object) => {
    const r = voxelQuestSchema.safeParse(p);
    assert.equal(r.success, false, JSON.stringify(p));
    return r.success ? "" : r.error.issues.map((i) => i.message).join("; ");
  };
  assert.match(message({ ...base, beats: [base.beats[1], base.beats[0], base.beats[2]] }), /1-2 problem, then 1-2 app, then one payoff/);
  assert.match(message({ ...base, beats: [...base.beats, { kind: "payoff", line: "Again" }] }), /then one payoff/);
  assert.match(message({ ...base, beats: [base.beats[0], { kind: "app", line: "App", foods: [{ prop: "egg", label: "1" }] }, base.beats[2]] }), /only problem beats show foods/);
  assert.match(message({ ...base, fromForm: "titan", toForm: "recrue" }), /higher form/);
  assert.match(message({ ...base, outro: "Seulement 9,99 € par mois" }), /no price on screen/);
  assert.match(message({ ...base, hook: "Dès 5 euros" }), /no price on screen/);
  assert.match(message({ ...base, beats: [{ ...base.beats[0], foods: [{ prop: "cake", label: "1" }] }, base.beats[1], base.beats[2]] }), /Invalid option|expected one of/);
  assert.match(message({ ...base, voice: { lines: [{ text: "Hook ?", start_s: 0, end_s: 1 }] } }), /one timing per script line/);
  assert.match(message({ ...base, beats: [{ ...base.beats[0], value: "12" }, base.beats[1], base.beats[2]] }), /only app beats show a value/);
  message({ ...base, extra: 1 });
});

test("script lines: hook, each beat, then the outro when there is one (048b)", () => {
  assert.deepEqual(voxelQuestScript(voxelQuestSchema.parse(base)).lines, ["Hook ?", "Problem", "App", "Payoff"]);
  const withOutro = voxelQuestSchema.parse({ ...base, outro: "Tagline" });
  const lines = voxelQuestScript(withOutro).lines;
  assert.deepEqual(lines, ["Hook ?", "Problem", "App", "Payoff", "Tagline"]);
  const timings = lines.map((text, i) => ({ text, start_s: i * 2, end_s: i * 2 + 1.5 }));
  const voiced = voxelQuestSchema.parse({ ...base, outro: "Tagline", voice: { lines: timings } });
  const { timeline, endStart } = timelineOf(voiced, 30);
  // The voice sets the pace; the end card starts on the outro line and lasts at least END_CARD_MIN_S.
  assert.equal(timeline.scenes[4].startFrame, 240);
  assert.equal(endStart, 240);
  assert.ok(timeline.totalFrames - endStart >= END_CARD_MIN_S * 30);
});

test("without an outro the end card follows the last beat; beats get room to animate", () => {
  const { timeline, endStart } = timelineOf(voxelQuestSchema.parse(base), 30);
  assert.equal(endStart, timeline.outroStart);
  assert.ok(timeline.totalFrames - endStart >= END_CARD_MIN_S * 30);
  const [hook, problem, app, payoff] = timeline.scenes.map((s) => (s.endFrame - s.startFrame) / 30);
  assert.ok(hook >= 2.5 && problem >= 3.6 && app >= 4.4 && payoff >= 3.8);
});

test("framing: the golem is whole in the picture every frame, and inside the safe area in every held shot", () => {
  for (const raw of EXAMPLES) {
    const p = voxelQuestSchema.parse(raw);
    const { timeline, endStart } = timelineOf(p, 30);
    const scenes = timeline.scenes;
    const flash = flashFrame(scenes[p.beats.length], 30);
    const held = new Set(scenes.slice(1, p.beats.length + 1).flatMap((s) => beatShots(p, s, 30).map((shot) => Math.min(shot.end, endStart - SETTLE) - 1)));
    for (let f = 0; f < endStart; f++) {
      const pose = cameraAt(f, p, scenes, endStart, 30);
      const scene = scenes.find((s) => f >= s.startFrame && f < s.endFrame)!;
      const beat = beatOf(p, scene);
      const onScale = p.hookProp === "scale" && (!beat || (beat.kind === "problem" && !beat.foods));
      const form = f >= flash ? reached(p) : before(p, beat);
      for (const point of golemPoints(form, onScale ? SCALE_LIFT : 0, 0)) {
        const [x, y] = projectIso(pose, point);
        assert.ok(x >= 0 && x <= 1080 && y >= 0 && y <= 1920, `${p.hook} frame ${f}: golem at ${x.toFixed(0)},${y.toFixed(0)}`);
        // Held shots: left of the Reels button rail, above the bottom UI (beats, not the hook's wide shot).
        if (held.has(f) && beat) assert.ok(x >= 65 && x <= 895 && y >= 640 && y <= 1248, `${p.hook} frame ${f}: golem at ${x.toFixed(0)},${y.toFixed(0)}`);
      }
    }
  }
});

test("pacing: a beat longer than LONG_BEAT_S changes shot halfway; no shot holds longer", () => {
  for (const raw of EXAMPLES) {
    const p = voxelQuestSchema.parse(raw);
    const { timeline } = timelineOf(p, 30);
    for (const scene of timeline.scenes.slice(1, p.beats.length + 1)) {
      const shots = beatShots(p, scene, 30);
      for (const shot of shots) assert.ok(shot.end - shot.start <= LONG_BEAT_S * 30, `${p.hook}: a ${(shot.end - shot.start) / 30} s shot`);
      if (shots.length === 2) assert.ok(Math.abs(shots[0].pose.azimuth - shots[1].pose.azimuth) >= 10);
    }
  }
});

test("countUp: the first number counts up with its own decimals and grouping", () => {
  assert.equal(countUp("1,6 g par kg", 0.5), "0,8 g par kg");
  assert.equal(countUp("308 kcal", 0), "0 kcal");
  assert.equal(countUp("2 236 kcal", 1), "2 236 kcal");
  assert.equal(countUp("2 236 kcal", 0.5), "1 118 kcal");
  assert.equal(countUp("21 h. Il reste 308 kcal", 1), "21 h. Il reste 308 kcal");
  assert.equal(countUp("Sans chiffre", 0.3), "Sans chiffre");
});
