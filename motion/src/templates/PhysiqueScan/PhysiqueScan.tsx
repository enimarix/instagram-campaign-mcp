// PhysiqueScan (owner order 75): « Physique Scan ». The object's shots (a muscle, a dumbbell, a
// kettlebell, a heart or a bone, bands of macro and calorie text gripping it, rocking, whooshing
// up and down and squeezing it, the motion design layer over it: src/studio/physique.py,
// cinematic/engine/anatomy.py) cut on the bed's beat, under
// the hook slammed in one word per beat, a measure readout popping in as each scene opens, a
// small push on every beat, a whoosh as the bands fly and a swish on each new scene. No voice:
// the words are on the bands. Ends on the physique end card.
import { useMemo } from "react";
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { MusicBed } from "../../components/MusicBed";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { Sfx } from "../../components/Sfx";
import { EndCard } from "../../endcards/EndCard";
import { Plate } from "../SitcomSkit/kit";
import { Hook, PHYSIQUE, Readout } from "./kit";
import { BEDS, beatAt, layoutOf, LEGS, WHOOSH, type PhysiqueProps } from "./schema";

export const PhysiqueScan = (props: PhysiqueProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { shots, starts, hookOut, cardStart } = useMemo(() => layoutOf(props), [props]);
  const at = (s: number) => Math.round(s * fps);
  const t = frame / fps;
  const end = at(cardStart);
  // a small push on each beat, easing back before the next
  const period = 60 / BEDS[props.music].bpm;
  const since = ((t - BEDS[props.music].first) % period + period) % period;
  const pulse = 1 + 0.018 * Math.max(0, 1 - since / (period * 0.6));
  const hookBeats = [0, 1, 2, 3, 4].map((n) => at(beatAt(props.music, n)));
  return (
    <AbsoluteFill style={{ background: PHYSIQUE.cream }}>
      {frame < end ? (
        <>
          <Plate src={props.plate} zoom={pulse} />
          {frame < at(hookOut) && <Hook text={props.hook} f={frame} beats={hookBeats} out={at(hookOut)} />}
          {props.scenes.map((s, i) => {
            const from = at(starts[i]);
            const until = i + 1 < starts.length ? at(starts[i + 1]) : end;
            // the first scene's readout lands on the hook's second beat, under it
            const show = i === 0 ? at(beatAt(props.music, 1)) : from;
            return s.label && frame >= show && frame < until ? <Readout key={`r${i}`} text={s.label} f={frame - show} /> : null;
          })}
        </>
      ) : (
        <Sequence from={end} layout="none">
          <EndCard style="physique" tagline={props.outro} accent={props.accent} address={props.address} pixelate={1} />
        </Sequence>
      )}
      {shots.map((s, i) =>
        // the bands fly LEGS times a shot, WHOOSH into each leg (cinematic/engine/anatomy.py state); a new scene swishes in
        [...Array.from({ length: LEGS }, (_, leg) => <Sfx key={`b${i}-${leg}`} id="sfx-swish" at={at(s.start_s + ((leg + WHOOSH) / LEGS) * (s.end_s - s.start_s))} db={-5} />),
         i > 0 && s.shot === 0 ? <Sfx key={`w${i}`} id="sfx-swish" at={at(s.start_s)} db={0} /> : null])}
      <MusicBed id={props.music} />
      <SafeZoneGuide show={!!props.safeZone} />
    </AbsoluteFill>
  );
};
