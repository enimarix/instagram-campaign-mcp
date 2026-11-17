import { useMemo } from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { z } from "zod";
import { scriptAreas } from "../brand";
import { Captions } from "../components/Captions";
import { HookCard } from "../components/HookCard";
import { SafeZoneGuide } from "../components/SafeZoneGuide";
import { Sprite } from "../components/Sprite";
import { colors } from "../lib/palette";
import { buildTimeline, sceneAt } from "../lib/timeline";
import { slime } from "../lib/sprites";

// Shows the script timeline (step 043): hook card, captions, loop back to frame 0. Not publishable.
export const timelineDemoSchema = z.strictObject({
  /** lines[0] is the hook. ~120 chars fit the caption band at scale 4. */
  lines: z.array(z.string().min(1).max(120)).min(1).max(12),
  /** Voice timings, one per line; none = estimated. */
  timings: z.array(z.strictObject({ text: z.string().optional(), start_s: z.number(), end_s: z.number() })).optional(),
  loop: z.boolean(),
  safeZone: z.boolean(),
});

type Props = z.infer<typeof timelineDemoSchema>;

const HOOK_S = 1.5;
const OUTRO_S = 0.5;

export const timelineOf = ({ lines, timings, loop }: Props, fps: number) =>
  buildTimeline({ lines, timings, fps, hookSeconds: HOOK_S, outroSeconds: OUTRO_S, loop });

export const TimelineDemo = (props: Props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const timeline = useMemo(() => timelineOf(props, fps), [props, fps]);
  const scene = sceneAt(timeline.scenes, frame);
  const hook = scriptAreas().hook;
  return (
    <AbsoluteFill style={{ backgroundColor: colors.background }}>
      {/* Scene art goes in the hook area once the hook is gone. */}
      {scene && scene.index > 0 && (
        <div style={{ position: "absolute", ...hook, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Sprite art={slime} scale={16} fps={3} />
        </div>
      )}
      <HookCard text={props.lines[0]} timeline={timeline} />
      <Captions timeline={timeline} />
      <SafeZoneGuide show={props.safeZone} />
    </AbsoluteFill>
  );
};
