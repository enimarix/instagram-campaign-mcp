// The paper style's building blocks (step 131), rewritten for Remotion from the owner's
// paper.js: kraft paper, cut-out pieces (a soft brown drop shadow under every piece), sheets
// with jittered corners, Fredoka labels on cream strips, Caveat handwriting, stars and moon,
// and the two transitions (a sheet torn in two, a coloured sheet wiped across).
import type { CSSProperties, ReactNode } from "react";
import { fonts } from "../lib/font";
import { frenchSpaces } from "../lib/french";
import { backOut, easeInOut, span } from "../voxel/anim.ts";
import { seeded } from "../lib/game";
import { CREAM, INK, KRAFT, SHEETS, type SheetId } from "./palette.ts";

/** Deterministic 0..1 jitter for cut corners and torn edges. */
const hash = (i: number, seed: number) => seeded(seed, i);

export const W = 1080;
export const H = 1920;
export const LABEL_FONT = `"${fonts.paper}", "${fonts.display}", sans-serif`;
export const HAND_FONT = `"${fonts.hand}", "${fonts.body}", cursive`;

/** Shadow of a cut-out piece lying `z` sheets above the paper (paper.js cut()). */
export const cutShadow = (z = 1) =>
  `drop-shadow(${(z * 2.5).toFixed(1)}px ${(z * 5).toFixed(1)}px ${((4 + z * 5) / 2).toFixed(1)}px rgba(70, 45, 20, 0.36))`;

/** SVG filters the pieces use (`filter="url(#cut1)"`), one per height. Put once in every SVG. */
export const CutDefs = () => (
  <defs>
    {[
      ["cut05", 0.5],
      ["cut1", 1],
      ["cut15", 1.5],
      ["cut2", 2],
    ].map(([id, z]) => (
      <filter key={id} id={id as string} x="-30%" y="-30%" width="160%" height="160%">
        <feDropShadow dx={(z as number) * 2.5} dy={(z as number) * 5} stdDeviation={(4 + (z as number) * 5) / 2} floodColor="rgb(70, 45, 20)" floodOpacity={0.36} />
      </filter>
    ))}
  </defs>
);

/** A wobbly circle path (paper.js wc): a hand-cut disc, radius jittered ±2 %. */
export const wobble = (x: number, y: number, r: number, seed = 1, ry = r) => {
  const n = 40;
  const pts: string[] = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    const k = 1 + (hash(i, seed) - 0.5) * 0.04;
    pts.push(`${(x + Math.cos(a) * r * k).toFixed(1)},${(y + Math.sin(a) * ry * k).toFixed(1)}`);
  }
  return `M${pts.join("L")}Z`;
};

/** A hand-cut rectangle (paper.js wrect): each corner moved up to `j` px. */
export const cutRect = (x: number, y: number, w: number, h: number, seed = 1, j = 5) => {
  const pts = [
    [x, y],
    [x + w, y],
    [x + w, y + h],
    [x, y + h],
  ].map(([a, b], i) => `${(a + (hash(i, seed) - 0.5) * j * 2).toFixed(1)},${(b + (hash(i + 9, seed) - 0.5) * j * 2).toFixed(1)}`);
  return `M${pts.join("L")}Z`;
};

/** Kraft paper: flat colour plus fibres (fractal noise), the same in every frame. */
export const Kraft = ({ id, color, seed }: { id: string; color: string; seed: number }) => (
  <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
    <filter id={id}>
      <feTurbulence type="fractalNoise" baseFrequency="0.9 0.35" numOctaves={3} seed={seed} />
      <feColorMatrix values="0 0 0 0 0.35  0 0 0 0 0.25  0 0 0 0 0.12  0 0 0 0.22 0" />
    </filter>
    <rect width="100%" height="100%" fill={color} />
    <rect width="100%" height="100%" filter={`url(#${id})`} />
  </svg>
);

/** The kraft frame and the scene's sheet on it (paper.js sheet()): slightly crooked, cut by hand. */
export const Sheet = ({ sheet, seed, children }: { sheet: SheetId; seed: number; children?: ReactNode }) => (
  <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
    <Kraft id={`kraft-${seed}`} color={KRAFT} seed={seed % 7} />
    <svg width={W} height={H} style={{ position: "absolute", inset: 0, transform: "rotate(-0.46deg)", filter: cutShadow(2) }}>
      <path d={cutRect(46, 46, W - 92, H - 92, seed, 9)} fill={SHEETS[sheet]} />
    </svg>
    {children}
  </div>
);

