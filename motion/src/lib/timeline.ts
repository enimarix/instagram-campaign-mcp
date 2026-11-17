// Script timeline: script lines (+ voice timings, or estimates when there is no voice) →
// scenes in frames. Pure (no imports) so `node --test` runs it directly (test/timeline.test.ts).
// Convention: lines[0] is the hook. It is on screen from frame 0 (HookCard), the other lines
// are captions (Captions).

/** Cover frame (Reel `thumb_offset`): ~0.4 s at 30 fps, the hook card is fully drawn by then. */
export const HOOK_FRAME = 12;
/** Estimated reading speed without a voice, in characters per second. */
export const READ_CHARS_PER_S = 15;
/** Shortest estimated line, in seconds. */
export const MIN_LINE_S = 1.2;
/** Estimated pause after each line, in seconds. */
export const LINE_GAP_S = 0.3;
/** Shortest outro when `loop` is on: the frames that fade back into frame 0. */
export const MIN_LOOP_S = 0.5;

/** Voice timing of one script line (TTS, step 036), seconds from the start of the video. */
export type Timing = { text?: string; start_s: number; end_s: number };

/** One script line on screen from startFrame (inclusive) to endFrame (exclusive). */
export type Scene = { index: number; text: string; startFrame: number; endFrame: number };

export type Timeline = {
  scenes: Scene[];
  /** Frames from the end of the last scene to the end: end card, or the fade back when looping. */
  outroStart: number;
  totalFrames: number;
  hookFrame: number;
  loop: boolean;
};

export type TimelineInput = {
  lines: string[];
  /** One per line; none = estimated from the text length. */
  timings?: Timing[];
  fps: number;
  /** Shortest hook scene (estimated timings only: a voice keeps its own pace). */
  hookSeconds: number;
  outroSeconds: number;
  loop: boolean;
};

const chars = (s: string) => Array.from(s).length;

export const buildTimeline = ({ lines, timings, fps, hookSeconds, outroSeconds, loop }: TimelineInput): Timeline => {
  if (!lines.length) throw new Error("timeline: at least one line (the hook) is needed");
  const at = (s: number) => Math.round(s * fps);
  let starts: number[];
  let end: number;
  if (timings) {
    if (timings.length !== lines.length) {
      throw new Error(`timeline: ${timings.length} timings for ${lines.length} lines`);
    }
    timings.forEach((t, i) => {
      if (!(t.start_s >= 0 && t.end_s >= t.start_s) || (i && t.start_s < timings[i - 1].start_s)) {
        throw new Error(`timeline: timing ${i} (${t.start_s}-${t.end_s} s) is out of order`);
      }
    });
    // The hook shows from frame 0 even when the voice starts a little later.
    starts = timings.map((t, i) => (i ? at(t.start_s) : 0));
    // A caption stays up until the next line starts (no flicker in pauses).
    end = Math.max(at(timings[timings.length - 1].end_s), starts[starts.length - 1] + 1);
  } else {
    let t = 0;
    starts = lines.map((line, i) => {
      const start = at(t);
      const read = Math.max(MIN_LINE_S, chars(line) / READ_CHARS_PER_S, i ? 0 : hookSeconds);
      t += read + LINE_GAP_S;
      return start;
    });
    end = at(t);
  }
  const scenes = lines.map((text, index) => ({
    index,
    text,
    startFrame: starts[index],
    endFrame: index + 1 < lines.length ? starts[index + 1] : end,
  }));
  const outro = at(loop ? Math.max(outroSeconds, MIN_LOOP_S) : outroSeconds);
  return { scenes, outroStart: end, totalFrames: end + outro, hookFrame: Math.min(HOOK_FRAME, fps - 1), loop };
};

/** The scene on screen at `frame`, if any (none during the outro). */
export const sceneAt = (scenes: Scene[], frame: number): Scene | undefined =>
  scenes.find((s) => frame >= s.startFrame && frame < s.endFrame);

/**
 * Opacity of frame 0's picture laid over the outro when looping: 0 before the outro, then rising
 * in `steps` hard steps to 1 on the last frame, so the replay starts where the video ended.
 */
export const loopFade = (frame: number, t: Timeline, steps = 4): number => {
  if (!t.loop || frame < t.outroStart) return 0;
  const p = Math.min(1, (frame - t.outroStart + 1) / (t.totalFrames - t.outroStart));
  return Math.floor(p * steps) / steps;
};
