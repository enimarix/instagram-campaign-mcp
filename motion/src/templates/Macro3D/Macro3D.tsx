// Macro3D (step 154): a dark photoreal 3D macro explainer. The Blender plates (food and body
// pieces in a black studio void, glossy rims, shallow depth of field, a slow macro move per
// shot, a hard cut every 1-3 s) play under word-by-word captions with the blue selection box on
// the key word, small honest labels, a counter when a number is told, and Marco, the macroBody
// coach, reacting to every line in the corner. Ends on the Macro 3D end card.
import { useMemo } from "react";
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { MusicBed } from "../../components/MusicBed";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { EndCard } from "../../endcards/EndCard";
import { ACCENTS } from "../../endcards/schema";
import { spokenLines } from "../../lib/duck";
import { loopFade } from "../../lib/timeline";
import { Callout, Caption, Counter, Label, Plate } from "../../macro3d/kit";
import { Marco } from "../../macro3d/Presenter";
import { autoLabel, LABELS } from "../../macro3d/subjects.ts";
import { mouthAt } from "../../macro3d/words.ts";
import { easeOut, span } from "../../voxel/anim.ts";
import { counterText, poseAt, shotAt, shotsOf } from "./layout";
import { type Macro3DProps, timelineOf } from "./schema";

/** Marco's box: bottom-right, the bust cut by the frame's edge, clear of the right rail's edge. */
const MARCO = { left: 560, top: 1352, width: 440 };

/** Blinks: 4 frames every 2.7-4 s. */
const blinking = (frame: number, fps: number) => {
  const period = Math.round(3.3 * fps);
  const at = frame % period;
  return at >= period - 4 && at < period - 1;
};

export const Macro3D = (props: Macro3DProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { timeline, endStart, timings } = useMemo(() => timelineOf(props, fps), [props, fps]);
  const shots = useMemo(() => shotsOf(props, timeline, endStart, fps), [props, timeline, endStart, fps]);
  const t = frame / fps;
  const shot = shotAt(shots, frame);
  const i = shot.scene;
  const scene = props.scenes[i];
  const sceneStart = timeline.scenes[i].startFrame;
  const sceneEnd = i + 1 < props.scenes.length ? timeline.scenes[i + 1].startFrame : endStart;
  const f = frame - sceneStart;
  const { pose, since } = poseAt(props, shots, frame);
  // The line being said (scenes, then the outro over the end card): the mouth follows it, in steps of 3 frames.
  const said = timings.findIndex((x) => t >= x.start_s && t < x.end_s);
  const step = (Math.floor(frame / 3) * 3) / fps;
  const mouth = said < 0 ? "closed" : mouthAt(timings[said].text ?? "", timings[said].start_s, timings[said].end_s, step);
  const pop = easeOut(span(frame, since, 5));
  const label = scene.label ?? autoLabel(shot.subject, shot.look);
  const loop = loopFade(frame, timeline);
  return (
    <AbsoluteFill style={{ background: "#050506" }}>
      {frame < endStart ? (
        <>
          <Plate src={props.plate} />
          <Caption line={scene.line} keyWord={scene.key} start={timings[i].start_s} end={timings[i].end_s} t={t} fps={fps} />
          {label !== "none" && <Label key={`l${i}`} text={LABELS[label]} f={f} />}
          {scene.callout && <Callout text={scene.callout} f={f} side={i % 2 ? 1 : -1} />}
          {scene.counter && (
            <Counter value={counterText(scene.counter, easeOut(span(f, 6, Math.round((sceneEnd - sceneStart) * 0.7))))} unit={scene.counter.unit} color={ACCENTS[props.accent]} f={f} />
          )}
          <div style={{ position: "absolute", ...MARCO, height: MARCO.width * 1.3, transform: `translateY(${4 * Math.sin(t * 2.4) + (1 - pop) * 14}px) scale(${0.97 + 0.03 * pop})`, transformOrigin: "50% 100%", filter: "drop-shadow(0 18px 30px rgba(0,0,0,0.55))" }}>
            <Marco pose={pose} mouth={mouth} blink={blinking(frame, fps)} />
          </div>
        </>
      ) : (
        <Sequence from={endStart} layout="none">
          <EndCard style="macro3d" tagline={props.outro} accent={props.accent} address={props.address} pixelate={1} />
        </Sequence>
      )}
      {loop > 0 && (
        <AbsoluteFill style={{ opacity: loop }}>
          <Plate src={props.plate} />
        </AbsoluteFill>
      )}
      <MusicBed id={props.music} lines={spokenLines(props.voice)} />
      <SafeZoneGuide show={!!props.safeZone} />
      {props.voice?.audioSrc && <Html5Audio src={props.voice.audioSrc} />}
    </AbsoluteFill>
  );
};
