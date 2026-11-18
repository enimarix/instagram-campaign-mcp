// PaperStory (step 131): schema, script mapping (048b voice rule), timings, layout.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { CAMEOS, CARD_S } from "../src/endcards/schema.ts";
import { CHARACTER_IDS } from "../src/paper/palette.ts";
import { coverFrame, labelHeight, labelStack, payoffPlaces, rowY, sizeOf } from "../src/templates/PaperStory/layout.ts";
import { paperStorySchema, paperStoryScript, sceneLine, timelineOf } from "../src/templates/PaperStory/schema.ts";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../props/${name}.json`, import.meta.url), "utf8"));
const NAMES = ["paperstory", "paperstory-proteines", "paperstory-moyenne"];
const EXAMPLES = NAMES.map(read);
const base = {
  hook: { labels: ["Hook ?"] },
  beats: [
    { kind: "problem", labels: ["Problem"], options: [{ food: "pizza", label: "300 kcal", verdict: "too_much" }] },
    { kind: "app", labels: ["App"], value: "308" },
    { kind: "payoff", labels: ["Payoff"] },
  ],
  citations: [],
};

test("the three examples parse and run 20-30 s; defaults: Inès, vous, kalimba, no loop", () => {
  for (const [i, raw] of EXAMPLES.entries()) {
    const parsed = paperStorySchema.safeParse(raw);
    assert.ok(parsed.success, parsed.success ? "" : `${NAMES[i]}: ${parsed.error.message}`);
    const s = timelineOf(parsed.data, 30).timeline.totalFrames / 30;
    assert.ok(s >= 20 && s <= 30, `${NAMES[i]}: ${s} s`);
  }
  const p = paperStorySchema.parse(base);
  assert.deepEqual([p.character, p.address, p.music, p.loop, p.accent, p.hook.prop, p.hook.time], ["ines", "vous", "music-kalimba", false, "brand", "clock", "21:00"]);
  const [problem, app] = p.beats;
  assert.ok(problem.kind === "problem" && problem.prop === "fridge" && problem.options[0].note === "environ");
  assert.ok(app.kind === "app" && app.button === "Compléter ma journée" && app.unit === "kcal restantes");
});

test("bad props fail with clear messages", () => {
  const message = (p: object) => {
    const r = paperStorySchema.safeParse(p);
    assert.equal(r.success, false, JSON.stringify(p));
    return r.success ? "" : r.error.issues.map((i) => i.message).join("; ");
  };
  const [problem, app, payoff] = base.beats;
  assert.match(message({ ...base, beats: [app, problem, payoff] }), /1-2 problem, then 1-2 app, then one payoff/);
  assert.match(message({ ...base, beats: [problem, app, { ...app, rows: [{ food: "egg", name: "Œuf", to: 50 }, { food: "rice", name: "Riz", to: 80 }] }, payoff] }), /phone \(value\) or the list \(rows\)/);
  assert.match(message({ ...base, beats: [problem, { ...app, value: undefined, total: "+306 kcal" }, payoff] }), /total goes with rows/);
  assert.match(message({ ...base, beats: [problem, app, { ...payoff, of: "/ 2 238 kcal" }] }), /of goes with value/);
  assert.match(message({ ...base, outro: "Seulement 9,99 € par mois" }), /no price on screen/);
  assert.match(message({ ...base, hook: { labels: [{ text: "Dès 5 euros", tone: "brand" }] } }), /no price on screen/);
  assert.match(message({ ...base, hook: { labels: ["Hook"], aside: "(4,99 € /mois)" } }), /no price on screen/);
  assert.match(message({ ...base, beats: [{ ...problem, options: [{ food: "pizza", label: "9,99 €" }] }, app, payoff] }), /no price on screen/);
  assert.match(message({ ...base, hook: { labels: ["Hook"], time: "25:00" } }), /a time like 21:00/);
  assert.match(message({ ...base, beats: [{ ...problem, options: [{ food: "cake", label: "1" }] }, app, payoff] }), /Invalid option|expected one of/);
  assert.match(message({ ...base, voice: { lines: [{ text: "Hook ?", start_s: 0, end_s: 1 }] } }), /one timing per script line/);
  assert.match(message({ ...base, hook: { labels: ["a", "b", "c", "d"] } }), /Too big|at most/);
  message({ ...base, cameo: "golem" });
  message({ ...base, extra: 1 });
});

test("script lines: hook, each beat, then the outro; strips joined into sentences (048b)", () => {
  assert.deepEqual(paperStoryScript(paperStorySchema.parse(base)).lines, ["Hook ?", "Problem", "App", "Payoff"]);
  assert.equal(sceneLine(["21 h. Il vous reste", { text: "308 kcal", tone: "brand", size: "l" }, "Vous mangez quoi ?"]), "21 h. Il vous reste 308 kcal. Vous mangez quoi ?");
  assert.equal(sceneLine(["Elle choisit ce qu'elle a…", "…bloque ses grammes…"]), "Elle choisit ce qu'elle a… …bloque ses grammes…");
  assert.equal(sceneLine(["Léa mange", "2 000 kcal", "comme sur l'étiquette."]), "Léa mange 2 000 kcal comme sur l'étiquette.");
  // Same lines as src/studio/motion.py SCRIPTS["PaperStory"] (tests/test_studio_motion.py checks the Python side).
  assert.deepEqual(paperStoryScript(paperStorySchema.parse(EXAMPLES[0])).lines.slice(0, 2), ["21 h. Il vous reste 308 kcal. Vous mangez quoi ?", "Trois parts de pizza ? Trop."]);
  const withOutro = paperStorySchema.parse({ ...base, outro: "Tagline" });
  const lines = paperStoryScript(withOutro).lines;
  assert.deepEqual(lines, ["Hook ?", "Problem", "App", "Payoff", "Tagline"]);
  const timings = lines.map((text, i) => ({ text, start_s: i * 2, end_s: i * 2 + 1.5 }));
  const voiced = paperStorySchema.parse({ ...base, outro: "Tagline", voice: { lines: timings } });
  const { timeline, endStart } = timelineOf(voiced, 30);
  // The voice sets the pace; the end card starts on the outro line and lasts at least CARD_S.paper.
  assert.equal(timeline.scenes[4].startFrame, 240);
  assert.equal(endStart, 240);
  assert.ok(timeline.totalFrames - endStart >= CARD_S.paper * 30);
});

test("without a voice every beat gets room to animate; the end card lasts CARD_S.paper", () => {
  for (const raw of [base, ...EXAMPLES]) {
    const p = paperStorySchema.parse(raw);
    const { timeline, endStart } = timelineOf(p, 30);
    const [hook, ...beats] = timeline.scenes.slice(0, p.beats.length + 1).map((s) => (s.endFrame - s.startFrame) / 30);
    assert.ok(hook >= 2.5, `hook ${hook}`);
    beats.forEach((s, i) => assert.ok(s >= 3.2, `beat ${i}: ${s} s`));
    assert.ok(timeline.totalFrames - endStart >= CARD_S.paper * 30);
  }
});

test("layout: the hook lands by 2.5 s; strips and payoff stay inside the safe area", () => {
  for (const raw of EXAMPLES) {
    const p = paperStorySchema.parse(raw);
    assert.ok(coverFrame(p, 30) <= 2.5 * 30);
    for (const labels of [p.hook.labels, ...p.beats.map((b) => b.labels)]) {
      const { ys, bottom } = labelStack(labels);
      assert.ok(ys[0] - labelHeight(sizeOf(labels[0])) / 2 >= 269, "first strip under the top of the safe area");
      assert.ok(bottom <= 780, `strips end at ${bottom}, above the props and faces`);
    }
    for (const b of p.beats) if (b.kind === "payoff" && b.value) assert.ok(payoffPlaces(b).ringY + 232 <= 1248, "payoff ring above the bottom UI");
  }
});

test("app list rows never overlap each other or the total (2-5 rows)", () => {
  for (let n = 2; n <= 5; n++) {
    for (let i = 1; i < n; i++) assert.ok(rowY(i, n) - rowY(i - 1, n) >= 124, `${n} rows`);
    assert.ok(rowY(n - 1, n) + 62 <= 1240 - 62, `${n} rows end above the total`);
  }
});

test("every character can be the end card's cameo", () => {
  for (const id of CHARACTER_IDS) assert.ok((CAMEOS.paper as readonly string[]).includes(id), id);
});
