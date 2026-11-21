// Music ducking (step 148): the bed steps down while the voice speaks, so the voice sits clearly
// on top after the studio's -14 LUFS loudnorm, and comes back up in the gaps. Pure functions
// (no imports), used by components/MusicBed.tsx and components/Sfx.tsx (the sound effects'
// levels, step 159), unit-tested in test/duck.test.ts and test/sfx.test.ts.

export type Span = { start_s: number; end_s: number };

// Levels against the bed alone (no voice): measured on the conteur_grave voice (about -29 LUFS)
// over the step-148 beds (about -18 LUFS at the file, x0.25 in MusicBed): the voice ends ~15 LU
// above the bed while it speaks, ~7 LU in the gaps (report in the step-148 PR).
/** The bed's level while a line is spoken. */
export const DUCK_DB = -15;
/** The bed's level between lines of a voiced video (a voice-over sits a little forward). */
export const GAP_DB = -5;
/** Down-ramp, finished as the line starts (the bed makes room before the first word). */
export const ATTACK_S = 0.2;
/** Up-ramp after the line ends. */
export const RELEASE_S = 0.25;
/** Gaps between lines shorter than this stay ducked (no pumping between sentences). */
export const HOLD_S = 0.6;

/** The voice's line timings when the voice is actually heard (a voice with audio), else none. */
export const spokenLines = (voice?: { audioSrc?: string; lines?: Span[] }) => (voice?.audioSrc ? voice.lines : undefined);

/** Speech spans, sorted, with the gaps shorter than HOLD_S bridged. */
export const speechSpans = (lines: readonly Span[]): Span[] => {
  const out: Span[] = [];
  for (const l of [...lines].filter((l) => l.end_s > l.start_s).sort((a, b) => a.start_s - b.start_s)) {
    const last = out[out.length - 1];
    if (last && l.start_s - last.end_s < HOLD_S) last.end_s = Math.max(last.end_s, l.end_s);
    else out.push({ ...l });
  }
  return out;
};

const smooth = (x: number) => {
  const t = Math.min(1, Math.max(0, x));
  return t * t * (3 - 2 * t);
};

/**
 * Bed gain (linear) at `t` seconds for `spans` from speechSpans(): 1 without spans (no voice),
 * else GAP_DB between lines and DUCK_DB while one is spoken, an S-curve in dB over ATTACK_S
 * before it and RELEASE_S after it.
 */
export const duckGain = (spans: readonly Span[], t: number): number =>
  spans.length ? 10 ** ((GAP_DB + (DUCK_DB - GAP_DB) * speechDepth(spans, t)) / 20) : 1;

/** How far into a spoken line `t` is: 0 in the gaps, 1 while a line plays, the S-curve ramps between. */
export const speechDepth = (spans: readonly Span[], t: number): number => {
  let depth = 0;
  for (const s of spans) {
    const down = (t - (s.start_s - ATTACK_S)) / ATTACK_S;
    const up = (s.end_s + RELEASE_S - t) / RELEASE_S;
    depth = Math.max(depth, smooth(Math.min(down, up)));
  }
  return depth;
};

/**
 * Integrated loudness (LUFS, ffmpeg ebur128) of every music bed in motion/public/audio. The
 * levels above were set on the step-148 beds (about -17 LUFS); the 8-bit loops are about 4 LU
 * louder and buried the voice (10 LU over the bed, step 159), so a bed louder than BED_LUFS
 * comes down to it. A quieter bed is left as it is (the soft beds were chosen by ear).
 */
export const MUSIC_LUFS = {
  "music-overworld": -13.1,
  "music-cave": -13.4,
  "music-marimba": -19.7,
  "music-kalimba": -19.2,
  "music-lounge": -23.5,
  "music-dusk": -19.4,
  "music-cutaway-a": -17.8,
  "music-cutaway-b": -16.9,
  "music-cutaway-c": -17.1,
  "music-nocturne": -23.9,
} as const;
export const BED_LUFS = -17;
/** Gain that brings bed `id` down to BED_LUFS when it is louder (1 otherwise). */
export const bedLevel = (id: keyof typeof MUSIC_LUFS) => Math.min(1, 10 ** ((BED_LUFS - MUSIC_LUFS[id]) / 20));

