// The cinema style's typography over the pixel set (step 143): clean bold white Inter Tight
// with one key word in amber, a red strike-through, numbered tag chips with a leader line into
// the set, a big counting stat, and the app as a small rounded card that floats in.
import type { CSSProperties } from "react";
import { MbTile, Wordmark } from "../endcards/base";
import { countUp } from "../lib/countUp";
import { fonts } from "../lib/font";
import { frenchSpaces } from "../lib/french";
import { splitHighlight } from "../templates/PixelCinema/schema.ts";
import { backOut, easeOut, span } from "../voxel/anim.ts";

export const CREAM = "#F7F3EA";
export const AMBER = "#FFB547";
export const RED = "#E8553E";
export const INK = "#12131F";
const SHADOW = "0 5px 0 rgba(6, 7, 20, 0.6), 0 12px 30px rgba(6, 7, 20, 0.5)";
/** Over the lightning's white sky: a thick ink outline under the fill (the reference keeps its white type). */
const OUTLINE: CSSProperties = { WebkitTextStroke: `12px ${INK}`, paintOrder: "stroke fill" };
export const DISPLAY: CSSProperties = { fontFamily: `"${fonts.display}", sans-serif`, fontWeight: 900, letterSpacing: "-0.03em" };
export const BODY: CSSProperties = { fontFamily: `"${fonts.body}", sans-serif` };

/** Rises 18 px and fades in over 6 frames from `start`. */
const rise = (f: number, start: number): CSSProperties => {
  const t = easeOut(span(f, start, 6));
  return { opacity: t, transform: `translateY(${(1 - t) * 18}px)` };
};

/** A rich text (`*key word*` in amber), French spacing. */
export const Rich = ({ text, accent = AMBER }: { text: string; accent?: string }) => {
  const [before, key, after] = splitHighlight(text);
  return (
    <>
      {frenchSpaces(before)}
      {key && <span style={{ color: accent }}>{frenchSpaces(key)}</span>}
      {frenchSpaces(after)}
    </>
  );
};

/**
 * A headline centred at `y` (its top): `f` frames since it started, `start` = when it rises
 * in; `strike` 0..1 draws the red bar through it and greys it.
 */
export const Headline = ({ text, y, f, start = 0, size = 76, strike, flash = false }: { text: string; y: number; f: number; start?: number; size?: number; strike?: number; flash?: boolean }) => {
  if (f < start) return null;
  const s = strike ?? 0;
  // A struck line stays on one line (the bar crosses it once): shrink it to fit 920 px.
  const px = strike === undefined ? size : Math.min(size, Math.floor(920 / (Array.from(text).length * 0.5)));
  return (
    <div style={{ position: "absolute", left: 80, right: 80, top: y, display: "flex", justifyContent: "center", ...rise(f, start) }}>
      <div style={{ ...DISPLAY, position: "relative", fontSize: px, lineHeight: 1.06, color: s > 0 ? `rgba(247, 243, 234, ${1 - 0.25 * s})` : CREAM, textAlign: "center", textWrap: "balance", whiteSpace: strike === undefined ? undefined : "nowrap", ...(flash ? OUTLINE : { textShadow: SHADOW }) }}>
        <Rich text={text} />
        {s > 0 && <div style={{ position: "absolute", left: -8, top: "54%", height: px * 0.12, width: `calc(${s * 100}% + 16px)`, background: RED, borderRadius: 4, boxShadow: "0 3px 0 rgba(6, 7, 20, 0.45)" }} />}
      </div>
    </div>
  );
};

/** A numbered tag chip centred at (x, y), popping in at `start`; a leader line to `target` (px) draws after. */
export const Chip = ({ n, text, x, y, f, start, target, leaderAt, leaderLen }: { n: number; text: string; x: number; y: number; f: number; start: number; target?: [number, number]; leaderAt: number; leaderLen: number }) => {
  if (f < start) return null;
  const sc = backOut(span(f, start, 8), 0.25);
  const draw = easeOut(span(f, leaderAt, leaderLen));
  const [tx, ty] = target ?? [x, y];
  const from: [number, number] = [x, y + 34];
  const ex = from[0] + (tx - from[0]) * draw;
  const ey = from[1] + (ty - from[1]) * draw;
  return (
    <>
      {target && draw > 0 && (
        <svg width={1080} height={1920} style={{ position: "absolute", inset: 0 }}>
          <line x1={from[0]} y1={from[1]} x2={ex} y2={ey} stroke={INK} strokeWidth={8} strokeLinecap="round" opacity={0.55} />
          <line x1={from[0]} y1={from[1]} x2={ex} y2={ey} stroke={CREAM} strokeWidth={4} strokeLinecap="round" />
          {draw >= 1 && (
            <>
              <circle cx={tx} cy={ty} r={15 + 3 * Math.sin(f / 5)} fill="none" stroke={AMBER} strokeWidth={5} />
              <circle cx={tx} cy={ty} r={5} fill={AMBER} />
            </>
          )}
        </svg>
      )}
      <div style={{ position: "absolute", left: x, top: y, transform: `translate(-50%, -50%) scale(${sc})`, display: "flex", alignItems: "center", gap: 14, background: CREAM, border: `4px solid ${INK}`, borderRadius: 18, padding: "8px 26px 8px 10px", boxShadow: "0 7px 0 rgba(6, 7, 20, 0.55)", whiteSpace: "nowrap" }}>
        <div style={{ ...DISPLAY, width: 50, height: 50, borderRadius: 12, background: AMBER, border: `4px solid ${INK}`, boxSizing: "border-box", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 30, color: INK, letterSpacing: 0 }}>{n}</div>
        <div style={{ ...BODY, fontWeight: 700, fontSize: 40, color: INK, letterSpacing: "-0.01em" }}>{frenchSpaces(text)}</div>
      </div>
    </>
  );
};

