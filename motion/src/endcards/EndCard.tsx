// The animated end card, one per style (owner, 2026-11-18): templates render <EndCard style=…>,
// Track A recipes a standalone clip of it (src/studio/motion.py). Static ffmpeg card (step
// 050) = fallback only.
import { AbsoluteFill } from "remotion";
import { CRTOverlay } from "../components/CRTOverlay";
import type { EndCardProps } from "./schema.ts";
import { CleanEndCard } from "./CleanEndCard";
import { CutawayEndCard } from "./CutawayEndCard";
import { LiveEndCard } from "./LiveEndCard";
import { PaperEndCard } from "./PaperEndCard";
import { PixelEndCard } from "./PixelEndCard";
import { VoxelEndCard } from "./VoxelEndCard";
import { CinemaEndCard } from "./CinemaEndCard";
import { EditorialEndCard } from "./EditorialEndCard";
import { Macro3dEndCard } from "./Macro3dEndCard";
import { SitcomEndCard } from "./SitcomEndCard";
import { PhysiqueEndCard } from "./PhysiqueEndCard";

const CARDS = { voxel: VoxelEndCard, paper: PaperEndCard, clean: CleanEndCard, pixel: PixelEndCard, live: LiveEndCard, cutaway: CutawayEndCard, editorial: EditorialEndCard, cinema: CinemaEndCard, macro3d: Macro3dEndCard, sitcom: SitcomEndCard, physique: PhysiqueEndCard } as const;

export const EndCard = ({ style, ...props }: EndCardProps) => {
  const Card = CARDS[style];
  return <Card {...props} />;
};

/** The card as a clip of its own (the EndCard composition): pixel gets the 8-bit templates' scanlines. */
export const EndCardClip = (props: EndCardProps) => (
  <AbsoluteFill>
    <EndCard {...props} />
    {props.style === "pixel" && <CRTOverlay />}
  </AbsoluteFill>
);
