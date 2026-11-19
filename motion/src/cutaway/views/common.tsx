// What every cutaway view gets and shares (step 142). A view draws its mechanism around (0, 0)
// in world units (about ±420 across) and says where its named points are.
import type { ReactNode } from "react";
import { seeded } from "../../lib/game";
import type { Anchor, ViewId } from "../views";

export type ViewState = {
  /** Mechanism cycles done so far (the clock times the view's hz): its cyclic motion. */
  phase: number;
  /** The beat's slow change, 0..1 (src/cutaway/views.ts says what it means per view). */
  stage: number;
  /** Cycles per second as seen: above ~3 the moving parts blur. */
  rate: number;
  /** Frame, for shimmer. */
  f: number;
};

export type View<V extends ViewId = ViewId> = {
  Draw: (s: ViewState) => ReactNode;
  anchors: (s: ViewState) => Record<Anchor<V>, readonly [number, number]>;
};

export const frac = (x: number) => x - Math.floor(x);
export const rad = (deg: number) => (deg * Math.PI) / 180;
/** 0 -> 1 -> 0 over one cycle, eased (cosine). */
export const pulse = (phase: number) => 0.5 - 0.5 * Math.cos(2 * Math.PI * phase);

/** How many ghost copies a moving part gets (1 = sharp) and their phase spread, from the seen rate. */
export const ghosts = (rate: number) => (rate > 3 ? { n: 4, spread: Math.min(0.35, rate / 40) } : { n: 1, spread: 0 });

/**
 * Seeded sparkles (gas, energy) in an ellipse: small squares that blink on the frame, `on`
 * (0..1) of them lit. The cutaway's "particles inside the cylinder".
 */
export const Sparkles = ({ cx, cy, rx, ry, n, seed, f, on = 1, color, size = 9 }: { cx: number; cy: number; rx: number; ry: number; n: number; seed: number; f: number; on?: number; color: string; size?: number }) => (
  <>
    {Array.from({ length: n }, (_, i) => {
      if (seeded(seed, i) > on) return null;
      if (Math.floor((f + seeded(seed + 1, i) * 40) / 6) % 4 === 0) return null;
      const a = seeded(seed + 2, i) * 2 * Math.PI;
      const r = Math.sqrt(seeded(seed + 3, i));
      return <rect key={i} x={cx + Math.cos(a) * r * rx - size / 2} y={cy + Math.sin(a) * r * ry - size / 2} width={size} height={size} fill={color} />;
    })}
  </>
);

/** A four-point spark (ATP, a bang) of radius `r`. */
export const Spark = ({ x, y, r, color, core = "#FFFFFF" }: { x: number; y: number; r: number; color: string; core?: string }) =>
  r <= 0 ? null : (
    <g transform={`translate(${x} ${y})`}>
      <path d={`M0 ${-r}L${r * 0.22} ${-r * 0.22}L${r} 0L${r * 0.22} ${r * 0.22}L0 ${r}L${-r * 0.22} ${r * 0.22}L${-r} 0L${-r * 0.22} ${-r * 0.22}Z`} fill={color} />
      <rect x={-r * 0.18} y={-r * 0.18} width={r * 0.36} height={r * 0.36} fill={core} />
    </g>
  );

/** Outline width that stays one art pixel thick at any camera zoom. */
export const LINE = { strokeWidth: 6, vectorEffect: "non-scaling-stroke" as const, strokeLinejoin: "round" as const };
