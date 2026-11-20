import { Fragment, useMemo } from "react";
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { assetById } from "../../assets";
import { scriptAreas } from "../../brand";
import { Captions } from "../../components/Captions";
import { CRTOverlay } from "../../components/CRTOverlay";
import { HookCard } from "../../components/HookCard";
import { HUD } from "../../components/HUD";
import { MusicBed } from "../../components/MusicBed";
import { PixelText } from "../../components/PixelText";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { Sfx } from "../../components/Sfx";
import { Sprite } from "../../components/Sprite";
import { Flash, Wipe } from "../../components/Transitions";
import { EndCard } from "../../endcards/EndCard";
import { CARD_S } from "../../endcards/schema";
import { spokenLines } from "../../lib/duck";
import { progress } from "../../lib/game";
import { colors } from "../../lib/palette";
import { snap } from "../../lib/pixel";
import { buildTimeline, fitEndCard, loopFade, sceneAt } from "../../lib/timeline";
import { type BossBattleProps, bossBattleScript, foe, type Health, healthSteps, type Side } from "./schema";

// BossBattle (step 045): hook card (with "A VS B" in the band), one "ROUND n" scene per
// argument, then the verdict. Scenes come from the script timeline: 0 = hook, 1..N = rounds,
// N+1 = verdict, then the pixel end card (step 137, `tagline`) in the outro, where `loop`
// fades the hook back in over its last frames so the last frame matches frame 0. In each round the attacker dashes in and lands a hit (flash + sfx, the foe's
// health bar drops); in the verdict the winner knocks the loser out, or a draw is called.

const HOOK_S = 1.5;
const OUTRO_S = 0.5;
/** Frames of the wipe between scenes; scenes cut at its midpoint. */
const WIPE = 12;
/** Typewriter speed, chars/s: twice the estimated reading speed, so the text is whole early. */
const TYPE_CPS = 30;
/** Frames from a scene's start to its hit: the wipe has uncovered the arena, the attacker dashed. */
const HIT = WIPE / 2 + 12;
/** The hit's level from the voice's (Sfx `db`). */
const HIT_DB = -1;
/** Frames of the attacker's dash in (and back out after the hit). */
const DASH = 8;
const FLASH = 8;
/** Frames the hit fighter shakes. */
const SHAKE = 12;
/** Frames from the knockout to the verdict jingle. */
const JINGLE = 15;
/** Fighter sprite height to aim for, px (whole sprite scales). */
const FIGHTER_PX = 160;
const HEARTS = 3;
const CELLS = 12;
const GAP = 24;

export const timelineOf = (props: BossBattleProps, fps: number) =>
  fitEndCard(
      (outroSeconds) => buildTimeline({ ...bossBattleScript(props), fps, hookSeconds: HOOK_S, outroSeconds, loop: props.loop }),
      OUTRO_S,
      (t) => t.outroStart,
      CARD_S.pixel,
      fps,
    );

type Colors = typeof colors;
type Fighter = BossBattleProps["left"];
const DEFAULT_SPRITE = { left: "mascot", right: "slime" } as const;

const FighterColumn = (p: {
  side: Side;
  fighter: Fighter;
  health: Health;
  /** Frame of this scene's hit, and who lands it (none: a draw). */
  hit: number;
  attacker?: Side;
  width: number;
  c: Colors;
}) => {
  const frame = useCurrentFrame();
  const sheet = assetById(p.fighter.sprite ?? DEFAULT_SPRITE[p.side]);
  const px = Math.max(1, Math.floor(FIGHTER_PX / sheet.frameHeight));
  const toward = p.side === "left" ? 1 : -1;
  let dx = 0;
  if (p.attacker === p.side) {
    // Dash toward the foe, peaking on the hit frame, in whole sprite pixels.
    dx = toward * snap(Math.sin(Math.PI * progress(frame, p.hit - DASH, 2 * DASH)) * 12 * px, px);
  } else if (p.attacker && frame >= p.hit && frame < p.hit + SHAKE) {
    dx = (Math.floor((frame - p.hit) / 2) % 2 ? 1 : -1) * 2 * px;
  }
  const own = p.health[p.side];
  return (
    <div style={{ width: p.width, display: "flex", flexDirection: "column", alignItems: p.side === "left" ? "flex-start" : "flex-end", gap: GAP }}>
      <PixelText text={p.fighter.name} scale={3} color={p.c.secondary} />
      <HUD
        hearts={Math.ceil(own * HEARTS)}
        maxHearts={HEARTS}
        // Damage dealt so far.
        score={Math.round((1 - p.health[foe(p.side)]) * 1000)}
        level={own}
        cells={CELLS}
        width={p.width}
      />
      {/* The right fighter faces left; a knocked-out fighter fades. */}
      <div style={{ transform: `translateX(${dx}px) scaleX(${toward})`, opacity: own > 0 ? 1 : 0.4 }}>
        <Sprite {...sheet} scale={px} fps={4} />
      </div>
    </div>
  );
};

