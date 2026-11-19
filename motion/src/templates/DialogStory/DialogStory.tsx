import { useMemo } from "react";
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { assetById } from "../../assets";
import { scriptAreas } from "../../brand";
import { CRTOverlay } from "../../components/CRTOverlay";
import { DialogBox } from "../../components/DialogBox";
import { HookCard } from "../../components/HookCard";
import { MusicBed } from "../../components/MusicBed";
import { PixelText } from "../../components/PixelText";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { Sprite } from "../../components/Sprite";
import { Wipe } from "../../components/Transitions";
import { EndCard } from "../../endcards/EndCard";
import { CARD_S } from "../../endcards/schema";
import { spokenLines } from "../../lib/duck";
import { colors } from "../../lib/palette";
import { snap } from "../../lib/pixel";
import { buildTimeline, fitEndCard, loopFade, sceneAt } from "../../lib/timeline";
import { BEAT, type DialogStoryProps, dialogStoryScript, sceneRoles, talkSpan } from "./schema";

// DialogStory (step 047): an RPG-style dialogue between two characters. Hook card with the cast
// (both portraits) under it, then one scene per dialogue line: the two portraits in the top half,
// the speaker's lit and bouncing while it talks, the listener dimmed; the line types into a dialog
// box with the speaker's name tag in the band below (`sfx-select` as it opens, after a short beat
// with the empty box). An optional moral ends it in a box without a name tag (`sfx-confirm`).
// Scenes come from the script timeline: 0 = hook, 1..N = lines, N+1 = moral, then the pixel end
// card (step 137, `tagline`) in the outro, where `loop` fades the hook and cast back in over its
// last frames so the last frame matches frame 0.

const HOOK_S = 1.5;
const OUTRO_S = 0.5;
/** Frames of the wipe after the hook and before the moral; scenes cut at its midpoint. */
const WIPE = 12;
/** Typewriter speed, chars/s: twice the estimated reading speed, so the text is whole early. */
const TYPE_CPS = 30;
/** Portrait sprite height to aim for, px (whole sprite scales). */
const PORTRAIT_PX = 160;
/** Portrait frame: border and inner square, px; the room above the sprite is for the bounce. */
const FRAME_BORDER = 8;
const FRAME_INNER = 224;
/** Bounces per second while talking, and their height in sprite pixels. */
const HOPS_PER_S = 4;
const HOP = 3;
const BOX_SCALE = 4;
const GAP = 24;
const DEFAULT_SPRITE = ["mascot", "slime"] as const;

export const timelineOf = (props: DialogStoryProps, fps: number) =>
  fitEndCard(
      (outroSeconds) => buildTimeline({ ...dialogStoryScript(props), fps, hookSeconds: HOOK_S, outroSeconds, loop: props.loop }),
      OUTRO_S,
      (t) => t.outroStart,
      CARD_S.pixel,
      fps,
    );

type Colors = typeof colors;
type Area = ReturnType<typeof scriptAreas>["hook"];
/** Speaker index and the frames it talks; none = nobody talks (hook, moral). */
type Talk = { speaker: 0 | 1; span: [number, number] };

const Portrait = ({ p, index, talk, c }: { p: DialogStoryProps; index: 0 | 1; talk?: Talk; c: Colors }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const who = p.characters[index];
  const sheet = assetById(who.sprite ?? DEFAULT_SPRITE[index]);
  const px = Math.max(1, Math.floor(Math.min(PORTRAIT_PX / sheet.frameHeight, FRAME_INNER / sheet.frameWidth)));
  const speaking = talk?.speaker === index;
  const [from, to] = speaking ? talk.span : [0, 0];
  const talking = frame >= from && frame < to;
  // Hops up and down while talking, in whole sprite pixels.
  const lift = talking ? snap(Math.abs(Math.sin((Math.PI * HOPS_PER_S * (frame - from)) / fps)) * HOP * px, px) : 0;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: GAP / 2, opacity: talk && !speaking ? 0.5 : 1 }}>
      <div
        style={{
          width: FRAME_INNER,
          height: FRAME_INNER,
          border: `${FRAME_BORDER}px solid ${speaking ? c.accent : c.text}`,
          backgroundColor: c.background,
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "center",
          overflow: "hidden",
        }}
      >
        {/* The right character faces left; the sprite animates (mouth, blink) only while talking. */}
        <div style={{ transform: `translateY(${-lift}px) scaleX(${who.side === "left" ? 1 : -1})` }}>
          <Sprite {...sheet} scale={px} fps={8} frame={talking ? undefined : 0} />
        </div>
      </div>
      <PixelText text={who.name} scale={3} color={speaking ? c.accent : c.secondary} />
    </div>
  );
};

