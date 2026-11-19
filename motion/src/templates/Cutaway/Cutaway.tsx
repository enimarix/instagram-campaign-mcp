// Cutaway (step 142): a pixel-art mechanism explainer, the body as a machine. A hook question in
// a framed pixel box over the mechanism at real speed, 4-6 beats that slow it down (RALENTI
// 1/84 ... 1/2, « ×2 »), zoom in and out, label its parts and step through its cycle, then a
// payoff back at real speed and the HUD's own end card. Dusk palette, dithered sky, everything
// on a P-px grid (src/cutaway/kit.tsx), a game HUD in a 5x7 pixel font (src/cutaway/pixelfont.ts).
import { useMemo } from "react";
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { type AssetId, assetById } from "../../assets";
import { MusicBed } from "../../components/MusicBed";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { BASE, Box, Defs, DitherRect, H, P, px, SkyLayer, STAGE, steps, Tag, tagHeight, Type, typeSize, W } from "../../cutaway/kit";
import { C } from "../../cutaway/palette";
import { chipText, dashesOf, mechanismClock, VIEWS, type ViewId } from "../../cutaway/views";
import type { ViewState } from "../../cutaway/views/common";
import { cycleOf, VIEW_COMPONENTS } from "../../cutaway/views/index";
import { EndCard } from "../../endcards/EndCard";
import { loopFade } from "../../lib/timeline";
import { easeInOut, easeOut, span } from "../../voxel/anim.ts";
import { lerpText, stepsLayout, titleLayout } from "./layout";
import { type CutawayProps, type Resolved, resolveScenes, type SceneProps, scenesOf, timelineOf } from "./schema";

/** Frames of a cut's zoom-through dither; seconds of a camera move, of a speed ramp, of the gauge counting. */
const CUT = 12;
const CAM_S = 0.8;
const RAMP_S = 0.6;
const COUNT_S = 0.7;
const CHIP_Y = 280;
const RIGHT = 960;

/** Everything one frame needs, from the props (memoised once). */
const usePlan = (p: CutawayProps, fps: number) =>
  useMemo(() => {
    const { timeline, endStart } = timelineOf(p, fps);
    const all = scenesOf(p);
    const scenes = timeline.scenes.slice(0, all.length);
    const resolved = resolveScenes(p);
    const clock = mechanismClock(
      scenes.map((s, i) => ({ start: s.startFrame, rate: resolved[i].rate })),
      timeline.totalFrames,
      fps,
      Math.round(RAMP_S * fps),
    );
    return { timeline, endStart, all, scenes, resolved, clock, fps };
  }, [p, fps]);
type Plan = ReturnType<typeof usePlan>;

const stateAt = (plan: Plan, frame: number, view: ViewId, stage: number): ViewState => {
  const f = Math.min(frame, plan.clock.length - 2);
  const hz = VIEWS[view].hz;
  return { phase: plan.clock[f] * hz, stage, rate: (plan.clock[f + 1] - plan.clock[f]) * plan.fps * hz, f: frame };
};

type Cam = { zoom: number; center: readonly [number, number] };
const camOf = (s: SceneProps, view: ViewId, st: ViewState): Cam => ({
  zoom: s.zoom * BASE,
  center: s.focus ? (VIEW_COMPONENTS[view].anchors(st) as Record<string, readonly [number, number]>)[s.focus] : [0, 0],
});
const toScreen = (cam: Cam, [x, y]: readonly [number, number]) => [STAGE[0] + (x - cam.center[0]) * cam.zoom, STAGE[1] + (y - cam.center[1]) * cam.zoom] as const;

/** One picture of the art: sky and a view under a camera, through the pixel grid. */
const Layer = ({ view, sky, st, cam, mask }: { view: ViewId; sky: "dusk" | "night"; st: ViewState; cam: Cam; mask?: string }) => {
  const { Draw } = VIEW_COMPONENTS[view];
  const tx = px(STAGE[0] - cam.center[0] * cam.zoom);
  const ty = px(STAGE[1] - cam.center[1] * cam.zoom);
  return (
    <g mask={mask}>
      <g filter="url(#cw-px)">
        <SkyLayer sky={sky} f={st.f} pan={cam.center[0] * 0.1} />
        <g transform={`translate(${tx} ${ty}) scale(${cam.zoom})`}>
          <Draw {...st} />
        </g>
      </g>
    </g>
  );
};

