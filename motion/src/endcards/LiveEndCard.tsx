// The live style's end card (step 137), over real footage: the video's last frame (backdrop)
// freezes, then blurs, dims and pushes in slowly while the card's stack (the clean card's
// choreography, in light text) animates over it. Settles by SETTLE_S.live, then holds.
import { AbsoluteFill, Img, Sequence, useCurrentFrame } from "remotion";
import { easeOut, span } from "../voxel/anim.ts";
import { CardStack } from "./CleanEndCard";
import type { CardProps } from "./schema.ts";

/** Frames the freeze takes to blur and dim; the stack starts during it. */
const FREEZE = 20;
const STACK_DELAY = 10;

export const LiveEndCard = ({ tagline, accent, address, backdrop }: Omit<CardProps, "pixelate">) => {
  const frame = useCurrentFrame();
  const t = easeOut(span(frame, 2, FREEZE));
  return (
    <AbsoluteFill style={{ backgroundColor: "#0E1117", overflow: "hidden" }}>
      {backdrop && (
        <Img
          src={backdrop}
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            objectFit: "cover",
            // Slow push-in through the whole card; blur and dim during the freeze.
            transform: `scale(${1.02 + 0.04 * t + frame * 0.0006})`,
            filter: `blur(${t * 26}px) brightness(${1 - 0.52 * t}) saturate(${1 - 0.25 * t})`,
          }}
        />
      )}
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(14,17,23,0.25) 0%, rgba(14,17,23,0.05) 45%, rgba(14,17,23,0.45) 100%)", opacity: t }} />
      <Sequence from={STACK_DELAY} layout="none">
        <CardStack tagline={tagline} accent={accent} address={address} dark />
      </Sequence>
    </AbsoluteFill>
  );
};
