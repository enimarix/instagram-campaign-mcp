// The Macro 3D overlays (step 154), drawn over the Blender plates: word-by-word captions with
// the blue "design tool" selection box on the key word, the small honest label, a callout tag
// with its leader line, a counter, and the plate itself (or the dark void without one).
import { AbsoluteFill, Img, OffthreadVideo } from "remotion";
import { fonts } from "../lib/font";
import { frenchSpaces } from "../lib/french";
import { easeOut, span } from "../voxel/anim.ts";
import { chunksOf, keyIndexes, wordTimes } from "./words.ts";

export const BLUE = "#3E8EF7";
const SANS = `"${fonts.body}", sans-serif`;
const DISPLAY = `"${fonts.display}", sans-serif`;
/** Top of the captions: under the safe area's top (269), where the reference sets them. */
export const CAPTION_Y = 320;

/** The plates (a video of every shot, or an image for a still), else the black studio void. */
export const Plate = ({ src }: { src?: string }) => (
  <AbsoluteFill style={{ background: "radial-gradient(ellipse 80% 55% at 50% 58%, #2A2C30 0%, #111214 55%, #050506 100%)" }}>
    {src &&
      (/\.(png|jpe?g)$/i.test(src) ? (
        <Img src={src} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      ) : (
        <OffthreadVideo src={src} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      ))}
    {/* the lens: a soft vignette; the top darkened so the captions read over a close-up */}
    <AbsoluteFill style={{ background: "radial-gradient(ellipse 95% 70% at 50% 52%, transparent 55%, rgba(0,0,0,0.55) 100%)" }} />
    <AbsoluteFill style={{ background: "linear-gradient(to bottom, rgba(0,0,0,0.6) 0px, rgba(0,0,0,0.35) 420px, transparent 640px)" }} />
  </AbsoluteFill>
);

/** The selection frame around the key word: thin blue rule, square handles at the corners. */
const Selection = ({ k }: { k: number }) => (
  <span style={{ position: "absolute", inset: "-4px -10px -2px -10px", border: `2.5px solid ${BLUE}`, background: "rgba(62,142,247,0.16)", opacity: k, transform: `scale(${0.9 + 0.1 * k})` }}>
    {[
      [-1, -1],
      [1, -1],
      [-1, 1],
      [1, 1],
    ].map(([x, y]) => (
      <span key={`${x}${y}`} style={{ position: "absolute", width: 11, height: 11, background: "#FFFFFF", border: `2.5px solid ${BLUE}`, left: x < 0 ? -7 : undefined, right: x > 0 ? -7 : undefined, top: y < 0 ? -7 : undefined, bottom: y > 0 ? -7 : undefined }} />
    ))}
  </span>
);

/**
 * The line read from `start` to `end` (s), at `t` (s): only the chunk being said, its words
 * appearing as they are said (the line re-centres as it grows, like the reference); the word
 * being said white, the ones before it grey; the key word (or words, one box) white in its
 * selection box once said.
 */
export const Caption = ({ line, keyWord, start, end, t, fps }: { line: string; keyWord?: string; start: number; end: number; t: number; fps: number }) => {
  const words = wordTimes(frenchSpaces(line), start, end);
  const keys = keyIndexes(words, keyWord);
  const chunks = chunksOf(words, keys);
  const said = words.filter((w) => w.start <= t).length;
  if (!said) return null;
  const [from, to] = chunks.find(([a, b]) => said - 1 >= a && said - 1 < b) ?? chunks[chunks.length - 1];
  const shown = words.slice(from, Math.min(to, said)).map((w, j) => ({ ...w, i: from + j }));
  // consecutive key words share one selection box
  const groups: (typeof shown)[] = [];
  shown.forEach((w) => {
    const last = groups[groups.length - 1];
    if (last && keys.includes(w.i) && keys.includes(last[last.length - 1].i)) last.push(w);
    else groups.push([w]);
  });
  const word = (w: (typeof shown)[number], key: boolean) => {
    const appear = easeOut(span(t * fps, w.start * fps, 4));
    const color = w.i === said - 1 || key ? "#FFFFFF" : "rgba(214,218,224,0.55)";
    return <span key={w.i} style={{ position: "relative", color, opacity: appear, display: "inline-block", transform: `translateY(${(1 - appear) * 10}px)` }}>{w.text}</span>;
  };
  return (
    <div style={{ position: "absolute", top: CAPTION_Y, left: 120, right: 120, display: "flex", flexWrap: "wrap", justifyContent: "center", columnGap: 16, rowGap: 6, fontFamily: SANS, fontWeight: 600, fontSize: 58, lineHeight: 1.16, letterSpacing: "-0.01em", textShadow: "0 0 4px rgba(0,0,0,0.8), 0 2px 18px rgba(0,0,0,0.7)" }}>
      {/* a soft dark pool behind the line: it reads even over a bright object */}
      <div style={{ position: "absolute", inset: "-110px -150px", background: "radial-gradient(closest-side, rgba(0,0,0,0.55), rgba(0,0,0,0.3) 60%, transparent)", opacity: easeOut(span(t * fps, start * fps, 6)) }} />
      {groups.map((g) =>
        keys.includes(g[0].i) ? (
          <span key={g[0].i} style={{ position: "relative", display: "inline-flex", columnGap: 16 }}>
            <Selection k={easeOut(span(t * fps, g[0].start * fps, 5))} />
            {g.map((w) => word(w, true))}
          </span>
        ) : (
          word(g[0], false)
        ),
      )}
    </div>
  );
};

