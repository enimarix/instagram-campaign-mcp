// Builds our own (code-generated) assets into public/: sprite sheets from src/lib/sprites.ts as
// SVG, chiptune loops and sound effects from a tiny square/triangle/noise synth as WAV, and a
// warmer marimba bed (step 130) and the paper style's kalimba / glockenspiel bed (step 131)
// from the same synth's sine-based voices.
// Run: `node scripts/make-assets.ts` (from motion/), then commit the files it writes.
// Deterministic (no Math.random, no Math.sin: `sine` below is plain arithmetic): test/assets-licenses.test.ts checks the
// committed files still match this script, so re-run it after editing art, songs or the palette.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { palette } from "../src/lib/palette.ts";
import { seeded, sheetSvg } from "../src/lib/game.ts";
import * as art from "../src/lib/sprites.ts";

const RATE = 22050; // Hz, mono 16-bit: plenty for square waves, half the size of 44.1 kHz

/**
 * marimba: sine + a fast-fading 4th partial, struck; kalimba: sine + a short metallic 5.4x
 * partial and a soft octave (the owner's paper_audio.js); glock: sine + a bright 2.76x bell
 * partial, long ring; bass: soft sine; kick: falling sine thump.
 */
type Wave = "square" | "triangle" | "noise" | "marimba" | "kalimba" | "glock" | "bass" | "kick";
const SINE_WAVES: Wave[] = ["marimba", "kalimba", "glock", "bass", "kick"];
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

/** sin(2πx) for x in cycles, Bhaskara I's approximation (error < 0.2 %): same bytes on every platform. */
const sine = (x: number) => {
  const t = x - Math.floor(x);
  const h = t < 0.5 ? t * 2 : t * 2 - 1; // half cycle, 0..1
  const v = (16 * h * (1 - h)) / (5 - 4 * h * (1 - h));
  return t < 0.5 ? v : -v;
};

/** Struck-bar decay: 1 at the hit, about a quarter after `half` × 2 seconds (no Math.exp). */
const strike = (s: number, half: number) => 1 / (1 + s / half) ** 2;

