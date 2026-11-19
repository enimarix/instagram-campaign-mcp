// The editorial kit (step 144): the typographic duo (white Inter Tight 900 + pink Instrument
// Serif Italic), kicker chips, chapter counters, the timeline scrubber, viewfinder brackets,
// tag chips, the social-proof number card and the anatomy cards' deep blue ground. One easing
// everywhere: cubic-bezier(.22, 1, .36, 1).
import type { CSSProperties, ReactNode } from "react";
import { Easing } from "remotion";
import { brand } from "../brand";
import { fonts } from "../lib/font";
import { frenchSpaces } from "../lib/french";
import { seeded } from "../lib/game.ts";
import { span } from "../voxel/anim.ts";
import { BLOSSOM, CYAN, DEEP, GREY, PINK, WHITE, YELLOW } from "./palette.ts";

export const W = 1080;
export const H = 1920;
/** Left edge of the text column (safe area 65 px + air). */
export const LEFT = 90;
export const RIGHT = 990;

const smooth = Easing.bezier(0.22, 1, 0.36, 1);
/** 0..1, eased, over `length` frames from `start`. */
export const ease = (f: number, start: number, length: number) => smooth(span(f, start, length));

export const GROTESK: CSSProperties = { fontFamily: `"${fonts.display}", sans-serif`, fontWeight: 900, letterSpacing: "-0.045em", color: WHITE };
export const SERIF: CSSProperties = { fontFamily: `"${fonts.serif}", serif`, fontStyle: "italic", fontWeight: 400, letterSpacing: "-0.01em", color: PINK };
export const BODY: CSSProperties = { fontFamily: `"${fonts.body}", sans-serif`, color: WHITE };
const PIXEL: CSSProperties = { fontFamily: `"${fonts.pixel}", monospace` };

/** French spacing, and a number kept with the word after it (« 72 h », « 20 minutes »). */
export const glue = (text: string) => frenchSpaces(text).replace(/(\d) (?=\p{L})/gu, "$1\u00a0");

/** SVG defs every scene uses: `px` pixelates (8 px blocks) what it is applied to. */
export const PixelDefs = () => (
  <defs>
    <filter id="px" x="-20%" y="-20%" width="140%" height="140%">
      <feFlood x="4" y="4" height="1" width="1" />
      <feComposite width="8" height="8" />
      <feTile result="grid" />
      <feComposite in="SourceGraphic" in2="grid" operator="in" />
      <feMorphology operator="dilate" radius="4" />
    </filter>
  </defs>
);

/**
 * Words rising out of a mask, one after the other from `start` (frames, -1 = already there).
 * `struck` words get a pink line drawn through them from `strikeAt`.
 */
export const Rise = ({ text, f, start, style, stagger = 2, struck, strikeAt = 0 }: { text: string; f: number; start: number; style: CSSProperties; stagger?: number; struck?: (i: number) => boolean; strikeAt?: number }) => (
  <span style={style}>
    {glue(text)
      .split(" ")
      .map((w, i) => {
        const t = start < 0 ? 1 : ease(f, start + i * stagger, 16);
        const line = struck?.(i) ? ease(f, strikeAt + i, 10) : 0;
        return (
          <span key={i} style={{ display: "inline-block", overflow: "hidden", verticalAlign: "top", padding: "0.04em 0.06em 0.24em", margin: "-0.04em 0.12em -0.24em -0.06em" }}>
            <span style={{ display: "inline-block", position: "relative", transform: `translateY(${(1 - t) * 115}%)` }}>
              {w}
              {line > 0 && <span style={{ position: "absolute", left: "-3%", top: "54%", height: "0.09em", width: `${106 * line}%`, background: PINK, borderRadius: 4 }} />}
            </span>
          </span>
        );
      })}
  </span>
);

/** Indices of the words of `lead` that `strike` covers. */
export const struckWords = (lead: string, strike?: string) => {
  const at = strike ? lead.indexOf(strike) : -1;
  if (at < 0) return () => false;
  const words = glue(lead).split(" ");
  const ranges: [number, number][] = [];
  let pos = 0;
  for (const w of words) {
    ranges.push([pos, pos + w.length]);
    pos += w.length + 1;
  }
  return (i: number) => ranges[i][0] < at + strike!.length && ranges[i][1] > at;
};

