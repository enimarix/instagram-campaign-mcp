import { AbsoluteFill, useCurrentFrame } from "remotion";
import { seeded } from "../lib/game";
import { palette } from "../lib/palette";

export type CRTOverlayProps = {
  show?: boolean;
  /** Px per scanline period (a dark line of half the period, rounded down). */
  lineEvery?: number;
  /** Max brightness dip per frame, 0..1; 0 = no flicker. */
  flicker?: number;
  /** Flicker seed: same seed, same flicker in every render. */
  seed?: number;
};

// Old-TV look over the whole frame: scanlines, a subtle vignette, optional flicker.
export const CRTOverlay = ({ show = true, lineEvery = 6, flicker = 0, seed = 1 }: CRTOverlayProps) => {
  const frame = useCurrentFrame();
  if (!show) return null;
  const dark = palette[0];
  const line = Math.max(1, Math.floor(lineEvery / 2));
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <AbsoluteFill
        style={{
          backgroundImage: `repeating-linear-gradient(to bottom, transparent 0 ${lineEvery - line}px, ${dark}55 ${lineEvery - line}px ${lineEvery}px)`,
        }}
      />
      <AbsoluteFill style={{ backgroundImage: `radial-gradient(ellipse at center, transparent 60%, ${dark}99 100%)` }} />
      {flicker > 0 && <AbsoluteFill style={{ backgroundColor: dark, opacity: flicker * seeded(seed, frame) }} />}
    </AbsoluteFill>
  );
};
