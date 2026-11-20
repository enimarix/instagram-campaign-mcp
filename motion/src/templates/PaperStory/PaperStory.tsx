// PaperStory (step 131): the owner's paper cut-out house style (macrobody-video p1-p3, s1) as
// a template. Hook (question strips on a night sheet, the character with a clock, fridge,
// plate or phone), 1-2 problem beats (foods out of the fridge with their numbers on a receipt
// slip, crossed out or checked), 1-2 app beats (the phone with the app's ring and the green
// button tapped, or the app's list solving its grams with padlocks) and the payoff (a big ring
// counting up, a stamp, paper confetti), then the paper end card with the story's character.
// Sheets of paper on a kraft frame, Fredoka strips, Caveat asides, tear / wipe transitions,
// and every move on 12 fps steps.
import { useMemo } from "react";
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { MusicBed } from "../../components/MusicBed";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { Sfx } from "../../components/Sfx";
import { EndCard } from "../../endcards/EndCard";
import { PAPER } from "../../endcards/PaperEndCard";
import { ACCENTS, TEXT_ACCENT } from "../../endcards/schema";
import { countUp } from "../../lib/countUp";
import { type SfxId, spokenLines } from "../../lib/duck";
import { frenchSpaces } from "../../lib/french";
import { loopFade, type Scene } from "../../lib/timeline";
import { CharacterGroup, type Gesture, type Mood } from "../../paper/Character";
import { Confetti, Clock, Check, FoodSticker, Fridge, Lock, Phone, Plate, Ring, Slip, XMark } from "../../paper/props";
import { CutDefs, cutRect, Finish, H, Hand, Label, LABEL_FONT, Night, pop, Sheet, Tear, W, Wipe } from "../../paper/kit";
import { BRAND, BRAND_LIGHT, CREAM, INK, MACRO, stepped, YELLOW } from "../../paper/palette.ts";
import { backOut, easeInOut, easeOut, span } from "../../voxel/anim.ts";
import {
  HOOK_POP_S,
  isDark,
  labelStack,
  labelStart,
  optionTimes,
  payoffPlaces,
  payoffRatio,
  payoffTimes,
  phoneTimes,
  rowTimes,
  rowY,
  sheetOf,
  sizeOf,
  TEAR_S,
  transitionInto,
  WIPE_S,
} from "./layout";
import { type Beat, labelText, type PaperStoryProps, timelineOf } from "./schema";

type SceneProps = { p: PaperStoryProps; index: number; f: number; len: number; fps: number };

/** The scene's strips: stacked (or one at a time in an app list beat), popping in. */
const Strips = ({ p, index, f, len, fps }: SceneProps) => {
  const labels = index === 0 ? p.hook.labels : p.beats[index - 1].labels;
  const b = index === 0 ? null : p.beats[index - 1];
  const oneByOne = b?.kind === "app" && !!b.rows;
  const { ys } = labelStack(labels);
  return (
    <>
      {labels.map((l, i) => {
        const start = index === 0 ? (i ? Math.round(HOOK_POP_S[i] * fps) : -99) : labelStart(i, labels.length, len, fps, oneByOne);
        // One at a time: each strip leaves just before the next one pops.
        if (oneByOne && (f < start - Math.round(0.1 * fps) || (i + 1 < labels.length && f >= labelStart(i + 1, labels.length, len, fps, true) - Math.round(0.1 * fps)))) return null;
        const tone = typeof l === "string" ? "cream" : l.tone;
        return <Label key={i} text={labelText(l)} x={540} y={oneByOne ? ys[0] : ys[i]} size={sizeOf(l)} tone={tone} rot={[-1.7, 1.2, -1.1][i]} f={f} start={start} />;
      })}
    </>
  );
};

/** The character's face and gesture: the scene's own, else per kind and moment. */
const faceOf = (p: PaperStoryProps, index: number, f: number, len: number, fps: number): { mood: Mood; gesture: Gesture; closed?: boolean } => {
  const s = index === 0 ? p.hook : p.beats[index - 1];
  let mood: Mood = "neutral";
  let gesture: Gesture = "none";
  let closed = false;
  if (index === 0) {
    const last = Math.round(HOOK_POP_S[p.hook.labels.length - 1] * fps);
    mood = p.hook.labels.length > 1 && f >= last && f < last + fps ? "surprised" : "neutral";
    gesture = p.hook.prop === "phone" ? "none" : "phone";
  } else {
    const b = s as Beat;
    if (b.kind === "problem") {
      const first = b.options.length ? optionTimes(0, b.options.length, len, fps).verdict : Math.round(len * 0.4);
      mood = f >= first ? "worried" : "neutral";
      gesture = b.options.length ? "none" : "shrug";
    }
    if (b.kind === "payoff") {
      const stamp = payoffTimes(len).stamp;
      mood = "happy";
      gesture = b.value ? "wave" : "cheer";
      closed = f >= stamp && f < stamp + Math.round(0.7 * fps);
    }
  }
  return { mood: s.mood ?? mood, gesture: s.gesture ?? gesture, closed };
};