/** The small caps chip: a pink dot, spaced capitals, a thin pink outline. */
export const Kicker = ({ text, f, start = -1, style }: { text: string; f: number; start?: number; style?: CSSProperties }) => {
  const t = start < 0 ? 1 : ease(f, start, 14);
  return (
    <div
      style={{
        ...BODY,
        display: "inline-flex",
        alignItems: "center",
        gap: 14,
        padding: "10px 22px 11px 18px",
        border: `2px solid ${PINK}`,
        borderRadius: 999,
        fontSize: 24,
        fontWeight: 700,
        letterSpacing: "0.22em",
        textTransform: "uppercase",
        opacity: t,
        transform: `translateY(${(1 - t) * -16}px)`,
        ...style,
      }}
    >
      <span style={{ width: 12, height: 12, borderRadius: 6, background: PINK, boxShadow: `0 0 12px ${PINK}` }} />
      {frenchSpaces(text)}
    </div>
  );
};

const two = (n: number) => String(n).padStart(2, "0");

/** « 03 / 07 »: the current chapter ticks over when it changes. */
export const Counter = ({ n, total, f }: { n: number; total: number; f: number }) => {
  const t = ease(f, 0, 12);
  return (
    <div style={{ ...BODY, position: "absolute", right: W - RIGHT, top: 300, fontSize: 30, fontWeight: 700, letterSpacing: "0.08em", display: "flex", gap: 10 }}>
      <span style={{ display: "inline-block", overflow: "hidden", height: "1.2em" }}>
        <span style={{ display: "inline-block", transform: `translateY(${(1 - t) * 100}%)` }}>{two(n)}</span>
      </span>
      <span style={{ color: GREY }}>/ {two(total)}</span>
    </div>
  );
};

/** French seconds: « 12,4 S ». */
const seconds = (s: number, digits = 1) => `${s.toFixed(digits).replace(".", ",")}\u00a0S`;

/**
 * The timeline scrubber at the bottom of the safe area: ticks, « 0 S » … « 28 S », the pink
 * playhead (a diamond and a hairline) at `p` (0..1) with the time under it, and an optional
 * cyan range (the gust).
 */
export const Scrubber = ({ p, total_s, range, y = 1200, opacity = 1 }: { p: number; total_s: number; range?: [number, number]; y?: number; opacity?: number }) => {
  const x = (v: number) => LEFT + (RIGHT - LEFT) * v;
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H, opacity }}>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        <line x1={LEFT} x2={RIGHT} y1={y} y2={y} stroke="#4A4750" strokeWidth={2} />
        {Array.from({ length: 21 }, (_, i) => (
          <line key={i} x1={x(i / 20)} x2={x(i / 20)} y1={y - (i % 5 ? 6 : 12)} y2={y} stroke="#4A4750" strokeWidth={2} />
        ))}
        {range && <rect x={x(range[0])} y={y - 9} width={x(range[1]) - x(range[0])} height={18} rx={4} fill={CYAN} style={{ filter: `drop-shadow(0 0 10px ${CYAN})` }} />}
        <line x1={x(p)} x2={x(p)} y1={y - 26} y2={y + 14} stroke={WHITE} strokeWidth={3} />
        <rect x={x(p) - 11} y={y - 52} width={22} height={22} fill={PINK} transform={`rotate(45 ${x(p)} ${y - 41})`} style={{ filter: `drop-shadow(0 0 8px ${PINK})` }} />
      </svg>
      {[
        // The ends' labels give way to the playhead's.
        ...(p > 0.14 ? [[LEFT, "0\u00a0S", GREY, "left"]] : []),
        ...(p < 0.86 ? [[RIGHT, `${Math.round(total_s)}\u00a0S`, GREY, "right"]] : []),
        [x(p), seconds(p * total_s), PINK, "center"],
      ].map(([at, text, color, align], i) => (
        <div
          key={i}
          style={{
            ...BODY,
            position: "absolute",
            top: y + 20,
            left: (at as number) - (align === "left" ? 0 : align === "right" ? 200 : 100),
            width: 200,
            textAlign: align as "left",
            fontSize: 22,
            fontWeight: 700,
            letterSpacing: "0.12em",
            color: color as string,
          }}
        >
          {text}
        </div>
      ))}
    </div>
  );
};

/** Viewfinder corners closing in on a box (p 0 → 1). */
export const Brackets = ({ x, y, w, h, p, color = PINK }: { x: number; y: number; w: number; h: number; p: number; color?: string }) => {
  const grow = 160 * (1 - p);
  const [l, t, r, b] = [x - grow, y - grow, x + w + grow, y + h + grow];
  const arm = 56;
  return (
    <g fill="none" stroke={color} strokeWidth={5} opacity={Math.min(1, p * 2)}>
      <path d={`M${l} ${t + arm}V${t}H${l + arm}M${r - arm} ${t}H${r}V${t + arm}M${r} ${b - arm}V${b}H${r - arm}M${l + arm} ${b}H${l}V${b - arm}`} />
    </g>
  );
};

