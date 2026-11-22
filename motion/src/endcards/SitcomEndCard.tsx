// The sitcom style's end card (step 164): a TV-show title card. Warm sunburst rays (orange and
// pink) turn slowly over a turquoise floor; a cream panel with a thick ink outline bounces in
// (boing), the studio sign « APPLAUDISSEZ » lights up above it, and inside the brand stack plays
// as on the clean card: the mB tile, the wordmark rising letter by letter, the tagline, the
// « 7 jours gratuits » pill, macrobody.fr. Never a price. Settles by SETTLE_S.sitcom, then holds.
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame } from "remotion";
import { assetById } from "../assets";
import { fonts } from "../lib/font";
import { backOut, easeOut, span } from "../voxel/anim.ts";
import { CardStack } from "./CleanEndCard";
import { type CardProps, cameoOf, cardVolume } from "./schema.ts";

/** The sitcom palette: warm saturated sets, turquoise, pink, ink outlines. */
export const SITCOM = { orange: "#FF7A1A", pink: "#FF4F8B", turquoise: "#18C7C1", cream: "#FFF4E2", ink: "#1B1530", sun: "#FFC83D" } as const;

const RAYS = 18;

/** Frames (from the card's start) at which each piece comes in. */
const AT = { panel: 0, sign: 14 };

export const SitcomEndCard = ({ tagline, accent, address, cameo }: Omit<CardProps, "pixelate">) => {
  const frame = useCurrentFrame();
  const panel = backOut(span(frame, AT.panel, 14), 0.5);
  const sign = cameoOf("sitcom", cameo) === "applause";
  // the sign flickers on, then stays lit
  const lit = frame >= AT.sign && (frame >= AT.sign + 24 || Math.floor((frame - AT.sign) / 4) % 2 === 0);
  const signIn = easeOut(span(frame, AT.sign - 6, 8));
  return (
    <AbsoluteFill style={{ background: SITCOM.orange, overflow: "hidden" }}>
      {/* sunburst rays turning slowly round a point above the panel */}
      <svg width={1080} height={1920} style={{ position: "absolute", inset: 0 }}>
        <g transform={`translate(540 760) rotate(${frame * 0.4})`}>
          {Array.from({ length: RAYS }, (_, i) => {
            const a = (i * 2 * Math.PI) / RAYS;
            const b = a + Math.PI / RAYS;
            return <path key={i} d={`M0 0 L${2000 * Math.cos(a)} ${2000 * Math.sin(a)} L${2000 * Math.cos(b)} ${2000 * Math.sin(b)} Z`} fill={SITCOM.pink} opacity={0.55} />;
          })}
        </g>
        <circle cx={540} cy={760} r={420} fill={SITCOM.sun} opacity={0.35} />
        <rect x={0} y={1420} width={1080} height={500} fill={SITCOM.turquoise} />
        <rect x={0} y={1420} width={1080} height={14} fill={SITCOM.ink} />
      </svg>
      {sign && (
        <div style={{ position: "absolute", left: 540 - 300, top: 90, width: 600, opacity: signIn, transform: `translateY(${(1 - signIn) * -60}px)` }}>
          <div style={{ background: lit ? "#FF2D3D" : "#7A1E2A", border: `8px solid ${SITCOM.ink}`, borderRadius: 26, padding: "16px 0 18px", textAlign: "center", fontFamily: `"${fonts.display}", sans-serif`, fontWeight: 900, fontSize: 58, letterSpacing: "0.04em", color: lit ? "#FFFFFF" : "#E7B9BF", boxShadow: lit ? "0 0 60px rgba(255, 45, 61, 0.8)" : "none" }}>
            APPLAUDISSEZ
          </div>
        </div>
      )}
      <div style={{ position: "absolute", left: 70, right: 70, top: 250, height: 880, background: SITCOM.cream, border: `12px solid ${SITCOM.ink}`, borderRadius: 72, boxShadow: `0 26px 0 ${SITCOM.ink}`, transform: `scale(${panel})`, transformOrigin: "50% 50%" }} />
      <div style={{ position: "absolute", inset: 0, opacity: span(frame, 4, 4) }}>
        <CardStack tagline={tagline} accent={accent} address={address} />
      </div>
      <Sequence from={AT.panel} durationInFrames={30} layout="none">
        <Html5Audio src={assetById("sfx-boing").src} volume={cardVolume("sfx-boing")} />
      </Sequence>
    </AbsoluteFill>
  );
};
