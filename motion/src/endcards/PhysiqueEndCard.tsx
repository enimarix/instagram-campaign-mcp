// The physique style's end card: the cream drafting grid of the owner's reference Reel, two
// bands of type rolling across it in opposite ways (« macroBody » in the italic serif on ink,
// the trial in orange caps), the mB tile dropping onto an orange measuring ring, the wordmark
// rising letter by letter, the « 7 jours gratuits » pill and macrobody.fr underlined in the
// topic's accent. Settles by SETTLE_S.physique, then holds.
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame } from "remotion";
import { assetById } from "../assets";
import { fonts } from "../lib/font";
import { Grid, PHYSIQUE, RollingBand } from "../templates/PhysiqueScan/kit";
import { backOut, easeOut, span } from "../voxel/anim.ts";
import { MbTile, NAME_PARTS, TRIAL, taglineOf, URL, Wordmark } from "./base";
import { ACCENTS, type CardProps, cardVolume } from "./schema.ts";

const AT = { bands: 0, tagline: 6, ring: 12, tile: 16, word: 24, pill: 38, url: 46, line: 50 };

export const PhysiqueEndCard = ({ tagline, accent, address }: Omit<CardProps, "pixelate">) => {
  const frame = useCurrentFrame();
  const bands = easeOut(span(frame, AT.bands, 12));
  const ring = easeOut(span(frame, AT.ring, 16));
  const tile = frame < AT.tile ? 0 : backOut(span(frame, AT.tile, 14), 0.5);
  const pill = frame < AT.pill ? 0 : backOut(span(frame, AT.pill, 12), 0.4);
  const url = easeOut(span(frame, AT.url, 14));
  const tag = easeOut(span(frame, AT.tagline, 12));
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <Grid />
      <RollingBand text={NAME_PARTS.join("")} f={frame} speed={5} tone="dark" style={{ top: 140, transform: `rotate(-8deg) translateX(${(1 - bands) * -1200}px)` }} />
      <RollingBand text={TRIAL} f={frame} speed={-6} tone="orange" style={{ top: 1560, transform: `rotate(6deg) translateX(${(1 - bands) * 1200}px)` }} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 380, display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center" }}>
        <div style={{ opacity: tag, transform: `translateY(${(1 - tag) * 30}px)`, maxWidth: 900, fontFamily: `"${fonts.display}", sans-serif`, fontWeight: 900, fontSize: 66, lineHeight: 1.06, color: PHYSIQUE.ink, textWrap: "balance" }}>
          {taglineOf({ tagline, address })}
        </div>
        <div style={{ position: "relative", marginTop: 60, width: 340, height: 340, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <svg width={340} height={340} viewBox="-170 -170 340 340" style={{ position: "absolute", inset: 0, overflow: "visible" }}>
            <circle r={158} fill="none" stroke={PHYSIQUE.orange} strokeWidth={6} strokeDasharray={`${993 * ring} 993`} transform="rotate(-90)" />
            {Array.from({ length: 36 }, (_, i) => {
              const a = (i / 36) * 2 * Math.PI;
              const l = i % 3 ? 10 : 22;
              return i / 36 <= ring ? <line key={i} x1={Math.sin(a) * 158} y1={-Math.cos(a) * 158} x2={Math.sin(a) * (158 - l)} y2={-Math.cos(a) * (158 - l)} stroke={PHYSIQUE.orange} strokeWidth={4} /> : null;
            })}
          </svg>
          <div style={{ transform: `translateY(${(1 - tile) * -300}px) scale(${0.6 + 0.4 * tile})`, opacity: tile > 0 ? 1 : 0, filter: `drop-shadow(10px 10px 0 ${PHYSIQUE.orange})` }}>
            <MbTile size={220} fill={PHYSIQUE.ink} ink={PHYSIQUE.cream} />
          </div>
        </div>
        <div style={{ marginTop: 50, overflow: "hidden", padding: "0 10px 12px" }}>
          <Wordmark
            style={{ fontFamily: `"${fonts.display}", sans-serif`, fontWeight: 900, fontSize: 132, lineHeight: 1.04, letterSpacing: "-0.045em", color: PHYSIQUE.ink }}
            letter={(i) => ({ transform: `translateY(${(1 - easeOut(span(frame, AT.word + i * 1.6, 14))) * 110}%)` })}
          />
        </div>
        <div style={{ marginTop: 26, transform: `scale(${pill})`, background: PHYSIQUE.orange, border: `5px solid ${PHYSIQUE.ink}`, borderRadius: 999, padding: "14px 44px 18px", boxShadow: `8px 8px 0 ${PHYSIQUE.ink}`, whiteSpace: "nowrap", fontFamily: `"${fonts.display}", sans-serif`, fontWeight: 900, fontSize: 56, color: PHYSIQUE.cream }}>
          {TRIAL}
        </div>
        <div style={{ marginTop: 34, position: "relative", opacity: url, transform: `translateY(${(1 - url) * 24}px)`, fontFamily: `"${fonts.body}", sans-serif`, fontWeight: 700, fontSize: 44, color: PHYSIQUE.ink }}>
          {URL}
          <div style={{ position: "absolute", left: 0, bottom: -10, height: 6, borderRadius: 3, background: ACCENTS[accent], width: `${100 * easeOut(span(frame, AT.line, 14))}%` }} />
        </div>
      </div>
      <Sequence from={AT.pill} durationInFrames={30} layout="none">
        <Html5Audio src={assetById("sfx-pop").src} volume={cardVolume("sfx-pop")} />
      </Sequence>
    </AbsoluteFill>
  );
};
