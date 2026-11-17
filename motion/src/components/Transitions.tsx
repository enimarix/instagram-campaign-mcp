import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { flashOpacity, progress, wipeSpan } from "../lib/game";
import { colors } from "../lib/palette";
import { snap } from "../lib/pixel";

export type WipeProps = {
  /** Direction the wipe travels. */
  direction?: "left" | "right" | "up" | "down";
  startFrame?: number;
  /** Frames to cover and uncover the screen. */
  duration: number;
  color?: string;
  /** Edges move in steps of this many px (chunky 8-bit wipe). */
  block?: number;
};

// Scene-change wipe: a colour panel slides in from one side covering the screen (first half),
// then leaves on the other side (second half). Cut scenes at the midpoint.
export const Wipe = ({ direction = "right", startFrame = 0, duration, color = colors.background, block = 40 }: WipeProps) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const [from, to] = wipeSpan(progress(frame, startFrame, duration));
  if (to <= from) return null;
  const horizontal = direction === "left" || direction === "right";
  const size = horizontal ? width : height;
  // "left"/"up" travel toward 0: mirror the span.
  const [a, b] = direction === "right" || direction === "down" ? [from, to] : [1 - to, 1 - from];
  const start = snap(a * size, block);
  const end = Math.min(size, snap(b * size, block));
  if (end <= start) return null;
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          backgroundColor: color,
          ...(horizontal
            ? { left: start, width: end - start, top: 0, height }
            : { top: start, height: end - start, left: 0, width }),
        }}
      />
    </AbsoluteFill>
  );
};

export type FlashProps = {
  startFrame?: number;
  duration: number;
  color?: string;
};

/** Full-screen flash that fades out in hard steps. */
export const Flash = ({ startFrame = 0, duration, color = colors.text }: FlashProps) => {
  const opacity = flashOpacity(useCurrentFrame(), startFrame, duration);
  if (!opacity) return null;
  return <AbsoluteFill style={{ backgroundColor: color, opacity, pointerEvents: "none" }} />;
};
