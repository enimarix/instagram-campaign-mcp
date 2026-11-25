// PhysiqueScan (owner order 75): « Physique Scan ». The troupe's blueprint shots (a jacked statue
// on a cream drafting grid, bands of macro and calorie text wrapping round his muscles and
// rolling: src/studio/physique.py, cinematic/engine/bands.py) cut on the bed's beat, under the
// hook slammed in one word per beat, a measure readout popping in as each scene opens, a small
// push on every beat and a swish on every cut. No voice: the words are on the bands. Ends on
// the physique end card.
import { useMemo } from "react";
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { MusicBed } from "../../components/MusicBed";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { Sfx } from "../../components/Sfx";
import { EndCard } from "../../endcards/EndCard";
import { Plate } from "../SitcomSkit/kit";
import { Hook, PHYSIQUE, Readout } from "./kit";
import { BEDS, beatAt, layoutOf, type PhysiqueProps } from "./schema";

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
      {shots.slice(1).map((s, i) => (
        <Sfx key={`w${i}`} id="sfx-swish" at={at(s.start_s)} db={s.shot === 0 ? 0 : -6} />
      ))}
      <MusicBed id={props.music} />
      <SafeZoneGuide show={!!props.safeZone} />
    </AbsoluteFill>
  );
};
