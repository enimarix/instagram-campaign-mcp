import { useMemo } from "react";
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { assetById } from "../../assets";
import { scriptAreas } from "../../brand";
import { Captions } from "../../components/Captions";
import { CRTOverlay } from "../../components/CRTOverlay";
import { HookCard } from "../../components/HookCard";
import { PixelText } from "../../components/PixelText";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { Sprite } from "../../components/Sprite";
import { Flash, Wipe } from "../../components/Transitions";
import type { PixelArt } from "../../lib/game";
import { progress } from "../../lib/game";
import { colors } from "../../lib/palette";
import { fitTextScale, fontPx, linePx, snap } from "../../lib/pixel";
import { buildTimeline, loopFade } from "../../lib/timeline";
import { wrap } from "../../lib/typewriter";
import { countdownAt, countdownTicks, type QuizChestProps, quizChestScript, withCountdown } from "./schema";

// QuizChest (step 046): hook card, then the question (whole, top) over 2–4 choices (band), a
// countdown ticking next to a closed chest (sfx-select each second), the reveal (flash, the chest
// opens and a coin pops out, the right choice lights up, the others dim), the explanation typed
// into the band under the open chest, and the end card with the call to comment. Scenes: the
// script timeline (0 hook, 1 question, 2 explanation, 3 cta) with the countdown and reveal
// inserted into scene 1 (`withCountdown`); the cta holds through the outro, where `loop` fades
// the hook back in so the last frame matches frame 0.

const HOOK_S = 1.5;
const OUTRO_S = 0.5;
/** Frames of the wipe between scenes; scenes cut at its midpoint. */
const WIPE = 12;
/** Typewriter speed, chars/s: twice the estimated reading speed, so the text is whole early. */
const TYPE_CPS = 30;
const FLASH = 8;
/** Frames the chest shakes after each tick. */
const SHAKE = 6;
/** Frames from the reveal to the coin popping out (and its sfx). */
const COIN_DELAY = 6;
/** Frames the coin takes to rise out of the chest. */
const COIN_RISE = 10;
const CHEST_PX = 8;
/** Room above the chest for the coin that pops out (one coin, 8 sheet px, high). */
const COIN_ROOM = 8 * CHEST_PX;
const DIGIT_SCALE = 12;
/** Largest choice font scale; the choices shrink in whole steps until all fit the band. */
const MAX_CHOICE_SCALE = 5;
const GAP = 24;
/** Background music level: under the voice and the sfx. */
const MUSIC_VOLUME = 0.25;

/** Treasure chest, frame 0 closed, frame 1 open (gold inside). Colours: brand palette indices. */
const chestBody = [
  ".KYYYYYYYYYYYYK.",
  ".KRRRRRYYRRRRRK.",
  ".KOOOOOYWOOOOOK.",
  ".KOOOOOYYOOOOOK.",
  ".KRRRRRRRRRRRRK.",
  ".KOOOOOOOOOOOOK.",
  ".KYYYYYYYYYYYYK.",
  ".KKKKKKKKKKKKKK.",
];
const chest: PixelArt = {
  colors: { K: 0, O: 3, R: 2, Y: 4, W: 12, D: 15 },
  frames: [
    ["................", "................", "..KKKKKKKKKKKK..", ".KOOOOOOOOOOOOK.", ".KOOOOOOOOOOOOK.", ".KRRRRRRRRRRRRK.", ...chestBody],
    ["..KKKKKKKKKKKK..", ".KOOOOOOOOOOOOK.", ".KRRRRRRRRRRRRK.", ".KDDDDDDDDDDDDK.", ".KDWYYDDYYWYDDK.", ".KYYYYYYYYYYYYK.", ...chestBody],
  ],
};
const CHEST_H = chest.frames[0].length * CHEST_PX;

export const timelineOf = (props: QuizChestProps, fps: number) =>
  withCountdown(
    buildTimeline({ ...quizChestScript(props), fps, hookSeconds: HOOK_S, outroSeconds: OUTRO_S, loop: props.loop }),
    props.countdownSeconds,
    fps,
  );

type Colors = typeof colors;
type Choice = QuizChestProps["choices"][number];
/** Font scale of the choice buttons and the label column (widest label + a space), in chars. */
type ChoiceFit = { scale: number; labelCols: number };

/** Button frame (border + padding, both sides) at font scale `s`, px. */
const frameOf = (s: number) => 2 * (2 * s + 4 * s);

