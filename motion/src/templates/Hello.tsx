import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { z } from "zod";
import { brand } from "../brand";
import { fonts } from "../lib/font";

// Proves the pipeline only, in the brand kit (step 050: clean light surface, Inter Tight).
export const helloSchema = z.strictObject({
  title: z.string().min(1).max(40),
  subtitle: z.string().max(80),
  seconds: z.number().min(1).max(60),
  safeZone: z.boolean(),
});

type Props = z.infer<typeof helloSchema>;

const { colors, safe_zone: zone } = brand;
// Where text may go on a Reel: inside the UI-free insets, left of the button rail.
const area = { top: zone.top, bottom: zone.bottom, left: zone.left, right: zone.right + zone.right_rail };

export const Hello = ({ title, subtitle, safeZone }: Props) => {
  const frame = useCurrentFrame();
  const rise = (start: number) => ({
    opacity: interpolate(frame, [start, start + 12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
    transform: `translateY(${interpolate(frame, [start, start + 12], [40, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px)`,
  });
  return (
    <AbsoluteFill style={{ backgroundColor: colors.light.bg, color: colors.light.ink, fontFamily: `"${fonts.body}", sans-serif` }}>
      <div
        style={{
          position: "absolute",
          ...area,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          textAlign: "center",
          gap: 40,
          outline: safeZone ? `4px dashed ${colors.macros.kcal}` : undefined,
        }}
      >
        <div
          style={{
            ...rise(0),
            fontFamily: `"${fonts.display}", sans-serif`,
            fontWeight: fonts.displayWeight,
            fontSize: 150,
            lineHeight: 1,
            letterSpacing: "-0.04em",
            color: colors.brand,
          }}
        >
          {title}
        </div>
        <div style={{ ...rise(8), fontSize: 48, fontWeight: 500, color: colors.light.muted }}>{subtitle}</div>
      </div>
    </AbsoluteFill>
  );
};
