// Body sound effects under the voice (step 159): src/lib/duck.ts sfxVolume / sfxGain, and no
// template plays a sound at a hand-set volume.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { ASSETS } from "../src/assets.ts";
import { BANG_SPEECH_DB, SFX_PEAK_LUFS, type SfxId, sfxGain, sfxVolume, SPEECH_SFX_DB, speechSpans, VOICE_LUFS } from "../src/lib/duck.ts";

const dB = (g: number) => 20 * Math.log10(g);
const near = (a: number, b: number, msg?: string) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b} ${msg ?? ""}`);
const IDS = Object.keys(SFX_PEAK_LUFS) as SfxId[];

test("every sound effect has a measured peak", () => {
  const sfx = Object.entries(ASSETS).filter(([, a]) => a.kind === "sfx").map(([id]) => id);
  assert.deepEqual([...IDS].sort(), sfx.sort());
});

test("a sound peaks at the voice's level in the gaps and further under it on a spoken line", () => {
  const spans = speechSpans([{ start_s: 1, end_s: 3 }]);
  for (const id of IDS) {
    const peak = (g: number) => dB(g) + SFX_PEAK_LUFS[id];
    assert.ok(sfxVolume(id) <= 1, `${id} never past full volume`);
    near(peak(sfxGain(spans, id, 5)), VOICE_LUFS, `${id} in a gap`);
    near(peak(sfxGain(spans, id, 5, -4)), VOICE_LUFS - 4, `${id} quieter accent`);
    near(peak(sfxGain(spans, id, 2)), VOICE_LUFS + SPEECH_SFX_DB, `${id} on a word`);
    near(peak(sfxGain(spans, id, 2, -3, BANG_SPEECH_DB)), VOICE_LUFS - 3 + BANG_SPEECH_DB, `${id} bang on a word`);
    near(sfxGain([], id, 2), sfxVolume(id), "no voice: the gap level");
  }
  assert.ok(sfxVolume("sfx-coin") < 0.2, "the loudest file comes well down");
  assert.ok(SPEECH_SFX_DB <= -6 && BANG_SPEECH_DB <= 0 && BANG_SPEECH_DB > SPEECH_SFX_DB);
});

test("no template plays a sound at a hand-set volume: only the voice is a plain Html5Audio", () => {
  const dir = new URL("../src/templates/", import.meta.url);
  const files = readdirSync(dir, { recursive: true, encoding: "utf8" }).filter((n) => n.endsWith(".tsx")).sort();
  assert.ok(files.length >= 10);
  for (const name of files) {
    const src = readFileSync(new URL(name.replaceAll("\\", "/"), dir), "utf8");
    assert.doesNotMatch(src, /volume/, `${name}: sounds go through <Sfx> / <MusicBed>, never a volume`);
    for (const [tag] of src.matchAll(/<Html5Audio\b[^>]*>/g)) {
      assert.match(tag, /src=\{(voice|props\.voice\.audioSrc)\}/, `${name}: ${tag} (sound effects go through <Sfx>)`);
    }
  }
});