/** Scene `i`'s own camera and state at `frame` (stage eased over the first 70 %). */
const sceneState = (plan: Plan, i: number, frame: number) => {
  const r = plan.resolved[i];
  const s = plan.scenes[i];
  const len = s.endFrame - s.startFrame;
  const stage = r.stageFrom + (r.stageTo - r.stageFrom) * easeInOut(span(frame - s.startFrame, 0, len * 0.7));
  const st = stateAt(plan, frame, r.view, stage);
  return { r, st, cam: camOf(plan.all[i], r.view, st) };
};

const Art = ({ plan, i, frame, fps }: { plan: Plan; i: number; frame: number; fps: number }) => {
  const { r, st, cam } = sceneState(plan, i, frame);
  const f = frame - plan.scenes[i].startFrame;
  if (i > 0 && !r.cut) {
    // Same view: the camera glides from the last scene's framing.
    const prev = camOf(plan.all[i - 1], r.view, st);
    const t = easeInOut(span(f, 0, CAM_S * fps));
    const zoom = Math.exp(Math.log(prev.zoom) + (Math.log(cam.zoom) - Math.log(prev.zoom)) * t);
    const center = [prev.center[0] + (cam.center[0] - prev.center[0]) * t, prev.center[1] + (cam.center[1] - prev.center[1]) * t] as const;
    return <Layer view={r.view} sky={r.sky} st={st} cam={{ zoom, center }} />;
  }
  if (i > 0 && r.cut && f < CUT) {
    // A cut: the old picture zooms through (in to a deeper view, out to a shallower one) while the new one dithers in.
    const pr = plan.resolved[i - 1];
    const pst = stateAt(plan, frame, pr.view, pr.stageTo);
    const pcam = camOf(plan.all[i - 1], pr.view, pst);
    const t = f / CUT;
    const inward = VIEWS[r.view].depth >= VIEWS[pr.view].depth;
    const e = easeOut(t);
    return (
      <>
        <Layer view={pr.view} sky={pr.sky} st={pst} cam={{ ...pcam, zoom: pcam.zoom * (inward ? 1 + 1.6 * e : 1 - 0.5 * e) }} />
        <Layer view={r.view} sky={r.sky} st={st} cam={{ ...cam, zoom: cam.zoom * (inward ? 0.6 + 0.4 * e : 1.6 - 0.6 * e) }} mask={`url(#cw-m${Math.round(steps(t + 1 / CUT, 8) * 16)})`} />
      </>
    );
  }
  return <Layer view={r.view} sky={r.sky} st={st} cam={cam} />;
};

/** Mode chip (top left) with its dashes, and the « ×2 » badge. */
const Chip = ({ plan, i, frame, fps }: { plan: Plan; i: number; frame: number; fps: number }) => {
  const r = plan.resolved[i];
  const f = frame - plan.scenes[i].startFrame;
  const prev = i ? plan.resolved[i - 1] : r;
  const changing = prev.rate !== r.rate && f < RAMP_S * fps;
  const text = changing ? (r.rate < prev.rate ? "‖ Ralenti..." : "▶ Accélère...") : chipText(r.speed);
  const color = changing || r.speed.startsWith("1/") ? C.hudBlue : r.speed === "real" ? C.hudOrange : C.hot;
  const rate = (plan.clock[Math.min(frame + 1, plan.clock.length - 1)] - plan.clock[Math.min(frame, plan.clock.length - 2)]) * fps;
  const lit = dashesOf(rate);
  const blink = changing && Math.floor(f / 4) % 2 === 1;
  const w = typeSize(text, 4, true).w + 8 * 4 + 8;
  const x2 = plan.all[i].x2;
  return (
    <g>
      {!blink && <Tag text={text} x={65} y={CHIP_Y} unit={4} color={color} />}
      {Array.from({ length: 6 }, (_, k) => (
        <rect key={k} x={65 + k * 34} y={CHIP_Y + tagHeight(4) + 12} width={24} height={10} fill={k < lit ? color : C.cloud} />
      ))}
      {x2 && f >= 4 && <Type text="×2" x={65 + w + 24} y={CHIP_Y - (f < 8 ? 6 : 0)} unit={f < 8 ? 8 : 7} color={C.yellow} bold outline={C.ink} />}
    </g>
  );
};

