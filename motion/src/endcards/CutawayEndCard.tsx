// The cutaway style's end card (step 142): the HUD's final « level » screen. Over the night sky
// the chip reads « ▶ NIVEAU TERMINÉ » and the gauge fills to 100 %, a framed pixel box opens in
// hard steps, the mB tile dithers in on the pixel grid with a light flash, the story's mechanism
// keeps running small beside it (the cameo), the wordmark macro + Body types in, the tagline
// follows in pixel type, the « 7 JOURS GRATUITS » button pops in two steps, then MACROBODY.FR.
// Never a price. Settles by SETTLE_S.cutaway.
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { assetById } from "../assets";
import { Box, Defs, DitherRect, H, SkyLayer, steps, Tag, tagHeight, Type, typeSize, W } from "../cutaway/kit";
import { C } from "../cutaway/palette";
import { VIEWS, type ViewId } from "../cutaway/views";
import { VIEW_COMPONENTS } from "../cutaway/views/index";
import { fonts } from "../lib/font";
import { MbTile, NAME_PARTS, taglineOf, TRIAL, URL } from "./base";
import { ACCENTS, type CardProps, cameoOf } from "./schema.ts";

/** Frames (from the card's start) at which each piece comes in. */
const AT = { box: 4, tile: 14, flash: 28, cameo: 30, word: 34, tagline: 48, button: 62, url: 70 };
const BOX = { x: 110, y: 470, w: 860, h: 960 };

export const CutawayEndCard = ({ tagline, accent, address, cameo }: Omit<CardProps, "pixelate">) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const color = ACCENTS[accent];
  const who = cameoOf("cutaway", cameo);
  const view = who in VIEWS ? (who as ViewId) : null;
  const open = frame < AT.box ? 0 : frame < AT.box + 2 ? 0.25 : frame < AT.box + 4 ? 0.6 : 1;
  const tileLevel = steps((frame - AT.tile) / 14, 8);
  const word = [...NAME_PARTS.join("")];
  const shown = Math.max(0, Math.min(word.length, Math.floor((frame - AT.word) / 1.5)));
  const line = taglineOf({ tagline, address });
  const typed = Math.max(0, Math.min(line.length, Math.floor((frame - AT.tagline) * 2.5)));
  const button = frame < AT.button ? 0 : frame < AT.button + 3 ? 0.6 : frame < AT.button + 5 ? 1.12 : 1;
  const xp = Math.min(1, Math.max(0, frame / 30));
  const tileX = view ? 400 : 540;
  const Draw = view ? VIEW_COMPONENTS[view].Draw : null;
  const trial = TRIAL.toUpperCase();
  const tw = typeSize(trial, 5, true).w + 8 * 5 + 8;
  return (
    <AbsoluteFill style={{ background: C.night }}>
      <Defs />
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        <g filter="url(#cw-px)">
          <SkyLayer sky="night" f={frame} />
          {open === 1 && (
            <g mask={`url(#cw-m${Math.round(tileLevel * 16)})`}>
              <circle cx={tileX} cy={720} r={190} fill={color} opacity={0.35} />
              <g transform={`translate(${tileX - 150} 570)`}>
                <MbTile size={300} />
              </g>
            </g>
          )}
          {Draw && frame >= AT.cameo && (
            <g transform={`translate(785 ${720 - (frame < AT.cameo + 6 ? 40 - (frame - AT.cameo) * 7 : 0)}) scale(0.42)`}>
              <Draw phase={(frame / fps) * VIEWS[view!].hz} stage={0.6} rate={VIEWS[view!].hz} f={frame} />
            </g>
          )}
        </g>
        <g transform={`translate(540 0) scale(${open} 1) translate(-540 0)`}>
          {open > 0 && (
            <>
              <rect x={BOX.x} y={BOX.y} width={BOX.w} height={BOX.h} fill="none" stroke={C.cream} strokeWidth={6} />
              <rect x={BOX.x + 12} y={BOX.y + 12} width={BOX.w - 24} height={BOX.h - 24} fill="none" stroke={C.violet} strokeWidth={4} />
            </>
          )}
        </g>
        {frame >= AT.flash && frame < AT.flash + 6 && <DitherRect y={0} h={H} color={C.sun} level={0.75 - 0.25 * Math.floor((frame - AT.flash) / 2)} />}
        {/* HUD: chip and an XP gauge filling up. */}
        {Math.floor(frame / 5) % 2 === 0 || frame > 20 ? <Tag text="▶ Niveau terminé" x={65} y={280} unit={4} color={C.hudOrange} /> : null}
        <Tag text={`${Math.round(xp * 100)} % XP`} x={960} y={280} unit={4} color={C.white} border={C.hudBlue} align="right" />
        {Array.from({ length: 14 }, (_, k) => (
          <rect key={k} x={960 - (14 - k) * 18 + 4} y={280 + tagHeight(4) + 12} width={14} height={16} fill={k < Math.round(xp * 14) ? C.green : C.cloudDark} />
        ))}
        {frame >= AT.tagline && <Type text={line.slice(0, typed)} x={540} y={1060} unit={4} color={C.yellow} bold align="center" maxWidth={760} />}
        {button > 0 && (
          <g transform={`translate(540 1222) scale(${button}) translate(-540 -1222)`}>
            <Box x={540 - tw / 2 - 6} y={1180 + 6} w={tw + 12} h={tagHeight(5) + 0} border={C.ink} fill={C.ink} />
            <Tag text={trial} x={540} y={1180} unit={5} color={C.ink} border={C.cream} fill={color} align="center" />
          </g>
        )}
        {frame >= AT.url && <Type text={URL} x={540} y={1330} unit={4} color={C.white} bold align="center" />}
      </svg>
      {/* The wordmark stays the brand's own type: macro + Body (Body in emerald). */}
      <div style={{ position: "absolute", left: 0, right: 0, top: 930, textAlign: "center", fontFamily: fonts.display, fontWeight: fonts.displayWeight, fontSize: 112, letterSpacing: -3, lineHeight: 1 }}>
        {word.map((ch, i) => (
          <span key={i} style={{ color: i >= NAME_PARTS[0].length ? ACCENTS.brand : C.white, visibility: i < shown ? "visible" : "hidden" }}>
            {ch}
          </span>
        ))}
      </div>
      <Sequence from={AT.flash} durationInFrames={30} layout="none">
        <Html5Audio src={assetById("sfx-confirm").src} volume={0.5} />
      </Sequence>
      <Sequence from={AT.button} durationInFrames={30} layout="none">
        <Html5Audio src={assetById("sfx-coin").src} volume={0.5} />
      </Sequence>
    </AbsoluteFill>
  );
};
