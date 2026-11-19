// Volume shading for the cutaway views (step 142, review round 1): every body is painted in a
// 5-tone material ramp with Bayer-dithered seams, a warm sunset rim light on the lit side, a
// cool shadow side and specular pixels. The dither masks are defined in world units per layer
// (cell = P / zoom), so after the camera they land exactly on the screen's pixel grid.
import { createContext, type ReactNode, useContext, useId } from "react";
import { P } from "./kit";
import { C } from "./palette";

/** Material ramps, darkest (cool shadow) to brightest (highlight). */
export const RAMPS = {
  skin: ["#5B2C4A", "#9A4757", "#D7745F", "#F2A57A", "#FFD7A8"],
  muscle: ["#3E1430", "#7A2132", "#B83A36", "#E2654B", "#FFA37A"],
  tendon: ["#6E5A8A", "#B79BB0", "#E9CFAE", "#FBE8C6", "#FFFBEF"],
  bone: ["#6A5A86", "#B59EB2", "#E6D2B4", "#F8EBD0", "#FFFDF3"],
  steel: ["#232651", "#3D4588", "#6672C0", "#99A6E6", "#E4E9FF"],
  copper: ["#3A1428", "#7A2A2A", "#C2553A", "#EE8D5C", "#FFC793"],
  teal: ["#0F3346", "#17606A", "#25A29B", "#6FE0CF", "#D8FFF6"],
  gold: ["#5A2A1E", "#A0621E", "#E3A93A", "#FFD76A", "#FFF7D0"],
  fat: ["#6B3A1E", "#B8742A", "#EFB451", "#FFD98A", "#FFF6D6"],
  violet: ["#1C1640", "#2E2560", "#4A3A84", "#6F58B0", "#A893E0"],
} as const satisfies Record<string, readonly [string, string, string, string, string]>;
export type Ramp = readonly [string, string, string, string, string];

/** The sun: warm light from the upper right (unit vector, screen y down). */
export const LIGHT = [0.62, -0.78] as const;
const RIM = "#FFE08A";

// 4x4 Bayer order (= kit.tsx).
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];

type Ctx = { key: string; mask: (level: number) => string | undefined };
const ShadeCtx = createContext<Ctx>({ key: "x", mask: (level) => (level >= 1 ? undefined : `url(#cw-m${Math.round(Math.max(0, level) * 16)})`) });

/** A dither mask (0..1 of the pixels lit) aligned to the screen grid in the current layer. */
export const useDither = () => useContext(ShadeCtx).mask;

/**
 * World-unit dither masks for one camera layer (`zoom` = world -> screen scale; the layer's
 * translation must be a multiple of P), and the context the views' shading reads them from.
 */
export const DitherLayer = ({ id, zoom, children }: { id: string; zoom: number; children: ReactNode }) => {
  const cell = P / zoom;
  const big = 20000;
  return (
    <>
      <defs>
        {Array.from({ length: 17 }, (_, k) => (
          <g key={k}>
            <pattern id={`cw-wp${id}${k}`} width={4 * cell} height={4 * cell} patternUnits="userSpaceOnUse">
              {BAYER.map((v, i) => (v < k ? <rect key={i} x={(i % 4) * cell} y={Math.floor(i / 4) * cell} width={cell} height={cell} fill="#fff" /> : null))}
            </pattern>
            <mask id={`cw-wm${id}${k}`} maskUnits="userSpaceOnUse" x={-big} y={-big} width={2 * big} height={2 * big}>
              <rect x={-big} y={-big} width={2 * big} height={2 * big} fill={`url(#cw-wp${id}${k})`} />
            </mask>
          </g>
        ))}
      </defs>
      <ShadeCtx.Provider value={{ key: id, mask: (level) => (level >= 1 ? undefined : `url(#cw-wm${id}${Math.round(Math.max(0, level) * 16)})`) }}>{children}</ShadeCtx.Provider>
    </>
  );
};

