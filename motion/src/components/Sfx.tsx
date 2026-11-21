import { useMemo } from "react";
import { Html5Audio, Sequence, staticFile, useVideoConfig } from "remotion";
import { assetById } from "../assets";
import { type AnySfx, isLibrarySfx, sfxGain, speechSpans, type Span, SPEECH_SFX_DB } from "../lib/duck";

/** A sound's file: a library sound (`ov:<id>`, step 150) sits in the bundle's public/ov-sfx/,
 * copied there by the render (src/studio/sfx.py stage). */
const sfxSrc = (id: AnySfx) => (isLibrarySfx(id) ? staticFile(`ov-sfx/${id.slice(3)}.wav`) : assetById(id).src);

/**
 * A body sound effect from frame `at` (step 159): it peaks `db` from the voice's level in the
 * gaps and `speech` dB further down while a line of `lines` (the voice line timings on the
 * video's clock, as MusicBed gets them) is spoken. Never a hand-set volume. Stills are silent.
 */
export const Sfx = ({ id, at, db = 0, lines, speech = SPEECH_SFX_DB }: { id: AnySfx; at: number; db?: number; lines?: readonly Span[]; speech?: number }) => {
  const { fps } = useVideoConfig();
  const spans = useMemo(() => speechSpans(lines ?? []), [lines]);
  const from = Math.max(0, Math.round(at));
  return (
    <Sequence from={from} layout="none">
      <Html5Audio src={sfxSrc(id)} volume={(f) => sfxGain(spans, id, (from + f) / fps, db, speech)} />
    </Sequence>
  );
};
