// The GTA 6 style's end card: the sunset beach dimmed behind, the tagline in outlined white,
// the mB tile dropping into a yellow waypoint marker (the map's ring pulsing round it), the
// wordmark rising letter by letter, the « 7 jours gratuits » pill in the gold mission gradient,
// macrobody.fr underlined in the topic's accent, and the duo standing at the bottom (cameo
// "duo"). Settles by SETTLE_S.gta6, then holds.
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame } from "remotion";
import { assetById } from "../assets";
import { fonts } from "../lib/font";
import { At, BeachScene, C, H, OUTLINE, W } from "../openworld/kit";
import { HER, HIM, Person, STAND } from "../openworld/person";
import { backOut, easeOut, span } from "../voxel/anim.ts";
import { MbTile, taglineOf, TRIAL, URL, Wordmark } from "./base";
import { ACCENTS, type CardProps, cardVolume } from "./schema.ts";

const AT = { tagline: 0, ring: 8, tile: 12, word: 20, pill: 34, url: 42, line: 46, duo: 4 };

export const Gta6EndCard = ({ tagline, accent, address, cameo }: Omit<CardProps, "pixelate">) => {
  const frame = useCurrentFrame();
  const tag = easeOut(span(frame, AT.tagline, 12));
  const ring = easeOut(span(frame, AT.ring, 14));
  const tile = frame < AT.tile ? 0 : backOut(span(frame, AT.tile, 14), 0.5);
  const pill = frame < AT.pill ? 0 : backOut(span(frame, AT.pill, 12), 0.4);
  const url = easeOut(span(frame, AT.url, 14));
  const duo = easeOut(span(frame, AT.duo, 18));
  const pulse = 1 + 0.08 * Math.sin(frame / 5);
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: C.night }}>
      <div style={{ position: "absolute", inset: 0, opacity: 0.6, transform: `scale(${1.08 + frame * 0.0008})` }}>
        <BeachScene w={W} h={H} t={frame + 200} id="ec">
          {cameo !== "none" && (
            <g opacity={duo} transform={`translate(0 ${(1 - duo) * 200})`}>
              <At x={300} y={2060} s={0.95}><Person look={HIM} pose={{ ...STAND, tilt: 3 }} t={frame} /></At>
              <At x={790} y={2060} s={0.95}><Person look={HER} pose={{ ...STAND, tilt: -4 }} t={frame + 20} /></At>
            </g>
          )}
        </BeachScene>
      </div>
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(22,8,48,.75), rgba(22,8,48,.35) 55%, rgba(22,8,48,0))" }} />
      <div style={{ position: "absolute", left: 70, right: 140, top: 300, display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center" }}>
        <div style={{ opacity: tag, transform: `translateY(${(1 - tag) * 30}px)`, maxWidth: 860, fontFamily: `"${fonts.display}", sans-serif`, fontWeight: 900, fontSize: 64, lineHeight: 1.06, color: "#FFFFFF", filter: OUTLINE, textWrap: "balance" }}>
          {taglineOf({ tagline, address })}
        </div>
        <div style={{ position: "relative", marginTop: 50, width: 320, height: 320, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <svg width={320} height={320} viewBox="-160 -160 320 320" style={{ position: "absolute", inset: 0, overflow: "visible" }}>
            <circle r={150 * pulse} fill="none" stroke={C.yellow} strokeWidth={8} opacity={ring * 0.5} />
            <circle r={130} fill="none" stroke={C.yellow} strokeWidth={10} strokeDasharray={`${817 * ring} 817`} transform="rotate(-90)" />
          </svg>
          <div style={{ transform: `translateY(${(1 - tile) * -300}px) scale(${0.6 + 0.4 * tile})`, opacity: tile > 0 ? 1 : 0, filter: `drop-shadow(0 0 24px ${C.pink})` }}>
            <MbTile size={200} fill={C.ink} ink="#FFFFFF" />
          </div>
        </div>
        <div style={{ marginTop: 40, overflow: "hidden", padding: "0 10px 12px" }}>
          <Wordmark
            style={{ fontFamily: `"${fonts.display}", sans-serif`, fontWeight: 900, fontSize: 128, lineHeight: 1.04, letterSpacing: "-0.045em", color: "#FFFFFF", filter: OUTLINE }}
            letter={(i) => ({ transform: `translateY(${(1 - easeOut(span(frame, AT.word + i * 1.6, 14))) * 110}%)` })}
          />
        </div>
        <div style={{ marginTop: 24, transform: `scale(${pill})`, background: `linear-gradient(180deg, #FFF3A8, ${C.gold} 45%, ${C.orange})`, border: `5px solid ${C.ink}`, borderRadius: 999, padding: "14px 44px 18px", boxShadow: `8px 8px 0 ${C.ink}`, whiteSpace: "nowrap", fontFamily: `"${fonts.display}", sans-serif`, fontWeight: 900, fontSize: 54, color: C.ink }}>
          {TRIAL}
        </div>
        <div style={{ marginTop: 32, position: "relative", opacity: url, transform: `translateY(${(1 - url) * 24}px)`, fontFamily: `"${fonts.body}", sans-serif`, fontWeight: 700, fontSize: 44, color: "#FFFFFF", filter: OUTLINE }}>
          {URL}
          <div style={{ position: "absolute", left: 0, bottom: -10, height: 6, borderRadius: 3, background: ACCENTS[accent], width: `${100 * easeOut(span(frame, AT.line, 14))}%` }} />
        </div>
      </div>
      <Sequence from={AT.pill} durationInFrames={30} layout="none">
        <Html5Audio src={assetById("sfx-coin").src} volume={cardVolume("sfx-coin", -3)} />
      </Sequence>
    </AbsoluteFill>
  );
};