/** The film's finish over every frame: paper grain, a 12 fps light flicker, a warm vignette. */
export const Finish = ({ step }: { step: number }) => {
  const flicker = (hash(step, 3) - 0.5) * 0.05;
  return (
    <>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, mixBlendMode: "soft-light", opacity: 0.5 }}>
        <filter id="grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.8 0.5" numOctaves={2} seed={77} />
          <feColorMatrix values="0 0 0 0 0.85  0 0 0 0 0.8  0 0 0 0 0.72  0 0 0 0.9 0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#grain)" />
      </svg>
      <div style={{ position: "absolute", inset: 0, background: flicker > 0 ? `rgba(255, 240, 210, ${flicker})` : `rgba(30, 20, 10, ${-flicker})` }} />
      <div style={{ position: "absolute", inset: 0, background: "radial-gradient(circle 1250px at 50% 50%, rgba(40, 25, 10, 0) 48%, rgba(40, 25, 10, 0.35) 100%)" }} />
    </>
  );
};

/** Label tones: the strip's paper and its text colour. */
export const TONES = {
  cream: { bg: CREAM, fg: INK },
  brand: { bg: "#10B981", fg: "#FFFFFF" },
  yellow: { bg: "#FFD24D", fg: INK },
  red: { bg: "#E5484D", fg: "#FFFFFF" },
  ink: { bg: INK, fg: "#FFFFFF" },
  sky: { bg: "#BDE0FE", fg: INK },
} as const;
export type Tone = keyof typeof TONES;

/** Fredoka 700 averages about 0.46 em a character (0.48 to be safe): the size whose strip fits `width`. */
export const fitLabel = (text: string, size: number, width: number) => Math.min(size, Math.floor(width / (Array.from(text).length * 0.48 + 0.9)));

/** A pop with overshoot from `start` (paper.js pop): 0 before, 1 settled. */
export const pop = (f: number, start: number, length = 7) => (f < start ? 0 : backOut(span(f, start, length), 0.15));

/**
 * A text strip (paper.js label): Fredoka on a cut strip of paper, a little crooked, popping
 * in at `start` (frames). Centred on (x, y); shrinks to fit `maxWidth`.
 */
export const Label = ({ text, x, y, size, tone = "cream", rot = 0, f, start, maxWidth = 820, bg }: { text: string; x: number; y: number; size: number; tone?: Tone; rot?: number; f: number; start: number; maxWidth?: number; bg?: string }) => {
  const s = pop(f, start);
  if (s <= 0) return null;
  const t = TONES[tone];
  const fs = fitLabel(text, size, maxWidth);
  return (
    <div style={{ position: "absolute", left: x, top: y, transform: `translate(-50%, -50%) rotate(${rot}deg) scale(${s})`, filter: cutShadow(1.2) }}>
      <div
        style={{
          fontFamily: LABEL_FONT,
          fontWeight: 700,
          fontSize: fs,
          lineHeight: 1,
          whiteSpace: "nowrap",
          color: t.fg,
          background: bg ?? t.bg,
          padding: `${fs * 0.24}px ${fs * 0.45}px ${fs * 0.28}px`,
          clipPath: `polygon(${[0, 1, 2, 3].map((i) => `${[0, 100, 100, 0][i] + (hash(i, text.length) - 0.5) * 0.8}% ${[0, 0, 100, 100][i] + (hash(i + 9, text.length) - 0.5) * 6}%`).join(", ")})`,
        }}
      >
        {frenchSpaces(text)}
      </div>
    </div>
  );
};

/** Handwriting (Caveat) for asides, e.g. « (spoiler : pas une pizza) ». */
export const Hand = ({ text, x, y, size = 62, color = INK, rot = -3, style }: { text: string; x: number; y: number; size?: number; color?: string; rot?: number; style?: CSSProperties }) => (
  <div style={{ position: "absolute", left: x, top: y, transform: `translate(-50%, -50%) rotate(${rot}deg)`, fontFamily: HAND_FONT, fontWeight: 700, fontSize: size, lineHeight: 1, whiteSpace: "nowrap", color, ...style }}>
    {frenchSpaces(text)}
  </div>
);

