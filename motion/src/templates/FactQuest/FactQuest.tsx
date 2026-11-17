import { useMemo } from "react";
import { AbsoluteFill, Html5Audio, useCurrentFrame, useVideoConfig } from "remotion";
import { scriptAreas } from "../../brand";
import { Captions } from "../../components/Captions";
import { CRTOverlay } from "../../components/CRTOverlay";
import { HookCard } from "../../components/HookCard";
import { HUD } from "../../components/HUD";
import { PixelText } from "../../components/PixelText";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { Sprite } from "../../components/Sprite";
import { Wipe } from "../../components/Transitions";
import { progress } from "../../lib/game";
import { colors } from "../../lib/palette";
import { fitTextScale, snap } from "../../lib/pixel";
import { coin, slime } from "../../lib/sprites";
import { buildTimeline, loopFade, sceneAt } from "../../lib/timeline";
import { wrap } from "../../lib/typewriter";
import { factQuestScript, type FactQuestProps } from "./schema";

// FactQuest (step 044): hook card, one "LEVEL n" scene per fact, end card with the outro.
// Scenes come from the script timeline: 0 = hook, 1..N = facts, N+1 = end card (held through
// the outro, where `loop` fades the hook back in so the last frame matches frame 0).

const HOOK_S = 1.5;
const OUTRO_S = 0.5;
/** Frames of the wipe between scenes; scenes cut at its midpoint. */
const WIPE = 12;
/** Typewriter speed, chars/s: twice the estimated reading speed, so the text is whole early. */
const TYPE_CPS = 30;
/** Frames of the sprite's hop when a level starts. */
const HOP = 10;
const SPRITE = 12;
const HEARTS = 3;
const GAP = 24;

export const timelineOf = (props: FactQuestProps, fps: number) =>
  buildTimeline({ ...factQuestScript(props), fps, hookSeconds: HOOK_S, outroSeconds: OUTRO_S, loop: props.loop });

type Colors = typeof colors;
type Area = ReturnType<typeof scriptAreas>["hook"];

const Level = ({ n, total, title, start, area, c }: { n: number; total: number; title?: string; start: number; area: Area; c: Colors }) => {
  const frame = useCurrentFrame();
  // The sprite hops once the wipe has uncovered the level, in whole sprite pixels.
  const lift = snap(Math.sin(Math.PI * progress(frame, start + WIPE / 2, HOP)) * 6 * SPRITE, SPRITE);
  return (
    <div style={{ position: "absolute", ...area, display: "flex", flexDirection: "column", alignItems: "center", gap: GAP }}>
      <HUD hearts={HEARTS} maxHearts={HEARTS} score={n * 100} level={n / total} cells={total * 3} width={area.width} />
      <PixelText text={`LEVEL ${n}`} scale={6} color={c.primary} />
      {/* Whole, not typed: centred text would shift while it grows. 24 chars fit one line. */}
      {title && <PixelText text={title} scale={4} color={c.secondary} />}
      <div style={{ display: "flex", alignItems: "flex-end", gap: GAP, transform: `translateY(${-lift}px)` }}>
        {/* 042: swap slime for the CC0 mascot and play the level-up sfx here (src/assets.ts). */}
        <Sprite art={slime} scale={SPRITE} fps={3} />
        <Sprite art={coin} scale={SPRITE / 2} />
      </div>
    </div>
  );
};

const EndCard = ({ outro, note, opacity, c }: { outro: string; note?: string; opacity: number; c: Colors }) => {
  const { hook: area, captions: band } = scriptAreas();
  const s = outro.normalize("NFC");
  const coinPx = 8 * (SPRITE / 2);
  const scale = fitTextScale((cols) => wrap(s, cols).length, area.width, area.height - coinPx - GAP, 6);
  return (
    <AbsoluteFill style={{ opacity }}>
      <div
        style={{
          position: "absolute",
          ...area,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          textAlign: "center",
          gap: GAP,
        }}
      >
        <Sprite art={coin} scale={SPRITE / 2} />
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

export const FactQuest = (props: FactQuestProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const timeline = useMemo(() => timelineOf(props, fps), [props, fps]);
  const c = { ...colors, ...props.palette };
  const total = props.facts.length;
  const scene = sceneAt(timeline.scenes, frame);
  const level = scene && scene.index >= 1 && scene.index <= total ? scene : undefined;
  const end = timeline.scenes[total + 1];
  return (
    <AbsoluteFill style={{ backgroundColor: c.background }}>
      {level && (
        <Level
          n={level.index}
          total={total}
          title={props.facts[level.index - 1].title}
          start={level.startFrame}
          area={scriptAreas().hook}
          c={c}
        />
      )}
      {/* Fact text types into the caption band (sound-off captions). */}
      {level && <Captions timeline={timeline} speed={TYPE_CPS} />}
      {frame >= end.startFrame && (
        <EndCard
          outro={props.outro}
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
      <CRTOverlay />
      <SafeZoneGuide show={!!props.safeZone} />
      {props.voice?.audioSrc && <Html5Audio src={props.voice.audioSrc} />}
    </AbsoluteFill>
  );
};