/** Both portraits in `area`, each on its character's side. */
const Cast = ({ p, area, talk, opacity, c }: { p: DialogStoryProps; area: Area; talk?: Talk; opacity: number; c: Colors }) => {
  const left = p.characters[0].side === "left" ? 0 : 1;
  return (
    <div style={{ position: "absolute", ...area, opacity, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
      <Portrait p={p} index={left} talk={talk} c={c} />
      <Portrait p={p} index={left ? 0 : 1} talk={talk} c={c} />
    </div>
  );
};

/** One sound from `from` on (stills are silent). */
const Sfx = ({ id, from }: { id: "sfx-select" | "sfx-confirm"; from: number }) => (
  <Sequence from={from} layout="none">
    <Html5Audio src={assetById(id).src} />
  </Sequence>
);

export const DialogStory = (props: DialogStoryProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const timeline = useMemo(() => timelineOf(props, fps), [props, fps]);
  const roles = useMemo(() => sceneRoles(props), [props]);
  const c = { ...colors, ...props.palette };
  const { scenes } = timeline;
  const last = scenes[scenes.length - 1];
  // The last scene stays up under the end card (no scene in the outro).
  const scene = sceneAt(scenes, frame) ?? (frame >= last.startFrame ? last : undefined);
  const role = scene ? roles[scene.index] : undefined;
  const fade = loopFade(frame, timeline);
  const { hook: top, captions: band } = scriptAreas();
  const px = BOX_SCALE;
  const talk: Talk | undefined =
    scene && role?.kind === "line"
      ? { speaker: role.speaker, span: talkSpan(timeline, scene.index, TYPE_CPS, fps, props.voice?.lines?.[scene.index].end_s) }
      : undefined;
  const cover = frame < scenes[0].endFrame ? 1 : fade;
  const note = props.citations.length ? props.sourcesNote : undefined;
  return (
    <AbsoluteFill style={{ backgroundColor: c.background }}>
      {/* The cast under the hook, part of the cover; fades back in with it when looping. */}
      {cover > 0 && <Cast p={props} area={band} opacity={cover} c={c} />}
      {scene && role && role.kind !== "hook" && (
        <>
          <Cast p={props} area={top} talk={talk} opacity={1 - fade} c={c} />
          {/* Inset by the box's ring and drop shadow (as Captions): all of it stays in the safe area. */}
          <div style={{ position: "absolute", ...band, padding: px, opacity: 1 - fade }}>
            <DialogBox
              key={scene.index}
              text={scene.text}
              name={role.kind === "line" ? props.characters[role.speaker].name : undefined}
              width={band.width - 4 * px}
              scale={px}
              speed={TYPE_CPS}
              startFrame={scene.startFrame + BEAT}
            />
          </div>
        </>
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
      {/* Wipes into the dialogue and into the moral; lines follow each other in the same box. */}
      {scenes
        .filter((s) => s.index === 1 || roles[s.index].kind === "moral")
        .map((s) => (
          <Wipe
            key={s.index}
            direction={s.index === 1 ? "right" : "left"}
            startFrame={s.startFrame - WIPE / 2}
            duration={WIPE}
            color={s.index === 1 ? c.accent : c.secondary}
          />
        ))}
      {scenes.slice(1).map((s) => (
        <Sfx key={s.index} id={roles[s.index].kind === "moral" ? "sfx-confirm" : "sfx-select"} from={s.startFrame + BEAT} />
      ))}
      <MusicBed id={props.music} lines={spokenLines(props.voice)} />
      <CRTOverlay />
      <SafeZoneGuide show={!!props.safeZone} />
      {props.voice?.audioSrc && <Html5Audio src={props.voice.audioSrc} />}
    </AbsoluteFill>
  );
};
