// Builds our own (code-generated) assets into public/: sprite sheets from src/lib/sprites.ts as
// SVG, chiptune loops and sound effects from a tiny square/triangle/noise synth as WAV.
// Run: `node scripts/make-assets.ts` (from motion/), then commit the files it writes.
// Deterministic (no Math.random, no Math.sin): test/assets-licenses.test.ts checks the
// committed files still match this script, so re-run it after editing art, songs or the palette.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import brand from "../../brand/brand.json" with { type: "json" };
import { seeded, sheetSvg } from "../src/lib/game.ts";
import * as art from "../src/lib/sprites.ts";

const RATE = 22050; // Hz, mono 16-bit: plenty for square waves, half the size of 44.1 kHz

type Wave = "square" | "triangle" | "noise";
type Tone = {
  wave: Wave;
  /** Start and end frequency in Hz (linear sweep); noise: the rate it picks new values. */
  from: number;
  to?: number;
  seconds: number;
  volume: number;
  /** Square duty cycle. */
  duty?: number;
  /** Fade linearly to silence over the tone (percussive); otherwise hold, short release. */
  decay?: boolean;
};

const ATTACK = 0.002; // s, avoids clicks
const RELEASE = 0.01;

/** Adds `t` to `buf` from sample `start`; the tone ends at silence, so loops stay click-free. */
const addTone = (buf: Float64Array, start: number, t: Tone, seed = 1) => {
  const n = Math.min(Math.round(t.seconds * RATE), buf.length - start);
  const { from, to = from, duty = 0.5 } = t;
  let phase = 0;
  for (let i = 0; i < n; i++) {
    const p = i / n;
    phase += (from + (to - from) * p) / RATE;
    const x = phase % 1;
    const v =
      t.wave === "square"
        ? x < duty ? 1 : -1
        : t.wave === "triangle"
          ? 1 - 4 * Math.abs(x - 0.5)
          : seeded(seed, Math.floor(phase)) * 2 - 1;
    const s = i / RATE;
    const env = t.decay
      ? Math.min(1, s / ATTACK) * (1 - p)
      : Math.min(1, s / ATTACK, (n - i) / RATE / RELEASE);
    buf[start + i] += v * env * t.volume;
  }
};

/** 16-bit mono PCM WAV. */
const wav = (buf: Float64Array): Buffer => {
  const out = Buffer.alloc(44 + buf.length * 2);
  out.write("RIFF", 0);
  out.writeUInt32LE(36 + buf.length * 2, 4);
  out.write("WAVEfmt ", 8);
  out.writeUInt32LE(16, 16);
  out.writeUInt16LE(1, 20); // PCM
  out.writeUInt16LE(1, 22); // mono
  out.writeUInt32LE(RATE, 24);
  out.writeUInt32LE(RATE * 2, 28);
  out.writeUInt16LE(2, 32);
  out.writeUInt16LE(16, 34);
  out.write("data", 36);
  out.writeUInt32LE(buf.length * 2, 40);
  buf.forEach((v, i) => out.writeInt16LE(Math.round(Math.max(-1, Math.min(1, v)) * 32767), 44 + i * 2));
  return out;
};