/** Cut-out paper stars and a crescent moon for the night sheet; stars twinkle on 12 fps steps. */
export const Night = ({ step, seed }: { step: number; seed: number }) => (
  <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
    <CutDefs />
    {Array.from({ length: 14 }, (_, i) => {
      const x = 90 + hash(i, seed) * 900;
      const y = 100 + hash(i + 40, seed) * 1100;
      const r = (10 + hash(i + 80, seed) * 14) * ((step + i) % 7 === 0 ? 0.6 : 1);
      const rot = hash(i + 120, seed) * 3;
      const d = Array.from({ length: 10 }, (_, k) => {
        const a = rot + (k / 10) * Math.PI * 2;
        const rr = k % 2 ? r * 0.5 : r;
        return `${(x + Math.cos(a) * rr).toFixed(1)},${(y + Math.sin(a) * rr).toFixed(1)}`;
      });
      return <path key={i} d={`M${d.join("L")}Z`} fill="#FFF1B8" filter="url(#cut05)" />;
    })}
    <mask id="moon">
      <rect width={W} height={H} fill="#fff" />
      <circle cx={971.5} cy={172.5} r={59.5} fill="#000" />
    </mask>
    <g filter="url(#cut1)">
      <circle cx={940} cy={190} r={70} fill="#FFF1B8" mask="url(#moon)" />
    </g>
  </svg>
);

/** The torn line of a sheet torn top to bottom (paper.js tearPath), as polygon points. */
const tearLine = () => {
  const pts: [number, number][] = [];
  for (let y = -100, i = 0; y <= H + 100; y += 24, i++) pts.push([540 + Math.sin(y * 0.006) * 80 + (hash(i, 9) - 0.5) * 50, y]);
  return pts;
};
const TEAR = tearLine();

/**
 * Tear (paper.js tear): the previous scene, frozen, torn down the middle; its halves swing
 * apart and away over `p` (0..1), showing the new scene under them. `children` = the frozen scene.
 */
export const Tear = ({ p, children }: { p: number; children: ReactNode }) => {
  const e = easeInOut(p);
  return (
    <>
      {[-1, 1].map((side) => {
        const outer = side < 0 ? -300 : W + 300;
        const poly = [[outer, -100] as [number, number], ...TEAR, [outer, H + 100] as [number, number]];
        const points = poly.map(([x, y]) => `${x}px ${y}px`).join(", ");
        return (
          <div
            key={side}
            style={{
              position: "absolute",
              inset: 0,
              transformOrigin: "540px 960px",
              transform: `translate(${side * e * 900}px, ${e * 120}px) rotate(${side * e * 9.2}deg)`,
              filter: `drop-shadow(${side * -8}px 0 15px rgba(40, 25, 10, 0.5))`,
            }}
          >
            <div style={{ position: "absolute", inset: 0, clipPath: `polygon(${points})` }}>{children}</div>
            <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
              <polyline points={TEAR.map(([x, y]) => `${x},${y}`).join(" ")} fill="none" stroke="#FBF4E6" strokeWidth={12} />
            </svg>
          </div>
        );
      })}
    </>
  );
};

/** Wipe (paper.js sheetWipe): a coloured sheet with torn edges swept right to left; covers the frame at p = 0.5. */
export const Wipe = ({ p, color }: { p: number; color: string }) => {
  const x = 2080 + (-1000 - 2080) * easeInOut(p);
  const pts: string[] = [];
  for (let y = -1300, i = 0; y <= 1300; y += 26, i++) pts.push(`${(850 + (hash(i, 4) - 0.5) * 36).toFixed(1)},${y}`);
  for (let y = 1300, i = 0; y >= -1300; y -= 26, i++) pts.push(`${(-850 + (hash(i, 6) - 0.5) * 36).toFixed(1)},${y}`);
  return (
    <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
      <CutDefs />
      <g transform={`translate(${x} 960) rotate(-5.7)`}>
        <path d={`M${pts.join("L")}Z`} fill={color} filter="url(#cut2)" />
      </g>
    </svg>
  );
};
