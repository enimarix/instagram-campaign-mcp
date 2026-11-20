// The sitcom style's overlay kit (step 164): the shots under it, the hook slammed in word by
// word, bold karaoke captions (the word being said in yellow, the key word popping in an emerald
// pill), a character's speech bubble, the big number, a scene slate. Ink outlines everywhere, the
// look of a loud TV sitcom.
import type { CSSProperties } from "react";
import { AbsoluteFill, Img, OffthreadVideo } from "remotion";
import { ACCENTS, type Accent } from "../../endcards/schema.ts";
import { SITCOM } from "../../endcards/SitcomEndCard";
import { fonts } from "../../lib/font";
import { frenchSpaces } from "../../lib/french";
import { chunksOf, keyIndexes, wordTimes } from "../../macro3d/words.ts";
import { backOut, easeOut, span } from "../../voxel/anim.ts";

const DISPLAY = `"${fonts.display}", sans-serif`;
/** White letters in a thick ink outline (the stroke painted under the fill). */
const outlined = (stroke: number): CSSProperties => ({ color: "#FFFFFF", WebkitTextStroke: `${stroke}px ${SITCOM.ink}`, paintOrder: "stroke fill" });
/** Captions sit here: over the action, clear of the hook and of Instagram's bottom bar. */
export const CAPTION_Y = 1040;

/** The troupe's shots (a video, or a picture for a still); `zoom` pushes in on the frozen punchline. */
export const Plate = ({ src, zoom = 1 }: { src?: string; zoom?: number }) => (
  <AbsoluteFill style={{ background: SITCOM.ink, transform: `scale(${zoom})` }}>
    {src && (/\.(png|jpe?g)$/i.test(src) ? <Img src={src} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <OffthreadVideo src={src} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />)}
  </AbsoluteFill>
);

/** The hook: each word slams in (big, then settling), on a tilted pink band; from frame 0. */
export const Hook = ({ text, f, out }: { text: string; f: number; out: number }) => {
  const words = frenchSpaces(text).split(" ");
  const leave = easeOut(span(f, out - 6, 6));
  return (
    <div style={{ position: "absolute", left: 60, right: 60, top: 300, display: "flex", justifyContent: "center", opacity: 1 - leave, transform: `translateY(${-leave * 40}px) rotate(-3deg)` }}>
      <div style={{ background: SITCOM.pink, border: `8px solid ${SITCOM.ink}`, borderRadius: 28, padding: "18px 34px 24px", boxShadow: `0 14px 0 ${SITCOM.ink}`, display: "flex", flexWrap: "wrap", justifyContent: "center", columnGap: 22, maxWidth: 920 }}>
        {words.map((w, i) => {
          const k = f < i * 3 ? 0 : backOut(span(f, i * 3, 6), 0.6);
          return (
            <span key={i} style={{ ...outlined(12), fontFamily: DISPLAY, fontWeight: 900, fontSize: 92, lineHeight: 1.08, letterSpacing: "-0.02em", display: "inline-block", opacity: k > 0 ? 1 : 0, transform: `scale(${1.8 - 0.8 * k})` }}>
              {w}
            </span>
          );
        })}
      </div>
    </div>
  );
};

/** Karaoke: the line's chunk being said, word by word; the word being said yellow, the key word in an emerald pill that pops. */
export const Karaoke = ({ line, keyWord, start, end, t, fps }: { line: string; keyWord?: string; start: number; end: number; t: number; fps: number }) => {
  const words = wordTimes(frenchSpaces(line), start, end);
  const keys = keyIndexes(words, keyWord);
  const said = words.filter((w) => w.start <= t).length;
  if (!said) return null;
  const chunks = chunksOf(words, keys);
  const [from, to] = chunks.find(([a, b]) => said - 1 >= a && said - 1 < b) ?? chunks[chunks.length - 1];
  const word = (i: number, key: boolean) => {
    const w = words[i];
    const on = w.start <= t;
    const pop = on ? backOut(span(t * fps, w.start * fps, 6), 0.8) : 0;
    return (
      <span key={i} style={{ ...outlined(key ? 0 : 11), fontFamily: DISPLAY, fontWeight: 900, fontSize: key ? 84 : 70, lineHeight: 1.1, letterSpacing: "-0.015em", display: "inline-block", opacity: on ? 1 : 0, transform: `scale(${on ? 0.7 + 0.3 * pop : 0.7})`, ...(i === said - 1 && !key ? { color: SITCOM.sun } : {}) }}>
        {w.text}
      </span>
    );
  };
  // consecutive key words share one pill, popping in with its first word
  const groups: number[][] = [];
  for (let i = from; i < to; i++) {
    const last = groups[groups.length - 1];
    if (last && keys.includes(i) && keys.includes(last[last.length - 1])) last.push(i);
    else groups.push([i]);
  }
  return (
    <div style={{ position: "absolute", top: CAPTION_Y, left: 80, right: 80, display: "flex", flexWrap: "wrap", justifyContent: "center", alignItems: "center", columnGap: 18, rowGap: 8 }}>
      {groups.map((g) => {
        if (!keys.includes(g[0])) return word(g[0], false);
        const on = words[g[0]].start <= t;
        const pop = on ? backOut(span(t * fps, words[g[0]].start * fps, 7), 1) : 0;
        return (
          <span key={`k${g[0]}`} style={{ display: "inline-flex", columnGap: 16, background: "#10B981", border: `7px solid ${SITCOM.ink}`, borderRadius: 18, padding: "2px 18px 8px", boxShadow: `0 8px 0 ${SITCOM.ink}`, opacity: on ? 1 : 0, transform: `scale(${0.6 + 0.4 * pop}) rotate(-3deg)` }}>
            {g.map((i) => word(i, true))}
          </span>
        );
      })}
    </div>
  );
};