/** Largest scale at which every choice button fits `width` and all of them stack within `height`. */
const fitChoices = (choices: Choice[], width: number, height: number): ChoiceFit => {
  const labelCols = Math.max(...choices.map((c) => Array.from(c.label).length)) + 1;
  for (let s = MAX_CHOICE_SCALE; s > 1; s--) {
    const cols = Math.floor((width - frameOf(s)) / fontPx(s)) - labelCols;
    const rows = choices.reduce((h, c) => h + wrap(c.text.normalize("NFC"), Math.max(1, cols)).length * linePx(s) + frameOf(s), 0);
    if (cols >= 1 && rows + (choices.length - 1) * (GAP / 2) <= height) return { scale: s, labelCols };
  }
  return { scale: 1, labelCols };
};

/** The closed chest (shaking on each tick) or, from `reveal`, the open one with a coin rising out. */
const Chest = ({ ticks, reveal }: { ticks: number[]; reveal: number }) => {
  const frame = useCurrentFrame();
  const open = frame >= reveal;
  const tick = ticks.findLast((t) => frame >= t);
  const dx = !open && tick !== undefined && frame < tick + SHAKE ? (Math.floor((frame - tick) / 2) % 2 ? 1 : -1) * CHEST_PX : 0;
  // The coin rises from behind the lid until it sits on the chest, in whole sprite pixels.
  const rise = snap(progress(frame, reveal + COIN_DELAY, COIN_RISE) * 10 * CHEST_PX, CHEST_PX);
  const coin = assetById("coin");
  return (
    <div style={{ position: "relative", width: 16 * CHEST_PX, height: COIN_ROOM + CHEST_H }}>
      {open && frame >= reveal + COIN_DELAY && (
        <div style={{ position: "absolute", left: 4 * CHEST_PX, top: COIN_ROOM + 2 * CHEST_PX - rise }}>
          <Sprite {...coin} scale={CHEST_PX} fps={8} />
        </div>
      )}
      <div style={{ position: "absolute", top: COIN_ROOM, transform: `translateX(${dx}px)` }}>
        <Sprite art={chest} scale={CHEST_PX} frame={open ? 1 : 0} />
      </div>
    </div>
  );
};

/** One answer as a pixel button; `state` lights it up (the right one) or dims it after the reveal. */
const ChoiceRow = (p: { choice: Choice; state: "idle" | "right" | "wrong"; width: number; fit: ChoiceFit; c: Colors }) => {
  const { choice, state, width, c } = p;
  const px = p.fit.scale;
  const border = 2 * px;
  const pad = 4 * px;
  const labelW = p.fit.labelCols * fontPx(px);
  const right = state === "right";
  return (
    <div
      style={{
        boxSizing: "border-box",
        width,
        display: "flex",
        padding: pad,
        border: `${border}px solid ${right ? c.accent : c.text}`,
        backgroundColor: right ? c.accent : c.background,
        opacity: state === "wrong" ? 0.4 : 1,
      }}
    >
      <div style={{ width: labelW, flexShrink: 0 }}>
        <PixelText text={choice.label} scale={px} color={right ? c.background : c.accent} />
      </div>
      <PixelText text={choice.text} scale={px} color={right ? c.background : c.text} maxWidth={width - 2 * (border + pad) - labelW} />
    </div>
  );
};