const TextSvg = ({ s, x, y, size, color, weight = 700 }: { s: string; x: number; y: number; size: number; color: string; weight?: number }) => (
  <text x={x} y={y} fontFamily={LABEL_FONT} fontWeight={weight} fontSize={size} fill={color} textAnchor="middle" dominantBaseline="central">
    {frenchSpaces(s)}
  </text>
);

/** A stamp (paper.js stampP): outlined text slammed down from 2.4× at `start`. */
const Stamp = ({ text, x, y, color, f, start }: { text: string; x: number; y: number; color: string; f: number; start: number }) => {
  if (f < start) return null;
  const sc = 2.4 + (1 - 2.4) * backOut(span(f, start, 7), 0.15);
  return (
    <div style={{ position: "absolute", left: x, top: y, transform: `translate(-50%, -50%) rotate(-4.6deg) scale(${sc})`, border: `10px solid ${color}`, padding: "6px 34px 10px", fontFamily: LABEL_FONT, fontWeight: 700, fontSize: 96, lineHeight: 1, color, whiteSpace: "nowrap" }}>
      {frenchSpaces(text)}
    </div>
  );
};

const HookScene = ({ p, f, len, fps }: SceneProps) => {
  const h = p.hook;
  const [hr, mn] = h.time.split(":").map(Number);
  // The minute hand ticks up to the hour (or the minute) in the first half second.
  const tick = Math.max(0, Math.round(0.6 * fps) - f);
  const shown = (hr * 60 + mn - Math.ceil(tick / (0.15 * fps)) + 1440) % 1440;
  const face = faceOf(p, 0, f, len, fps);
  const alone = h.prop === "none";
  return (
    <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
      <CutDefs />
      {h.prop === "clock" && <Clock x={290} y={960} r={170} hour={Math.floor(shown / 60)} minute={shown % 60} />}
      {h.prop === "fridge" && <Fridge x={300} y={960} s={0.78} open={0} />}
      {h.prop === "plate" && (
        <Plate x={320} y={1080} s={0.86}>
          {(h.foods ?? []).map((food, i) => (
            <FoodSticker key={i} food={food} x={[-120, 0, 120][i]} y={[-10, -40, -10][i]} size={150} seed={i + 2} />
          ))}
        </Plate>
      )}
      {h.prop === "phone" && <Phone x={300} y={950} s={0.55} screen={{ ring: 0.86, value: "", unit: "", bars: [0.7, 0.5, 0.8], button: "Compléter ma journée", pressed: false }} />}
      <CharacterGroup id={p.character} x={alone ? 540 : 790} y={1340} scale={alone ? 0.76 : 0.7} f={f} fps={fps} look={f < Math.round(HOOK_POP_S[Math.min(2, h.labels.length - 1)] * fps) ? -1 : 0} {...face} />
    </svg>
  );
};

const ProblemScene = ({ p, index, f, len, fps }: SceneProps) => {
  const b = p.beats[index - 1] as Extract<Beat, { kind: "problem" }>;
  const n = b.options.length;
  const current = n ? Math.max(0, ...b.options.map((_, i) => (f >= optionTimes(i, n, len, fps).start ? i : 0))) : -1;
  const o = n ? b.options[current] : null;
  const t = n ? optionTimes(current, n, len, fps) : null;
  const fromFridge = b.prop === "fridge";
  const fly = t ? easeOut(span(f, t.start, Math.round(0.35 * fps))) : 0;
  const land = t ? backOut(span(f, t.start, Math.round(0.35 * fps)), 0.15) : 0;
  // Out of the open fridge, else tossed in from the left edge.
  const [x0, y0] = fromFridge ? [300, 940] : [-200, 900];
  const face = faceOf(p, index, f, len, fps);
  const [hr, mn] = b.time.split(":").map(Number);
  return (
    <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
      <CutDefs />
      {b.prop === "fridge" && <Fridge x={300} y={980} s={0.78} open={easeOut(span(f, 2, Math.round(0.3 * fps)))} foods={["egg", "cheese", "yogurt"]} />}
      {b.prop === "clock" && <Clock x={290} y={960} r={150} hour={hr} minute={mn} />}
      {b.prop === "plate" && <Plate x={330} y={1130} s={0.55} />}
      {o && t && f >= t.start && (
        <>
          <FoodSticker food={o.food} x={x0 + (590 - x0) * fly} y={y0 + (790 - y0) * fly} size={Math.max(2, 200 * land)} rot={Math.sin(f / 3) * 4} seed={current + 3} />
          {f >= t.start + Math.round(0.15 * fps) && <Slip x={600} y={1010} rot={2.3} small={o.note} big={o.label} color={o.verdict === "ok" ? BRAND : INK} />}
          {(o.verdict === "too_much" || o.verdict === "too_little") && <XMark x={600} y={790} s={pop(f, t.verdict, 5)} />}
          {o.verdict === "ok" && <Check x={660} y={740} s={pop(f, t.verdict, 5)} />}
        </>
      )}
      <CharacterGroup id={p.character} x={n ? 840 : 690} y={1330} scale={0.62} f={f} fps={fps} look={-1} {...face} />
    </svg>
  );
};

