// The cutaway style's kit (step 142): the pixel grid (a mosaic filter turns the vector art into
// P-px pixels), Bayer dithering, the dusk / night sky with drifting pixel clouds, the pixel type
// and the game HUD (mode chip, gauge, title box, numbered steps, callouts with leader lines,
// « BANG » bursts). Templates and the end card build on it; a mechanism is a view
// (src/cutaway/views/).
import type { ReactNode } from "react";
import { seeded } from "../lib/game";
import { C, SKIES, type Sky } from "./palette";
import { CAP, LINE_PITCH, linePath, lineWidth, wrapText } from "./pixelfont";

export const W = 1080;
export const H = 1920;
/** The art's pixel, in output px (the mosaic filter's block). */
export const P = 5;
/** Where a view's (0, 0) sits on screen, and its scale at zoom 1 (views are drawn about ±420 across). */
export const STAGE = [540, 1100] as const;
export const BASE = 1.2;

/** Snap to the pixel grid. */
export const px = (v: number, unit = P) => Math.round(v / unit) * unit;
/** Hard steps: `t` (0..1) rounded down to `n` levels (pixel-art easing). */
export const steps = (t: number, n: number) => Math.floor(Math.min(1, Math.max(0, t)) * n) / n;

// 4x4 Bayer matrix: the order pixels light up in when dithering.
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];

/**
 * Shared SVG defs (ids are global to the page, so one copy serves every svg): the mosaic
 * filter `cw-px` and the Bayer masks `cw-b<k>` (k of 16 cells lit, P px cells).
 */
export const Defs = () => (
  <svg width={0} height={0} style={{ position: "absolute" }}>
    <defs>
      {/* Keep one sample per P x P block (its pixel at 2,2), then grow it over the block. */}
      <filter id="cw-px" x={0} y={0} width={W} height={H} filterUnits="userSpaceOnUse" primitiveUnits="userSpaceOnUse" colorInterpolationFilters="sRGB">
        <feFlood x={2} y={2} width={1} height={1} floodColor="#000" />
        <feComposite x={0} y={0} width={P} height={P} />
        <feTile result="grid" />
        <feComposite in="SourceGraphic" in2="grid" operator="in" />
        <feMorphology operator="dilate" radius={(P - 1) / 2} />
      </filter>
      {Array.from({ length: 17 }, (_, k) => (
        <pattern key={k} id={`cw-b${k}`} width={4 * P} height={4 * P} patternUnits="userSpaceOnUse">
          {BAYER.map((v, i) => (v < k ? <rect key={i} x={(i % 4) * P} y={Math.floor(i / 4) * P} width={P} height={P} fill="#fff" /> : null))}
        </pattern>
      ))}
      {Array.from({ length: 17 }, (_, k) => (
        <mask key={k} id={`cw-m${k}`} maskUnits="userSpaceOnUse" x={0} y={0} width={W} height={H}>
          <rect width={W} height={H} fill={`url(#cw-b${k})`} />
        </mask>
      ))}
    </defs>
  </svg>
);

/** Mask id for a dither level 0..1 (0 = nothing shows, 1 = all). */
export const ditherMask = (level: number) => `url(#cw-m${Math.round(Math.min(1, Math.max(0, level)) * 16)})`;

/** A colour laid over what is below at a dithered level (0..1), in a band. */
export const DitherRect = ({ x = 0, y, w = W, h, color, level }: { x?: number; y: number; w?: number; h: number; color: string; level: number }) =>
  level <= 0 ? null : <rect x={x} y={y} width={w} height={h} fill={color} mask={level >= 1 ? undefined : ditherMask(level)} />;

const CLOUDS = Array.from({ length: 7 }, (_, i) => ({
  x: seeded(71, i) * 1300 - 100,
  y: 260 + seeded(72, i) * 1100,
  s: 0.5 + seeded(73, i) * 0.8,
  speed: 0.25 + seeded(74, i) * 0.35,
}));
const STARS = Array.from({ length: 40 }, (_, i) => ({ x: px(seeded(81, i) * W), y: px(seeded(82, i) * 1300), phase: Math.floor(seeded(83, i) * 60) }));

/** One pixel cumulus: bumps on a flat base, a lit rim on top. */
const Cloud = ({ x, y, s, top, body }: { x: number; y: number; s: number; top: string; body: string }) => (
  <g transform={`translate(${x} ${y}) scale(${s})`}>
    <circle cx={-60} cy={-10} r={46} fill={top} />
    <circle cx={10} cy={-40} r={62} fill={top} />
    <circle cx={80} cy={-6} r={44} fill={top} />
    <circle cx={-60} cy={-2} r={42} fill={body} />
    <circle cx={10} cy={-30} r={56} fill={body} />
    <circle cx={80} cy={2} r={40} fill={body} />
    <rect x={-110} y={0} width={240} height={36} rx={18} fill={body} />
  </g>
);

/**
 * The sky behind every view: colour bands with Bayer-dithered seams, twinkling stars (night),
 * clouds drifting left, a sea of clouds at the bottom. `f` = frame, `pan` shifts it (parallax).
 */