// Sound effects (steps 158-159): every sound is set against the voice from its measured peak,
// never by a hand-set file volume (a coin at full volume peaked 21 LU over the speech once the
// studio's -14 LUFS finish lifted the quiet voice).

/**
 * Peak momentary loudness (LUFS, ffmpeg ebur128 over the whole sound) of every sound effect in
 * motion/public/audio (mono). A new sound is measured before it is played (test/sfx.test.ts).
 */
export const SFX_PEAK_LUFS = {
  "sfx-pop": -20.9,
  "sfx-select": -24.6,
  "sfx-confirm": -16.7,
  "sfx-coin": -13.2,
  "sfx-chime": -15.2,
  "sfx-hit": -17.3,
  "sfx-jump": -19.7,
  "sfx-rip": -18.1,
  "sfx-swish": -25.7,
  "sfx-thunder": -17.9,
} as const;
export type SfxId = keyof typeof SFX_PEAK_LUFS;
/**
 * A library sound (step 150): `ov:<Openverse id>`, a real recording the studio cached
 * (src/studio/sfx.py) with its loudest moment set to LIBRARY_PEAK_LUFS (or under it), so it
 * plays from that peak like the sounds above. The render copies its file into the bundle.
 */
export type LibrarySfx = `ov:${string}`;
export const LIBRARY_SFX = /^ov:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const LIBRARY_PEAK_LUFS = -20; // = PEAK_LUFS in src/studio/sfx.py (tests check both)
/** Any sound a template plays: a synthesized one or a library one. */
export type AnySfx = SfxId | LibrarySfx;
export const isLibrarySfx = (id: string): id is LibrarySfx => LIBRARY_SFX.test(id);
const peakOf = (id: AnySfx) => (isLibrarySfx(id) ? LIBRARY_PEAK_LUFS : SFX_PEAK_LUFS[id]);
/**
 * The level sounds are set against: the quietest approved voice's own (conteur_grave, about
 * -29 LUFS integrated in a template's mix); a louder voice leaves every sound further under it.
 */
export const VOICE_LUFS = -29;
/** A body sound peaks this far further down while a line is spoken (in the gaps: its own level). */
export const SPEECH_SFX_DB = -12;
/** A planned « BANG » beat stays this close under a spoken line (it is the beat's point). */
export const BANG_SPEECH_DB = -6;

/** Volume that puts sound `id`'s peak `db` from VOICE_LUFS (0 = at the voice's level), never past full. */
export const sfxVolume = (id: AnySfx, db = 0) => Math.min(1, 10 ** ((VOICE_LUFS + db - peakOf(id)) / 20));

/**
 * A body sound's volume at `t` seconds: sfxVolume(id, db) in the gaps, `speech` dB lower while a
 * line of `spans` (speechSpans()) is spoken, with the bed's ramps.
 */
export const sfxGain = (spans: readonly Span[], id: AnySfx, t: number, db = 0, speech = SPEECH_SFX_DB) =>
  sfxVolume(id, db + speech * speechDepth(spans, t));

/**
 * Voice line timings (audio time) on the video's clock when the template pauses the voice:
 * each pause holds the voice `frames` frames from plain (unpaused) frame `at`, as
 * PixelSkit's voiceParts and QuizChest's countdown do.
 */
export const pausedLines = <L extends Span>(lines: readonly L[], pauses: readonly { at: number; frames: number }[], fps: number): L[] => {
  const shift = (s: number) => s + pauses.reduce((n, p) => n + (p.at <= Math.round(s * fps) ? p.frames : 0), 0) / fps;
  return lines.map((l) => ({ ...l, start_s: shift(l.start_s), end_s: shift(l.end_s) }));
};
