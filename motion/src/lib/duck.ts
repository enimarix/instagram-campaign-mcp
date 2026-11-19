// Music ducking (step 148): the bed steps down while the voice speaks, so the voice sits clearly
// on top after the studio's -14 LUFS loudnorm, and comes back up in the gaps. Pure functions
// (no imports), used by components/MusicBed.tsx and unit-tested in test/duck.test.ts.

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
export const duckGain = (spans: readonly Span[], t: number): number => {
  if (!spans.length) return 1;
  let depth = 0;
  for (const s of spans) {
    const down = (t - (s.start_s - ATTACK_S)) / ATTACK_S;
    const up = (s.end_s + RELEASE_S - t) / RELEASE_S;
    depth = Math.max(depth, smooth(Math.min(down, up)));
  }
  return 10 ** ((GAP_DB + (DUCK_DB - GAP_DB) * depth) / 20);
};

/**
 * Voice line timings (audio time) on the video's clock when the template pauses the voice:
 * each pause holds the voice `frames` frames from plain (unpaused) frame `at`, as
 * PixelSkit's voiceParts and QuizChest's countdown do.
 */
export const pausedLines = <L extends Span>(lines: readonly L[], pauses: readonly { at: number; frames: number }[], fps: number): L[] => {
  const shift = (s: number) => s + pauses.reduce((n, p) => n + (p.at <= Math.round(s * fps) ? p.frames : 0), 0) / fps;
  return lines.map((l) => ({ ...l, start_s: shift(l.start_s), end_s: shift(l.end_s) }));
};
