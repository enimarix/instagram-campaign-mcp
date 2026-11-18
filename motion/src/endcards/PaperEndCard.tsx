// The paper style's end card (step 137), the owner's house style: a kraft frame, a kraft
// cover that tears open across the middle (white paper core along the torn edges) on the
// cream #FFF8EC sheet, then cut-out pieces slide in with a small overshoot and settle a little
// crooked, as paper does: the mB tile drops, the wordmark slides in, the tagline on a white
// strip, the « 7 jours gratuits » label stamps down, macrobody.fr is handwritten and
// underlined in the accent; the cameo (a cut-out character waving, or a food) slides up into
// the corner. Every move steps at 12 fps like the owner's paper videos. Settles by
// SETTLE_S.paper, then holds.
import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { assetById } from "../assets";
import { brand } from "../brand";
import { fonts } from "../lib/font";
import { seeded } from "../lib/game";
import { backOut, easeInOut, easeOut, span } from "../voxel/anim.ts";
import { MbTile, taglineOf, TRIAL, URL, Wordmark } from "./base";
import { ACCENTS, type CardProps, cameoOf } from "./schema.ts";

/** The owner's paper palette (brand-sources.md). */
export const PAPER = { kraft: "#C9A67A", kraftDark: "#B48F62", cream: "#FFF8EC", navy: "#2C3A63", mint: "#BFE8D6" } as const;
/** Fredoka (step 131) once its files are in; until then the fallback in the stack draws. */
export const PAPER_FONT = "Fredoka";
/** The handwriting face for the url (step 131 adds Caveat). */
const HAND = "Caveat";
const STEP_FPS = 12;

/** Frames (from the card's start, before stepping) at which each piece comes in. */
const AT = { tear: 3, tile: 12, word: 20, strip: 28, cameo: 30, pill: 38, url: 46, line: 52 };

/** The cut-out look: a white paper rim and a soft shadow round any silhouette. */
const CUT = "drop-shadow(4px 0 0 #fff) drop-shadow(-4px 0 0 #fff) drop-shadow(0 4px 0 #fff) drop-shadow(0 -4px 0 #fff) drop-shadow(0 10px 8px rgba(60, 40, 20, 0.28))";

/** A piece sliding in from (dx, dy) px with a small overshoot, rotation settling at `tilt`°. */
const slide = (f: number, start: number, dx: number, dy: number, tilt: number, length = 9): CSSProperties => {
  if (f < start) return { opacity: 0 };
  const t = backOut(span(f, start, length), 0.18);
  return { transform: `translate(${(1 - t) * dx}px, ${(1 - t) * dy}px) rotate(${tilt + (1 - t) * tilt * -4}deg)` };
};

/** A jagged torn line across the frame at height y: points every ~36 px, seeded. */
const tornEdge = (y: number, width: number, seed: number, amp = 26) => {
  const pts: [number, number][] = [];
  for (let i = 0, x = -20; x <= width + 20; i++, x += 30 + seeded(seed, i) * 14) {
    pts.push([x, y + (seeded(seed + 1, i) - 0.5) * amp]);
  }
  return pts;
};
const EDGE = tornEdge(980, 1080, 7);
const poly = (pts: [number, number][]) => pts.map(([x, y]) => `${x},${y}`).join(" ");

/** Kraft paper: flat colour plus fibres (fractal noise), the same in every frame. */
const Kraft = ({ id, color, seed }: { id: string; color: string; seed: number }) => (
  <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
    <filter id={id}>
      <feTurbulence type="fractalNoise" baseFrequency="0.9 0.35" numOctaves={3} seed={seed} />
      <feColorMatrix values="0 0 0 0 0.35  0 0 0 0 0.25  0 0 0 0 0.12  0 0 0 0.22 0" />
    </filter>
    <rect width="100%" height="100%" fill={color} />
    <rect width="100%" height="100%" filter={`url(#${id})`} />
  </svg>
);