/** A faint dot grid: the editor's canvas. */
export const DotGrid = ({ opacity }: { opacity: number }) => (
  <div style={{ position: "absolute", inset: 0, opacity, backgroundImage: "radial-gradient(rgba(255,255,255,0.14) 1.6px, transparent 1.8px)", backgroundSize: "30px 30px" }} />
);

/** A chip beside the tree: « ✕ grignotage » (pink) or « ✓ 8 h de sommeil » (green). */
export const TagChip = ({ text, mark, style }: { text: string; mark: "no" | "yes"; style?: CSSProperties }) => {
  const color = mark === "no" ? PINK : brand.colors.brand;
  return (
    <div style={{ ...BODY, display: "inline-flex", alignItems: "center", gap: 12, padding: "10px 22px 12px 16px", borderRadius: 999, border: `2px solid ${color}`, background: "rgba(0,0,0,0.75)", fontSize: 32, fontWeight: 600, whiteSpace: "nowrap", ...style }}>
      <span style={{ color, fontWeight: 800 }}>{mark === "no" ? "✕" : "✓"}</span>
      {frenchSpaces(text)}
    </div>
  );
};

/** The social-proof number: big bold value, its unit in pink italic, a small note under it. */
export const StatCard = ({ value, unit, note, f, start, style }: { value: string; unit: string; note?: string; f: number; start: number; style?: CSSProperties }) => {
  const t = ease(f, start, 18);
  return (
    <div style={{ opacity: t, transform: `translateY(${(1 - t) * 40}px)`, ...style }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 18 }}>
        <span style={{ ...GROTESK, fontSize: 168, lineHeight: 1 }}>{frenchSpaces(value)}</span>
        <span style={{ ...SERIF, fontSize: 96, lineHeight: 1 }}>{frenchSpaces(unit)}</span>
      </div>
      {note && <div style={{ ...BODY, marginTop: 14, fontSize: 34, fontWeight: 500, color: "rgba(247,245,242,0.72)" }}>{frenchSpaces(note)}</div>}
    </div>
  );
};

/**
 * Capitals for the pixel font, without accents: Press Start 2P draws accented capitals as
 * small letters (« SéANCE »), and French capitals may drop their accents.
 */
export const pixelCaps = (text: string) => glue(text).toUpperCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").normalize("NFC");

/** The pixel caption of an anatomy card: capitals, the `highlight` part in yellow. */
export const PixelCaption = ({ text, highlight, style }: { text: string; highlight?: string; style?: CSSProperties }) => {
  const up = pixelCaps(text);
  const mark = highlight ? pixelCaps(highlight) : "";
  const at = mark ? up.indexOf(mark) : -1;
  const parts = at < 0 ? [up] : [up.slice(0, at), up.slice(at, at + mark.length), up.slice(at + mark.length)];
  return (
    <div style={{ ...PIXEL, fontSize: 40, lineHeight: 1.6, color: WHITE, textAlign: "center", textShadow: "4px 4px 0 #0C0E33", textWrap: "balance", ...style }}>
      {parts.map((p, i) => (
        <span key={i} style={i === 1 ? { color: YELLOW } : undefined}>
          {p}
        </span>
      ))}
    </div>
  );
};

/** A wavy rope from top to bottom: `x0` its axis, `ph` its phase, `amp` its swing. */
const rope = (x0: number, ph: number, amp: number) =>
  `M${Array.from({ length: 14 }, (_, k) => `${(x0 + Math.sin(k * 0.9 + ph) * amp).toFixed(1)} ${k * 130 - 80}`).join("L")}`;

/**
 * The anatomy card's ground: deep blue, layered and moving at different speeds (parallax): far
 * dark ropes, near light ropes, drifting rings, bubbles rising, a soft glow behind the
 * character, a halftone dither and a vignette. `drift` shifts the near layers (the camera).
 */
