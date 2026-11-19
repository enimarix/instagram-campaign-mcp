// The step-148 music beds: registry entries match the songs, and each loops cleanly.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { barSamples, BEDS, SR } from "../scripts/beds.ts";
import { ASSETS } from "../src/assets.ts";

const root = join(import.meta.dirname, "..");

for (const [id, song] of Object.entries(BEDS)) {
  test(`${id}: registered, intro + body on whole frames, loops seamlessly`, () => {
    const entry = ASSETS[id as keyof typeof ASSETS];
    assert.ok(entry && entry.kind === "music" && entry.file === `audio/${id}.wav`, "in src/assets.ts");
    const bar = barSamples(song);
    assert.equal(bar % 1, 0, "a bar is whole samples");
    assert.equal(entry.loopStart_s * SR, song.introBars * bar, "loopStart_s = the intro");
    assert.equal((entry.loopStart_s * 30) % 1, 0, "the loop starts on a frame");

    const wav = readFileSync(join(root, "public", entry.file));
    assert.equal(wav.readUInt16LE(22), 2, "stereo");
    assert.equal(wav.readUInt32LE(24), SR);
    const frames = wav.readUInt32LE(40) / 4;
    assert.equal(frames, (song.introBars + song.bodyBars) * bar, "intro + one body");
    assert.equal(((frames - song.introBars * bar) * 30) % SR, 0, "the body is whole frames");

    // Both joins into the body (from the intro, and from the body's own end) continue from the
    // same sample, so the wrap is as smooth as the intro's way in.
    const at = (i: number, c: number) => wav.readInt16LE(44 + i * 4 + c * 2);
    const start = song.introBars * bar;
    for (const c of [0, 1]) assert.ok(Math.abs(at(start - 1, c) - at(frames - 1, c)) <= 64, `channel ${c}`);
    // Mastered: real level, never clipping.
    let peak = 0;
    let sum = 0;
    for (let i = 0; i < frames; i++)
      for (const c of [0, 1]) {
        const v = at(i, c);
        peak = Math.max(peak, Math.abs(v));
        sum += v * v;
      }
    assert.ok(peak < 32767 * 0.9, `peak ${peak}`);
    const rms = 20 * Math.log10(Math.sqrt(sum / (2 * frames)) / 32767);
    assert.ok(rms > -24 && rms < -15, `rms ${rms}`);
  });
}