/** Top-right gauge: value and label, a 14-cell bar green to red; counts from the last gauge. */
const Gauge = ({ r, f, fps }: { r: Resolved; f: number; fps: number }) => {
  if (!r.gauge) return null;
  const t = easeOut(span(f, 0, COUNT_S * fps));
  const g = r.gauge;
  // The number counts from the last gauge when it measures the same thing.
  const value = g.value ? lerpText(r.gaugeFrom?.label === g.label ? r.gaugeFrom.value : undefined, g.value, t) : undefined;
  const fill = (r.gaugeFrom?.fill ?? g.fill) + (g.fill - (r.gaugeFrom?.fill ?? g.fill)) * t;
  const text = value ? `${value} ${g.label}` : g.label;
  const cells = 14;
  const lit = Math.round(fill * cells);
  // At full speed the last lit cell flickers, like a revving needle.
  const flicker = Math.floor(f / 2) % 2 && fill > 0.6;
  return (
    <g>
      <Tag text={text} x={RIGHT} y={CHIP_Y} unit={4} color={C.white} border={C.hudBlue} align="right" />
      {Array.from({ length: cells }, (_, k) => {
        const on = k < lit - (flicker && k === lit - 1 ? 1 : 0);
        const color = k < 8 ? C.green : k < 11 ? C.yellow : C.red;
        return <rect key={k} x={RIGHT - (cells - k) * 18 + 4} y={CHIP_Y + tagHeight(4) + 12} width={14} height={16} fill={on ? color : C.cloudDark} />;
      })}
    </g>
  );
};

/** Title box(es) and the numbered steps under them. */
const Titles = ({ plan, i, frame, st }: { plan: Plan; i: number; frame: number; st: ViewState }) => {
  const s = plan.all[i];
  const big = i === 0 || i === plan.all.length - 1;
  const f = frame - plan.scenes[i].startFrame;
  const { boxes, bottom } = useMemo(() => titleLayout(s, big), [s, big]);
  // Opens in two hard steps (the hook is up from frame 0: it is the cover).
  const open = i === 0 ? 1 : f < 2 ? 0.3 : f < 4 ? 0.7 : 1;
  return (
    <g>
      {boxes.map((b, k) => (
        <g key={k} transform={`translate(540 0) scale(${open} 1) translate(-540 0)`}>
          <Box x={px(b.x, 1)} y={b.y} w={b.w} h={b.h} border={k ? C.hudOrange : C.cream} b={k ? 4 : 6} />
          {open === 1 && b.lines.map((l, n) => <Type key={n} text={l.text} x={540} y={l.y} unit={l.unit} color={l.color === "yellow" ? C.yellow : C.white} bold align="center" />)}
        </g>
      ))}
      {s.steps && open === 1 && <Steps items={s.steps.items} current={s.steps.current} view={plan.resolved[i].view} st={st} y={bottom + 22} />}
    </g>
  );
};