/** A character's line in a comic bubble (its name tag on top), popping in. */
export const Bubble = ({ name, text, f, side }: { name: string; text: string; f: number; side: 1 | -1 }) => {
  const k = backOut(span(f, 0, 8), 0.7);
  return (
    <div style={{ position: "absolute", top: 560, left: side < 0 ? 70 : 230, width: 780, transform: `scale(${k}) rotate(${side * 2}deg)`, transformOrigin: side < 0 ? "20% 100%" : "80% 100%" }}>
      <div style={{ display: "inline-block", marginLeft: 40, marginBottom: -8, background: SITCOM.turquoise, border: `6px solid ${SITCOM.ink}`, borderRadius: 14, padding: "4px 18px 8px", fontFamily: DISPLAY, fontWeight: 900, fontSize: 36, color: SITCOM.ink, position: "relative", zIndex: 1 }}>{frenchSpaces(name)}</div>
      <div style={{ position: "relative", background: "#FFFFFF", border: `8px solid ${SITCOM.ink}`, borderRadius: 40, padding: "26px 34px 32px", fontFamily: DISPLAY, fontWeight: 900, fontSize: 64, lineHeight: 1.08, color: SITCOM.ink, textAlign: "center", boxShadow: `0 12px 0 ${SITCOM.ink}` }}>
        {frenchSpaces(text)}
        {/* the tail, toward the speaker below */}
        <svg width={90} height={70} style={{ position: "absolute", bottom: -62, left: side < 0 ? 90 : 600 }}>
          <path d="M8 0 L82 0 L30 64 Z" fill="#FFFFFF" stroke={SITCOM.ink} strokeWidth={8} strokeLinejoin="round" />
          <rect x={10} y={-8} width={70} height={12} fill="#FFFFFF" />
        </svg>
      </div>
    </div>
  );
};

/** The key fact as a big number in the accent, counting up when it has a `from`. */
export const BigNumber = ({ text, unit, accent, f }: { text: string; unit?: string; accent: Accent; f: number }) => {
  const k = backOut(span(f, 0, 10), 0.6);
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: 640, display: "flex", flexDirection: "column", alignItems: "center", transform: `scale(${k}) rotate(-4deg)` }}>
      <div style={{ ...outlined(18), color: ACCENTS[accent], fontFamily: DISPLAY, fontWeight: 900, fontSize: 250, lineHeight: 1, letterSpacing: "-0.04em", fontVariantNumeric: "tabular-nums" }}>{text}</div>
      {unit && <div style={{ ...outlined(10), fontFamily: DISPLAY, fontWeight: 900, fontSize: 72, marginTop: -6 }}>{frenchSpaces(unit)}</div>}
    </div>
  );
};

/** A scene's slate (« L'ÉTÉ »): stamped in the middle, then gone. */
export const Slate = ({ text, f, frames }: { text: string; f: number; frames: number }) => {
  const k = backOut(span(f, 0, 8), 0.5);
  const leave = easeOut(span(f, frames - 6, 6));
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: 820, display: "flex", justifyContent: "center", opacity: 1 - leave }}>
      <div style={{ background: SITCOM.sun, border: `10px solid ${SITCOM.ink}`, borderRadius: 24, padding: "14px 44px 22px", boxShadow: `0 14px 0 ${SITCOM.ink}`, fontFamily: DISPLAY, fontWeight: 900, fontSize: 96, color: SITCOM.ink, transform: `scale(${k}) rotate(3deg)`, textTransform: "uppercase" }}>{frenchSpaces(text)}</div>
    </div>
  );
};

/** A count in French style (« 1 250 », « 2,5 »). */
export const numberText = (v: number, decimals: number) => {
  const [whole, dec] = v.toFixed(decimals).split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+$)/g, " ");
  return dec ? `${grouped},${dec}` : grouped;
};