const Question = (p: QuizChestProps & { countdownStart: number; reveal: number; c: Colors }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { hook: area, captions: band } = scriptAreas();
  const row = Math.max(COIN_ROOM + CHEST_H, linePx(DIGIT_SCALE));
  const q = p.question.normalize("NFC");
  const scale = fitTextScale((cols) => wrap(q, cols).length, area.width, area.height - row - GAP, 6);
  const n = countdownAt(frame, p.countdownStart, p.countdownSeconds, fps);
  const revealed = frame >= p.reveal;
  const fit = fitChoices(p.choices, band.width, band.height);
  return (
    <>
      <div
        style={{ position: "absolute", ...area, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", gap: GAP }}
      >
        <PixelText text={q} scale={scale} color={p.c.primary} maxWidth={area.width} />
        <div style={{ display: "flex", alignItems: "flex-end", gap: 2 * GAP, height: row }}>
          <Chest ticks={countdownTicks(p.countdownStart, p.countdownSeconds, fps)} reveal={p.reveal} />
          {/* Fixed slot (2 digits) so the chest never moves when the number changes. */}
          <div style={{ width: 2 * fontPx(DIGIT_SCALE) }}>
            {n !== undefined && <PixelText text={String(n)} scale={DIGIT_SCALE} color={n <= 2 ? p.c.secondary : p.c.accent} />}
          </div>
        </div>
      </div>
      <div style={{ position: "absolute", ...band, display: "flex", flexDirection: "column", gap: GAP / 2 }}>
        {p.choices.map((choice, i) => (
          <ChoiceRow key={i} choice={choice} state={!revealed ? "idle" : i === p.answer ? "right" : "wrong"} width={band.width} fit={fit} c={p.c} />
        ))}
      </div>
    </>
  );
};

/** After the reveal: the open chest over the right answer (the explanation types in the band). */
const Answer = ({ choices, answer, start, c }: { choices: Choice[]; answer: number; start: number; c: Colors }) => {
  const { hook: area, captions: band } = scriptAreas();
  return (
    <div style={{ position: "absolute", ...area, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 2 * GAP }}>
      {/* Already open: `reveal` in the past keeps the coin up. */}
      <Chest ticks={[]} reveal={start - COIN_DELAY - COIN_RISE} />
      {/* Same size as in the question scene. */}
      <ChoiceRow choice={choices[answer]} state="right" width={area.width} fit={fitChoices(choices, band.width, band.height)} c={c} />
    </div>
  );
};

const EndCard = ({ cta, note, opacity, c }: { cta: string; note?: string; opacity: number; c: Colors }) => {
  const { hook: area, captions: band } = scriptAreas();
  const s = cta.normalize("NFC");
  const scale = fitTextScale((cols) => wrap(s, cols).length, area.width, area.height - COIN_ROOM - GAP, 6);
  return (
    <AbsoluteFill style={{ opacity }}>
      <div
        style={{ position: "absolute", ...area, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", gap: GAP }}
      >
        <Sprite {...assetById("coin")} scale={CHEST_PX} fps={8} />
        <PixelText text={s} scale={scale} color={c.primary} maxWidth={area.width} />
      </div>
      {note && (
        <div style={{ position: "absolute", ...band, display: "flex", justifyContent: "center", textAlign: "center" }}>
          <PixelText text={note} scale={3} color={c.text} maxWidth={band.width} />
        </div>
      )}
    </AbsoluteFill>
  );
};

/** One sound from `from` on (stills are silent). */
const Sfx = ({ id, from }: { id: "sfx-select" | "sfx-confirm" | "sfx-coin"; from: number }) => (
  <Sequence from={from} layout="none">
    <Html5Audio src={assetById(id).src} />
  </Sequence>
);

export const QuizChest = (props: QuizChestProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { timeline, countdownStart, reveal, gap } = useMemo(() => timelineOf(props, fps), [props, fps]);
  const c = { ...colors, ...props.palette };
  const [, question, explanation, cta] = timeline.scenes;
  const voice = props.voice?.audioSrc;
  return (
    <AbsoluteFill style={{ backgroundColor: c.background }}>
      {frame >= question.startFrame && frame < question.endFrame && (
        <Question {...props} countdownStart={countdownStart} reveal={reveal} c={c} />
      )}
      {frame >= explanation.startFrame && frame < explanation.endFrame && (
        <>
          <Answer choices={props.choices} answer={props.answer} start={explanation.startFrame} c={c} />
          <Captions timeline={timeline} speed={TYPE_CPS} />
        </>
      )}
      {frame >= cta.startFrame && (
        <EndCard
          cta={props.cta}
          note={props.citations.length ? props.sourcesNote : undefined}
          // Gives way to the hook as it fades back in: the last frame is frame 0's picture.
          opacity={1 - loopFade(frame, timeline)}
          c={c}
        />
      )}
      <HookCard text={props.hook} timeline={timeline} color={c.primary} />
      {timeline.scenes.slice(1).map((s) => (
        <Wipe
          key={s.index}
          direction={s.index % 2 ? "right" : "left"}
          startFrame={s.startFrame - WIPE / 2}
          duration={WIPE}
          color={s.index % 2 ? c.accent : c.secondary}
        />
      ))}
      {countdownTicks(countdownStart, props.countdownSeconds, fps).map((t) => (
        <Sfx key={t} id="sfx-select" from={t} />
      ))}
      <Flash startFrame={reveal} duration={FLASH} color={c.text} />
      <Sfx id="sfx-confirm" from={reveal} />
      <Sfx id="sfx-coin" from={reveal + COIN_DELAY} />
      {props.music !== "none" && <Html5Audio src={assetById(props.music).src} loop volume={MUSIC_VOLUME} />}
      <CRTOverlay />
      <SafeZoneGuide show={!!props.safeZone} />
      {/* The voice pauses through the countdown and reveal: its first part up to the end of the
          question line, the rest from the explanation on. */}
      {voice && (
        <>
          <Sequence durationInFrames={countdownStart} layout="none">
            <Html5Audio src={voice} />
          </Sequence>
          <Sequence from={countdownStart + gap} layout="none">
            <Html5Audio src={voice} trimBefore={countdownStart} />
          </Sequence>
        </>
      )}
    </AbsoluteFill>
  );
};
