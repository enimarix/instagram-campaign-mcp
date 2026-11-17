import { AbsoluteFill, useVideoConfig } from "remotion";
import { z } from "zod";
import { safeArea } from "../brand";
import { DialogBox } from "../components/DialogBox";
import { PixelText } from "../components/PixelText";
import { SafeZoneGuide } from "../components/SafeZoneGuide";
import { colors, palette } from "../lib/palette";

// Shows the 8-bit building blocks (step 040) on one screen; not a publishable template.
export const preview8bitSchema = z.strictObject({
  title: z.string().min(1).max(20),
  text: z.string().min(1).max(120),
  name: z.string().max(16),
  dialog: z.string().min(1).max(160),
  speed: z.number().positive().max(100),
  seconds: z.number().min(1).max(60),
  safeZone: z.boolean(),
});

type Props = z.infer<typeof preview8bitSchema>;

const PAUSE = 10; // frames between two typed blocks
const SWATCH = 96;
const GAP = 32;

export const Preview8bit = ({ title, text, name, dialog, speed, safeZone }: Props) => {
  const { fps } = useVideoConfig();
  const area = safeArea();
  // Each block starts typing when the one before has finished.
  const after = (start: number, s: string) => start + Math.ceil((Array.from(s).length / speed) * fps) + PAUSE;
  const textStart = after(0, title);
  const dialogStart = after(textStart, text);
  return (
    <AbsoluteFill style={{ backgroundColor: colors.background }}>
      <div style={{ position: "absolute", ...area, display: "flex", flexDirection: "column", gap: GAP }}>
        <PixelText text={title} scale={8} color={colors.primary} speed={speed} />
        <PixelText text={text} scale={4} speed={speed} startFrame={textStart} cursor maxWidth={area.width} />
        {/* Whole-number scales of the 8 px font: every glyph pixel stays square. */}
        <div style={{ display: "flex", alignItems: "flex-end", gap: GAP }}>
          {[1, 2, 3, 4, 6].map((s) => (
            <PixelText key={s} text={`${s}x`} scale={s} color={colors.secondary} />
          ))}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, width: 8 * SWATCH + 7 * 8 }}>
          {palette.map((c) => (
            <div key={c} style={{ width: SWATCH, height: SWATCH, backgroundColor: c, outline: `4px solid ${palette[15]}` }} />
          ))}
        </div>
        <DialogBox text={dialog} name={name || undefined} width={area.width} speed={speed} startFrame={dialogStart} />
      </div>
      <SafeZoneGuide show={safeZone} />
    </AbsoluteFill>
  );
};
