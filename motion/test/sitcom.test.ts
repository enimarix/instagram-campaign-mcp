// SitcomSkit (step 164): schema, the narrator's script (048b voice rule), the timed parts the
// troupe shoots (src/studio/sitcom.py), the voice paused for the characters' lines and the
// freeze, the karaoke words, and the end card.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { CAMEOS, CARD_S, END_CARD_STYLES } from "../src/endcards/schema.ts";
import { MUSIC_LUFS, SFX_PEAK_LUFS } from "../src/lib/duck.ts";
import { coverOf, FREEZE_S, layoutOf, SAY_GAP_S, SFX_FILE, sitcomSchema, sitcomScript } from "../src/templates/SitcomSkit/schema.ts";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../props/${name}.json`, import.meta.url), "utf8"));
const NAMES = ["sitcomskit", "sitcomskit-salle", "sitcomskit-salon"];
const EXAMPLES = NAMES.map((n) => sitcomSchema.parse(read(n)));
const ok = (p: object) => sitcomSchema.safeParse(p).success;

test("the three examples parse, run 15-40 s with a troupe of 5-8, tu, the card after the picture", () => {
  for (const [i, p] of EXAMPLES.entries()) {
    const { parts, cardStart, total } = layoutOf(p);
    assert.ok(total >= 15 && total <= 40, `${NAMES[i]}: ${total} s`);
    assert.ok(total - cardStart >= CARD_S.sitcom, NAMES[i]);
    const cast = new Set(p.scenes.flatMap((s) => s.cast.map((m) => m.who)));
    assert.ok(cast.size >= 5 && cast.size <= 8, NAMES[i]);
    assert.equal(p.address, "tu");
    assert.equal(parts[0].part, "hook");
    assert.ok(p.hook.split(" ").length <= 6);
  }
  assert.ok(EXAMPLES[2].citations.length >= 1, "a stated fact cites its source");
});

test("the parts run end to end from frame 0 to the end card, the punchline frozen last", () => {
  for (const p of EXAMPLES) {
    const { parts, cardStart } = layoutOf(p);
    assert.equal(parts[0].start_s, 0);
    parts.slice(1).forEach((x, i) => assert.ok(Math.abs(x.start_s - parts[i].end_s) < 1e-9, "no gap, no overlap"));
    assert.equal(parts[parts.length - 1].part, "freeze");
    assert.ok(Math.abs(parts[parts.length - 1].end_s - parts[parts.length - 1].start_s - FREEZE_S) < 1e-9);
    assert.equal(parts[parts.length - 1].end_s, cardStart);
    const beats = p.scenes.flatMap((s, i) => s.beats.map((b, j) => ({ b, i, j })));
    for (const { b, i, j } of beats) {
      assert.ok(parts.some((x) => x.scene === i && x.beat === j && x.part === "line"), "every beat has its line");
      assert.equal(parts.some((x) => x.scene === i && x.beat === j && x.part === "say"), !!b.say);
    }
  }
});

test("the narrator reads the hook, every beat and the outro; it pauses for each character line and the freeze", () => {
  const p = EXAMPLES[0];
  const lines = sitcomScript(p).lines;
  assert.deepEqual(lines, [p.hook, ...p.scenes[0].beats.map((b) => b.line), p.outro]);
  const timings = lines.map((text, i) => ({ text, start_s: 2 * i, end_s: 2 * i + 1.5 }));
  const says = p.scenes[0].beats.filter((b) => b.say).length;
  const voiced = { ...p, voice: { audioSrc: "public/voice/a.wav", lines: timings } };
  voiced.scenes = [{ ...p.scenes[0], beats: p.scenes[0].beats.map((b) => (b.say ? { ...b, say: { ...b.say, seconds: 1 } } : b)) }];
  const { voiceParts, spoken } = layoutOf(sitcomSchema.parse(voiced));
  assert.equal(voiceParts.length, 1 + says + 1);
  const shifts = voiceParts.map((v) => v.at_s - v.audio_s);
  assert.ok(Math.abs(shifts[1] - (1 + 2 * SAY_GAP_S)) < 1e-9);
  assert.ok(Math.abs(shifts[shifts.length - 1] - shifts[shifts.length - 2] - FREEZE_S) < 1e-9);
  const character = spoken.filter((x) => x.say);
  assert.equal(character.length, says);
  // a character speaks in the narrator's silence
  for (const c of character) {
    assert.ok(!spoken.some((n) => !n.say && n.start_s < c.end_s && n.end_s > c.start_s), "never over the narrator");
  }
  assert.ok(!ok({ ...voiced, voice: { lines: timings.slice(1) } }), "one timing per script line");
});

test("refused: a long hook, a lonely or crowded skit, an actor outside the scene, a price", () => {
  const p = read("sitcomskit");
  assert.ok(ok(p));
  assert.ok(!ok({ ...p, hook: "un deux trois quatre cinq six sept" }));
  assert.ok(!ok({ ...p, scenes: [{ ...p.scenes[0], cast: p.scenes[0].cast.slice(0, 4), beats: p.scenes[0].beats.slice(0, 1) }] }));
  const nine = ["dad", "mum", "teen", "uncle", "aunt", "grandma", "grandpa", "kid_boy", "kid_girl"].map((who) => ({ who }));
  assert.ok(!ok({ ...p, scenes: [{ ...p.scenes[0], cast: nine.slice(0, 8) }, { ...p.scenes[0], cast: [nine[8], ...nine.slice(0, 7)] }] }));
  const stranger = structuredClone(p);
  stranger.scenes[0].beats[0].who = "chef";
  assert.ok(!ok(stranger));
  assert.ok(!ok({ ...p, outro: "Seulement 4,99 € par mois" }));
  const key = structuredClone(p);
  key.scenes[0].beats[0].key = "absent";
  assert.ok(!ok(key));
});

test("the cover is the hook over the opening action; the sounds and bed are measured; the card exists", () => {
  assert.ok(coverOf(30) > 0 && coverOf(30) < 30);
  for (const id of Object.values(SFX_FILE)) assert.ok(id in SFX_PEAK_LUFS, id);
  assert.ok("music-sitcom" in MUSIC_LUFS);
  assert.ok(END_CARD_STYLES.includes("sitcom"));
  assert.deepEqual([...CAMEOS.sitcom], ["applause"]);
});