const Steps = ({ items, current, view, st, y }: { items: string[]; current?: number; view: ViewId; st: ViewState; y: number }) => {
  const { unit, width, item } = stepsLayout(items);
  // No `current`: the lit step follows the mechanism; too fast to follow = all lit.
  const fast = current === undefined && st.rate > 3;
  const lit = current ?? Math.floor(cycleOf(view, st.phase) * items.length);
  const xs = items.map((_, k) => 540 - width / 2 + items.slice(0, k).reduce((sum, t) => sum + item(t) + 12, 0));
  return (
    <g>
      {items.map((t, k) => {
        const on = fast ? (k + Math.floor(st.f / 3)) % 2 === 0 : k === lit;
        return <Tag key={k} text={t} x={px(xs[k], 1)} y={y} unit={unit} color={on ? C.ink : C.mauve} border={on ? C.yellow : C.violet} fill={on ? C.yellow : C.ink} />;
      })}
    </g>
  );
};

const CALLOUT_COLORS = [C.yellow, C.tealLight, C.white];

/** The scene's callouts: boxed labels with an elbow leader line to their point, one after the other. */
const Callouts = ({ plan, i, frame, fps, st, top }: { plan: Plan; i: number; frame: number; fps: number; st: ViewState; top: number }) => {
  const s = plan.all[i];
  const r = plan.resolved[i];
  const f = frame - plan.scenes[i].startFrame;
  const { cam } = sceneState(plan, i, frame);
  const anchors = VIEW_COMPONENTS[r.view].anchors(st) as Record<string, readonly [number, number]>;
  const used: number[][] = [[], []];
  return (
    <g>
      {s.callouts.map((c, k) => {
        const start = Math.round((0.35 + 0.5 * k) * fps) + (r.cut ? CUT : 0);
        if (f < start) return null;
        const [ax, ay] = toScreen(cam, anchors[c.at]).map((v, n) => Math.max(40, Math.min(n ? H - 300 : W - 40, v)));
        const right = ax >= 540;
        const unit = 4;
        const { w } = typeSize(c.text, unit, true);
        const bw = w + 8 * unit + 8;
        const bh = tagHeight(unit);
        let by = Math.max(top, Math.min(1180, ay - 170));
        for (const u of used[+right]) if (Math.abs(by - u) < bh + 16) by = u + bh + 16;
        used[+right].push(by);
        const bx = right ? RIGHT - bw : 70;
        const color = CALLOUT_COLORS[k % 3];
        const lx = px(Math.max(bx + 20, Math.min(bx + bw - 20, ax)), 1);
        const below = ay > by + bh;
        const ly = below ? by + bh : by;
        const grown = f >= start + 3;
        return (
          <g key={k}>
            {grown && (
              <>
                <rect x={lx - 3} y={Math.min(ly, ay)} width={6} height={Math.abs(ay - ly)} fill={color} />
                <rect x={Math.min(lx, ax)} y={ay - 3} width={Math.abs(ax - lx)} height={6} fill={color} />
                <rect x={ax - 9} y={ay - 9} width={18} height={18} fill={color} stroke={C.ink} strokeWidth={4} />
              </>
            )}
            <g transform={f < start + 2 ? `translate(${bx + bw / 2} 0) scale(0.5 1) translate(${-bx - bw / 2} 0)` : undefined}>
              <Tag text={c.text} x={bx} y={by} unit={unit} color={color} />
            </g>
          </g>
        );
      })}
    </g>
  );
};

/** « BANG ! »: a burst word popping in hard steps with a dithered light flash, a third into the scene. */
const bangStart = (len: number) => Math.round(len * 0.32);
const Bang = ({ text, f }: { text: string; f: number }) => {
  const { w } = typeSize(text, 12, true);
  const unit = w > 900 ? 9 : 12;
  const scale = f < 2 ? 1.5 : f < 4 ? 1.2 : 1;
  const jitter = f < 6 ? ((f % 2) * 2 - 1) * P : 0;
  return (
    <g transform={`translate(${540 + jitter} 760) scale(${scale}) translate(-540 -760)`}>
      <Type text={text} x={540} y={760 - 3.5 * unit} unit={unit} color={C.yellow} bold align="center" outline={C.ink} />
    </g>
  );
};