const Arena = (p: BossBattleProps & { scene: number; start: number; steps: Health[]; opacity: number; c: Colors }) => {
  const frame = useCurrentFrame();
  const area = scriptAreas().hook;
  const verdict = p.scene > p.rounds.length;
  const hit = p.start + HIT;
  const attacker = verdict ? (p.verdict.winner === "draw" ? undefined : p.verdict.winner) : p.rounds[p.scene - 1].attacker;
  const health = p.steps[frame < hit ? p.scene - 1 : p.scene];
  const title = !verdict
    ? `ROUND ${p.scene}`
    : frame < hit
      ? "VERDICT"
      : p.verdict.winner === "draw"
        ? "DRAW!"
        : `${p[p.verdict.winner].name} WINS!`;
  const width = Math.floor((area.width - GAP) / 2);
  return (
    <div
      style={{ position: "absolute", ...area, opacity: p.opacity, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 2 * GAP }}
    >
      {/* Bounded by the schema: 16-char names, so every title fits one line. */}
      <PixelText text={title} scale={4} color={p.c.primary} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", width: area.width }}>
        {(["left", "right"] as const).map((side) => (
          <FighterColumn key={side} side={side} fighter={p[side]} health={health} hit={hit} attacker={attacker} width={width} c={p.c} />
        ))}
      </div>
    </div>
  );
};

export const BossBattle = (props: BossBattleProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const timeline = useMemo(() => timelineOf(props, fps), [props, fps]);
  const steps = useMemo(() => healthSteps(props), [props]);
  const c = { ...colors, ...props.palette };
  const { scenes } = timeline;
  const last = scenes[scenes.length - 1];
  // The verdict stays up under the end card (no scene in the outro).
  const scene = sceneAt(scenes, frame) ?? (frame >= last.startFrame ? last : undefined);
  const fade = loopFade(frame, timeline);
  const band = scriptAreas().captions;
  const versus = frame < scenes[0].endFrame ? 1 : fade;
  const knockout = props.verdict.winner !== "draw";
  const note = props.citations.length ? props.sourcesNote : undefined;
  const lines = spokenLines(props.voice);
  return (
    <AbsoluteFill style={{ backgroundColor: c.background }}>
      {scene && scene.index > 0 && <Arena {...props} scene={scene.index} start={scene.startFrame} steps={steps} opacity={1 - fade} c={c} />}
      {/* Each argument (and the verdict) types into the caption band (sound-off captions). */}
      <Captions timeline={timeline} speed={TYPE_CPS} />
      {/* "A VS B" under the hook, part of the cover; fades back in with it when looping. */}
      {versus > 0 && (
        <div style={{ position: "absolute", ...band, opacity: versus, display: "flex", justifyContent: "center", textAlign: "center" }}>
          <PixelText text={`${props.left.name} VS ${props.right.name}`} scale={4} color={c.accent} maxWidth={band.width} />
        </div>
      )}
      {note && frame >= last.startFrame && (
        <div
          style={{ position: "absolute", ...band, opacity: 1 - fade, display: "flex", alignItems: "flex-end", justifyContent: "center", textAlign: "center" }}
        >
          <PixelText text={note} scale={3} color={c.text} maxWidth={band.width} />
        </div>
      )}
      {/* The pixel end card (step 137) after the last scene; the hook fades back in over its end. */}
      {frame >= timeline.outroStart && (
        <AbsoluteFill style={{ opacity: 1 - fade }}>
          <Sequence from={timeline.outroStart} layout="none">
            <EndCard style="pixel" tagline={props.tagline} cameo="mascot" note={note} accent="brand" address={"vous"} pixelate={1} />
          </Sequence>
        </AbsoluteFill>
      )}
      <HookCard text={props.hook} timeline={timeline} color={c.primary} />
      {scenes.slice(1).map((s) => (
        <Wipe
          key={s.index}
          direction={s.index % 2 ? "right" : "left"}
          startFrame={s.startFrame - WIPE / 2}
          duration={WIPE}
          color={s.index % 2 ? c.accent : c.secondary}
        />
      ))}
      {/* A hit per round, and the knockout; the verdict jingle after it (at once for a draw). The hit
          lands on a spoken line: 1 dB under the other cues keeps the voice 12 LU over it (step 161). */}
      {scenes.slice(1, knockout ? undefined : -1).map((s) => (
        <Fragment key={s.index}>
          <Flash startFrame={s.startFrame + HIT} duration={FLASH} color={c.text} />
          <Sfx id="sfx-hit" at={s.startFrame + HIT} db={HIT_DB} lines={lines} />
        </Fragment>
      ))}
      <Sfx id="sfx-confirm" at={last.startFrame + HIT + (knockout ? JINGLE : 0)} lines={lines} />
      <MusicBed id={props.music} lines={lines} />
      <CRTOverlay />
      <SafeZoneGuide show={!!props.safeZone} />
      {props.voice?.audioSrc && <Html5Audio src={props.voice.audioSrc} />}
    </AbsoluteFill>
  );
};
