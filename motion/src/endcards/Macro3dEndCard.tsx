// The Macro 3D style's end card (step 154): the black studio void, dust drifting in the light;
// a beam sweeps across and lands on the mB tile (a specular glint runs over its glossy face as
// it rises), Marco gives a thumbs-up beside it, the wordmark rises letter by letter, the tagline
// follows, the « 7 jours gratuits » pill pops in emerald and macrobody.fr underlines itself in the
// topic's accent. Never a price. Settles by SETTLE_S.macro3d, then holds.
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame } from "remotion";
import { assetById } from "../assets";
import { fonts } from "../lib/font";
import { Marco } from "../macro3d/Presenter";
import { backOut, easeInOut, easeOut, span } from "../voxel/anim.ts";
import { MbTile, taglineOf, TRIAL, URL, Wordmark } from "./base";
import { ACCENTS, type CardProps, cameoOf } from "./schema.ts";

/** Frames (from the card's start) at which each piece comes in. */
const AT = { beam: 0, tile: 8, glint: 18, cameo: 20, word: 24, tagline: 34, pill: 42, url: 50, line: 54 };

/** Dust specks: fixed positions, drifting slowly up (no randomness: every render the same). */
const DUST = Array.from({ length: 40 }, (_, i) => ({ x: (i * 397) % 1080, y: (i * 733) % 1920, r: 1.5 + (i % 4), v: 0.3 + (i % 5) * 0.15 }));

export const Macro3dEndCard = ({ tagline, accent, address, cameo }: Omit<CardProps, "pixelate">) => {
  const frame = useCurrentFrame();
  const beam = easeInOut(span(frame, AT.beam, 26));
  const tile = easeOut(span(frame, AT.tile, 18));
  const glint = span(frame, AT.glint, 16);
  const who = cameoOf("macro3d", cameo);
  const cameoIn = easeOut(span(frame, AT.cameo, 14));
  const pill = frame < AT.pill ? 0 : backOut(span(frame, AT.pill, 14), 0.3);
  const url = easeOut(span(frame, AT.url, 14));
  const lineK = easeOut(span(frame, AT.line, 16));
  const tag = easeOut(span(frame, AT.tagline, 14));
  const tileX = who === "none" ? 540 : 430;
  return (
    <AbsoluteFill style={{ background: "#050506", overflow: "hidden" }}>
      {/* the pool of light on the floor and the beam that lands on the tile */}
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 60% 22% at ${tileX / 10.8}% 47%, rgba(120,130,145,${0.35 * beam}) 0%, transparent 100%)` }} />
      <div style={{ position: "absolute", left: -400 + beam * (tileX + 400) - 160, top: -200, width: 320, height: 1400, transform: "rotate(18deg)", background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.10), transparent)", opacity: 1 - 0.6 * span(frame, 26, 20) }} />
      <svg width={1080} height={1920} style={{ position: "absolute", inset: 0 }}>
        {DUST.map((d, i) => (
          <circle key={i} cx={d.x} cy={(d.y - frame * d.v + 1920) % 1920} r={d.r} fill="#FFFFFF" opacity={0.12 + (i % 3) * 0.06} />
        ))}
      </svg>
      <div style={{ position: "absolute", left: tileX - 130, top: 560, width: 260, height: 260, opacity: tile, transform: `translateY(${(1 - tile) * 60}px) scale(${0.85 + 0.15 * tile})`, filter: "drop-shadow(0 40px 50px rgba(0,0,0,0.8)) drop-shadow(0 0 40px rgba(16,185,129,0.25))" }}>
        <MbTile size={260} fill="#111315" />
        {/* the specular glint running over the glossy face */}
        <div style={{ position: "absolute", inset: 0, borderRadius: 58, overflow: "hidden" }}>
          <div style={{ position: "absolute", top: -60, bottom: -60, width: 70, left: -120 + glint * 420, transform: "rotate(20deg)", background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.35), transparent)" }} />
          <div style={{ position: "absolute", inset: 0, borderRadius: 58, boxShadow: "inset 0 2px 0 rgba(255,255,255,0.25), inset 0 -20px 40px rgba(0,0,0,0.4)" }} />
        </div>
      </div>
      {who === "marco" && (
        <div style={{ position: "absolute", left: 600, top: 530, width: 300, height: 390, opacity: cameoIn, transform: `translateX(${(1 - cameoIn) * 50}px)` }}>
          <Marco pose="thumbs" mouth="closed" blink={frame % 90 > 86} />
        </div>
      )}
      <div style={{ position: "absolute", left: 0, right: 0, top: 960, display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center" }}>
        <div style={{ overflow: "hidden", padding: "0 10px 12px" }}>
          <Wordmark
            style={{ fontFamily: `"${fonts.display}", sans-serif`, fontWeight: 900, fontSize: 128, lineHeight: 1.04, letterSpacing: "-0.045em", color: "#FFFFFF" }}
            letter={(i) => ({ transform: `translateY(${(1 - easeOut(span(frame, AT.word + i * 1.5, 16))) * 110}%)` })}
          />
        </div>
        <div style={{ marginTop: 18, maxWidth: 860, fontFamily: `"${fonts.body}", sans-serif`, fontWeight: 600, fontSize: 44, lineHeight: 1.2, color: "rgba(235,238,242,0.85)", opacity: tag, transform: `translateY(${(1 - tag) * 20}px)`, textWrap: "balance" }}>
          {taglineOf({ tagline, address })}
        </div>
        <div style={{ marginTop: 44, transform: `scale(${pill})`, background: "#10B981", borderRadius: 999, padding: "18px 48px", boxShadow: "0 0 50px rgba(16,185,129,0.45)", fontFamily: `"${fonts.display}", sans-serif`, fontWeight: 800, fontSize: 52, color: "#FFFFFF", whiteSpace: "nowrap" }}>
          {TRIAL}
        </div>
        <div style={{ marginTop: 40, position: "relative", opacity: url, transform: `translateY(${(1 - url) * 20}px)`, fontFamily: `"${fonts.body}", sans-serif`, fontWeight: 700, fontSize: 44, color: "#FFFFFF" }}>
          {URL}
          <div style={{ position: "absolute", left: 0, bottom: -10, height: 6, borderRadius: 3, background: ACCENTS[accent], width: `${100 * lineK}%` }} />
        </div>
      </div>
      <Sequence from={AT.pill} durationInFrames={30} layout="none">
        <Html5Audio src={assetById("sfx-pop").src} volume={0.35} />
      </Sequence>
    </AbsoluteFill>
  );
};
