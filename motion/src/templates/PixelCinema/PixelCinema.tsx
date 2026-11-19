// PixelCinema (step 143): a macroBody story told as a short film over one living pixel-art set
// (src/cinema: a rainy city at 21 h, a dawn run on the pier, the fridge at night), with clean
// editorial type on top. Hook: a belief struck through in red, then the real line (the beam
// comes on); 2-4 numbered chips pointing into the set while the camera pushes in toward the
// light; one lightning beat cuts to a white / black silhouette frame; a payoff stat counting
// up or the app card floating in over the darkened set; then the cinema end card (the beam
// sweeps onto the mB tile, the rain goes on).
import { useMemo } from "react";
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { type AssetId, assetById } from "../../assets";
import { Stage } from "../../cinema/Stage";
import { AppCard, Chip, Headline, Stat, Tag } from "../../cinema/type";
import { MusicBed } from "../../components/MusicBed";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { EndCard } from "../../endcards/EndCard";
import { ACCENTS } from "../../endcards/schema";
import { spokenLines } from "../../lib/duck";
import { loopFade, type Scene, type Timeline } from "../../lib/timeline";
import { easeOut, span } from "../../voxel/anim.ts";
import { anchorPx, beamOf, cameraAt, chipTimes, flashAt, flashTimes, hookTimes, openOf, payoffTimes, sceneIndex } from "./layout";
import { type PixelCinemaProps, timelineOf, titleOf } from "./schema";

/** Tops of the text blocks (px): the upper third, under the safe area's top (269). */
const TITLE_Y = 300;
const CHIP_Y = 490;
const STAT_Y = 520;
const CARD_Y = 500;

/** The set as it is at `frame` (camera, beam, lightning, dim). */
const SetAt = ({ p, frame, t, fps }: { p: PixelCinemaProps; frame: number; t: Timeline; fps: number }) => {
  const i = sceneIndex(t, p.beats.length + 1, frame);
  const s = t.scenes[i];
  const f = frame - s.startFrame;
  const b = i ? p.beats[i - 1] : null;
  const { white, silhouette } = flashAt(p, t, frame, fps);
  const dim = b && b.kind !== "chip" ? easeOut(span(f, 0, Math.round(0.4 * fps))) : 0;
  const { power, sweep } = beamOf(p, t, frame, fps);
  const { view, cam } = cameraAt(p, t, frame, fps);
  return <Stage scene={p.scene} view={view} t={frame / fps} cam={cam} beam={power} sweep={sweep} flash={silhouette} whiteout={white} dim={dim} open={openOf(p, t, frame, fps)} />;
};

/** The text over scene `i`, `f` frames into it. */
const Words = ({ p, i, f, frame, fps, t }: { p: PixelCinemaProps; i: number; f: number; frame: number; fps: number; t: Timeline }) => {
  if (i === 0) {
    const ht = hookTimes(p, t.scenes[0].endFrame - t.scenes[0].startFrame, fps);
    return p.hook.strike ? (
      <>
        <Headline text={p.hook.strike} y={TITLE_Y} f={f} start={-99} size={70} strike={easeOut(span(f, ht.strike, Math.round(0.25 * fps)))} />
        <Headline text={p.hook.line} y={TITLE_Y + 96} f={f} start={ht.line} size={96} />
      </>
    ) : (
      <Headline text={p.hook.line} y={TITLE_Y + 40} f={f} start={-99} size={96} />
    );
  }
  const b = p.beats[i - 1];
  if (b.kind === "chip") {
    const ct = chipTimes(fps);
    const n = p.beats.slice(0, i).filter((x) => x.kind === "chip").length;
    const title = titleOf(p.beats, i - 1);
    const shot = cameraAt(p, t, frame, fps);
    const target = b.point ? anchorPx(p, shot.view, b.point, shot.cam, frame / fps) : undefined;
    return (
      <>
        {title && <Headline text={title} y={TITLE_Y} f={f} start={b.title ? ct.title : -99} size={68} flash={flashAt(p, t, frame, fps).silhouette} />}
        <Chip n={n} text={b.text} x={540} y={CHIP_Y} f={f} start={ct.chip} target={target} leaderAt={ct.leader} leaderLen={ct.leaderLen} />
      </>
    );
  }
  const pt = payoffTimes(fps);
  return (
    <>
      <Headline text={b.title} y={TITLE_Y} f={f} start={pt.title} size={68} />
      {b.kind === "stat" ? (
        <Stat value={b.value} unit={b.unit} label={b.label} y={STAT_Y} f={f} start={pt.value} count={pt.count} />
      ) : (
        <AppCard value={b.value} unit={b.unit} accent={ACCENTS[p.accent]} y={CARD_Y} f={f} start={pt.value} count={pt.count} />
      )}
    </>
  );
};