/** The cover's two halves split along EDGE, each with the white core along its torn side. */
const TearHalf = ({ top, t }: { top: boolean; t: number }) => {
  const H = 1920;
  const W = 1080;
  const edge = top ? EDGE : [...EDGE].reverse();
  const shape = top ? [[-40, -40] as [number, number], ...edge, [W + 40, -40] as [number, number]] : [[W + 40, H + 40] as [number, number], ...edge, [-40, H + 40] as [number, number]];
  const core = edge.map(([x, y], i) => [x, y + (top ? 1 : -1) * (6 + seeded(3, i) * 8)] as [number, number]);
  const away = easeInOut(t);
  const move = top ? `translate(${-away * 140}px, ${-away * 1150}px) rotate(${-away * 9}deg)` : `translate(${away * 160}px, ${away * 1150}px) rotate(${away * 7}deg)`;
  return (
    <div style={{ position: "absolute", inset: 0, transform: move, transformOrigin: top ? "0 50%" : "100% 50%", filter: "drop-shadow(0 12px 14px rgba(60, 40, 20, 0.35))" }}>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        <defs>
          <clipPath id={`half-${top}`}>
            <polygon points={poly(shape)} />
          </clipPath>
          <filter id={`fib-${top}`}>
            <feTurbulence type="fractalNoise" baseFrequency="0.9 0.35" numOctaves={3} seed={top ? 11 : 12} />
            <feColorMatrix values="0 0 0 0 0.35  0 0 0 0 0.25  0 0 0 0 0.12  0 0 0 0.22 0" />
          </filter>
        </defs>
        {/* The white core shows a few px past the coloured face along the tear. */}
        <polygon points={poly(top ? [[-40, -40], ...core, [W + 40, -40]] : [[W + 40, H + 40], ...core, [-40, H + 40]])} fill="#F7F1E6" />
        <g clipPath={`url(#half-${top})`}>
          <rect x={-40} y={-40} width={W + 80} height={H + 80} fill={PAPER.kraftDark} />
          <rect x={-40} y={-40} width={W + 80} height={H + 80} filter={`url(#fib-${top})`} />
        </g>
      </svg>
    </div>
  );
};

const Ines = ({ wave }: { wave: number }) => (
  <svg width={150} height={330} viewBox="0 0 150 330" style={{ overflow: "visible" }}>
    {/* waving arm (behind the body), pivot at the shoulder */}
    <g transform={`rotate(${wave * 34} 112 134)`}>
      <rect x={102} y={44} width={22} height={92} rx={11} fill="#B9A3E3" />
      <circle cx={113} cy={42} r={14} fill="#C68B59" />
    </g>
    <rect x={44} y={232} width={24} height={86} rx={8} fill={PAPER.navy} />
    <rect x={82} y={232} width={24} height={86} rx={8} fill={PAPER.navy} />
    <rect x={36} y={312} width={36} height={14} rx={7} fill="#3B2A22" />
    <rect x={78} y={312} width={36} height={14} rx={7} fill="#3B2A22" />
    <rect x={30} y={120} width={90} height={124} rx={26} fill="#B9A3E3" />
    {[146, 172, 198, 224].map((y) => (
      <rect key={y} x={30} y={y} width={90} height={9} fill="#FFFFFF" opacity={0.85} />
    ))}
    <rect x={22} y={130} width={22} height={88} rx={11} fill="#B9A3E3" />
    <circle cx={33} cy={222} r={13} fill="#C68B59" />
    <rect x={64} y={100} width={22} height={24} fill="#C68B59" />
    <ellipse cx={75} cy={70} rx={42} ry={46} fill="#4A2C20" />
    <ellipse cx={75} cy={78} rx={33} ry={36} fill="#C68B59" />
    <path d="M40 66 Q75 20 112 64 Q96 44 75 46 Q54 44 40 66Z" fill="#4A2C20" />
    <circle cx={63} cy={80} r={4.5} fill="#2B1B14" />
    <circle cx={89} cy={80} r={4.5} fill="#2B1B14" />
    <path d="M64 96 Q76 106 88 96" fill="none" stroke="#2B1B14" strokeWidth={4} strokeLinecap="round" />
    <circle cx={56} cy={93} r={6} fill="#F08A7E" opacity={0.6} />
    <circle cx={96} cy={93} r={6} fill="#F08A7E" opacity={0.6} />
  </svg>
);

