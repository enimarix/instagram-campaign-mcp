// PixelCinema (step 143): schema, script mapping (048b voice rule), timings, direction, and the
// pixel painter (deterministic, the lightning frame's silhouette).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { bayer, dither, GH, GW, hash, ramp, toScreen, toWorld } from "../src/cinema/pixel.ts";
import { ANCHORS, paint, SCENE_IDS, SETS, solidAt } from "../src/cinema/scenes.ts";
import { CAMEOS, CARD_S } from "../src/endcards/schema.ts";
import { speechSpans } from "../src/lib/duck.ts";
import { beamOf, cameraAt, coverOf, hookTimes, openOf, segmentsOf, sfxGain, SPLIT_S, thunderAt } from "../src/templates/PixelCinema/layout.ts";
import { beatLine, joinParts, pixelCinemaSchema, pixelCinemaScript, splitHighlight, timelineOf, titleOf } from "../src/templates/PixelCinema/schema.ts";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../props/${name}.json`, import.meta.url), "utf8"));
const NAMES = ["pixelcinema", "pixelcinema-aube", "pixelcinema-frigo"];
const EXAMPLES = NAMES.map((n) => pixelCinemaSchema.parse(read(n)));
const base = {
  hook: { line: "C'est la *méthode*." },
  beats: [
    { kind: "chip", title: "Tout se joue *ici* :", text: "un" },
    { kind: "chip", text: "deux" },
    { kind: "stat", title: "Il vous reste", value: "308", unit: "kcal" },
  ],
  citations: [],
};
const ok = (p: object) => pixelCinemaSchema.safeParse(p).success;

test("the three examples parse, use the three sets and run 20-30 s with the hook landed by the cover", () => {
  assert.deepEqual(EXAMPLES.map((p) => p.scene).sort(), [...SCENE_IDS].sort());
  for (const [i, p] of EXAMPLES.entries()) {
    const { timeline, endStart } = timelineOf(p, 30);
    const s = timeline.totalFrames / 30;
    assert.ok(s >= 20 && s <= 30, `${NAMES[i]}: ${s} s`);
    assert.ok(coverOf(p, timeline, 30) <= 2.5 * 30, NAMES[i]);
    assert.ok(timeline.totalFrames - endStart >= CARD_S.cinema * 30, `${NAMES[i]}: the card plays in full`);
    assert.ok(p.citations.length >= 1, `${NAMES[i]}: numbers need a source`);
  }
  const p = pixelCinemaSchema.parse(base);
  assert.deepEqual([p.scene, p.address, p.music, p.loop, p.accent], ["window", "vous", "music-nocturne", false, "kcal"]);
});

test("bad props fail: beat order, one lightning, the first chip's heading, highlights, prices", () => {
  const chip = { kind: "chip", text: "x" };
  assert.equal(ok({ ...base, beats: [base.beats[0], base.beats[2]] }), false); // one chip
  assert.equal(ok({ ...base, beats: [base.beats[2], ...base.beats.slice(0, 2)] }), false); // stat first
  assert.equal(ok({ ...base, beats: [...base.beats, chip] }), false); // chip after the payoff
  assert.equal(ok({ ...base, beats: [{ ...base.beats[0], flash: true }, { ...chip, flash: true }, base.beats[2]] }), false);
  assert.equal(ok({ ...base, beats: [chip, ...base.beats.slice(1)] }), false); // no heading
  assert.equal(ok({ ...base, hook: { line: "Deux *mots* *clés*" } }), false);
  assert.equal(ok({ ...base, hook: { line: "Une *étoile seule" } }), false);
  assert.equal(ok({ ...base, outro: "Seulement 4,99 € par mois" }), false);
  assert.equal(ok({ ...base, beats: [...base.beats.slice(0, 2), { kind: "app", title: "App", value: "9,99 €" }] }), false);
  assert.equal(ok({ ...base, scene: "moon" }), false);
  assert.ok(ok({ ...base, beats: [...base.beats, { kind: "app", title: "macroBody le *sait*.", value: "308" }] }));
});

test("script: the voice reads what the viewer sees, stars removed, headings only when new", () => {
  const p = EXAMPLES[0];
  const { lines } = pixelCinemaScript(p);
  assert.equal(lines.length, 1 + p.beats.length + 1);
  assert.equal(lines[0], "Le problème, c'est pas le dîner. C'est ce qui vient après.");
  assert.equal(lines[1], "À 21 h, tout se joue là : le placard qui s'ouvre");
  assert.equal(lines[2], "30 g de cacahuètes : 180 kcal");
  assert.equal(lines[4], "Ce soir, il vous reste 308 kcal pas zéro, pas 800");
  assert.equal(lines[5], "macroBody vous le dit avant le placard.");
  assert.ok(lines.every((l) => !l.includes("*")));
  assert.equal(joinParts(["Une pomme ?", "Pas assez."]), "Une pomme ? Pas assez.");
  assert.equal(joinParts(["Il vous reste", "*Trois* choses"]), "Il vous reste. Trois choses");
  assert.equal(titleOf(p.beats, 2), "À 21 h, tout se joue *là* :");
  assert.equal(beatLine({ kind: "chip", text: "deux", flash: false }), "deux");
  assert.deepEqual(splitHighlight("C'est la *méthode*."), ["C'est la ", "méthode", "."]);
  assert.deepEqual(splitHighlight("Rien"), ["Rien", "", ""]);
  const timings = lines.map((text, i) => ({ text, start_s: i * 3, end_s: i * 3 + 2.5 }));
  assert.ok(ok({ ...read("pixelcinema"), voice: { lines: timings } }));
  assert.equal(ok({ ...read("pixelcinema"), voice: { lines: timings.slice(1) } }), false);
});

test("direction: strike then line, the beam comes on, the camera pushes in, the door opens", () => {
  const p = EXAMPLES[0];
  const { timeline } = timelineOf(p, 30);
  const hookLen = timeline.scenes[0].endFrame;
  const h = hookTimes(p, hookLen, 30);
  assert.ok(h.strike >= 18 && h.line > h.strike && h.line < hookLen);
  assert.deepEqual(hookTimes(EXAMPLES[2], hookLen, 30), { strike: -1, line: 0 });
  assert.ok(beamOf(p, timeline, 0, 30).power < 0.5);
  assert.ok(beamOf(p, timeline, h.line + 30, 30).power > 0.9);
  // Every shot is a new view, none lasts longer than SPLIT_S, and the camera moves within the first second of each.
  for (const ex of EXAMPLES) {
    const tl = timelineOf(ex, 30).timeline;
    const segs = segmentsOf(ex, tl, 30);
    assert.equal(segs[0].start, 0);
    for (const [i, s] of segs.entries()) {
      if (i) assert.ok(s.shot.view !== segs[i - 1].shot.view && s.start === segs[i - 1].end, `${ex.scene} shot ${i}`);
      assert.ok(s.end - s.start <= SPLIT_S * 30 + 1 || ex.beats.some((b) => b.kind === "chip" && b.flash), `${ex.scene} shot ${i} short`);
      const a = cameraAt(ex, tl, s.start, 30);
      const b = cameraAt(ex, tl, Math.min(s.end - 1, s.start + 30), 30);
      assert.equal(a.view, b.view);
      assert.ok(Math.abs(a.cam.zoom - b.cam.zoom) + Math.abs(a.cam.fx - b.cam.fx) + Math.abs(a.cam.fy - b.cam.fy) > 0.05, `${ex.scene} shot ${i} moves`);
    }
  }
  const fridge = EXAMPLES[2];
  const ft = timelineOf(fridge, 30).timeline;
  assert.equal(openOf(fridge, ft, 0, 30), 0); // the cover shows the door closed
  assert.equal(openOf(fridge, ft, 60, 30), 1);
});

test("pixel helpers: hash in [0, 1), dithering picks ramp colours, camera maps back and forth", () => {
  for (let i = 0; i < 200; i++) {
    const h = hash(i, i * 7, 3);
    assert.ok(h >= 0 && h < 1);
  }
  const r = ramp("#000000", "#FFFFFF");
  assert.deepEqual(dither(r, 0, 1, 1), r[0]);
  assert.deepEqual(dither(r, 1, 1, 1), r[1]);
  assert.ok(bayer(0, 0) > 0 && bayer(3, 3) < 1);
  const cam = { zoom: 1.2, fx: 90, fy: 140, dx: 1, dy: 0 };
  const [wx, wy] = toWorld(cam, 30, 200, 0.7);
  const [sx, sy] = toScreen(cam, wx, wy, 0.7);
  assert.ok(Math.abs(sx - 30) < 1e-9 && Math.abs(sy - 200) < 1e-9);
});

test("every view paints the same frame twice, darkens under dim, and has a white / black lightning frame", () => {
  const cam = { zoom: 1.1, fx: 90, fy: 150, dx: 0, dy: 0 };
  const opts = { t: 4.2, cam, beam: 1, sweep: 0, flash: false, dim: 0, open: 1 };
  const luma = (d: Uint8ClampedArray) => d.reduce((s, v, i) => (i % 4 === 3 ? s : s + v), 0) / (GW * GH * 3);
  for (const id of SCENE_IDS) {
    const shots = SETS[id].shots;
    assert.ok(shots.every((s, i) => s.view !== shots[(i + 1) % shots.length].view), `${id}: no view twice in a row`);
    for (const view of Object.keys(SETS[id].views)) {
      const paint1 = (d: Uint8ClampedArray, o: object) => paint(id, view, d, { ...opts, ...o });
      const a = new Uint8ClampedArray(GW * GH * 4);
      const b = new Uint8ClampedArray(GW * GH * 4);
      paint1(a, {});
      paint1(b, {});
      assert.deepEqual(a, b, `${id} ${view}`);
      const flash = new Uint8ClampedArray(GW * GH * 4);
      paint1(flash, { flash: true });
      const tones = new Set<number>();
      for (let i = 0; i < flash.length; i += 4) tones.add(flash[i]);
      assert.ok(tones.size <= 6, `${id} ${view}: the lightning frame is a few flat tones`);
      const solid = Array.from({ length: GW * GH }, (_, k) => solidAt(id, view, k % GW, Math.floor(k / GW), { ...opts, flash: true }));
      assert.ok(solid.includes(true) && solid.includes(false), `${id} ${view}: some sky, some silhouette`);
      const dark = new Uint8ClampedArray(GW * GH * 4);
      paint1(dark, { dim: 1 });
      assert.ok(luma(dark) < luma(a), `${id} ${view}: dim darkens`);
      const anchors = SETS[id].views[view].anchors(4.2);
      for (const k of ANCHORS) {
        const [x, y] = toScreen(cam, anchors[k][0], anchors[k][1], anchors[k][2]);
        assert.ok(x >= -20 && x < GW + 20 && y >= -20 && y < GH + 20, `${id} ${view} ${k} near the frame`);
      }
    }
  }
  assert.deepEqual([...CAMEOS.cinema], [...SCENE_IDS]);
});

test("sound: the sfx duck under a spoken line, the thunder waits for the next gap", () => {
  const spans = speechSpans([{ start_s: 1, end_s: 3 }, { start_s: 5, end_s: 6 }]);
  assert.equal(sfxGain([], 2), 1);
  assert.equal(sfxGain(spans, 4), 1);
  assert.ok(Math.abs(20 * Math.log10(sfxGain(spans, 2)) + 20) < 0.01, "20 dB down under the voice");
  assert.equal(thunderAt(spans, 0.5), 0.5);
  assert.equal(thunderAt(spans, 2), 3.25);
  assert.equal(thunderAt(spans, 4.9), 6.25);
  assert.equal(thunderAt(spans, 4), 4);
});
