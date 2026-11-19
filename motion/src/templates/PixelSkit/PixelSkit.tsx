import { useMemo } from "react";
import { AbsoluteFill, Freeze, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { type AssetId, assetById } from "../../assets";
import { scriptAreas } from "../../brand";
import { CRTOverlay } from "../../components/CRTOverlay";
import { DialogBox } from "../../components/DialogBox";
import { HookCard } from "../../components/HookCard";
import { MusicBed } from "../../components/MusicBed";
import { PixelText } from "../../components/PixelText";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { Sprite } from "../../components/Sprite";
import { Flash, Wipe } from "../../components/Transitions";
import { EndCard } from "../../endcards/EndCard";
import { CARD_S } from "../../endcards/schema";
import { pausedLines, spokenLines } from "../../lib/duck";
import type { PixelArt } from "../../lib/game";
import { colors } from "../../lib/palette";
import { buildTimeline, fitEndCard, loopFade, sceneAt } from "../../lib/timeline";
import { type Action, actionPose, BEAT, comicTiming, type PixelSkitProps, pixelSkitScript, SFX, voiceParts } from "./schema";

// PixelSkit (step 047a): the humour template, a short "POV:" sketch. Hook card with the cast
// standing on the ground under it (the cover), then one scene per beat: the cast on stage in the
// top half, the beat's actor playing its action (walk in, hop, shake, fall over, stare, facepalm)
// while the line types into a dialog box in the band below (the speaker's name tag, if any).
// Comic timing (`comicTiming`): the beat before the punchline holds a moment, the punchline's
// `sting` plays as it lands (typed or voiced), and the picture freezes there with a flash. An
// optional tag beat follows, then the pixel end card (step 137, `tagline`, tu) in the outro,
// where `loop` fades the hook and cast back in over its last frames so the last frame matches
// frame 0.

const HOOK_S = 1.5;
const OUTRO_S = 0.5;
/** Frames of the wipe after the hook; scenes cut at its midpoint. */
const WIPE = 12;
/** Typewriter speed, chars/s: twice the estimated reading speed, so the text is whole early. */
const TYPE_CPS = 30;
/** Actor sprite height to aim for, and the widest it may get, px (whole sprite scales). */
const ACTOR_PX = 192;
const ACTOR_W = 288;
/** Ground tile scale (8 px grass tiles). */
const GROUND_PX = 6;
const BOX_SCALE = 4;
const FLASH = 6;
const DEFAULT_SPRITE = ["mascot", "slime"] as const;

/** A hand (palm out) slapped over the face; colours are 8-bit palette indices. */
const hand: PixelArt = {
  colors: { K: 0, Y: 4 },
  frames: [[".K.K.K.", "KYKYKYK", "KYYYYYK", "KYYYYYK", ".KYYYK.", "..KKK.."]],
};

export const timelineOf = (props: PixelSkitProps, fps: number) =>
  comicTiming(
    fitEndCard(
      (outroSeconds) => buildTimeline({ ...pixelSkitScript(props), fps, hookSeconds: HOOK_S, outroSeconds, loop: props.loop }),
      OUTRO_S,
      (t) => t.outroStart,
      CARD_S.pixel,
      fps,
    ),
    props,
    TYPE_CPS,
    fps,
  );

type Colors = typeof colors;
type Area = ReturnType<typeof scriptAreas>["hook"];
/** Who acts and from which frame; none = everybody stands still (the cover). */
type Act = { actor: number; action: Action; start: number };

const Actor = ({ p, index, act }: { p: PixelSkitProps; index: number; act?: Act }) => {
  const frame = useCurrentFrame();
  const sheet = assetById(p.cast[index].sprite ?? DEFAULT_SPRITE[index]);
  const px = Math.max(1, Math.floor(Math.min(ACTOR_PX / sheet.frameHeight, ACTOR_W / sheet.frameWidth)));
  const side = index ? "right" : "left";
  const acting = act?.actor === index;
  const pose = acting ? actionPose(act.action, frame - act.start, side) : undefined;
  return (
    // Tips over its outer bottom corner, so a fallen actor lies on the ground.
    <div
      style={{
        position: "relative",
        transform: pose ? `translate(${pose.dx * px}px, ${pose.dy * px}px) rotate(${pose.tilt}deg)` : undefined,
        transformOrigin: `${side === "left" ? 0 : 100}% 100%`,
      }}
    >
      {!!pose?.dots && (
        <div style={{ position: "absolute", bottom: "100%", width: "100%", display: "flex", justifyContent: "center", paddingBottom: px }}>
          <PixelText text={".".repeat(pose.dots)} scale={4} color={p.palette?.text ?? colors.text} />
        </div>
      )}
      {/* The second actor faces the first; it animates only while it acts. */}
      <div style={{ position: "relative", transform: index ? "scaleX(-1)" : undefined }}>
        <Sprite {...sheet} scale={px} fps={8} frame={pose?.animate ? undefined : 0} />
        {pose?.hand && (
          <div style={{ position: "absolute", top: Math.round(sheet.frameHeight / 6) * px, width: "100%", display: "flex", justifyContent: "center" }}>
            <Sprite art={hand} scale={px} />
          </div>
        )}
      </div>
    </div>
  );
};

/** The cast standing on a strip of grass at the bottom of `area`. */
const Stage = ({ p, area, act, opacity }: { p: PixelSkitProps; area: Area; act?: Act; opacity: number }) => {
  const tiles = assetById("tiles");
  const ground = tiles.frameHeight * GROUND_PX;
  return (
    <div style={{ position: "absolute", ...area, opacity }}>
      <div
        style={{ position: "absolute", left: 0, right: 0, bottom: ground, display: "flex", alignItems: "flex-end", justifyContent: "space-around" }}
      >
        {p.cast.map((_, i) => (
          <Actor key={i} p={p} index={i} act={act} />
        ))}
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, display: "flex", overflow: "hidden" }}>
        {Array.from({ length: Math.ceil(area.width / (tiles.frameWidth * GROUND_PX)) }, (_, i) => (
          <Sprite key={i} {...tiles} scale={GROUND_PX} frame={0} />
        ))}
      </div>
    </div>
  );
};

