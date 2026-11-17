import { useMemo } from "react";
import { Img, useCurrentFrame, useVideoConfig } from "remotion";
import { type PixelArt, sheetSvg, spriteFrame } from "../lib/game";
import { palette } from "../lib/palette";
import { crisp, intScale } from "../lib/pixel";

type Common = {
  /** Whole multiple of the sheet's pixels (rounded, at least 1). */
  scale?: number;
  /** Animation speed in sheet frames per second. */
  fps?: number;
  /** Wrap around (default) or hold the last frame. */
  loop?: boolean;
  startFrame?: number;
  /** Show this sheet frame, no animation (e.g. a HUD icon). */
  frame?: number;
};

type Sheet = {
  /** Sprite sheet image (e.g. `staticFile(...)`): frames left to right, then top to bottom. */
  src: string;
  frameWidth: number;
  frameHeight: number;
  frames: number;
  /** Frames per sheet row; default all in one row. */
  columns?: number;
};

export type SpriteProps = Common & (Sheet | { art: PixelArt });

// Code-drawn art becomes an SVG sheet, so both kinds share the sheet path below.
const fromArt = (art: PixelArt): Sheet => ({
  src: `data:image/svg+xml,${encodeURIComponent(sheetSvg(art, palette))}`,
  frameWidth: art.frames[0][0].length,
  frameHeight: art.frames[0].length,
  frames: art.frames.length,
});

/** One frame of a sprite sheet, scaled by a whole number, picked from the current video frame. */
export const Sprite = (props: SpriteProps) => {
  const { scale = 1, fps: rate = 8, loop = true, startFrame = 0, frame: fixed } = props;
  const art = "art" in props ? props.art : undefined;
  const fromArtSheet = useMemo(() => (art ? fromArt(art) : undefined), [art]);
  const sheet = fromArtSheet ?? (props as Sheet);
  const { src, frameWidth: w, frameHeight: h, frames, columns = sheet.frames } = sheet;
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const px = intScale(scale);
  const i = fixed ?? spriteFrame(frame, fps, frames, rate, loop, startFrame);
  return (
    <div style={{ position: "relative", overflow: "hidden", width: w * px, height: h * px, flexShrink: 0 }}>
      <Img
        src={src}
        style={{
          ...crisp,
          position: "absolute",
          left: -(i % columns) * w * px,
          top: -Math.floor(i / columns) * h * px,
          // Scale the natural-size sheet, so any sheet size works and pixels stay square.
          transform: `scale(${px})`,
          transformOrigin: "0 0",
          maxWidth: "none",
        }}
      />
    </div>
  );
};