export const DeepGround = ({ f, drift = 0, children }: { f: number; drift?: number; children?: ReactNode }) => (
  <svg width={1000} height={1560} viewBox="0 0 1000 1560" style={{ position: "absolute", inset: 0 }}>
    <defs>
      <pattern id="dither" width="8" height="8" patternUnits="userSpaceOnUse">
        <rect width="4" height="4" fill="#000" opacity="0.18" />
        <rect x="4" y="4" width="4" height="4" fill="#000" opacity="0.18" />
      </pattern>
      <radialGradient id="deepVignette" cx="50%" cy="45%" r="75%">
        <stop offset="0.55" stopColor="#000" stopOpacity="0" />
        <stop offset="1" stopColor="#000" stopOpacity="0.55" />
      </radialGradient>
      <radialGradient id="deepGlow" cx="50%" cy="50%" r="50%">
        <stop offset="0" stopColor="#5A63E8" stopOpacity="0.55" />
        <stop offset="1" stopColor="#5A63E8" stopOpacity="0" />
      </radialGradient>
    </defs>
    <rect width={1000} height={1560} fill={DEEP.ground} />
    <g fill="none" stroke={DEEP.rim} strokeWidth={34} strokeLinecap="round" opacity={0.7} filter="url(#px)" transform={`translate(${drift * 0.3} 0)`}>
      {[220, 520, 800].map((x0, i) => (
        <path key={i} d={rope(x0, f / 80 + i * 2, 40)} />
      ))}
    </g>
    <ellipse cx={500} cy={560} rx={460} ry={520} fill="url(#deepGlow)" />
    <g fill="none" stroke={DEEP.shape} strokeWidth={46} strokeLinecap="round" filter="url(#px)" transform={`translate(${drift * 0.7} 0)`}>
      {[80, 360, 660, 920].map((x0, i) => (
        <path key={i} d={rope(x0, f / 45 + i, 60)} opacity={0.85} />
      ))}
    </g>
    <g fill="none" stroke={DEEP.shapeLight} strokeWidth={30} filter="url(#px)" transform={`translate(${drift} 0)`}>
      {[[120, 260, 70], [830, 520, 90], [180, 1180, 80], [860, 1320, 60]].map(([x, y, r], i) => (
        <circle key={i} cx={x + Math.sin(f / 40 + i) * 16} cy={y + Math.cos(f / 47 + i) * 14} r={r} />
      ))}
    </g>
    <g fill="none" stroke="#7C84FF" strokeWidth={6} opacity={0.6}>
      {Array.from({ length: 9 }, (_, i) => {
        const y = 1600 - ((f * (2 + (i % 3)) + i * 190) % 1700);
        return <circle key={i} cx={60 + ((i * 337) % 880) + Math.sin(f / 15 + i) * 14} cy={y} r={8 + (i % 4) * 5} />;
      })}
    </g>
    <rect width={1000} height={1560} fill="url(#dither)" />
    {children}
    <rect width={1000} height={1560} fill="url(#deepVignette)" />
  </svg>
);

/**
 * Petals drifting down the whole frame (the hook, the type beats, the end card), at depths:
 * far ones small pixel squares, near ones big soft petals, faster and out of focus (parallax).
 * Seeded; `frame` drives everything, so they move from the first frame.
 */
export const Drift = ({ frame, count = 16, opacity = 1 }: { frame: number; count?: number; opacity?: number }) => (
  <svg width={W} height={H} style={{ position: "absolute", inset: 0, opacity, overflow: "visible" }}>
    <defs>
      <filter id="driftBlur" x="-100%" y="-100%" width="300%" height="300%">
        <feGaussianBlur stdDeviation="5" />
      </filter>
    </defs>
    {Array.from({ length: count }, (_, i) => {
      const r = (k: number) => seeded(41, i * 7 + k);
      const z = r(6);
      const speed = (1.2 + r(1) * 1.2) * (0.6 + 1.6 * z);
      const y = ((r(2) * 2100 + frame * speed) % 2100) - 100;
      const x = (((r(3) * W + Math.sin(frame / 22 + i) * 30 + frame * 0.8 * (0.5 + z)) % (W + 120)) + W + 120) % (W + 120) - 60;
      const color = BLOSSOM[3 + (i % 3)];
      if (z < 0.7) {
        const size = z < 0.35 ? 4 : 8;
        const flip = Math.floor((frame + i * 5) / 7) % 2;
        return <rect key={i} x={Math.round(x / 4) * 4} y={Math.round(y / 4) * 4} width={size} height={flip ? size / 2 : size} fill={color} opacity={0.45 + z * 0.6} shapeRendering="crispEdges" />;
      }
      // Near: a soft petal, turning and tumbling.
      const size = 14 + (z - 0.7) * 70;
      return (
        <ellipse key={i} cx={x} cy={y} rx={size} ry={size * 0.55 * Math.max(0.25, Math.abs(Math.cos(frame / 9 + i)))} transform={`rotate(${(frame * 3 + i * 40) % 360} ${x} ${y})`} fill={color} opacity={0.75} filter="url(#driftBlur)" />
      );
    })}
  </svg>
);
