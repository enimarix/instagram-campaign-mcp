// The editorial style's end card (step 144): pure black, petals drifting down, the stores
// chip drops in, the tagline rises in duo type (its last word in the pink italic serif), the
// mB tile with a pink rim scales up beside its cameo (a small blossom tree or the story's
// anatomy character), the wordmark rises letter by letter, the « 7 jours *gratuits* » pill
// pops in pink and macrobody.fr underlines itself in the topic's accent. Settles by
// SETTLE_S.editorial, then holds.
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame } from "remotion";
import { assetById } from "../assets";
import { Character } from "../editorial/Character";
import { Drift, ease, GROTESK, Kicker, Rise, SERIF } from "../editorial/kit";
import { BLACK, type CharacterId, PINK, WHITE } from "../editorial/palette.ts";
import { Tree } from "../editorial/Tree";
import { TREE } from "../editorial/blossom.ts";
import { fonts } from "../lib/font";
import { backOut, span } from "../voxel/anim.ts";
import { MbTile, STORES, taglineOf, TRIAL, URL, Wordmark } from "./base";
import { ACCENTS, type CardProps, cameoOf, cardVolume } from "./schema.ts";

/** Frames (from the card's start) at which each piece comes in. */
const AT = { chip: 2, tagline: 6, tile: 18, cameo: 24, word: 26, pill: 40, url: 48, line: 52 };

/** The text split before its last word: ["7 jours", "gratuits"]. */
const lastWord = (s: string) => {
  const cut = s.lastIndexOf(" ");
  return cut < 0 ? ["", s] : [s.slice(0, cut), s.slice(cut + 1)];
};

export const EditorialEndCard = ({ tagline, accent, address, cameo }: Omit<CardProps, "pixelate">) => {
  const frame = useCurrentFrame();
  const [lead, key] = lastWord(taglineOf({ tagline, address }));
  const [trialLead, trialKey] = lastWord(TRIAL);
  const who = cameoOf("editorial", cameo);
  const tile = ease(frame, AT.tile, 20);
  const cameoIn = ease(frame, AT.cameo, 18);
  const pill = frame < AT.pill ? 0 : backOut(span(frame, AT.pill, 14), 0.3);
  const url = ease(frame, AT.url, 16);
  return (
    <AbsoluteFill style={{ background: BLACK, overflow: "hidden" }}>
      <Drift frame={frame + 400} count={22} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 300, display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center" }}>
        <Kicker text={STORES} f={frame} start={AT.chip} style={{ fontSize: 22, letterSpacing: "0.14em" }} />
        <div style={{ marginTop: 44, maxWidth: 900, lineHeight: 1.08, textWrap: "balance" }}>
          {lead && <Rise text={lead} f={frame} start={AT.tagline} style={{ ...GROTESK, fontSize: 64 }} />} <Rise text={key} f={frame} start={AT.tagline + 6} style={{ ...SERIF, fontSize: 80 }} />
        </div>
        <div style={{ marginTop: 56, display: "flex", alignItems: "center", gap: 36, height: 210 }}>
          <div style={{ opacity: tile, transform: `scale(${0.7 + 0.3 * tile})`, filter: `drop-shadow(0 0 ${30 * tile}px rgba(255,61,139,0.45))` }}>
            <MbTile size={200}>
              <rect x={-14} y={-14} width={540} height={540} rx={124} fill={PINK} />
            </MbTile>
          </div>
          {who !== "none" && (
            <svg width={220} height={220} viewBox="-110 -110 220 220" style={{ overflow: "visible", opacity: cameoIn, transform: `translateX(${(1 - cameoIn) * 40}px)` }}>
              {who === "tree" ? (
                <Tree x={0} y={100} s={200 / TREE.height} frame={frame} bloom={1} petals={8} />
              ) : (
                <Character id={who as CharacterId} mood="happy" f={frame} x={0} y={0} s={0.42} pixel={false} />
              )}
            </svg>
          )}
        </div>
        <div style={{ marginTop: 40, overflow: "hidden", padding: "0 10px 12px" }}>
          <Wordmark
            style={{ fontFamily: `"${fonts.display}", sans-serif`, fontWeight: 900, fontSize: 132, lineHeight: 1.04, letterSpacing: "-0.045em", color: WHITE }}
            letter={(i) => ({ transform: `translateY(${(1 - ease(frame, AT.word + i * 1.6, 18)) * 110}%)` })}
          />
        </div>
        <div style={{ marginTop: 30, transform: `scale(${pill})`, background: PINK, borderRadius: 999, padding: "16px 46px 22px", boxShadow: "0 0 40px rgba(255,61,139,0.55)", whiteSpace: "nowrap" }}>
          <span style={{ ...GROTESK, fontSize: 58 }}>{trialLead} </span>
          <span style={{ ...SERIF, color: WHITE, fontSize: 70 }}>{trialKey}</span>
        </div>
        <div style={{ marginTop: 36, position: "relative", opacity: url, transform: `translateY(${(1 - url) * 24}px)`, fontFamily: `"${fonts.body}", sans-serif`, fontWeight: 700, fontSize: 44, color: WHITE }}>
          {URL}
          <div style={{ position: "absolute", left: 0, bottom: -10, height: 6, borderRadius: 3, background: ACCENTS[accent], width: `${100 * ease(frame, AT.line, 16)}%` }} />
        </div>
      </div>
      <Sequence from={AT.pill} durationInFrames={30} layout="none">
        <Html5Audio src={assetById("sfx-pop").src} volume={cardVolume("sfx-pop")} />
      </Sequence>
    </AbsoluteFill>
  );
};