/** One sound from `from` on (stills are silent). */
const Sfx = ({ id, from }: { id: AssetId; from: number }) => (
  <Sequence from={from} layout="none">
    <Html5Audio src={assetById(id).src} />
  </Sequence>
);

const sfxId = (name: (typeof SFX)[number]) => `sfx-${name}` as const;

export const PixelSkit = (props: PixelSkitProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { timeline, pauses, land, freezeStart, freezeEnd } = useMemo(() => timelineOf(props, fps), [props, fps]);
  const c: Colors = { ...colors, ...props.palette };
  const { scenes } = timeline;
  const last = scenes[scenes.length - 1];
  // The last scene stays up under the end card (no scene in the outro).
  const scene = sceneAt(scenes, frame) ?? (frame >= last.startFrame ? last : undefined);
  const beat = scene && scene.index ? props.beats[scene.index - 1] : undefined;
  const fade = loopFade(frame, timeline);
  const { hook: top, captions: band } = scriptAreas();
  const cover = frame < scenes[0].endFrame ? 1 : fade;
  const note = props.citations.length ? props.sourcesNote : undefined;
  const voice = props.voice?.audioSrc;
  return (
    <AbsoluteFill style={{ backgroundColor: c.background }}>
      {/* The cast under the hook, part of the cover; fades back in with it when looping. */}
      {cover > 0 && <Stage p={props} area={band} opacity={cover} />}
      <Freeze frame={freezeStart} active={(f) => f >= freezeStart && f < freezeEnd}>
        {scene && beat && (
          <>
            <Stage
              p={props}
              area={top}
              act={{ actor: beat.speaker ?? 0, action: beat.action, start: scene.startFrame + BEAT }}
              opacity={1 - fade}
            />
            {/* Inset by the box's ring and drop shadow (as Captions): all of it stays in the safe area. */}
            <div style={{ position: "absolute", ...band, padding: BOX_SCALE, opacity: 1 - fade }}>
              <DialogBox
                key={scene.index}
                text={scene.text}
                name={beat.speaker === undefined ? undefined : props.cast[beat.speaker].name}
                width={band.width - 4 * BOX_SCALE}
                scale={BOX_SCALE}
                speed={TYPE_CPS}
                startFrame={scene.startFrame + BEAT}
              />
            </div>
          </>
        )}
      </Freeze>
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
            <EndCard style="pixel" tagline={props.tagline} cameo="mascot" note={note} accent="brand" address={"tu"} pixelate={1} />
          </Sequence>
        </AbsoluteFill>
      )}
      <HookCard text={props.hook} timeline={timeline} color={c.primary} />
      <Wipe direction="right" startFrame={scenes[1].startFrame - WIPE / 2} duration={WIPE} color={c.accent} />
      {freezeEnd > freezeStart && <Flash startFrame={freezeStart} duration={FLASH} color={c.text} />}
      {scenes.slice(1).map((s) => {
        const sfx = props.beats[s.index - 1].sfx;
        return sfx && <Sfx key={s.index} id={sfxId(sfx)} from={s.startFrame + BEAT} />;
      })}
      {props.sting !== "none" && <Sfx id={sfxId(props.sting)} from={land} />}
      <MusicBed id={props.music} lines={pausedLines(spokenLines(props.voice) ?? [], pauses, fps)} />
      <CRTOverlay />
      <SafeZoneGuide show={!!props.safeZone} />
      {/* The voice pauses through the hold and the freeze: plain audio in parts around them. */}
      {voice &&
        voiceParts(pauses).map((v, i) => (
          <Sequence key={i} from={v.from} durationInFrames={v.frames} layout="none">
            <Html5Audio src={voice} trimBefore={v.trimBefore} />
          </Sequence>
        ))}
    </AbsoluteFill>
  );
};