/** The small label bottom-left (« Illustration agrandie »). */
export const Label = ({ text, f }: { text: string; f: number }) => (
  <div style={{ position: "absolute", left: 72, top: 1196, fontFamily: SANS, fontWeight: 500, fontSize: 25, color: "rgba(235,238,242,0.62)", opacity: easeOut(span(f, 2, 8)), letterSpacing: "0.01em" }}>{text}</div>
);

/** An uppercase tag above the subject, its leader line drawing down onto it. */
export const Callout = ({ text, f, side }: { text: string; f: number; side: 1 | -1 }) => {
  const x = 540 + side * 150;
  const k = easeOut(span(f, 4, 10));
  const line = easeOut(span(f, 9, 10));
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: 1080, height: 1920 }}>
      <div style={{ position: "absolute", left: x - 300, width: 600, top: 600, textAlign: "center", fontFamily: SANS, fontWeight: 700, fontSize: 26, letterSpacing: "0.16em", color: "#FFFFFF", opacity: k, textShadow: "0 2px 12px rgba(0,0,0,0.7)" }}>
        {text.toUpperCase()}
      </div>
      <div style={{ position: "absolute", left: x - 1, top: 646, width: 2, height: 190 * line, background: "rgba(255,255,255,0.85)" }} />
      <div style={{ position: "absolute", left: x - 5, top: 646 + 190 * line - 5, width: 10, height: 10, borderRadius: 5, background: "#FFFFFF", opacity: line }} />
    </div>
  );
};

/**
 * The counter: small left of the subject (digits in fixed widths, the unit small, an accent rule),
 * or `big`: glowing white in the middle of the frame, the unit under it, rolling up.
 */
export const Counter = ({ value, unit, color, f, big }: { value: string; unit: string; color: string; f: number; big?: boolean }) => {
  const k = easeOut(span(f, 3, 8));
  if (big) {
    return (
      <div style={{ position: "absolute", left: 0, right: 0, top: 760, display: "flex", flexDirection: "column", alignItems: "center", opacity: k, transform: `scale(${0.9 + 0.1 * k})` }}>
        <span style={{ fontFamily: DISPLAY, fontWeight: 800, fontSize: 200, lineHeight: 1, color: "#FFFFFF", fontVariantNumeric: "tabular-nums", letterSpacing: "-0.03em", textShadow: `0 0 24px rgba(255,255,255,0.75), 0 0 70px ${color}, 0 4px 30px rgba(0,0,0,0.6)` }}>{value}</span>
        <span style={{ marginTop: 14, fontFamily: SANS, fontWeight: 700, fontSize: 34, letterSpacing: "0.14em", color: "rgba(255,255,255,0.88)", textShadow: "0 2px 14px rgba(0,0,0,0.8)" }}>{unit.toUpperCase()}</span>
      </div>
    );
  }
  return (
    <div style={{ position: "absolute", left: 72, top: 1066, opacity: k, transform: `translateY(${(1 - k) * 16}px)`, display: "flex", alignItems: "baseline", gap: 12 }}>
      <span style={{ fontFamily: DISPLAY, fontWeight: 800, fontSize: 76, color: "#FFFFFF", fontVariantNumeric: "tabular-nums", letterSpacing: "-0.02em", textShadow: "0 2px 18px rgba(0,0,0,0.6)" }}>{value}</span>
      <span style={{ fontFamily: SANS, fontWeight: 700, fontSize: 26, letterSpacing: "0.12em", color: "rgba(235,238,242,0.8)" }}>{unit.toUpperCase()}</span>
      <div style={{ position: "absolute", left: 0, bottom: -10, width: 64, height: 5, borderRadius: 3, background: color }} />
    </div>
  );
};