const PhoneScene = ({ p, index, f, len, fps }: SceneProps) => {
  const b = p.beats[index - 1] as Extract<Beat, { kind: "app" }>;
  const t = phoneTimes(len, fps);
  const c = easeInOut(span(f, t.count[0], t.count[1] - t.count[0]));
  const sy = f < t.pop ? 0.02 : backOut(span(f, t.pop, Math.round(0.35 * fps)), 0.15);
  const tapP = span(f, t.tap, Math.round(0.6 * fps));
  const s = 0.92;
  // Under the strips, 30 px clear of the last one.
  const y = Math.max(960, labelStack(b.labels).bottom + 30 + 440 * s);
  const button = [540, y + 276 * s] as const;
  return (
    <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
      <CutDefs />
      <Phone x={540} y={y} s={s} sy={sy} screen={{ ring: (b.value ? 0.86 : 1) * c, value: b.value ? countUp(b.value, c) : "", unit: b.value ? b.unit : "", bars: [0.7 * c, 0.5 * c, 0.8 * c], button: b.button, pressed: f >= t.tap && f < t.tap + Math.round(0.2 * fps) }} />
      {!b.value && <Check x={540} y={y - 130 * s} s={0.9 * pop(f, t.count[1], 5)} />}
      {f >= t.tap && tapP < 1 && <circle cx={button[0]} cy={button[1]} r={30 + tapP * 120} fill="none" stroke={BRAND} strokeOpacity={1 - tapP} strokeWidth={10 * (1 - tapP) + 2} />}
    </svg>
  );
};

const RowsScene = ({ p, index, f, len, fps }: SceneProps) => {
  const b = p.beats[index - 1] as Extract<Beat, { kind: "app" }>;
  const rows = b.rows ?? [];
  const t = rowTimes(rows.length, len, fps);
  const solve = easeInOut(span(f, t.solve[0], t.solve[1] - t.solve[0]));
  return (
    <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
      <CutDefs />
      {rows.map((r, i) => {
        const start = t.row(i);
        if (f < start) return null;
        const e = backOut(span(f, start, Math.round(0.3 * fps)), 0.15);
        const x = (i % 2 ? 1400 : -400) + (540 - (i % 2 ? 1400 : -400)) * e;
        const from = r.from ?? r.to;
        const g = Math.round(from + (r.to - from) * solve);
        const active = from !== r.to && f >= t.solve[0] && f < t.solve[1] + 4;
        const lock = r.locked ? t.lock(rows.slice(0, i).filter((x) => x.locked).length) : null;
        return (
          <g key={i} transform={`translate(${x} ${rowY(i, rows.length)}) rotate(${i % 2 ? 0.7 : -0.7})`}>
            <path d={cutRect(-410, -62, 820, 124, i + 40, 3)} fill="#FFFFFF" filter="url(#cut1)" />
            <FoodSticker food={r.food} x={-338} y={0} size={100} seed={i} />
            <text x={-272} y={2} fontFamily={LABEL_FONT} fontWeight={700} fontSize={48} fill={INK} dominantBaseline="central">
              {r.name}
            </text>
            <rect x={120} y={-40} width={160} height={80} rx={20} fill={active ? YELLOW : "#F2EBDD"} filter="url(#cut05)" />
            <TextSvg s={`${g} g`} x={200} y={2} size={44} color={INK} />
            {lock !== null && f >= lock && <Lock x={338} y={4} s={1.1 * backOut(span(f, lock, 5), 0.15)} />}
          </g>
        );
      })}
      {b.total && f >= t.total && (
        <g transform={`translate(540 1240) rotate(-1.2) scale(${backOut(span(f, t.total, 6), 0.15)})`}>
          <path d={cutRect(-300, -62, 600, 124, 9, 4)} fill={BRAND} filter="url(#cut15)" />
          <TextSvg s={b.total} x={0} y={0} size={Math.min(66, Math.floor(540 / (b.total.length * 0.56)))} color="#FFFFFF" />
        </g>
      )}
    </svg>
  );
};

