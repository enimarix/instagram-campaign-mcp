// PixelCinema direction (step 143): when things land inside each scene, where the camera and
// the beam go, when the lightning strikes. Frames from the scene's start unless named
// otherwise. Pure, so `node --test` checks it (test/pixelcinema.test.ts).
import { CELL, type Camera, toScreen } from "../../cinema/pixel.ts";
import { type AnchorId, SETS, type Shot, viewOf } from "../../cinema/scenes.ts";
import { ATTACK_S, duckGain, GAP_DB, RELEASE_S, type Span } from "../../lib/duck.ts";
import { easeInOut, easeOut, span } from "../../voxel/anim.ts";
import type { Timeline } from "../../lib/timeline.ts";
import { plain, type PixelCinemaProps } from "./schema.ts";

const chars = (s: string) => Array.from(s).length;

/** Hook: when the red bar strikes the belief through, and when the real line lands (-1 / 0 without a strike). */
export const hookTimes = (p: PixelCinemaProps, len: number, fps: number) => {
  if (!p.hook.strike) return { strike: -1, line: 0 };
  // Struck as the voice finishes reading it (its share of the hook's characters), 0.6-1.6 s.
  const share = chars(p.hook.strike) / (chars(p.hook.strike) + chars(plain(p.hook.line)));
  const strike = Math.min(Math.round(1.6 * fps), Math.max(Math.round(0.6 * fps), Math.round(len * share) - Math.round(0.2 * fps)));
  return { strike, line: strike + Math.round(0.3 * fps) };
};

/** The Reel cover: once the real line has landed. */
export const coverOf = (p: PixelCinemaProps, t: Timeline, fps: number) => {
  const hook = t.scenes[0];
  return hookTimes(p, hook.endFrame - hook.startFrame, fps).line + Math.round(0.4 * fps);
};

/**
 * Sound effects under the voice (owner, round 3c): full in the gaps, down by the bed's duck depth
 * (DUCK_DB - GAP_DB) while a line is spoken, with the bed's ramps. `spans` from speechSpans().
 */
export const sfxGain = (spans: readonly Span[], t: number) => Math.min(1, duckGain(spans, t) / 10 ** (GAP_DB / 20));

/** The thunder rolls in after its lightning at `t` (s): moved to the first gap if a line is spoken then. */
export const thunderAt = (spans: readonly Span[], t: number) => {
  const s = spans.find((s) => t > s.start_s - ATTACK_S && t < s.end_s + RELEASE_S);
  return s ? s.end_s + RELEASE_S : t;
};

/** A chip beat: the heading (when new) lands first, then the chip pops, then its leader line draws. */
export const chipTimes = (fps: number) => ({ title: 0, chip: Math.round(0.3 * fps), leader: Math.round(0.45 * fps), leaderLen: Math.round(0.35 * fps) });

/** The lightning in a beat of `len` frames: white frames at `at`, the silhouette until `until`. */
export const flashTimes = (len: number, fps: number) => ({ at: Math.round(0.2 * fps), white: 2, until: Math.round(len * 0.8) });

/** The lightning at `frame`: `white` (0..1, the flash itself), then `silhouette` (the white / black set). */
export const flashAt = (p: PixelCinemaProps, t: Timeline, frame: number, fps: number) => {
  const i = sceneIndex(t, p.beats.length + 1, frame);
  const b = i ? p.beats[i - 1] : null;
  if (b?.kind !== "chip" || !b.flash) return { white: 0, silhouette: false };
  const s = t.scenes[i];
  const f = frame - s.startFrame;
  const ft = flashTimes(s.endFrame - s.startFrame, fps);
  if (f >= ft.at && f < ft.at + ft.white) return { white: f === ft.at ? 1 : 0.7, silhouette: false };
  return { white: 0, silhouette: f >= ft.at + ft.white && f < ft.until };
};

/** Stat / app beats: the title, then the number counts up (or the card floats in). */
export const payoffTimes = (fps: number) => ({ title: 0, value: Math.round(0.35 * fps), count: Math.round(0.9 * fps) });

/** Index of the scene on screen at `frame` (0 = hook) among `n` scenes. */
export const sceneIndex = (t: Timeline, n: number, frame: number) => Math.max(0, ...t.scenes.slice(0, n).map((s, i) => (frame >= s.startFrame ? i : 0)));

/** A scene longer than this is cut into two shots halfway (no slow beats). */
export const SPLIT_S = 4;

/** A shot on screen from frame `start` (inclusive) to `end` (exclusive). */
export type Segment = { start: number; end: number; shot: Shot };

/**
 * The film's shots: the set's list in order, looping, one per scene and two for a scene longer
 * than SPLIT_S; the lightning beat takes the set's flash shot (unless its view was just on
 * screen) without using up a list shot. Never the same view twice in a row.
 */