const NOTES: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
/** "C5", "F#3" → Hz (A4 = 440). */
const hz = (note: string): number => {
  const m = /^([A-G])(#?)(\d)$/.exec(note);
  if (!m) throw new Error(`bad note ${note}`);
  const midi = 12 * (Number(m[3]) + 1) + NOTES[m[1]] + (m[2] ? 1 : 0);
  return 440 * 2 ** ((midi - 69) / 12);
};

type Track = { wave: Wave; volume: number; duty?: number; decay?: boolean; steps: string };
type Song = { bpm: number; tracks: Track[] };

/**
 * One loop of a song. Each track is one token per 16th step: a note ("E5") starts it, "-" holds
 * the previous note, "." rests, "x" is a drum hit (noise). Every track must have the same number
 * of steps; the loop is exactly that many steps long, so it repeats seamlessly.
 */
const song = ({ bpm, tracks }: Song): Float64Array => {
  const step = Math.round((RATE * 60) / bpm / 4); // samples per 16th, whole so the loop is exact
  const lengths = new Set(tracks.map((t) => t.steps.split(/\s+/).length));
  if (lengths.size !== 1) throw new Error(`tracks differ in length: ${[...lengths]}`);
  const steps = [...lengths][0];
  const buf = new Float64Array(steps * step);
  tracks.forEach((track, ti) => {
    const tokens = track.steps.split(/\s+/);
    tokens.forEach((tok, i) => {
      if (tok === "-" || tok === ".") return;
      let len = 1;
      while (tokens[i + len] === "-") len++;
      const tone = { ...track, seconds: (len * step) / RATE };
      if (tok === "x") addTone(buf, i * step, { ...tone, wave: "noise", from: 8000, seconds: 0.06, decay: true }, ti * 1000 + i);
      else addTone(buf, i * step, { ...tone, from: hz(tok) });
    });
  });
  return buf;
};

const sfx = (...tones: [atSeconds: number, Tone][]): Float64Array => {
  const end = Math.max(...tones.map(([at, t]) => at + t.seconds));
  const buf = new Float64Array(Math.round(end * RATE));
  tones.forEach(([at, t], i) => addTone(buf, Math.round(at * RATE), t, i + 1));
  return buf;
};

const sq = (from: number, seconds: number, extra: Partial<Tone> = {}): Tone => ({
  wave: "square", from, seconds, volume: 0.3, duty: 0.5, decay: true, ...extra,
});

// Two 2-bar loops; the bar count keeps each file small (~140 KB).
const songs: Record<string, Song> = {
  // Bright C major, 150 bpm.
  "music-overworld": {
    bpm: 150,
    tracks: [
      {
        wave: "square", duty: 0.25, volume: 0.18,
        steps: "E5 - G5 - C6 - G5 - E5 - D5 - C5 - - - D5 - F5 - A5 - F5 - D5 - C5 - B4 - G4 -",
      },
      {
        wave: "triangle", volume: 0.35,
        steps: "C3 - . C3 G2 - . G2 C3 - . C3 G2 - . G2 F2 - . F2 C3 - . C3 G2 - . G2 G2 - B2 -",
      },
      {
        wave: "noise", volume: 0.12,
        steps: "x . . . x . x . x . . . x . x . x . . . x . x . x . . . x . x x",
      },
    ],
  },
  // Moody A minor arpeggios, 120 bpm.
  "music-cave": {
    bpm: 120,
    tracks: [
      {
        wave: "square", duty: 0.125, volume: 0.14,
        steps: "A4 C5 E5 C5 A4 C5 E5 C5 A4 C5 E5 C5 A4 C5 E5 C5 F4 A4 C5 A4 F4 A4 C5 A4 G4 B4 D5 B4 E4 G#4 B4 G#4",
      },
      {
        wave: "triangle", volume: 0.4,
        steps: "A2 - - - - - - - A2 - - - - - - - F2 - - - - - - - G2 - - - E2 - - -",
      },
      {
        wave: "noise", volume: 0.08,
        steps: "x . . . . . . . x . . . . . . . x . . . . . . . x . . . x . x .",
      },
    ],
  },
};

const effects: Record<string, Float64Array> = {
  "sfx-jump": sfx([0, sq(300, 0.18, { to: 900, duty: 0.25 })]),
  "sfx-coin": sfx([0, sq(988, 0.07, { decay: false })], [0.07, sq(1319, 0.3)]),
  "sfx-hit": sfx(
    [0, { wave: "noise", from: 4000, to: 1000, seconds: 0.22, volume: 0.35, decay: true }],
    [0, sq(400, 0.15, { to: 80 })],
  ),
  "sfx-select": sfx([0, sq(880, 0.05, { duty: 0.25 })]),
  "sfx-confirm": sfx([0, sq(660, 0.06, { duty: 0.25, decay: false })], [0.06, sq(990, 0.14, { duty: 0.25 })]),
};

/** Every generated file: path under motion/ → contents. */
export const build = (): Map<string, string | Buffer> => {
  const files = new Map<string, string | Buffer>();
  for (const [name, a] of Object.entries(art)) files.set(`public/sprites/${name}.svg`, `${sheetSvg(a, brand.colors.palette)}\n`);
  for (const [name, s] of Object.entries(songs)) files.set(`public/audio/${name}.wav`, wav(song(s)));
  for (const [name, b] of Object.entries(effects)) files.set(`public/audio/${name}.wav`, wav(b));
  return files;
};

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  for (const [path, data] of build()) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), data);
    console.log(path, data.length);
  }
}
