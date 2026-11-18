// The animated end card, one per style (owner, 2026-11-18): templates render <EndCard style=…>
// and step 137 adds the other styles here. Static ffmpeg card (step 050) = fallback only.
import type { EndCardProps } from "./schema.ts";
import { VoxelEndCard } from "./VoxelEndCard.tsx";

const CARDS = { voxel: VoxelEndCard } as const;

export const EndCard = ({ style, ...props }: EndCardProps) => {
  const Card = CARDS[style];
  return <Card {...props} />;
};