const useKey = () => {
  const { key } = useContext(ShadeCtx);
  return `cw${key}${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
};

/**
 * A body painted in volume: `d` its outline, `c` its centre, `size` its rough diameter. Tones
 * step from the shadow side to the lit side (each seam dithered), a highlight blob sits toward
 * the light, a rim light rings the lit edge, specular pixels sparkle on it, an ink outline.
 * `children` are drawn inside the body (clipped), e.g. striations or a cutaway window.
 */
export const Shade = ({ d, c, size, ramp, light = LIGHT, axis, rim = RIM, outline = true, spec = true, children }: { d: string; c: readonly [number, number]; size: number; ramp: Ramp; light?: readonly [number, number]; axis?: number; rim?: string | null; outline?: boolean; spec?: boolean; children?: ReactNode }) => {
  const id = useKey();
  const dither = useDither();
  const [lx, ly] = light;
  // Each lighter tone is the body shrunk toward the lit side: shadow wraps the far edges.
  // A long body (`axis`, its direction in degrees) shrinks across its axis only, like a cylinder.
  const shrink = (k: number) => (axis === undefined ? `scale(${1 - k * 0.9})` : `rotate(${axis}) scale(${1 - k * 0.12} ${1 - k * 0.9}) rotate(${-axis})`);
  const at = (k: number) => `translate(${c[0] + lx * size * k * 0.6} ${c[1] + ly * size * k * 0.6}) ${shrink(k)} translate(${-c[0]} ${-c[1]})`;
  const band = 0.03;
  const steps: [number, string][] = [[0.08, ramp[1]], [0.2, ramp[2]], [0.42, ramp[3]]];
  const hl = at(0.62);
  return (
    <g>
      <defs>
        <clipPath id={`${id}c`}>
          <path d={d} />
        </clipPath>
        {rim && (
          <mask id={`${id}r`} maskUnits="userSpaceOnUse" x={c[0] - size * 2} y={c[1] - size * 2} width={size * 4} height={size * 4}>
            <path d={d} fill="#fff" />
            <path d={d} fill="#000" transform={`translate(${-lx * size * 0.06} ${-ly * size * 0.06})`} />
          </mask>
        )}
      </defs>
      <g clipPath={`url(#${id}c)`}>
        <path d={d} fill={ramp[0]} />
        {steps.map(([k, color]) => (
          <g key={k}>
            <g mask={dither(0.5)}>
              <path d={d} fill={color} transform={at(k - band)} />
            </g>
            <path d={d} fill={color} transform={at(k)} />
          </g>
        ))}
        <g mask={dither(0.5)}>
          <path d={d} fill={ramp[4]} transform={hl} />
        </g>
        <path d={d} fill={ramp[4]} transform={at(0.72)} />
        {children}
      </g>
      {rim && <path d={d} fill={rim} mask={`url(#${id}r)`} />}
      {spec && (
        <g fill="#FFFFFF">
          <rect x={c[0] + lx * size * 0.36 - 6} y={c[1] + ly * size * 0.36 - 6} width={12} height={12} />
          <rect x={c[0] + lx * size * 0.36 + 10} y={c[1] + ly * size * 0.36 + 10} width={7} height={7} />
        </g>
      )}
      {outline && <path d={d} fill="none" stroke={C.ink} strokeWidth={6} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />}
    </g>
  );
};

// Outline helpers: paths for common bodies.
/** An ellipse as a path. */
export const ellipseD = (cx: number, cy: number, rx: number, ry: number) =>
  `M${cx - rx} ${cy}A${rx} ${ry} 0 1 0 ${cx + rx} ${cy}A${rx} ${ry} 0 1 0 ${cx - rx} ${cy}Z`;
/** A capsule (rounded rod) from a to b, `w` wide. */
export const capsuleD = (a: readonly [number, number], b: readonly [number, number], w: number) => {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
  const nx = (-(b[1] - a[1]) / len) * (w / 2);
  const ny = ((b[0] - a[0]) / len) * (w / 2);
  const r = w / 2;
  return `M${a[0] + nx} ${a[1] + ny}L${b[0] + nx} ${b[1] + ny}A${r} ${r} 0 0 0 ${b[0] - nx} ${b[1] - ny}L${a[0] - nx} ${a[1] - ny}A${r} ${r} 0 0 0 ${a[0] + nx} ${a[1] + ny}Z`;
};
/** A closed smooth outline through points (Catmull-Rom as cubic Béziers). */
export const blobD = (pts: readonly (readonly [number, number])[]) => {
  const n = pts.length;
  let d = `M${pts[0][0]} ${pts[0][1]}`;
  for (let i = 0; i < n; i++) {
    const p0 = pts[(i - 1 + n) % n];
    const p1 = pts[i];
    const p2 = pts[(i + 1) % n];
    const p3 = pts[(i + 2) % n];
    d += `C${p1[0] + (p2[0] - p0[0]) / 6} ${p1[1] + (p2[1] - p0[1]) / 6} ${p2[0] - (p3[0] - p1[0]) / 6} ${p2[1] - (p3[1] - p1[1]) / 6} ${p2[0]} ${p2[1]}`;
  }
  return `${d}Z`;
};
