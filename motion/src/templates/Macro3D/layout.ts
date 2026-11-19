// Macro3D direction (step 154): the shot list Blender renders (a hard cut every 1-3 s, never the
// same move twice in a row), Marco's pose at each frame, the cover. Pure, so `node --test`
// checks it (test/macro3d.test.ts) and schemas.mjs hands the shots to Python (`plates`).
import type { Timeline, Timing } from "../../lib/timeline.ts";
import { chunksOf, keyIndexes, wordTimes } from "../../macro3d/words.ts";
import { type Pose, poseFor, reactionTo } from "../../macro3d/poses.ts";
import type { Look, Move, Subject } from "../../macro3d/subjects.ts";
import type { Macro3DProps } from "./schema.ts";

/** A shot is about this long; a scene gets as many as fit (1-3), so cuts land every 1-3 s. */
export const SHOT_S = 2.1;

/** One Blender shot on screen from frame `start` (inclusive) to `end` (exclusive), scene `scene`. */
export type Shot = { start: number; end: number; scene: number; subject: Subject; move: Move; look: Look; seed: number; text?: string };

/** The moves picked in turn when a scene names none (the hook opens on a push in). */
const AUTO: Move[] = ["orbit", "slide", "rise", "push", "pull", "orbit", "top", "slide"];

const seedOf = (...parts: (string | number)[]) => {
  let h = 2166136261;
  for (const ch of parts.join("/")) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return (h >>> 0) % 1000;
};

/** The number a counter shows at `k` (0..1 of the way), with its decimals. */
export const counterText = (c: { from: number; to: number; decimals: number }, k: number) => {
  const v = c.from + (c.to - c.from) * Math.min(1, Math.max(0, k));
  return v.toFixed(c.decimals).replace(".", ",");
};

/** Every shot from frame 0 to the end card (`endStart`), scene by scene. */
export const shotsOf = (p: Macro3DProps, t: Timeline, endStart: number, fps: number): Shot[] => {
  const out: Shot[] = [];
  let next = 0;
  p.scenes.forEach((s, i) => {
    const start = t.scenes[i].startFrame;
    const end = i + 1 < p.scenes.length ? t.scenes[i + 1].startFrame : endStart;
    const n = Math.max(s.cut ? 2 : 1, Math.min(3, Math.round((end - start) / (SHOT_S * fps))));
    for (let j = 0; j < n; j++) {
      const subject = s.cut && j >= n / 2 ? s.cut : s.subject;
      let move = s.moves ? s.moves[j % s.moves.length] : i === 0 && j === 0 ? "push" : AUTO[next++ % AUTO.length];
      const prev = out[out.length - 1];
      if (!s.moves && prev && prev.move === move) move = AUTO[next++ % AUTO.length];
      const text = subject === "scale" && s.counter ? counterText(s.counter, 1) : undefined;
      out.push({
        start: start + Math.round(((end - start) * j) / n),
        end: start + Math.round(((end - start) * (j + 1)) / n),
        scene: i,
        subject,
        move,
        look: s.look,
        seed: seedOf(i, j, subject, move),
        ...(text ? { text } : {}),
      });
    }
  });
  return out.filter((s) => s.end > s.start);
};

/** The shot on screen at `frame` (the last one past the end). */
export const shotAt = (shots: readonly Shot[], frame: number) => shots.find((s) => frame < s.end) ?? shots[shots.length - 1];

/** Marco's pose at `frame`: the scene's (given or read from its line), a reaction on its second shot. */
export const poseAt = (p: Macro3DProps, shots: readonly Shot[], frame: number): { pose: Pose; since: number } => {
  const shot = shotAt(shots, frame);
  const i = shot.scene;
  const s = p.scenes[i];
  const first = s.pose ?? poseFor(s.line, i);
  const sceneShots = shots.filter((x) => x.scene === i);
  const k = sceneShots.indexOf(shot);
  if (k <= 0 || s.pose) return { pose: first, since: sceneShots[0].start };
  return { pose: reactionTo(first, i), since: sceneShots[Math.min(k, 1)].start };
};

/** The Reel cover: once the hook's key word is boxed, else its first caption chunk said in full (0.6-3 s in). */
export const coverOf = (p: Macro3DProps, timings: readonly Timing[], fps: number) => {
  const words = wordTimes(p.scenes[0].line, timings[0].start_s, timings[0].end_s);
  const key = keyIndexes(words, p.scenes[0].key);
  const at = key.length ? words[key[key.length - 1]].start : words[chunksOf(words, key)[0][1] - 1].start;
  return Math.round(Math.min(3, Math.max(0.6, at + 0.3)) * fps);
};