export const SkyLayer = ({ sky, f, pan = 0 }: { sky: Sky; f: number; pan?: number }) => {
  const bands = SKIES[sky];
  let y = 0;
  const rects: ReactNode[] = [];
  bands.forEach(([color, share], i) => {
    const h = px(share * H);
    rects.push(<rect key={`b${i}`} y={y} width={W} height={h + P} fill={color} />);
    // Seam into the next band: three dithered steps, 2 cells each.
    const next = bands[i + 1]?.[0];
    if (next) [0.25, 0.5, 0.75].forEach((lv, k) => rects.push(<DitherRect key={`d${i}-${k}`} y={y + h - (3 - k) * 2 * P} h={2 * P} color={next} level={lv} />));
    y += h;
  });
  const dusk = sky === "dusk";
  return (
    <g>
      {rects}
      {!dusk &&
        STARS.map((s, i) => (Math.floor((f + s.phase) / 12) % 5 ? <rect key={i} x={s.x} y={s.y} width={P} height={P} fill={i % 3 ? C.violet : C.cream} /> : null))}
      {CLOUDS.map((c, i) => {
        const x = ((((c.x - (f + pan * 2) * c.speed) % 1400) + 1400) % 1400) - 200;
        return <Cloud key={i} x={px(x)} y={c.y} s={c.s} top={dusk ? C.orange : C.cloud} body={dusk ? C.pink : C.cloudDark} />;
      })}
      {/* The sea of clouds at the bottom. */}
      <g transform={`translate(${px(-((f * 0.6 + pan) % 180))} 0)`}>
        {Array.from({ length: 9 }, (_, i) => (
          <circle key={i} cx={i * 180} cy={1650 + (i % 2) * 30} r={110} fill={dusk ? C.peach : C.cloud} />
        ))}
        {Array.from({ length: 9 }, (_, i) => (
          <circle key={i} cx={i * 180 + 90} cy={1730 + (i % 2) * 20} r={110} fill={dusk ? C.mauve : C.cloudDark} />
        ))}
        <rect x={-200} y={1760} width={W + 400} height={200} fill={dusk ? C.mauve : C.cloudDark} />
      </g>
    </g>
  );
};

/** Pixel type (src/cutaway/pixelfont.ts) in an svg: one path per line. `x` per `align`, `y` = top of the first capital. */
export const Type = ({ text, x, y, unit, color, bold = false, align = "left", maxWidth, outline }: { text: string; x: number; y: number; unit: number; color: string; bold?: boolean; align?: "left" | "center" | "right"; maxWidth?: number; outline?: string }) => {
  const lines = maxWidth ? wrapText(text, Math.floor(maxWidth / unit), bold) : text.split("\n");
  const paths = lines.map((l, i) => {
    const w = lineWidth(l, bold) * unit;
    const lx = align === "left" ? x : align === "center" ? x - w / 2 : x - w;
    return linePath(l, px(lx, unit), y + i * LINE_PITCH * unit, unit, bold);
  });
  const d = paths.join("");
  return (
    <>
      {outline && [[-1, 0], [1, 0], [0, -1], [0, 1], [1, 1]].map(([dx, dy], i) => <path key={i} d={d} fill={outline} transform={`translate(${dx * unit} ${dy * unit})`} />)}
      <path d={d} fill={color} />
    </>
  );
};

/** Size in px of `text` at `unit` (wrapped at `maxWidth`). */
export const typeSize = (text: string, unit: number, bold = false, maxWidth?: number) => {
  const lines = maxWidth ? wrapText(text, Math.floor(maxWidth / unit), bold) : text.split("\n");
  return { w: Math.max(...lines.map((l) => lineWidth(l, bold))) * unit, h: ((lines.length - 1) * LINE_PITCH + CAP) * unit, lines: lines.length };
};

/** A HUD box: ink fill, a `border`-coloured frame `b` px thick. */
export const Box = ({ x, y, w, h, border, b = 4, fill = C.ink }: { x: number; y: number; w: number; h: number; border: string; b?: number; fill?: string }) => (
  <>
    <rect x={x} y={y} width={w} height={h} fill={border} />
    <rect x={x + b} y={y + b} width={w - 2 * b} height={h - 2 * b} fill={fill} />
  </>
);

/** A label in a box (callouts, chips): its text at `unit`, padded. Returns the box at (x, y) per align. */
export const Tag = ({ text, x, y, unit, color, border = color, fill = C.ink, align = "left", bold = true }: { text: string; x: number; y: number; unit: number; color: string; border?: string; fill?: string; align?: "left" | "center" | "right"; bold?: boolean }) => {
  const { w, h } = typeSize(text, unit, bold);
  const pad = 2 * unit;
  const bw = w + 2 * pad + 8;
  const bx = align === "left" ? x : align === "center" ? x - bw / 2 : x - bw;
  return (
    <>
      <Box x={px(bx, 1)} y={y} w={bw} h={h + 2 * pad + 8} border={border} fill={fill} />
      <Type text={text} x={bx + pad + 4} y={y + pad + 4} unit={unit} color={color} bold={bold} />
    </>
  );
};

/** Height of a Tag at `unit`. */
export const tagHeight = (unit: number) => CAP * unit + 4 * unit + 8;