const Paul = ({ wave }: { wave: number }) => (
  <svg width={150} height={330} viewBox="0 0 150 330" style={{ overflow: "visible" }}>
    <g transform={`rotate(${wave * 34} 112 134)`}>
      <rect x={102} y={44} width={24} height={92} rx={12} fill="#3FBF7F" />
      <circle cx={114} cy={42} r={14} fill="#E8B48A" />
    </g>
    <rect x={42} y={232} width={28} height={86} rx={8} fill="#3E5C8A" />
    <rect x={80} y={232} width={28} height={86} rx={8} fill="#3E5C8A" />
    <rect x={34} y={312} width={40} height={14} rx={7} fill="#FFFFFF" stroke="#2C3A63" strokeWidth={3} />
    <rect x={76} y={312} width={40} height={14} rx={7} fill="#FFFFFF" stroke="#2C3A63" strokeWidth={3} />
    <rect x={28} y={118} width={94} height={126} rx={24} fill="#3FBF7F" />
    <rect x={20} y={128} width={24} height={88} rx={12} fill="#3FBF7F" />
    <circle cx={32} cy={220} r={13} fill="#E8B48A" />
    <rect x={64} y={100} width={22} height={24} fill="#E8B48A" />
    <ellipse cx={75} cy={76} rx={34} ry={38} fill="#E8B48A" />
    <path d="M40 70 Q42 32 76 34 Q110 34 110 68 Q100 52 78 54 Q58 50 40 70Z" fill="#2B1B14" />
    <circle cx={63} cy={80} r={4.5} fill="#2B1B14" />
    <circle cx={89} cy={80} r={4.5} fill="#2B1B14" />
    <path d="M62 95 Q76 108 90 95" fill="none" stroke="#2B1B14" strokeWidth={4} strokeLinecap="round" />
  </svg>
);

const Avocado = ({ wave }: { wave: number }) => (
  <svg width={190} height={240} viewBox="0 0 190 240" style={{ overflow: "visible", transform: `rotate(${wave * 6 - 3}deg)` }}>
    <path d="M95 10 C140 10 168 96 176 150 C186 210 146 234 95 234 C44 234 4 210 14 150 C22 96 50 10 95 10Z" fill="#2F6B3A" />
    <path d="M95 26 C132 26 156 100 162 150 C170 202 138 220 95 220 C52 220 20 202 28 150 C34 100 58 26 95 26Z" fill="#CFE6A0" />
    <circle cx={95} cy={156} r={40} fill="#8A5A3B" />
    <circle cx={82} cy={142} r={10} fill="#A8754F" />
    <circle cx={75} cy={92} r={5} fill="#2B1B14" />
    <circle cx={115} cy={92} r={5} fill="#2B1B14" />
    <path d="M84 106 Q95 114 106 106" fill="none" stroke="#2B1B14" strokeWidth={4} strokeLinecap="round" />
  </svg>
);

const CAMEO: Record<string, (p: { wave: number }) => ReactNode> = { ines: Ines, paul: Paul, avocado: Avocado };