/** The small tag at the bottom (sources, context), over a dark plate. */
export const Tag = ({ text, f }: { text: string; f: number }) => (
  <div style={{ position: "absolute", left: 0, right: 0, top: 1170, display: "flex", justifyContent: "center", opacity: easeOut(span(f, 0, 8)) }}>
    <div style={{ ...BODY, fontWeight: 600, fontSize: 28, color: INK, background: CREAM, borderRadius: 10, padding: "6px 16px", border: `3px solid ${INK}` }}>{frenchSpaces(text)}</div>
  </div>
);

/** The big number counting up (amber), its unit beside it, a label under it. */
export const Stat = ({ value, unit, label, y, f, start, count }: { value: string; unit?: string; label?: string; y: number; f: number; start: number; count: number }) => {
  if (f < start) return null;
  const c = easeOut(span(f, start, count));
  const sc = backOut(span(f, start, 9), 0.2);
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: y, display: "flex", flexDirection: "column", alignItems: "center", textShadow: SHADOW }}>
      <div style={{ ...DISPLAY, fontSize: 210, lineHeight: 1, color: AMBER, transform: `scale(${sc})`, display: "flex", alignItems: "baseline", gap: 24 }}>
        {frenchSpaces(countUp(value, c))}
        {unit && <span style={{ fontSize: 96, color: CREAM }}>{unit}</span>}
      </div>
      {label && <div style={{ ...BODY, ...rise(f, start + count - 6), marginTop: 18, fontWeight: 700, fontSize: 46, color: CREAM }}>{frenchSpaces(label)}</div>}
    </div>
  );
};

/** The app as a small rounded card (vector-rebuilt): mark + name, the ring counting to `value`, three macro bars. */
export const AppCard = ({ value, unit, accent, y, f, start, count }: { value: string; unit: string; accent: string; y: number; f: number; start: number; count: number }) => {
  if (f < start) return null;
  const inT = backOut(span(f, start, 14), 0.12);
  const c = easeOut(span(f, start + 6, count));
  const r = 108;
  const len = 2 * Math.PI * r;
  const bars = [
    ["Protéines", "#FF6F61", 0.82],
    ["Glucides", "#3FBF7F", 0.64],
    ["Lipides", "#F5C242", 0.71],
  ] as const;
  return (
    <div style={{ position: "absolute", left: 540, top: y, transform: `translate(-50%, ${(1 - inT) * 160}px) rotate(${-3 + Math.sin(f / 30) * 0.8}deg)`, opacity: Math.min(1, inT * 1.4) }}>
      <div style={{ width: 560, borderRadius: 44, background: "#151833", border: "3px solid rgba(255, 255, 255, 0.12)", boxShadow: `0 40px 80px rgba(3, 4, 14, 0.7), 0 0 120px rgba(255, 181, 71, ${0.18 * c})`, padding: "30px 40px 40px", boxSizing: "border-box", color: CREAM }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <MbTile size={54} fill="#0B0B0B" ink="#FFFFFF" />
          <Wordmark style={{ ...DISPLAY, fontSize: 40, color: CREAM }} />
        </div>
        <div style={{ position: "relative", width: 260, height: 260, margin: "26px auto 22px" }}>
          <svg width={260} height={260} viewBox="0 0 260 260">
            <circle cx={130} cy={130} r={r} fill="none" stroke="rgba(255, 255, 255, 0.1)" strokeWidth={22} />
            <circle cx={130} cy={130} r={r} fill="none" stroke={accent} strokeWidth={22} strokeLinecap="round" strokeDasharray={len} strokeDashoffset={len * (1 - 0.86 * c)} transform="rotate(-90 130 130)" />
          </svg>
          <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
            <div style={{ ...DISPLAY, fontSize: 76, lineHeight: 1 }}>{frenchSpaces(countUp(value, c))}</div>
            <div style={{ ...BODY, fontWeight: 600, fontSize: 26, opacity: 0.75, marginTop: 6 }}>{frenchSpaces(unit)}</div>
          </div>
        </div>
        {bars.map(([name, color, k], i) => (
          <div key={name} style={{ display: "flex", alignItems: "center", gap: 18, marginTop: i ? 14 : 0 }}>
            <div style={{ ...BODY, fontWeight: 600, fontSize: 26, width: 150, opacity: 0.85 }}>{name}</div>
            <div style={{ flex: 1, height: 16, borderRadius: 8, background: "rgba(255, 255, 255, 0.1)" }}>
              <div style={{ width: `${100 * k * easeOut(span(f, start + 10 + i * 4, count))}%`, height: "100%", borderRadius: 8, background: color }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
