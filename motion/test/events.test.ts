import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { scriptEvents } from "../src/lib/events.ts";
import { buildTimeline } from "../src/lib/timeline.ts";

const motion = fileURLToPath(new URL("..", import.meta.url));

test("scriptEvents: one event per scene, music bed, voice-over, loop fade", () => {
  const t = buildTimeline({ lines: ["Hook?", "One.", "Two."], fps: 30, hookSeconds: 1.5, outroSeconds: 0.5, loop: true });
  const events = scriptEvents(t, 30, ["hook card", "fact 1"], { music: "music-cave", voice: { audioSrc: "voice/a.mp3" } });
  assert.deepEqual(
    events.slice(0, 3).map((e) => [e.e, e.text]),
    [
      ["hook card", "Hook?"],
      ["fact 1", "One."],
      ["line 2", "Two."],
    ],
  );
  assert.equal(events[0].t, 0);
  assert.equal(events[1].t, t.scenes[1].startFrame / 30);
  assert.deepEqual(events[3], { t: 0, d: t.totalFrames / 30, e: "music bed (music-cave)" });
  assert.equal(events[4].e, "voice-over reads the lines");
  assert.deepEqual(events[5], { t: t.outroStart / 30, d: (t.totalFrames - t.outroStart) / 30, e: "loop fade back to the hook" });
  const quiet = scriptEvents({ ...t, loop: false }, 30, [], { music: "none" });
  assert.deepEqual(quiet.map((e) => e.e), ["line 0", "line 1", "line 2", "end hold"]);
});

// Every script template's own events, through the same door Python uses (schemas.mjs --validate).
const templates = { FactQuest: "factquest", BossBattle: "bossbattle", QuizChest: "quizchest", DialogStory: "dialogstory", PixelSkit: "pixelskit" };
for (const [id, file] of Object.entries(templates)) {
  test(`${id} emits its timeline`, () => {
    const props = readFileSync(new URL(`../props/${file}.json`, import.meta.url), "utf8");
    const out = JSON.parse(execFileSync(process.execPath, ["schemas.mjs", "--validate", id], { cwd: motion, input: props, encoding: "utf8" }));
    assert.equal(out.ok, true, out.error);
    const total = out.durationInFrames / out.fps;
    assert.equal(out.events[0].e, "hook card");
    assert.equal(out.events[0].t, 0);
    assert.ok(out.events.length >= 4);
    for (const e of out.events) assert.ok(e.t >= 0 && e.d >= 0 && e.t + e.d <= total + 1e-9 && e.e, JSON.stringify(e));
    assert.ok(out.events.some((e: { e: string }) => e.e.startsWith("music bed")));
  });
}
