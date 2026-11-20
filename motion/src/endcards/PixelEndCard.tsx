// The pixel style's end card (step 137), for the 8-bit templates: a starfield, « PRESS START »
// blinks, gets "pressed" (a fast blink and the confirm sound), then the card assembles in pixels:
// the mB tile dissolves in cell by cell (each cell lights up in the accent first), the
// wordmark types in (Body in green), the tagline types fast in yellow, the « 7 JOURS
// GRATUITS » button pops in two hard steps, MACROBODY.FR appears and a small PRESS START
// blinks at the bottom, as in the owner's arcade video. The cameo sprite hops in beside the
// tile. Sweetie 16 colours, Press Start 2P (the templates' CRT scanlines go over it; the
// standalone clip adds them). Settles by SETTLE_S.pixel.
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame } from "remotion";
import { type AssetId, assetById } from "../assets";
import { PixelText } from "../components/PixelText";
import { Sprite } from "../components/Sprite";
import { seeded } from "../lib/game";
import { colors, palette } from "../lib/palette";
import { snap } from "../lib/pixel";
import { NAME_PARTS, taglineOf, TRIAL, URL } from "./base";
import { type Accent, type CardProps, cameoOf, cardVolume } from "./schema.ts";

/** The topic's macro colour, as the nearest Sweetie 16 colour. */
export const PIXEL_ACCENT: Record<Accent, string> = { brand: "#38B764", protein: "#EF7D57", carbs: "#A7F070", fat: "#FFCD75", kcal: "#41A6F6" };

/** Frames (from the card's start) at which each piece comes in. */
const AT = { press: 22, tile: 26, word: 46, cameo: 50, tagline: 60, button: 70, url: 76, again: 86 };
const TILE_CELLS = 24;
const CELL = 9; // px per tile cell: a 216 px tile
const DISSOLVE = 22; // frames for every tile cell to land

// --- The app mark rasterised from brand/logo.svg's geometry (512 units), one cell per sample.
const seg = (x: number, y: number, ax: number, ay: number, bx: number, by: number) => {
  const dx = bx - ax;
  const dy = by - ay;
  const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(x - ax - t * dx, y - ay - t * dy);
};
/** Distance to the upper half (or, `right`, the right half) of a circle. */
const arc = (x: number, y: number, cx: number, cy: number, r: number, right: boolean) =>
  (right ? x >= cx : y <= cy) ? Math.abs(Math.hypot(x - cx, y - cy) - r) : Infinity;
const inMark = (x: number, y: number) =>
  Math.min(seg(x, y, 110, 256, 110, 339), seg(x, y, 194, 256, 194, 339), arc(x, y, 152, 256, 42, false), arc(x, y, 236, 256, 42, false), seg(x, y, 278, 148, 278, 339)) <= 22 ||
  (x >= 88 && x <= 132 && y >= 192 && y <= 272) ||
  Math.min(seg(x, y, 278, 166, 350, 166), seg(x, y, 278, 236, 362, 236), seg(x, y, 278, 321, 362, 321), arc(x, y, 350, 201, 35, true), arc(x, y, 362, 278.5, 42.5, true)) <= 18;
/** Signed distance inside the rounded square (512 units, corner radius 113): > 0 inside. */
const inside = (x: number, y: number) => {
  const r = 113;
  const qx = Math.max(Math.abs(x - 256) - (256 - r), 0);
  const qy = Math.max(Math.abs(y - 256) - (256 - r), 0);
  return r - Math.hypot(qx, qy);
};
/** Latest cell start (bottom rows first: (cells - 1) x 0.45, plus up to 11 of scatter). */
const MAX_AT = (TILE_CELLS - 1) * 0.45 + 11;
type Cell = { x: number; y: number; color: string; at: number };
const TILE: Cell[] = (() => {
  const unit = 512 / TILE_CELLS;
  const cells: Cell[] = [];
  for (let y = 0; y < TILE_CELLS; y++) {
    for (let x = 0; x < TILE_CELLS; x++) {
      const [px, py] = [(x + 0.5) * unit, (y + 0.5) * unit];
      const d = inside(px, py);
      if (d <= 0) continue;
      const rim = d < unit * 1.1;
      const color = inMark(px, py) ? "#F4F4F4" : rim ? palette[15] : "#0B0B0B";
      // Bottom rows first, scattered: the tile fills up like a loading screen.
      cells.push({ x, y, color, at: (TILE_CELLS - 1 - y) * 0.45 + seeded(41, y * TILE_CELLS + x) * 11 });
    }
  }
  return cells;
})();

const STARS = Array.from({ length: 70 }, (_, i) => ({
  x: snap(seeded(5, i) * 1080, 6),
  y: snap(seeded(6, i) * 1920, 6),
  size: seeded(7, i) < 0.15 ? 12 : 6,
  phase: Math.floor(seeded(8, i) * 40),
}));

const Stars = ({ frame }: { frame: number }) => (
  <AbsoluteFill>
    {STARS.map((s, i) => {
      const on = Math.floor((frame + s.phase) / 10) % 4 !== 0;
      return <div key={i} style={{ position: "absolute", left: s.x, top: s.y, width: s.size, height: s.size, background: on ? palette[13] : palette[14], opacity: on ? 0.9 : 0.4 }} />;
    })}
  </AbsoluteFill>
);