const PayoffScene = ({ p, index, f, len, fps }: SceneProps) => {
  const b = p.beats[index - 1] as Extract<Beat, { kind: "payoff" }>;
  const t = payoffTimes(len);
  const color = ACCENTS[p.accent];
  const { stampY, ringY } = payoffPlaces(b);
  const c = easeInOut(span(f, t.count[0], t.count[1] - t.count[0]));
  const ratio = payoffRatio(b);
  const face = faceOf(p, index, f, len, fps);
  const dark = isDark(sheetOf(p, index));
  return (
    <>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        <CutDefs />
        {b.value && (
          <g transform={`translate(540 ${ringY})`}>
            <Ring r={210} p={ratio * (0.86 + 0.14 * c)} color={c >= 1 ? color : MACRO.kcal} width={44} />
            <g filter="url(#cut1)">
              <circle r={168} fill={CREAM} />
            </g>
            <TextSvg s={countUp(b.value, 0.86 + 0.14 * c)} x={0} y={-24} size={b.value.length > 6 ? 84 : 104} color={INK} />
            {b.of && <TextSvg s={b.of} x={0} y={58} size={40} color="#8b7d6b" weight={600} />}
          </g>
        )}
        {b.foods?.length ? (
          <Plate x={b.value ? 790 : 820} y={1230} s={0.55}>
            {b.foods.map((food, i) => (
              <FoodSticker key={i} food={food} x={[-120, 0, 120][i]} y={[-20, -50, -20][i]} size={190} seed={i + 5} />
            ))}
          </Plate>
        ) : null}
        <CharacterGroup id={p.character} x={b.value ? 230 : 400} y={1340} scale={b.value ? 0.56 : 0.72} f={f} fps={fps} look={1} {...face} />
        <Confetti x={540} y={b.value ? ringY : stampY} f={f} start={t.stamp} fps={fps} />
      </svg>
      {b.stamp && <Stamp text={b.stamp} x={540} y={stampY} color={dark ? BRAND_LIGHT : TEXT_ACCENT[p.accent]} f={f} start={t.stamp} />}
    </>
  );
};

/** Where a scene's handwritten aside goes: a free spot beside the character and props. */
const asidePlace = (p: PaperStoryProps, index: number): [number, number] => {
  const b = index === 0 ? null : p.beats[index - 1];
  if (!b) return p.hook.prop === "none" ? [540, 1100] : [330, 1265];
  if (b.kind === "problem") return [b.options.length || b.prop !== "none" ? 330 : 300, 1265];
  if (b.kind === "app") return b.rows ? [540, 1330] : [540, labelStack(b.labels).bottom + 50];
  if (b.value) return [540, payoffPlaces(b).ringY + 285];
  return [770, 1000];
};

/** One scene as drawn `f` (stepped) frames after its start; `len` = its length in frames. */
const SceneView = (sp: SceneProps) => {
  const { p, index, f, len } = sp;
  const sheet = sheetOf(p, index);
  const dark = isDark(sheet);
  const b = index === 0 ? null : p.beats[index - 1];
  const aside = index === 0 ? p.hook.aside : b?.aside;
  const asideAt = Math.round(len * (index === 0 ? 0.62 : 0.55));
  const [ax, ay] = asidePlace(p, index);
  return (
    <AbsoluteFill>
      <Sheet sheet={sheet} seed={21 + index}>
        {dark && <Night step={f} seed={4 + index} />}
      </Sheet>
      {index === 0 && <HookScene {...sp} />}
      {b?.kind === "problem" && <ProblemScene {...sp} />}
      {b?.kind === "app" && (b.rows ? <RowsScene {...sp} /> : <PhoneScene {...sp} />)}
      {b?.kind === "payoff" && <PayoffScene {...sp} />}
      <Strips {...sp} />
      {aside && f >= asideAt && <Hand text={aside} x={ax} y={ay} color={dark ? CREAM : INK} />}
    </AbsoluteFill>
  );
};

