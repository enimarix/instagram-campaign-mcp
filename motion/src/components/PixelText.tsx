import { useMemo } from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { fontFamily } from "../lib/font";
import { colors } from "../lib/palette";
import { fontPx, linePx } from "../lib/pixel";
import { visibleChars, wrap } from "../lib/typewriter";

export type PixelTextProps = {
  text: string;
  /** Whole multiple of the font's 8 px design size (rounded, at least 1). */
  scale?: number;
  color?: string;
  /** Typewriter speed in characters per second; none = all at once. */
  speed?: number;
  /** Frame the text starts at (typing or appearing). */
  startFrame?: number;
  /** Block cursor after the last shown character: solid while typing, blinking after. */
  cursor?: boolean;
  /** Wrap by words inside this width (px); none = only "\n" breaks lines. */
  maxWidth?: number;
};

// The pixel font is monospaced (every glyph 1 em wide), so lines are laid out here, not by
// the browser: the box never reflows while typing and every frame is deterministic.
export const PixelText = ({
  text,
  scale = 1,
  color = colors.text,
  speed,
  startFrame = 0,
  cursor = false,
  maxWidth,
}: PixelTextProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const size = fontPx(scale);
  const lineHeight = linePx(scale);
  // A cursor needs one free cell after a full line.
  const cols = maxWidth === undefined ? Infinity : Math.max(1, Math.floor(maxWidth / size) - (cursor ? 1 : 0));
  const lines = useMemo(() => wrap(text.normalize("NFC"), cols).map((l) => Array.from(l)), [text, cols]);
  const total = lines.reduce((n, l) => n + l.length, 0);
  const visible = visibleChars(frame, total, fps, speed, startFrame);

  let left = visible;
  const shown = lines.map((l) => {
    const n = Math.max(0, Math.min(l.length, left));
    left -= l.length;
    return n;
  });
  const cursorLine = Math.max(0, shown.findLastIndex((n) => n > 0));
  const cursorOn = visible < total || Math.floor((2 * frame) / fps) % 2 === 0;

  return (
    <div
      style={{
        fontFamily: `"${fontFamily}", monospace`,
        fontSize: size,
        lineHeight: `${lineHeight}px`,
        color,
        whiteSpace: "pre",
        width: Number.isFinite(cols) ? (cols + (cursor ? 1 : 0)) * size : undefined,
      }}
    >
      {lines.map((l, i) => (
        <div key={i} style={{ height: lineHeight }}>
          {l.slice(0, shown[i]).join("")}
          {cursor && i === cursorLine && (
            <span
              style={{
                display: "inline-block",
                width: size,
                height: size,
                backgroundColor: color,
                visibility: cursorOn ? "visible" : "hidden",
              }}
            />
          )}
        </div>
      ))}
    </div>
  );
};
