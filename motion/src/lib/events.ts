// What happens in a video, second by second (step 110): the events `schemas.mjs --validate`
// returns next to the duration. Python (src/studio/motion.py) rounds, quotes, sorts and caps
// them into `assets.timeline`. Pure (types only) so `node --test` runs it directly.
import type { Timeline } from "./timeline";

/** t = start, d = duration, both in seconds of the final video; e = what; text = on-screen/voice text. */
export type Event = { t: number; d: number; e: string; text?: string };

type Sound = { music?: string; voice?: { audioSrc?: string } };

/**
 * Events of a script timeline: one per scene (`labels[i]`, default "line i") with its text, the
 * voice-over when there is an audio file, the music bed, and the outro (loop fade or end hold).
 */
export const scriptEvents = (t: Timeline, fps: number, labels: string[], p: Sound): Event[] => {
  const s = (frames: number) => frames / fps;
  const events: Event[] = t.scenes.map((x) => ({
    t: s(x.startFrame),
    d: s(x.endFrame - x.startFrame),
    e: labels[x.index] ?? `line ${x.index}`,
    text: x.text,
  }));
  if (p.music && p.music !== "none") events.push({ t: 0, d: s(t.totalFrames), e: `music bed (${p.music})` });
  if (p.voice?.audioSrc) events.push({ t: 0, d: s(t.outroStart), e: "voice-over reads the lines" });
  if (t.totalFrames > t.outroStart) {
    events.push({ t: s(t.outroStart), d: s(t.totalFrames - t.outroStart), e: t.loop ? "loop fade back to the hook" : "end hold" });
  }
  return events;
};