/** Paper SFX cues (frame, sound, dB from the voice's level) for the whole film. */
const cuesOf = (p: PaperStoryProps, scenes: Scene[], endStart: number, fps: number) => {
  const cues: [number, SfxId, number, number?][] = [];
  const n = p.beats.length;
  for (let i = 1; i <= n; i++) {
    const s = scenes[i];
    const len = s.endFrame - s.startFrame;
    if (transitionInto(i) === "tear") cues.push([s.startFrame, "sfx-rip", 0]);
    else cues.push([s.startFrame - Math.round(0.3 * fps), "sfx-swish", -3]);
    const b = p.beats[i - 1];
    b.labels.forEach((_, k) => cues.push([s.startFrame + labelStart(k, b.labels.length, len, fps, b.kind === "app" && !!b.rows), "sfx-pop", -4]));
    if (b.kind === "problem") b.options.forEach((_, k) => cues.push([s.startFrame + optionTimes(k, b.options.length, len, fps).start, "sfx-pop", 0]));
    if (b.kind === "app" && !b.rows) cues.push([s.startFrame + phoneTimes(len, fps).tap, "sfx-pop", 0]);
    if (b.kind === "app" && b.total) cues.push([s.startFrame + rowTimes(b.rows!.length, len, fps).total, "sfx-pop", 0]);
    if (b.kind === "payoff") cues.push([s.startFrame + payoffTimes(len).stamp, "sfx-chime", 0]);
  }
  p.hook.labels.forEach((_, k) => k && cues.push([Math.round(HOOK_POP_S[k] * fps), "sfx-pop", -3]));
  cues.push([endStart - Math.round(0.3 * fps), "sfx-swish", -3]);
  return cues;
};

export const PaperStory = (props: PaperStoryProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { timeline, endStart } = useMemo(() => timelineOf(props, fps), [props, fps]);
  const scenes = timeline.scenes.slice(0, props.beats.length + 1);
  const index = Math.max(0, ...scenes.map((s, i) => (frame >= s.startFrame ? i : 0)));
  const scene = scenes[index];
  const sp = (i: number, at: number): SceneProps => ({ p: props, index: i, f: stepped(at - scenes[i].startFrame, fps), len: scenes[i].endFrame - scenes[i].startFrame, fps });
  // Transitions: a tear just after a cut, a wipe across it (and a kraft wipe into the end card).
  const tearing = index > 0 && transitionInto(index) === "tear" && frame < scene.startFrame + TEAR_S * fps;
  const half = (WIPE_S * fps) / 2;
  const wipes = [...scenes.slice(1).map((s, i) => [s.startFrame, i + 1] as const).filter(([, i]) => transitionInto(i) === "wipe"), [endStart, -1] as const];
  const wipe = wipes.find(([c]) => Math.abs(frame - c) < half);
  const cues = useMemo(() => cuesOf(props, timeline.scenes, endStart, fps), [props, timeline, endStart, fps]);
  const loop = loopFade(frame, timeline);
  const lines = spokenLines(props.voice);
  const wipeColor = (i: number) => (i < 0 ? PAPER.kraftDark : i % 4 === 2 ? BRAND : YELLOW);
  return (
    <AbsoluteFill style={{ background: PAPER.kraft }}>
      {frame < endStart ? (
        <>
          <SceneView {...sp(index, frame)} />
          {tearing && (
            <Tear p={span(stepped(frame - scene.startFrame, fps), 0, TEAR_S * fps)}>
              <SceneView {...sp(index - 1, scene.startFrame - 1)} />
            </Tear>
          )}
        </>
      ) : (
        <Sequence from={endStart} layout="none">
          <EndCard style="paper" tagline={props.outro} accent={props.accent} cameo={props.cameo ?? props.character} address={props.address} pixelate={2} />
        </Sequence>
      )}
      {wipe && <Wipe p={stepped(frame - wipe[0] + half, fps) / (2 * half)} color={wipeColor(wipe[1])} />}
      {loop > 0 && (
        // Loop on: the hook's first frame comes back over the last frames.
        <AbsoluteFill style={{ opacity: loop }}>
          <SceneView {...sp(0, 0)} />
        </AbsoluteFill>
      )}
      <Finish step={Math.floor((frame * 12) / fps)} />
      {cues.map(([at, id, db, speech], i) => (
        <Sfx key={i} id={id} at={at} db={db} speech={speech} lines={lines} />
      ))}
      <MusicBed id={props.music} lines={lines} />
      <SafeZoneGuide show={!!props.safeZone} />
      {props.voice?.audioSrc && <Html5Audio src={props.voice.audioSrc} />}
    </AbsoluteFill>
  );
};
