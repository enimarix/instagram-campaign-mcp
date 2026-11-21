// Body sound effects under the voice (step 159): src/lib/duck.ts sfxVolume / sfxGain, and no
// template plays a sound at a hand-set volume.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { ASSETS } from "../src/assets.ts";
import { BANG_SPEECH_DB, BED_LUFS, bedLevel, isLibrarySfx, LIBRARY_PEAK_LUFS, MUSIC_LUFS, SFX_PEAK_LUFS, type SfxId, sfxGain, sfxVolume, SPEECH_SFX_DB, speechSpans, VOICE_LUFS } from "../src/lib/duck.ts";

const dB = (g: number) => 20 * Math.log10(g);
const near = (a: number, b: number, msg?: string) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b} ${msg ?? ""}`);
const IDS = Object.keys(SFX_PEAK_LUFS) as SfxId[];

test("every sound effect has a measured peak", () => {
  const sfx = Object.entries(ASSETS).filter(([, a]) => a.kind === "sfx").map(([id]) => id);
  assert.deepEqual([...IDS].sort(), sfx.sort());
});

test("every music bed has a measured loudness; a loud one comes down to the beds' level", () => {
  const music = Object.entries(ASSETS).filter(([, a]) => a.kind === "music").map(([id]) => id);
  assert.deepEqual(Object.keys(MUSIC_LUFS).sort(), music.sort());
  near(dB(bedLevel("music-overworld")) + MUSIC_LUFS["music-overworld"], BED_LUFS, "the 8-bit loop at the level");
  assert.equal(bedLevel("music-nocturne"), 1, "a soft bed is left as it is");
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

test("a library sound (ov:<id>, step 150) plays from the library's peak, under the voice", () => {
  const ov = "ov:a8032d83-dd12-4978-b1e7-2cc07779387d";
  assert.ok(isLibrarySfx(ov));
  for (const id of ["ov:", "ov:../x", "sfx-pop", "OV:A8032D83-DD12-4978-B1E7-2CC07779387D"]) assert.ok(!isLibrarySfx(id), id);
  const spans = speechSpans([{ start_s: 1, end_s: 3 }]);
  near(dB(sfxGain(spans, ov, 5)) + LIBRARY_PEAK_LUFS, VOICE_LUFS, "in a gap");
  near(dB(sfxGain(spans, ov, 2)) + LIBRARY_PEAK_LUFS, VOICE_LUFS + SPEECH_SFX_DB, "on a word");
  // The studio's cache (src/studio/sfx.py) sets every library sound to that same peak.
  const py = readFileSync(new URL("../../src/studio/sfx.py", import.meta.url), "utf8");
  assert.equal(Number(/^PEAK_LUFS = (-?[\d.]+)/m.exec(py)?.[1]), LIBRARY_PEAK_LUFS);
});
