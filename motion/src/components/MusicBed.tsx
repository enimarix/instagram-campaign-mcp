import { useMemo } from "react";
import { Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { assetById } from "../assets";
import { duckGain, speechSpans, type Span } from "../lib/duck";

/** Level in the gaps, under the voice and the sfx; ducked further while a line is spoken. */
const VOLUME = 0.25;

export type MusicId =
  | "music-overworld"
  | "music-cave"
  | "music-marimba"
  | "music-kalimba"
  | "music-dusk"
  | "music-cutaway-a"
  | "music-cutaway-b"
  | "music-cutaway-c"
  | "none";

// A template's background music (step 048a): a music loop from src/assets.ts under the whole
// video, so a Reel without a voice still has sound. "none" plays nothing. With `lines` (the voice
// line timings on the video's clock, step 148) the bed ducks under the voice. A bed with an
// intro (`loopStart_s`) plays it once, then loops the rest.
export const MusicBed = ({ id, lines }: { id: MusicId; lines?: readonly Span[] }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const spans = useMemo(() => speechSpans(lines ?? []), [lines]);
  if (id === "none") return null;
  const bed = assetById(id);
  // A number per frame (not a callback): the callback's frame restarts in every loop.
  const volume = VOLUME * duckGain(spans, frame / fps);
  const intro = "loopStart_s" in bed ? Math.round(bed.loopStart_s * fps) : 0;
  if (!intro) return <Html5Audio src={bed.src} loop volume={volume} />;
  return (
    <>
      <Sequence durationInFrames={intro} layout="none">
        <Html5Audio src={bed.src} volume={volume} />
      </Sequence>
      <Sequence from={intro} layout="none">
        <Html5Audio src={bed.src} loop trimBefore={intro} volume={volume} />
      </Sequence>
    </>
  );
};
