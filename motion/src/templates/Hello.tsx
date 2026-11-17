import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { z } from "zod";
import { brand } from "../brand";

// Proves the pipeline only; real templates arrive in 044+.
export const helloSchema = z.strictObject({
  title: z.string().min(1).max(40),
  subtitle: z.string().max(80),
  seconds: z.number().min(1).max(60),
  safeZone: z.boolean(),
});

type Props = z.infer<typeof helloSchema>;

const { colors, fonts, safe_zone: zone } = brand;
// Where text may go on a Reel: inside the UI-free insets, left of the button rail.
const area = { top: zone.top, bottom: zone.bottom, left: zone.left, right: zone.right + zone.right_rail };

export const Hello = ({ title, subtitle, safeZone }: Props) => {
  const frame = useCurrentFrame();
  // Typewriter in whole characters and a hard on/off cursor: no smooth easing in 8-bit.
  const shown = Math.floor(interpolate(frame, [0, title.length * 3], [0, title.length], { extrapolateRight: "clamp" }));
  const cursor = Math.floor(frame / 15) % 2 === 0 ? "_" : " ";
  return (
    <AbsoluteFill
      style={{
        backgroundColor: colors.background,
        color: colors.text,
        // The font itself is loaded by src/lib/font.ts (step 040). One weight only: no faux bold.
        fontFamily: `"${fonts.display}", monospace`,
      }}
    >
      <div
        style={{
          position: "absolute",
          ...area,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          textAlign: "center",
          gap: 48,
          outline: safeZone ? `4px dashed ${colors.accent}` : undefined,
        }}
      >
        <div style={{ fontSize: 120, color: colors.primary, textShadow: `8px 8px 0 ${colors.palette[1]}` }}>
          {title.slice(0, shown).toUpperCase()}
          {cursor}
          {/* The hidden rest of the title keeps the line from re-centring while it types. */}
          <span style={{ visibility: "hidden" }}>{title.slice(shown).toUpperCase()}</span>
        </div>
        <div style={{ fontSize: 48, color: colors.secondary, textShadow: `4px 4px 0 ${colors.palette[15]}` }}>
          {subtitle.toUpperCase()}
        </div>
      </div>
    </AbsoluteFill>
  );
};