export const PaperEndCard = ({ tagline, accent, address, cameo, font }: Omit<CardProps, "pixelate">) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  // Stepped motion: every piece moves on 12 fps steps.
  const f = Math.floor((frame * STEP_FPS) / fps) * (fps / STEP_FPS);
  const color = ACCENTS[accent];
  const label = `"${font ?? PAPER_FONT}", "${fonts.display}", sans-serif`;
  const hand = `"${HAND}", "${fonts.body}", sans-serif`;
  const tear = span(f, AT.tear, 12);
  const Cameo = CAMEO[cameoOf("paper", cameo)];
  const wave = f > AT.cameo + 10 ? (Math.sin((f - AT.cameo) / 3.2) + 1) / 2 : 0;
  const line = easeOut(span(f, AT.line, 12));
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <Kraft id="kraft-bg" color={PAPER.kraft} seed={3} />
      {/* The cream sheet, a little crooked, with a soft shadow on the kraft. */}
      <div
        style={{
          position: "absolute",
          left: 54,
          top: 120,
          width: 972,
          height: 1680,
          background: PAPER.cream,
          transform: "rotate(-0.8deg)",
          boxShadow: "0 18px 30px rgba(60, 40, 20, 0.3), inset 0 0 120px rgba(200, 170, 120, 0.18)",
        }}
      />
      <div style={{ position: "absolute", left: 0, right: 0, top: 300, display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center" }}>
        <div style={{ filter: CUT, ...slide(f, AT.tile, 0, -420, -2.5) }}>
          <MbTile size={210} />
        </div>
        <div style={{ marginTop: 36, ...slide(f, AT.word, -900, 0, -1) }}>
          <Wordmark style={{ fontFamily: label, fontWeight: 700, fontSize: 124, lineHeight: 1, letterSpacing: "-0.02em", color: PAPER.navy }} />
        </div>
        <div
          style={{
            marginTop: 34,
            maxWidth: 840,
            padding: "14px 28px 16px",
            background: "#FFFFFF",
            boxShadow: "0 6px 10px rgba(60, 40, 20, 0.22)",
            fontFamily: label,
            fontWeight: 600,
            fontSize: 44,
            lineHeight: 1.18,
            color: PAPER.navy,
            textWrap: "balance",
            ...slide(f, AT.strip, 900, 0, 1),
          }}
        >
          {taglineOf({ tagline, address })}
        </div>
        <div
          style={{
            marginTop: 40,
            padding: "14px 40px 18px",
            background: brand.colors.brand,
            color: "#FFFFFF",
            fontFamily: label,
            fontWeight: 700,
            fontSize: 56,
            boxShadow: "0 8px 12px rgba(60, 40, 20, 0.25)",
            // Stamped down: from big and light to its place.
            ...(f < AT.pill ? { opacity: 0 } : { transform: `rotate(-1.5deg) scale(${1 + 0.5 * (1 - easeOut(span(f, AT.pill, 6)))})` }),
          }}
        >
          {TRIAL}
        </div>
        <div style={{ marginTop: 30, position: "relative", fontFamily: hand, fontWeight: 600, fontStyle: "italic", fontSize: 58, color: PAPER.navy, opacity: f < AT.url ? 0 : 1, clipPath: `inset(-20px ${(1 - easeOut(span(f, AT.url, 8))) * 100}% -20px -20px)` }}>
          {URL}
          <svg width="110%" height={24} viewBox="0 0 300 24" preserveAspectRatio="none" style={{ position: "absolute", left: "-5%", bottom: -18, overflow: "visible" }}>
            <path d="M4 14 C60 6 120 18 170 11 S260 6 296 12" fill="none" stroke={color} strokeWidth={7} strokeLinecap="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - line} />
          </svg>
        </div>
      </div>
      {Cameo && (
        <div style={{ position: "absolute", right: 130, top: 1000, transformOrigin: "50% 100%", scale: "1.25", filter: CUT, ...slide(f, AT.cameo, 0, 600, 3, 10) }}>
          <Cameo wave={wave} />
        </div>
      )}
      {tear < 1 && (
        <>
          <TearHalf top t={tear} />
          <TearHalf top={false} t={tear} />
        </>
      )}
      <Sequence from={AT.tear} durationInFrames={20} layout="none">
        <Html5Audio src={assetById("sfx-select").src} volume={0.25} />
      </Sequence>
      <Sequence from={AT.pill} durationInFrames={30} layout="none">
        <Html5Audio src={assetById("sfx-pop").src} volume={0.4} />
      </Sequence>
    </AbsoluteFill>
  );
};
