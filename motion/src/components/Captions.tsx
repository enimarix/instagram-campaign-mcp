import { useCurrentFrame } from "remotion";
import { scriptAreas } from "../brand";
import { intScale } from "../lib/pixel";
import { sceneAt, type Timeline } from "../lib/timeline";
import { DialogBox } from "./DialogBox";

export type CaptionsProps = {
  timeline: Timeline;
  /** Font and box scale (whole number). */
  scale?: number;
  /** Typewriter speed in chars/s from the line's start; none = whole at once. */
  speed?: number;
};

// Sound-off captions: the current script line, whole (or typed with `speed`), in a high-contrast
// box at the top of the band under the hook area, inside the safe area. Nothing during the hook
// scene (HookCard shows it) or the outro.
export const Captions = ({ timeline, scale = 4, speed }: CaptionsProps) => {
  const scene = sceneAt(timeline.scenes, useCurrentFrame());
  if (!scene || scene.index === 0) return null;
  const area = scriptAreas().captions;
  // DialogBox draws a ring of one box pixel around itself and a drop shadow of three to the
  // right and below: inset it by those so all of it stays in the safe area.
  const px = intScale(scale);
  return (
    // Anchored to the band's top: a long line grows the box downwards, never into the hook area.
    <div style={{ position: "absolute", ...area, padding: px }}>
      <DialogBox text={scene.text} width={area.width - 4 * px} scale={px} speed={speed} startFrame={scene.startFrame} cursor={false} />
    </div>
  );
};
