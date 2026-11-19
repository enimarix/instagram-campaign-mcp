// Cutaway (step 142): schema, script mapping (048b voice rule), timings, the pixel font, the
// mechanism clock and the HUD layout.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { CAP, glyphText, lineWidth, linePath, wrapText } from "../src/cutaway/pixelfont.ts";
import { chipText, dashesOf, mechanismClock, rateOf, VIEW_IDS, VIEWS } from "../src/cutaway/views.ts";
import { CAMEOS, CARD_S, endCardSchema } from "../src/endcards/schema.ts";
import { lerpText, stepsLayout, titleLayout } from "../src/templates/Cutaway/layout.ts";
import { cutawaySchema, cutawayScript, lineOf, resolveScenes, scenesOf, timelineOf } from "../src/templates/Cutaway/schema.ts";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../props/${name}.json`, import.meta.url), "utf8"));
const NAMES = ["cutaway", "cutaway-croissance", "cutaway-graisse"];
const EXAMPLES = NAMES.map(read);
const scene = (view: string, extra: object = {}) => ({ title: "Titre", view, ...extra });
const base = { hook: scene("arm"), beats: [scene("muscle"), scene("fibre"), scene("sarcomere"), scene("sarcomere")], payoff: scene("arm"), citations: [] };

test("the three examples parse, run 25-45 s without a voice, and end on the cutaway card", () => {
  for (const [i, raw] of EXAMPLES.entries()) {
    const parsed = cutawaySchema.safeParse(raw);
    assert.ok(parsed.success, parsed.success ? "" : `${NAMES[i]}: ${parsed.error.message}`);
    const { timeline, endStart } = timelineOf(parsed.data, 30);
    const s = timeline.totalFrames / 30;
    assert.ok(s >= 25 && s <= 45, `${NAMES[i]}: ${s} s`);
    assert.ok(timeline.totalFrames - endStart >= CARD_S.cutaway * 30, `${NAMES[i]}: the card plays whole`);
    assert.ok(parsed.data.citations.length > 0, `${NAMES[i]}: sources for its numbers`);
  }
  const p = cutawaySchema.parse(base);
  assert.deepEqual([p.address, p.music, p.loop, p.accent, p.hook.speed, p.hook.zoom, p.hook.x2], ["vous", "music-dusk", false, "brand", "real", 1, false]);
});

test("bad props fail with clear messages", () => {
  const message = (p: object) => {
    const r = cutawaySchema.safeParse(p);
    assert.equal(r.success, false, JSON.stringify(p));
    return r.success ? "" : r.error.issues.map((i) => i.message).join("; ");
  };
  assert.match(message({ ...base, hook: scene("arm", { callouts: [{ text: "Actine", at: "actine" }] }) }), /arm points: biceps/);
  assert.match(message({ ...base, hook: scene("arm", { focus: "tete" }) }), /arm points/);
  assert.match(message({ ...base, payoff: scene("arm", { steps: { items: ["a", "b"], current: 2 } }) }), /current must be one of the items/);
  assert.match(message({ ...base, beats: base.beats.slice(0, 3) }), /Too small|at least/);
  assert.match(message({ ...base, outro: "Seulement 9,99 € par mois" }), /no price on screen/);
  assert.match(message({ ...base, hook: scene("arm", { sub: "Dès 5 euros" }) }), /no price on screen/);
  assert.match(message({ ...base, hook: scene("arm", { gauge: { label: "Prix", value: "4,99 €", fill: 1 } }) }), /no price on screen/);
  assert.match(message({ ...base, hook: scene("heart") }), /Invalid option|expected one of/);
  assert.match(message({ ...base, hook: scene("arm", { speed: "1/3" }) }), /Invalid option|expected one of/);
  assert.match(message({ ...base, voice: { lines: [{ text: "Titre", start_s: 0, end_s: 1 }] } }), /one timing per script line/);
  message({ ...base, cameo: "golem" });
  message({ ...base, extra: 1 });
});

test("script lines: hook, each beat, payoff, then the outro; a scene reads its title then its sub (048b)", () => {
  const p = cutawaySchema.parse(EXAMPLES[0]);
  const { lines } = cutawayScript(p);
  assert.equal(lines.length, p.beats.length + 2 + (p.outro ? 1 : 0));
  assert.equal(lines[0], "Comment un muscle se contracte ? Avec des milliards de petits moteurs.");
  assert.equal(lines[lines.length - 1], p.outro);
  assert.equal(lineOf({ title: "Ralenti 84 fois : le sarcomère", sub: "La myosine tire l'actine vers le centre." }), "Ralenti 84 fois : le sarcomère. La myosine tire l'actine vers le centre.");
  assert.equal(lineOf({ title: "Pendant l'effort,", sub: "vous l'abîmez" }), "Pendant l'effort, vous l'abîmez");
  // With a voice, scenes follow its timings.
  const timings = lines.map((text, i) => ({ text, start_s: i * 4, end_s: i * 4 + 3.5 }));
  const { timeline } = timelineOf({ ...p, voice: { lines: timings } }, 30);
  assert.equal(timeline.scenes[3].startFrame, 360);
});

test("scenes resolve: dusk hook and payoff, night beats, stage carried within a view, cuts on a new view", () => {
  const p = cutawaySchema.parse({ ...base, beats: [scene("muscle"), scene("sarcomere", { stage: 0.4 }), scene("sarcomere"), scene("sarcomere", { stage: 1, speed: "1/84", x2: true })] });
  const r = resolveScenes(p);
  assert.deepEqual(r.map((s) => s.sky), ["dusk", "night", "night", "night", "night", "dusk"]);
  assert.deepEqual(r.map((s) => s.cut), [false, true, true, false, false, true]);
  assert.deepEqual([r[2].stageFrom, r[2].stageTo, r[3].stageFrom, r[3].stageTo, r[4].stageFrom, r[4].stageTo], [0.4, 0.4, 0.4, 0.4, 0.4, 1]);
  assert.equal(r[4].rate, 2 / 84);
  assert.equal(scenesOf(p).length, 6);
});

test("pixel font: capitals, accents above, wrapping, bold one pixel wider per letter", () => {
  assert.equal(glyphText("Cœur à 9,5 g"), "COEUR À 9,5 G");
  assert.equal(lineWidth("A"), 5);
  assert.equal(lineWidth("AB"), 11);
  assert.equal(lineWidth("AB", true), 13);
  // É: the acute sits above the capital (negative rows), the E keeps its full height.
  const d = linePath("É", 0, 30, 1);
  const ys = [...d.matchAll(/M\d+ (\d+)/g)].map((m) => Number(m[1]));
  assert.ok(Math.min(...ys) < 30 && Math.max(...ys) === 30 + CAP - 1, d);
  assert.equal(linePath("Ç", 0, 0, 1).includes(" 8h"), true);
  // Unknown characters draw as "?" instead of vanishing.
  assert.equal(linePath("☃", 0, 0, 1), linePath("?", 0, 0, 1));
  assert.deepEqual(wrapText("Comment un muscle se contracte ?", 60), ["Comment un", "muscle se", "contracte ?"]);
  assert.deepEqual(wrapText("a\nb", 100), ["a", "b"]);
});

test("speeds: rates, chip text, dashes; the mechanism clock eases between them", () => {
  assert.equal(rateOf("real"), 1);
  assert.equal(rateOf("1/84"), 1 / 84);
  assert.equal(rateOf("1/10", true), 0.2);
  assert.equal(rateOf("x1000"), 1000);
  assert.equal(chipText("real"), "▶ Vitesse réelle");
  assert.equal(chipText("1/42"), "‖ Ralenti 1/42");
  assert.equal(chipText("x1000"), "▶▶ Accéléré ×1000");
  assert.deepEqual([dashesOf(1), dashesOf(1 / 84), dashesOf(1000)], [6, 1, 6]);
  const clock = mechanismClock([{ start: 0, rate: 1 }, { start: 30, rate: 1 / 84 }], 90, 30, 18);
  assert.ok(clock.every((c, i) => !i || c > clock[i - 1]), "always moves forward");
  assert.ok(Math.abs(clock[30] - 1) < 1e-9, "one second of real speed");
  const slope = (f: number) => (clock[f + 1] - clock[f]) * 30;
  assert.ok(slope(31) < 1 && slope(31) > slope(40), "slows down gradually");
  assert.ok(Math.abs(slope(60) - 1 / 84) < 1e-9, "then runs at 1/84");
  for (const id of VIEW_IDS) assert.ok(VIEWS[id].hz > 0 && VIEWS[id].anchors.length > 0, id);
});

test("HUD layout: every example's title boxes and steps fit the safe width; the gauge counts", () => {
  for (const raw of EXAMPLES) {
    const p = cutawaySchema.parse(raw);
    scenesOf(p).forEach((s, i) => {
      const big = i === 0 || i === p.beats.length + 1;
      const { boxes, bottom } = titleLayout(s, big);
      for (const b of boxes) assert.ok(b.x >= 65 && b.x + b.w <= 1015, `${s.title}: box ${b.x}..${b.x + b.w}`);
      assert.ok(bottom < 800, `${s.title}: title ends at ${bottom}`);
      if (s.steps) assert.ok(stepsLayout(s.steps.items).width <= 900, s.title);
    });
  }
  assert.equal(lerpText("2 400 tr/min", "28,6 tr/min", 0), "2 400,0 tr/min");
  assert.equal(lerpText("10", "6", 0.5), "8");
  assert.equal(lerpText(undefined, "84 %", 0.2), "84 %");
  assert.equal(lerpText("10", "84 %", 1), "84 %");
});

test("the cutaway end card: cameos are the views, every one parses, never a price", () => {
  assert.deepEqual([...CAMEOS.cutaway], VIEW_IDS);
  for (const cameo of [...VIEW_IDS, "none"]) assert.ok(endCardSchema.safeParse({ style: "cutaway", cameo }).success, cameo);
  assert.equal(endCardSchema.safeParse({ style: "cutaway", cameo: "mascot" }).success, false);
  assert.ok(endCardSchema.safeParse(read("cutaway-endcard")).success);
});
