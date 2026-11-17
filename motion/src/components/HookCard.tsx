import { useCurrentFrame } from "remotion";
import { scriptAreas } from "../brand";
import { colors, palette } from "../lib/palette";
import { fitTextScale, intScale } from "../lib/pixel";
import { loopFade, type Timeline } from "../lib/timeline";
import { wrap } from "../lib/typewriter";
import { PixelText } from "./PixelText";

export type HookCardProps = {
  /** The hook (script line 0). */
  text: string;
  timeline: Timeline;
  /** Largest font scale; the text shrinks in whole steps until it fits the hook area. */
  maxScale?: number;
  color?: string;
};

// The first thing on screen: the hook, big and whole from frame 0 (no typing), so the cover
// frame (timeline.hookFrame) and a muted first second both show it. Lives in the top part of
// the safe area (Captions use the band below). With timeline.loop it fades back in over the
// outro, so the last frame leads into frame 0.
export const HookCard = ({ text, timeline, maxScale = 8, color = colors.primary }: HookCardProps) => {
  const frame = useCurrentFrame();
  const opacity = frame < timeline.scenes[0].endFrame ? 1 : loopFade(frame, timeline);
  if (!opacity) return null;
  const area = scriptAreas().hook;
  const s = text.normalize("NFC");
  const scale = fitTextScale((cols) => wrap(s, cols).length, area.width, area.height, maxScale);
  const px = intScale(scale);
  return (
    <div
      style={{
        position: "absolute",
        ...area,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        opacity,
        // One font pixel of dark outline: readable on any background.
        textShadow: [`${px}px 0`, `-${px}px 0`, `0 ${px}px`, `0 -${px}px`].map((o) => `${o} 0 ${palette[0]}`).join(", "),
      }}
    >
      <PixelText text={s} scale={scale} color={color} maxWidth={area.width} />
    </div>
  );
};