/** The whole picture at `frame` (before the end card). */
const Picture = ({ plan, frame, fps }: { plan: Plan; frame: number; fps: number }) => {
  const { scenes } = plan;
  const i = Math.max(0, ...scenes.map((s, k) => (frame >= s.startFrame ? k : 0)));
  const s = plan.all[i];
  const f = frame - scenes[i].startFrame;
  const len = scenes[i].endFrame - scenes[i].startFrame;
  const { st } = sceneState(plan, i, frame);
  const { bottom } = titleLayout(s, i === 0 || i === plan.all.length - 1);
  const bang = s.bang ? f - bangStart(len) : -1;
  const top = bottom + (s.steps ? 90 : 30);
  return (
    <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
      <Art plan={plan} i={i} frame={frame} fps={fps} />
      {bang >= 0 && bang < 6 && <DitherRect y={0} h={H} color={C.sun} level={0.75 - 0.25 * Math.floor(bang / 2)} />}
      <Chip plan={plan} i={i} frame={frame} fps={fps} />
      <Gauge r={plan.resolved[i]} f={f} fps={fps} />
      <Titles plan={plan} i={i} frame={frame} st={st} />
      <Callouts plan={plan} i={i} frame={frame} fps={fps} st={st} top={top} />
      {s.bang && bang >= 0 && bang < 0.9 * fps && <Bang text={s.bang} f={bang} />}
    </svg>
  );
};

/** SFX cues (frame, asset, volume): a blip per beat, a hit per burst, a swish per cut, the payoff's confirm. */
const cuesOf = (plan: Plan, endStart: number, fps: number) => {
  const cues: [number, AssetId, number][] = [];
  plan.scenes.forEach((sc, i) => {
    if (!i) return;
    const s = plan.all[i];
    const last = i === plan.all.length - 1;
    cues.push([sc.startFrame, last ? "sfx-confirm" : "sfx-select", 0.35]);
    if (plan.resolved[i].cut) cues.push([sc.startFrame, "sfx-swish", 0.3]);
    if (s.bang) cues.push([sc.startFrame + bangStart(sc.endFrame - sc.startFrame), "sfx-hit", 0.45]);
    s.callouts.forEach((_, k) => cues.push([sc.startFrame + Math.round((0.35 + 0.5 * k) * fps) + (plan.resolved[i].cut ? CUT : 0), "sfx-select", 0.15]));
  });
  cues.push([endStart - 8, "sfx-swish", 0.35]);
  return cues;
};

export const Cutaway = (props: CutawayProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const plan = usePlan(props, fps);
  const { timeline, endStart } = plan;
  const cues = useMemo(() => cuesOf(plan, endStart, fps), [plan, endStart, fps]);
  const loop = loopFade(frame, timeline);
  const last = plan.all[plan.all.length - 1];
  return (
    <AbsoluteFill style={{ background: C.night }}>
      <Defs />
      {frame < endStart ? (
        <>
          <Picture plan={plan} frame={frame} fps={fps} />
          {/* Into the end card: the picture dithers to ink. */}
          {frame >= endStart - 8 && (
            <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
              <DitherRect y={0} h={H} color={C.ink} level={(frame - endStart + 9) / 8} />
            </svg>
          )}
        </>
      ) : (
        <Sequence from={endStart} layout="none">
          <EndCard style="cutaway" tagline={props.outro} accent={props.accent} cameo={props.cameo ?? last.view} address={props.address} pixelate={1} />
        </Sequence>
      )}
      {loop > 0 && (
        <AbsoluteFill style={{ opacity: loop }}>
          <Picture plan={plan} frame={0} fps={fps} />
        </AbsoluteFill>
      )}
      {cues.map(([at, id, volume], i) => (
        <Sequence key={i} from={Math.max(0, at)} durationInFrames={45} layout="none">
          <Html5Audio src={assetById(id).src} volume={volume} />
        </Sequence>
      ))}
      <MusicBed id={props.music} />
      <SafeZoneGuide show={!!props.safeZone} />
      {props.voice?.audioSrc && <Html5Audio src={props.voice.audioSrc} />}
    </AbsoluteFill>
  );
};

