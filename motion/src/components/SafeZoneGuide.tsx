import { AbsoluteFill } from "remotion";
import { safeArea } from "../brand";
import { colors } from "../lib/palette";

// Editing aid: shades what Reels UI covers (brand.json safe_zone, on the 1080x1920 canvas)
// and outlines the free area. Off unless `show`, so finished renders never carry it.
export const SafeZoneGuide = ({ show = false }: { show?: boolean }) => {
  if (!show) return null;
  const area = safeArea();
  return (
    <AbsoluteFill style={{ pointerEvents: "none", overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          ...area,
          outline: `4px dashed ${colors.accent}`,
          // ponytail: one huge spread shadow shades everything outside the area.
          boxShadow: `0 0 0 4000px ${colors.accent}40`,
        }}
      />
    </AbsoluteFill>
  );
};
