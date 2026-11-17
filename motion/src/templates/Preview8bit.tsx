import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { z } from "zod";
import { assetById } from "../assets";
import { safeArea } from "../brand";
import { CRTOverlay } from "../components/CRTOverlay";
import { DialogBox } from "../components/DialogBox";
import { HUD } from "../components/HUD";
import { PixelText } from "../components/PixelText";
import { SafeZoneGuide } from "../components/SafeZoneGuide";
import { Sprite } from "../components/Sprite";
import { Flash, Wipe } from "../components/Transitions";
import { colors, palette } from "../lib/palette";
import { coin, slime } from "../lib/sprites";

// Shows the 8-bit building blocks (steps 040–042) on one screen; not a publishable template.
export const preview8bitSchema = z.strictObject({
  title: z.string().min(1).max(20),
  text: z.string().min(1).max(120),
  name: z.string().max(16),
  dialog: z.string().min(1).max(160),
  speed: z.number().positive().max(100),
  seconds: z.number().min(1).max(60),
  safeZone: z.boolean(),
  hud: z.boolean(),
  sprites: z.boolean(),
  crt: z.boolean(),
  transitions: z.boolean(),
});

type Props = z.infer<typeof preview8bitSchema>;

const PAUSE = 10; // frames between two typed blocks
const SWATCH = 48; // 16 swatches in one row fit the safe area (895 px)
const GAP = 32;
const MAX_HEARTS = 5;
const WIPE = 30; // frames

export const Preview8bit = ({ title, text, name, dialog, speed, safeZone, hud, sprites, crt, transitions }: Props) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const area = safeArea();
  // Each block starts typing when the one before has finished.
  const after = (start: number, s: string) => start + Math.ceil((Array.from(s).length / speed) * fps) + PAUSE;
  const textStart = after(0, title);
  const dialogStart = after(textStart, text);
  return (
    <AbsoluteFill style={{ backgroundColor: colors.background }}>
      <div style={{ position: "absolute", ...area, display: "flex", flexDirection: "column", gap: GAP }}>
        {hud && (
          <HUD
            // Demo values from the frame: a heart lost every 2 s, 10 points a frame, level = time.
            hearts={Math.max(1, MAX_HEARTS - Math.floor(frame / (2 * fps)))}
            maxHearts={MAX_HEARTS}
            score={frame * 10}
            level={frame / durationInFrames}
            width={area.width}
          />
        )}
        <PixelText text={title} scale={8} color={colors.primary} speed={speed} />
        <PixelText text={text} scale={4} speed={speed} startFrame={textStart} cursor maxWidth={area.width} />
        {/* Whole-number scales of the 8 px font: every glyph pixel stays square. */}
        <div style={{ display: "flex", alignItems: "flex-end", gap: GAP }}>
          {[1, 2, 3, 4, 6].map((s) => (
            <PixelText key={s} text={`${s}x`} scale={s} color={colors.secondary} />
          ))}
        </div>
        {sprites && (
          <div style={{ display: "flex", alignItems: "flex-end", gap: GAP }}>
            {/* Mascot sheet from public/ via the asset registry (placeholder art). */}
            <Sprite {...assetById("mascot")} scale={6} fps={6} />
            <Sprite art={slime} scale={8} fps={3} />
            {/* Coins: looping at three phases, then one spin that holds its last frame. */}
            {[0, 2, 4].map((s) => (
              <Sprite key={s} art={coin} scale={6} startFrame={s} />
            ))}
            <Sprite art={coin} scale={6} fps={4} loop={false} startFrame={fps} />
            {[0, 1, 2, 3].map((t) => (
              <Sprite key={t} {...assetById("tiles")} scale={6} frame={t} />
            ))}
          </div>
        )}
        <div style={{ display: "flex", gap: 8 }}>
          {palette.map((c) => (
            <div key={c} style={{ width: SWATCH, height: SWATCH, backgroundColor: c, outline: `4px solid ${palette[15]}` }} />
          ))}
        </div>
        <DialogBox text={dialog} name={name || undefined} width={area.width} speed={speed} startFrame={dialogStart} />
      </div>
      {transitions && (
        <>
          <Flash duration={12} />
          {/* Mid-clip scene change; the still frame (220) is after it. */}
          <Wipe direction="right" color={colors.accent} startFrame={Math.round(durationInFrames / 2 - WIPE / 2)} duration={WIPE} />
        </>
      )}
      {/* Music bed loops seamlessly; the coin sound plays when the one-shot coin spins (1 s). Stills are silent. */}
      <Html5Audio src={assetById("music-overworld").src} loop volume={0.5} />
      <Sequence from={fps} layout="none">
        <Html5Audio src={assetById("sfx-coin").src} />
      </Sequence>
      <CRTOverlay show={crt} flicker={0.08} seed={7} />
      <SafeZoneGuide show={safeZone} />
    </AbsoluteFill>
  );
};
