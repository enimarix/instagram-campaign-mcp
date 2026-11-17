import { barCells, padScore } from "../lib/game";
import { colors, palette } from "../lib/palette";
import { intScale, linePx } from "../lib/pixel";
import { heart } from "../lib/sprites";
import { PixelText } from "./PixelText";
import { Sprite } from "./Sprite";

export type HUDProps = {
  /** Full hearts out of `maxHearts`. */
  hearts: number;
  maxHearts: number;
  score: number;
  /** Score digits, zero-padded. */
  digits?: number;
  /** Level bar fill, 0..1. */
  level: number;
  /** Cells in the level bar. */
  cells?: number;
  /** Outer width in px. */
  width: number;
  /** Font and icon scale (whole number). */
  scale?: number;
};

// Game HUD: hearts and score on one line, the level bar under them. Values come from props:
// the template computes them from the frame.
export const HUD = ({ hearts, maxHearts, score, digits = 6, level, cells = 12, width, scale = 4 }: HUDProps) => {
  const px = intScale(scale);
  const filled = barCells(level, cells);
  return (
    <div style={{ width, display: "flex", flexDirection: "column", gap: 3 * px }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", gap: px }}>
          {Array.from({ length: maxHearts }, (_, i) => (
            <Sprite key={i} art={heart} scale={px} frame={i < hearts ? 0 : 1} />
          ))}
        </div>
        <PixelText text={padScore(score, digits)} scale={px} color={colors.primary} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 2 * px }}>
        <PixelText text="LV" scale={px} color={colors.secondary} />
        <div
          style={{
            display: "flex",
            gap: px,
            padding: px,
            border: `${px}px solid ${colors.text}`,
            height: linePx(px) - 2 * px,
            boxSizing: "border-box",
          }}
        >
          {Array.from({ length: cells }, (_, i) => (
            <div key={i} style={{ width: 3 * px, backgroundColor: i < filled ? colors.secondary : palette[15] }} />
          ))}
        </div>
      </div>
    </div>
  );
};