export const segmentsOf = (p: PixelCinemaProps, t: Timeline, fps: number): Segment[] => {
  const { shots, flash } = SETS[p.scene];
  const out: Segment[] = [];
  let next = 0;
  const take = (avoid?: string) => {
    let s = shots[next++ % shots.length];
    if (s.view === avoid) s = shots[next++ % shots.length];
    return s;
  };
  for (let i = 0; i <= p.beats.length; i++) {
    const { startFrame: start, endFrame: end } = t.scenes[i];
    const b = i ? p.beats[i - 1] : null;
    const prev = out[out.length - 1]?.shot.view;
    if (b?.kind === "chip" && b.flash) {
      out.push({ start, end, shot: prev !== flash.view ? flash : take(prev) });
      continue;
    }
    const first = take(prev);
    if (end - start <= SPLIT_S * fps) {
      out.push({ start, end, shot: first });
      continue;
    }
    const mid = start + Math.round((end - start) / 2);
    out.push({ start, end: mid, shot: first }, { start: mid, end, shot: take(first.view) });
  }
  return out;
};

/** How far the camera has moved through a shot of `len` frames: most of it in the first second, then on to the end. */
export const moveAt = (f: number, len: number, fps: number) => 0.55 * easeOut(span(f, 0, fps)) + 0.45 * easeInOut(span(f, 0, len));

/** The view and camera at `frame`: its shot, moving from its first key to its second; a small cut-in on the lightning. */
export const cameraAt = (p: PixelCinemaProps, t: Timeline, frame: number, fps: number): { view: string; cam: Camera } => {
  const segs = segmentsOf(p, t, fps);
  const seg = segs.find((s) => frame < s.end) ?? segs[segs.length - 1];
  const { view, from, to } = seg.shot;
  const k = moveAt(frame - seg.start, Math.max(1, seg.end - seg.start), fps);
  const flash = flashAt(p, t, frame, fps);
  const zoom = from[0] + (to[0] - from[0]) * k + (flash.white || flash.silhouette ? 0.06 : 0);
  return { view, cam: { zoom, fx: from[1] + (to[1] - from[1]) * k, fy: from[2] + (to[2] - from[2]) * k, dx: Math.sin(frame / fps / 2) * 0.8, dy: 0 } };
};

/**
 * The beam at `frame`: power (dim on the belief, full once the real line lands) and sweep:
 * on the hook it swings into place, on each chip it sweeps across to the other side, before
 * the lightning it sweeps wide.
 */
export const beamOf = (p: PixelCinemaProps, t: Timeline, frame: number, fps: number) => {
  const i = sceneIndex(t, p.beats.length + 1, frame);
  const s = t.scenes[i];
  const at = frame - s.startFrame;
  if (i === 0) {
    const on = easeOut(span(at, hookTimes(p, s.endFrame - s.startFrame, fps).line, Math.round(0.6 * fps)));
    return { power: 0.3 + 0.7 * on, sweep: -0.5 * (1 - on) };
  }
  const b = p.beats[i - 1];
  if (b.kind !== "chip") return { power: 0.75, sweep: 0.08 * Math.sin(at / fps) };
  const k = p.beats.slice(0, i - 1).filter((x) => x.kind === "chip").length;
  const side = k % 2 ? 1 : -1;
  const wide = b.flash ? 0.45 : 0.22;
  const move = easeInOut(span(at, 0, Math.round(0.9 * fps)));
  const breathe = Math.sin(Math.PI * span(at, chipTimes(fps).chip, Math.round(0.5 * fps)));
  return { power: (b.point === "light" ? 1.1 : 0.95) + 0.15 * breathe, sweep: side * wide * (1 - 2 * move) };
};

/** Fridge door: opens as the hook's real line lands (not before 0.8 s: the cover shows it closed). */
export const openOf = (p: PixelCinemaProps, t: Timeline, frame: number, fps: number) => {
  const hook = t.scenes[0];
  const at = Math.max(hookTimes(p, hook.endFrame - hook.startFrame, fps).line, Math.round(0.8 * fps));
  return easeOut(span(frame, at, Math.round(0.7 * fps)));
};

/** Screen position (px) of anchor `a` of view `view` under camera `cam`, `t` seconds in, kept inside the frame. */
export const anchorPx = (p: PixelCinemaProps, view: string, a: AnchorId, cam: Camera, t: number): [number, number] => {
  const [x, y, depth] = viewOf(p.scene, view).anchors(t)[a];
  const [sx, sy] = toScreen(cam, x, y, depth);
  return [Math.min(1040, Math.max(40, sx * CELL)), Math.min(1880, Math.max(40, sy * CELL))];
};
