// The physique style's overlay kit: the palette of the owner's reference Reel (cream paper,
// navy ink, orange, teal), the hook's words slammed in one per beat in thick 3D-ish caps (an
// orange extrusion under navy), the measure readout pill (« +180 G ») with its ruler, and a
// flat rolling band of type for the end card.
import type { CSSProperties } from "react";
import { fonts } from "../../lib/font";
import { frenchSpaces } from "../../lib/french";
import { backOut, easeOut, span } from "../../voxel/anim.ts";

export const PHYSIQUE = { cream: "#F2EBDA", paper: "#E9E1CC", ink: "#1C2140", orange: "#EE6E3D", teal: "#669E94", line: "#C9C2B4" } as const;
export const DISPLAY = `"${fonts.display}", sans-serif`;
export const BODY = `"${fonts.body}", sans-serif`;

/** Thick caps with an orange extrusion down-right and a cream rim: the reference's 3D type, flat. */
const extruded = (depth: number): CSSProperties => ({
  color: PHYSIQUE.ink,
  WebkitTextStroke: `4px ${PHYSIQUE.cream}`,
  paintOrder: "stroke fill",
  textShadow: Array.from({ length: depth }, (_, i) => `${i + 1}px ${i + 1}px 0 ${PHYSIQUE.orange}`).join(", "),
});

/** The hook: one word per beat (`beats`: the frame each word lands), stacked and tilted, each
 * slamming in from big; all leave together at `out`. */
export const Hook = ({ text, f, beats, out }: { text: string; f: number; beats: number[]; out: number }) => {
  const words = frenchSpaces(text).toUpperCase().split(" ");
  const leave = easeOut(span(f, out - 5, 5));
  return (
    <div style={{ position: "absolute", left: 40, right: 40, top: 260, display: "flex", flexDirection: "column", alignItems: "center", gap: 0, opacity: 1 - leave, transform: `translateY(${-leave * 60}px)` }}>
      {words.map((w, i) => {
        const at = beats[Math.min(i, beats.length - 1)] ?? 0;
        const k = f < at ? 0 : backOut(span(f, at, 6), 0.7);
        const tilt = i % 2 ? 4 : -5;
        return (
          <span key={i} style={{ ...extruded(14), fontFamily: DISPLAY, fontWeight: 900, fontSize: w.length > 7 ? 128 : 168, lineHeight: 0.98, letterSpacing: "-0.03em", display: "inline-block", opacity: k > 0 ? 1 : 0, transform: `rotate(${tilt}deg) scale(${2.2 - 1.2 * k})` }}>
            {w}
          </span>
        );
      })}
    </div>
  );
};

/** The measure readout: a cream pill in ink (« +180 G ») on a ruler with ticks, popping in,
 * below the statue's chest and above Instagram's caption area. */
export const Readout = ({ text, f }: { text: string; f: number }) => {
  const k = f < 0 ? 0 : backOut(span(f, 0, 8), 0.5);
  const rule = easeOut(span(f, 2, 10));
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: 1240, display: "flex", flexDirection: "column", alignItems: "center", opacity: k > 0 ? 1 : 0 }}>
      <div style={{ transform: `scale(${k})`, background: PHYSIQUE.cream, border: `5px solid ${PHYSIQUE.ink}`, borderRadius: 18, padding: "8px 26px 10px", fontFamily: BODY, fontWeight: 800, fontSize: 56, letterSpacing: "0.04em", color: PHYSIQUE.ink, fontVariantNumeric: "tabular-nums", boxShadow: `8px 8px 0 ${PHYSIQUE.orange}` }}>
        {frenchSpaces(text)}
      </div>
      <svg width={520} height={40} viewBox="0 0 520 40" style={{ marginTop: 14 }}>
        <line x1={260 - 250 * rule} x2={260 + 250 * rule} y1={6} y2={6} stroke={PHYSIQUE.ink} strokeWidth={4} />
        {Array.from({ length: 26 }, (_, i) => {
          const x = 10 + i * 20;
          return Math.abs(x - 260) <= 250 * rule ? <line key={i} x1={x} x2={x} y1={6} y2={i % 5 ? 20 : 34} stroke={PHYSIQUE.ink} strokeWidth={3} /> : null;
        })}
      </svg>
    </div>
  );
};

/** A flat band of type rolling sideways (the end card): `text` repeated, moving `speed` px a frame. */
export const RollingBand = ({ text, f, speed = 6, tone = "dark", style }: { text: string; f: number; speed?: number; tone?: "dark" | "orange" | "light"; style?: CSSProperties }) => {
  const [bg, fg, face] = tone === "dark" ? [PHYSIQUE.ink, PHYSIQUE.cream, "serif"] : tone === "orange" ? [PHYSIQUE.orange, PHYSIQUE.cream, "sans"] : [PHYSIQUE.cream, PHYSIQUE.ink, "sans"];
  const unit = `${face === "sans" ? text.toUpperCase() : text}   •   `;
  return (
    <div style={{ position: "absolute", left: -200, right: -200, height: 110, overflow: "hidden", background: bg, borderTop: `5px solid ${PHYSIQUE.ink}`, borderBottom: `5px solid ${PHYSIQUE.ink}`, ...style }}>
      <div style={{ whiteSpace: "nowrap", transform: `translateX(${-((f * speed) % 900)}px)`, fontFamily: face === "sans" ? DISPLAY : `"${fonts.serif}", serif`, fontStyle: face === "sans" ? "normal" : "italic", fontWeight: face === "sans" ? 900 : 400, fontSize: 70, lineHeight: "104px", color: fg, letterSpacing: face === "sans" ? "0.02em" : "0" }}>
        {unit.repeat(8)}
      </div>
    </div>
  );
};

/** The drafting grid on cream paper (the end card's ground). */
export const Grid = () => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      background: PHYSIQUE.cream,
      backgroundImage: `linear-gradient(${PHYSIQUE.line} 2px, transparent 2px), linear-gradient(90deg, ${PHYSIQUE.line} 2px, transparent 2px)`,
      backgroundSize: "90px 90px",
    }}
  />
);
