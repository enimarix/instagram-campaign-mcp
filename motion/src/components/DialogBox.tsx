import { colors, palette } from "../lib/palette";
import { intScale, linePx, snap } from "../lib/pixel";
import { PixelText } from "./PixelText";

export type DialogBoxProps = {
  text: string;
  /** Speaker shown in a tag on the top border. */
  name?: string;
  /** Outer width in px (snapped to the box's pixel grid). */
  width: number;
  /** Font and border scale (whole number). */
  scale?: number;
  /** Typewriter speed in characters per second; none = all at once. */
  speed?: number;
  startFrame?: number;
  /** Block cursor after the text (off for captions). */
  cursor?: boolean;
};

// RPG-style text box. All sizes are whole multiples of one "box pixel" (= scale px).
export const DialogBox = ({ text, name, width, scale = 4, speed, startFrame = 0, cursor = true }: DialogBoxProps) => {
  const px = intScale(scale);
  const border = 2 * px;
  const pad = 6 * px;
  const outer = snap(width, px);
  const tagPad = 2 * px;
  // Name tag: one text line inside its own border.
  const tagHeight = 2 * border + 2 * tagPad + linePx(px);
  return (
    <div
      style={{
        position: "relative",
        boxSizing: "border-box",
        width: outer,
        marginTop: name ? tagHeight - border : 0,
        padding: pad,
        border: `${border}px solid ${colors.text}`,
        backgroundColor: colors.background,
        // A dark ring and a hard drop shadow: no blur in 8-bit.
        boxShadow: `0 0 0 ${px}px ${palette[0]}, ${border}px ${border}px 0 ${px}px ${palette[0]}`,
      }}
    >
      {name && (
        <div
          style={{
            position: "absolute",
            left: pad,
            // Relative to the padding box: the tag's bottom border lies on the box's top border.
            top: -tagHeight,
            padding: tagPad,
            border: `${border}px solid ${colors.text}`,
            backgroundColor: colors.accent,
          }}
        >
          <PixelText text={name} scale={px} color={colors.background} />
        </div>
      )}
      <PixelText
        text={text}
        scale={px}
        speed={speed}
        startFrame={startFrame}
        cursor={cursor}
        maxWidth={outer - 2 * (border + pad)}
      />
    </div>
  );
};