/** Adds `t` to `buf` from sample `start`; the tone ends at silence, so loops stay click-free. */
const addTone = (buf: Float64Array, start: number, t: Tone, seed = 1) => {
  const n = Math.min(Math.round(t.seconds * RATE), buf.length - start);
  const { from, to = from, duty = 0.5 } = t;
  let phase = 0;
  for (let i = 0; i < n; i++) {
    const p = i / n;
    phase += (from + (to - from) * p) / RATE;
    const x = phase % 1;
    const s = i / RATE;
    const ends = Math.min(1, s / ATTACK, (n - i) / RATE / RELEASE);
    if (SINE_WAVES.includes(t.wave)) {
      const v =
        t.wave === "marimba"
          ? sine(phase) * strike(s, 0.22) + 0.22 * sine(phase * 4) * strike(s, 0.03)
          : t.wave === "kalimba"
            ? sine(phase) * strike(s, 0.2) + 0.35 * sine(phase * 5.4) * strike(s, 0.012) + 0.15 * sine(phase * 2) * strike(s, 0.08)
            : t.wave === "glock"
              ? sine(phase) * strike(s, 0.5) + 0.3 * sine(phase * 2.76) * strike(s, 0.04)
              : t.wave === "bass"
                ? sine(phase) * strike(s, 0.6)
                : sine(phase) * (1 - p) ** 2;
      buf[start + i] += v * ends * t.volume;
      continue;
    }
    const v =
      t.wave === "square"
        ? x < duty ? 1 : -1
        : t.wave === "triangle"
          ? 1 - 4 * Math.abs(x - 0.5)
          : seeded(seed, Math.floor(phase)) * 2 - 1;
    const env = t.decay ? Math.min(1, s / ATTACK) * (1 - p) : ends;
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
  // Rounded so a last-bit difference in `**` between platforms cannot change the bytes.
  return Math.round(440 * 2 ** ((midi - 69) / 12) * 100) / 100;
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
      else if (track.wave === "kick") addTone(buf, i * step, { ...tone, from: 150, to: 42, seconds: Math.min(tone.seconds, 0.2) });
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

const mallet = (from: number, seconds: number, volume = 0.3): Tone => ({ wave: "marimba", from, seconds, volume });

// Two 2-bar chiptune loops (the bar count keeps each file small, ~140 KB) and 4-bar marimba, kalimba and lounge beds.
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
  // Warm marimba bed (step 130), F major, 104 bpm, 4 bars: Fmaj7 Am7 Dm7 Bbmaj7, soft
  // sine bass, a light kick and shaker. For the brand styles (voxel, later paper/clean).
  "music-marimba": {
    bpm: 104,
    tracks: [
      {
        wave: "marimba", volume: 0.2,
        steps: [
          "F4 - C5 - A4 - E5 - C5 - A4 - E5 - C5 -",
          "A4 - E5 - C5 - G5 - E5 - C5 - G5 - E5 -",
          "D4 - A4 - F4 - C5 - A4 - F4 - C5 - A4 -",
          "A#3 - F4 - D4 - A4 - F4 - D4 - A4 - C5 -",
        ].join(" "),
      },
      {
        wave: "marimba", volume: 0.14,
        steps: [
          "A5 - - - - - G5 - A5 - C6 - - - - -",
          "E5 - - - - - D5 - E5 - G5 - - - - -",
          "F5 - - - - - E5 - F5 - A5 - - - - -",
          "D5 - - - - - C5 - D5 - F5 - G5 - - -",
        ].join(" "),
      },
      {
        wave: "bass", volume: 0.26,
        steps: [
          "F2 - - - - - - - - - F2 - C3 - - -",
          "A2 - - - - - - - - - A2 - E2 - - -",
          "D2 - - - - - - - - - D2 - A2 - - -",
          "A#1 - - - - - - - - - A#1 - C2 - - -",
        ].join(" "),
      },
      {
        wave: "kick", volume: 0.3,
        steps: "C2 - - - . . . . C2 - - - . . . . ".repeat(4).trim(),
      },
      {
        wave: "noise", volume: 0.05,
        steps: ". . x . . . x . . . x . . . x x ".repeat(4).trim(),
      },
    ],
  },
  // The paper style's bed (step 131), after the owner's paper_audio.js: kalimba arpeggios in
  // 8ths (root, third, fifth, third, octave…), a glockenspiel answer, sine bass, soft kick,
  // a snap on 2 and 4 and light off-beat hats. F major, 100 bpm, 4 bars: F Dm Bb C.
  "music-kalimba": {
    bpm: 100,
    tracks: [
      {
        wave: "kalimba", volume: 0.2,
        steps: [
          "F5 - A5 - C6 - A5 - F6 - C6 - A5 - C6 -",
          "D5 - F5 - A5 - F5 - D6 - A5 - F5 - A5 -",
          "A#4 - D5 - F5 - D5 - A#5 - F5 - D5 - F5 -",
          "C5 - E5 - G5 - E5 - C6 - G5 - E5 - G5 -",
        ].join(" "),
      },
      {
        wave: "glock", volume: 0.09,
        steps: [
          ". . . . . . . . A6 - - - G6 - F6 -",
          ". . . . . . . . F6 - - - - - - -",
          ". . . . . . . . D6 - - - F6 - A6 -",
          ". . . . . . . . G6 - - - E6 - - -",
        ].join(" "),
      },
      {
        wave: "bass", volume: 0.26,
        steps: [
          "F2 - - - - - F2 - C3 - - - F2 - - -",
          "D2 - - - - - D2 - A2 - - - D2 - - -",
          "A#1 - - - - - A#1 - F2 - - - A#1 - - -",
          "C2 - - - - - C2 - G2 - - - C2 - - -",
        ].join(" "),
      },
      {
        wave: "kick", volume: 0.3,
        steps: "C2 - - - C2 - - - C2 - - - C2 - - - ".repeat(4).trim(),
      },
      {
        wave: "noise", volume: 0.07,
        steps: ". . . . x . . . . . . . x . . . ".repeat(4).trim(),
      },
      {
        wave: "noise", volume: 0.025,
        steps: ". . x . . . x . . . x . . . x . ".repeat(4).trim(),
      },
    ],
  },
  // The blender style's bed: a warm, slow "cutscene at the dinner table" loop. Soft marimba
  // arpeggios over Gmaj7 Em7 Cmaj7 D7, a sparse glockenspiel answer, sine bass, a light kick
  // and shaker. G major, 84 bpm, 4 bars.
  "music-lounge": {
    bpm: 84,
    tracks: [
      {
        wave: "marimba", volume: 0.16,
        steps: [
          "G3 - B3 - D4 - F#4 - B4 - F#4 - D4 - B3 -",
          "E3 - G3 - B3 - D4 - G4 - D4 - B3 - G3 -",
          "C3 - E3 - G3 - B3 - E4 - B3 - G3 - E3 -",
          "D3 - F#3 - A3 - C4 - F#4 - C4 - A3 - F#3 -",
        ].join(" "),
      },
      {
        wave: "glock", volume: 0.07,
        steps: [
          ". . . . . . . . B5 - - - A5 - - -",
          ". . . . . . . . G5 - - - - - - -",
          ". . . . . . . . E5 - - - G5 - - -",
          ". . . . . . . . F#5 - - - - - A5 -",
        ].join(" "),
      },
      {
        wave: "bass", volume: 0.24,
        steps: [
          "G2 - - - - - - - D2 - - - - - - -",
          "E2 - - - - - - - B1 - - - - - - -",
          "C2 - - - - - - - G1 - - - - - - -",
          "D2 - - - - - - - A1 - - - - - - -",
        ].join(" "),
      },
      {
        wave: "kick", volume: 0.18,
        steps: "C2 - - - . . . . C2 - - - . . . . ".repeat(4).trim(),
      },
      {
        wave: "noise", volume: 0.03,
        steps: ". . x . . . x . . . x . . . x . ".repeat(4).trim(),
      },
    ],
  },
  // The cutaway style's bed (step 142): a dusk synth loop under the pixel explainers. Triangle
  // arpeggios over Dm9 Bbmaj7 Gm7 A7, a thin square lead, sine bass, a light kick and hat.
  // D minor, 92 bpm, 4 bars.
  "music-dusk": {
    bpm: 92,
    tracks: [
      {
        wave: "triangle", volume: 0.16,
        steps: [
          "D4 F4 A4 C5 E5 C5 A4 F4 D4 F4 A4 C5 E5 C5 A4 F4",
          "A#3 D4 F4 A4 C5 A4 F4 D4 A#3 D4 F4 A4 C5 A4 F4 D4",
          "G3 A#3 D4 F4 A4 F4 D4 A#3 G3 A#3 D4 F4 A4 F4 D4 A#3",
          "A3 C#4 E4 G4 A4 G4 E4 C#4 A3 C#4 E4 G4 A4 G4 E4 C#4",
        ].join(" "),
      },
      {
        wave: "square", duty: 0.125, volume: 0.06,
        steps: [
          "A5 - - - - - - - G5 - - - F5 - - -",
          "F5 - - - - - - - D5 - - - E5 - - -",
          "D5 - - - - - - - . . . . A#4 - - -",
          "C#5 - - - - - - - E5 - - - - - - -",
        ].join(" "),
      },
      {
        wave: "bass", volume: 0.26,
        steps: [
          "D2 - - - - - - - D2 - - - - - - -",
          "A#1 - - - - - - - A#1 - - - - - - -",
          "G1 - - - - - - - G1 - - - - - - -",
          "A1 - - - - - - - A1 - - - - - - -",
        ].join(" "),
      },
      {
        wave: "kick", volume: 0.18,
        steps: "C2 - . . . . . . C2 - . . . . . . ".repeat(4).trim(),
      },
      {
        wave: "noise", volume: 0.03,
        steps: ". . x . . . x . . . x . . . x . ".repeat(4).trim(),
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
  // Soft brand sounds (step 130): a wooden pop, and a rising marimba chime for a level-up.
  "sfx-pop": sfx([0, { wave: "kick", from: 900, to: 300, seconds: 0.09, volume: 0.45 }], [0, mallet(1397, 0.25, 0.2)]),
  // Paper sounds (step 131): a sheet torn (crackly noise, falling rate) and a sheet swished past.
  "sfx-rip": sfx(
    [0, { wave: "noise", from: 2600, to: 500, seconds: 0.5, volume: 0.32, decay: true }],
    [0.05, { wave: "noise", from: 300, to: 120, seconds: 0.4, volume: 0.18, decay: true }],
  ),
  "sfx-swish": sfx([0, { wave: "noise", from: 1200, to: 5000, seconds: 0.18, volume: 0.1 }], [0.18, { wave: "noise", from: 5000, to: 1500, seconds: 0.22, volume: 0.12, decay: true }]),
  "sfx-chime": sfx([0, mallet(698.46, 0.9)], [0.08, mallet(880, 0.9)], [0.16, mallet(1046.5, 0.9)], [0.24, mallet(1396.91, 1.1)]),
};

/** Every generated file: path under motion/ → contents. */
export const build = (): Map<string, string | Buffer> => {
  const files = new Map<string, string | Buffer>();
  for (const [name, a] of Object.entries(art)) files.set(`public/sprites/${name}.svg`, `${sheetSvg(a, palette)}\n`);
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