/** SFX cues (frame, asset, volume) for the whole film. */
const cuesOf = (p: PixelCinemaProps, scenes: Scene[], endStart: number, fps: number) => {
  const cues: [number, AssetId, number][] = [];
  const hook = hookTimes(p, scenes[0].endFrame - scenes[0].startFrame, fps);
  if (p.hook.strike) cues.push([hook.strike, "sfx-swish", 0.45], [hook.line, "sfx-pop", 0.35]);
  p.beats.forEach((b, k) => {
    const s = scenes[k + 1];
    if (b.kind === "chip") {
      cues.push([s.startFrame + chipTimes(fps).chip, "sfx-pop", 0.4]);
      if (b.flash) cues.push([s.startFrame + flashTimes(s.endFrame - s.startFrame, fps).at, "sfx-thunder", 0.9]);
    } else {
      const pt = payoffTimes(fps);
      cues.push(b.kind === "stat" ? [s.startFrame + pt.value + pt.count, "sfx-chime", 0.5] : [s.startFrame + pt.value, "sfx-swish", 0.45]);
    }
  });
  cues.push([endStart - Math.round(0.3 * fps), "sfx-swish", 0.45]);
  return cues;
};

export const PixelCinema = (props: PixelCinemaProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { timeline, endStart } = useMemo(() => timelineOf(props, fps), [props, fps]);
  const scenes = timeline.scenes.slice(0, props.beats.length + 1);
  const i = sceneIndex(timeline, scenes.length, frame);
  const f = frame - scenes[i].startFrame;
  const chips = props.beats.filter((b) => b.kind === "chip").length;
  const cues = useMemo(() => cuesOf(props, timeline.scenes, endStart, fps), [props, timeline, endStart, fps]);
  const loop = loopFade(frame, timeline);
  return (
    <AbsoluteFill style={{ background: "#07081A" }}>
      {frame < endStart ? (
        <>
          <SetAt p={props} frame={frame} t={timeline} fps={fps} />
          <Words p={props} i={i} f={f} frame={frame} fps={fps} t={timeline} />
          {props.tag && i >= 1 && i <= chips && <Tag text={props.tag} f={frame - scenes[1].startFrame} />}
        </>
      ) : (
        <Sequence from={endStart} layout="none">
          <EndCard style="cinema" tagline={props.outro} accent={props.accent} cameo={props.scene} address={props.address} pixelate={2} />
        </Sequence>
      )}
      {loop > 0 && (
        // Loop on: the hook's first frame comes back over the last frames.
        <AbsoluteFill style={{ opacity: loop }}>
          <SetAt p={props} frame={0} t={timeline} fps={fps} />
          <Words p={props} i={0} f={0} frame={0} fps={fps} t={timeline} />
        </AbsoluteFill>
      )}
      {cues.map(([at, id, volume], k) => (
        <Sequence key={k} from={Math.max(0, at)} durationInFrames={id === "sfx-thunder" ? 90 : 45} layout="none">
          <Html5Audio src={assetById(id).src} volume={volume} />
        </Sequence>
      ))}
      <MusicBed id={props.music} lines={spokenLines(props.voice)} />
      <SafeZoneGuide show={!!props.safeZone} />
      {props.voice?.audioSrc && <Html5Audio src={props.voice.audioSrc} />}
    </AbsoluteFill>
  );
};