const blink = (frame: number, period = 16) => Math.floor(frame / (period / 2)) % 2 === 0;

const SPRITES = { mascot: "mascot", slime: "slime", coin: "coin", heart: "heart" } as const satisfies Record<string, AssetId>;

export const PixelEndCard = ({ tagline, accent, address, cameo, note }: Omit<CardProps, "pixelate">) => {
  const frame = useCurrentFrame();
  const color = PIXEL_ACCENT[accent];
  const sprite = SPRITES[cameoOf("pixel", cameo) as keyof typeof SPRITES] as (typeof SPRITES)[keyof typeof SPRITES] | undefined;
  const head = NAME_PARTS[0];
  const tileOn = frame >= AT.tile;
  // The button pops in two hard steps (60 %, then 100 %), the 8-bit way.
  const button = frame < AT.button ? 0 : frame < AT.button + 3 ? 0.6 : frame < AT.button + 5 ? 1.12 : 1;
  const hopT = frame - AT.cameo;
  const hopY = hopT < 0 ? 0 : hopT < 12 ? -snap(Math.sin((Math.PI * hopT) / 12) * 90, 6) : -snap(Math.abs(Math.sin(hopT / 7)) * 18, 6);
  return (
    <AbsoluteFill style={{ backgroundColor: colors.background }}>
      <Stars frame={frame} />
      {/* Blinks slowly, then fast once "pressed", then gone. */}
      {frame < AT.press + 8 && (frame < AT.press ? blink(frame, 12) : blink(frame, 2)) && (
        <div style={{ position: "absolute", left: 0, right: 0, top: 720, display: "flex", justifyContent: "center" }}>
          <PixelText text="PRESS START" scale={6} color={colors.primary} />
        </div>
      )}
      {tileOn && (
        <div style={{ position: "absolute", left: 0, right: 0, top: 330, display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center" }}>
          <div style={{ position: "relative", width: TILE_CELLS * CELL, height: TILE_CELLS * CELL }}>
            {TILE.map((c, i) => {
              const t = frame - AT.tile - (c.at * DISSOLVE) / MAX_AT;
              if (t < 0) return null;
              return <div key={i} style={{ position: "absolute", left: c.x * CELL, top: c.y * CELL, width: CELL, height: CELL, background: t < 2 ? color : c.color }} />;
            })}
            {sprite && frame >= AT.cameo && (
              <div style={{ position: "absolute", left: TILE_CELLS * CELL + 48, bottom: 0, transform: `translateY(${hopY}px)` }}>
                <Sprite {...assetById(sprite)} scale={sprite === "mascot" ? 8 : 10} fps={4} />
              </div>
            )}
          </div>
          {/* Fixed width, left aligned: the wordmark types in place instead of growing from the centre. */}
          <div style={{ marginTop: 56, height: 64, width: [...NAME_PARTS.join("")].length * 64, display: "flex", textAlign: "left" }}>
            {frame >= AT.word && (
              <>
                {/* 30 chars/s: a letter a frame, Body follows on from macro. */}
                <PixelText text={head} scale={8} color={colors.text} speed={30} startFrame={AT.word} />
                <PixelText text={NAME_PARTS[1]} scale={8} color={colors.secondary} speed={30} startFrame={AT.word + head.length} />
              </>
            )}
          </div>
          <div style={{ marginTop: 44, minHeight: 96, display: "flex", justifyContent: "center" }}>
            {frame >= AT.tagline && <PixelText text={taglineOf({ tagline, address })} scale={4} color={colors.primary} speed={90} startFrame={AT.tagline} maxWidth={840} />}
          </div>
          <div
            style={{
              marginTop: 40,
              transform: `scale(${button})`,
              background: color,
              padding: "20px 28px",
              boxShadow: `0 6px 0 ${palette[15]}, 6px 0 0 ${palette[15]}, -6px 0 0 ${palette[15]}, 0 -6px 0 ${palette[15]}, 6px 6px 0 ${palette[0]}`,
            }}
          >
            <PixelText text={TRIAL.toUpperCase()} scale={5} color={colors.background} />
          </div>
          <div style={{ marginTop: 44, height: 32 }}>{frame >= AT.url && <PixelText text={URL.toUpperCase()} scale={4} color={colors.text} />}</div>
          <div style={{ marginTop: 40, height: 24 }}>{frame >= AT.again && blink(frame - AT.again, 24) && <PixelText text="PRESS START" scale={3} color={colors.primary} />}</div>
          {note && frame >= AT.url && (
            <div style={{ marginTop: 28 }}>
              <PixelText text={note} scale={2} color={palette[13]} maxWidth={840} />
            </div>
          )}
        </div>
      )}
      <Sequence from={AT.press} durationInFrames={30} layout="none">
        <Html5Audio src={assetById("sfx-confirm").src} volume={cardVolume("sfx-confirm")} />
      </Sequence>
      <Sequence from={AT.button} durationInFrames={30} layout="none">
        <Html5Audio src={assetById("sfx-coin").src} volume={cardVolume("sfx-coin")} />
      </Sequence>
    </AbsoluteFill>
  );
};
