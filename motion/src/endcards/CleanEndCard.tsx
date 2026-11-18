// The clean style's end card (step 137), the owner's v5 brand-film look: the light surface
// #F5F7F8 with soft colour glows drifting (the topic's accent leads), a kicker pill drops in,
// the mB tile scales up with a soft shadow, the wordmark rises letter by letter out of a mask,
// the tagline follows (its last word in the accent), the « 7 jours gratuits » pill pops and
// macrobody.fr fades up while its accent underline draws. Cameo "ring": an app card whose
// calorie ring fills beside the tile. One easing everywhere: cubic-bezier(.22, 1, .36, 1).
// Settles by SETTLE_S.clean, then holds. The live card draws the same stack over footage.
import { AbsoluteFill, Easing, Html5Audio, Sequence, useCurrentFrame } from "remotion";
import { assetById } from "../assets";
import { brand } from "../brand";
import { fonts } from "../lib/font";
import { backOut, span } from "../voxel/anim.ts";
import { MbTile, STORES, taglineOf, TRIAL, URL, Wordmark } from "./base";
import { ACCENTS, type CardProps, cameoOf, TEXT_ACCENT } from "./schema.ts";

const smooth = Easing.bezier(0.22, 1, 0.36, 1);
const ink = brand.colors.light.ink;
const muted = brand.colors.light.muted;
const display = { fontFamily: `"${fonts.display}", sans-serif`, fontWeight: fonts.displayWeight } as const;
const body = { fontFamily: `"${fonts.body}", sans-serif` } as const;

/** Frames (from the card's start) at which each piece comes in. */
const AT = { kicker: 2, tile: 6, word: 16, tagline: 30, ring: 24, pill: 40, url: 46, line: 50 };

/** 0..1, eased, over `length` frames from `start`. */
const ease = (frame: number, start: number, length: number) => smooth(span(frame, start, length));

const rise = (frame: number, start: number, length = 18, dy = 40) => {
  const t = ease(frame, start, length);
  return { opacity: t, transform: `translateY(${(1 - t) * dy}px)` };
};

/** A soft colour glow: a big blurred disc drifting a few px a second. */
const Glow = ({ x, y, r, color, frame, phase, alpha }: { x: number; y: number; r: number; color: string; frame: number; phase: number; alpha: number }) => (
  <div
    style={{
      position: "absolute",
      left: x - r + Math.sin(frame / 40 + phase) * 30,
      top: y - r + Math.cos(frame / 47 + phase) * 24,
      width: 2 * r,
      height: 2 * r,
      borderRadius: "50%",
      background: color,
      opacity: alpha,
      filter: "blur(120px)",
    }}
  />
);

/** The app's calorie ring card: the ring fills in the accent, then a check. */
const RingCard = ({ frame, color }: { frame: number; color: string }) => {
  const fill = ease(frame, AT.ring + 6, 26);
  const r = 46;
  const c = 2 * Math.PI * r;
  const check = ease(frame, AT.ring + 30, 10);
  return (
    <div
      style={{
        width: 168,
        height: 168,
        borderRadius: 36,
        background: "#FFFFFF",
        boxShadow: "0 18px 40px rgba(17, 24, 39, 0.12), 0 2px 6px rgba(17, 24, 39, 0.06)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <svg width={120} height={120} viewBox="0 0 120 120">
        <circle cx={60} cy={60} r={r} fill="none" stroke="#EEF1F3" strokeWidth={14} />
        <circle cx={60} cy={60} r={r} fill="none" stroke={color} strokeWidth={14} strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - fill)} transform="rotate(-90 60 60)" />
        <path d="M42 61 L55 74 L79 48" fill="none" stroke={color} strokeWidth={10} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={60} strokeDashoffset={60 * (1 - check)} />
      </svg>
    </div>
  );
};

type Stack = Pick<CardProps, "tagline" | "accent" | "address"> & {
  /** Light text over footage (live) instead of ink on the light surface. */
  dark?: boolean;
  /** The kicker pill on top (clean). */
  kicker?: boolean;
  ring?: boolean;
};

/** The card's stack, centred on the frame: [kicker], tile [+ ring card], wordmark, tagline, pill, url. */
export const CardStack = ({ tagline, accent, address, dark = false, kicker = false, ring = false }: Stack) => {
  const frame = useCurrentFrame();
  const color = ACCENTS[accent];
  const words = taglineOf({ tagline, address }).split(" ");
  const tile = ease(frame, AT.tile, 22);
  const pill = frame < AT.pill ? 0 : backOut(span(frame, AT.pill, 14), 0.3);
  const ringIn = ease(frame, AT.ring, 20);
  const text = dark ? "#FFFFFF" : ink;
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: kicker ? 300 : 340, display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", color: text }}>
      {kicker && (
        <div
          style={{
            ...rise(frame, AT.kicker, 18, -30),
            ...body,
            fontWeight: 600,
            fontSize: 30,
            color: muted,
            background: "rgba(255, 255, 255, 0.85)",
            borderRadius: 999,
            padding: "12px 26px 13px",
            boxShadow: "0 6px 18px rgba(17, 24, 39, 0.06)",
            display: "flex",
            alignItems: "center",
            gap: 14,
            marginBottom: 56,
          }}
        >
          <span style={{ width: 14, height: 14, borderRadius: 7, background: color }} />
          {STORES}
        </div>
      )}
      {/* Tile, with the ring card beside it */}
      <div style={{ position: "relative" }}>
        <div
          style={{
            opacity: tile,
            transform: `scale(${0.72 + 0.28 * tile}) translateY(${(1 - tile) * 30}px)`,
            filter: `drop-shadow(0 ${24 * tile}px ${40 * tile}px rgba(17, 24, 39, ${dark ? 0.5 : 0.22}))`,
          }}
        >
          {/* Over footage a thin light rim keeps the black tile off the dark picture. */}
          <MbTile size={230}>{dark && <rect x={-6} y={-6} width={524} height={524} rx={118} fill="rgba(255, 255, 255, 0.28)" />}</MbTile>
        </div>
        {ring && (
          <div
            style={{
              position: "absolute",
              left: 230 + 34,
              top: 40 + Math.sin(frame / 18) * 5,
              opacity: ringIn,
              transform: `translateX(${(1 - ringIn) * 60}px) rotate(${6 - 2 * ringIn}deg)`,
            }}
          >
            <RingCard frame={frame} color={color} />
          </div>
        )}
      </div>
      {/* Wordmark rising out of a mask */}
      <div style={{ marginTop: 42, overflow: "hidden", padding: "0 10px 12px" }}>
        <Wordmark
          style={{ ...display, fontSize: 140, lineHeight: 1.04, letterSpacing: "-0.045em", color: text }}
          letter={(i) => {
            const t = ease(frame, AT.word + i * 1.6, 18);
            return { transform: `translateY(${(1 - t) * 110}%)` };
          }}
        />
      </div>
      <div style={{ ...rise(frame, AT.tagline), ...body, marginTop: 8, fontWeight: 600, fontSize: 46, lineHeight: 1.22, maxWidth: 820, textWrap: "balance", color: dark ? "rgba(255, 255, 255, 0.92)" : ink }}>
        {words.slice(0, -1).join(" ")} <span style={{ color: dark ? color : TEXT_ACCENT[accent] }}>{words[words.length - 1]}</span>
      </div>
      <div
        style={{
          ...display,
          marginTop: 40,
          transform: `scale(${pill})`,
          background: brand.colors.brand,
          color: "#FFFFFF",
          fontSize: 56,
          letterSpacing: "-0.02em",
          padding: "18px 46px 20px",
          borderRadius: 999,
          boxShadow: `0 14px 30px rgba(16, 185, 129, ${dark ? 0.4 : 0.28})`,
        }}
      >
        {TRIAL}
      </div>
      <div style={{ ...rise(frame, AT.url, 16, 24), ...body, marginTop: 34, fontWeight: 700, fontSize: 44, position: "relative" }}>
        {URL}
        <div style={{ position: "absolute", left: 0, bottom: -10, height: 6, borderRadius: 3, background: color, width: `${100 * ease(frame, AT.line, 16)}%` }} />
      </div>
      <Sequence from={AT.pill} durationInFrames={30} layout="none">
        <Html5Audio src={assetById("sfx-pop").src} volume={0.4} />
      </Sequence>
    </div>
  );
};

export const CleanEndCard = ({ tagline, accent, address, cameo }: Omit<CardProps, "pixelate">) => {
  const frame = useCurrentFrame();
  const color = ACCENTS[accent];
  return (
    <AbsoluteFill style={{ background: brand.colors.light.bg, overflow: "hidden" }}>
      <AbsoluteFill style={{ opacity: ease(frame, 0, 24) }}>
        <Glow x={160} y={420} r={360} color={color} frame={frame} phase={0} alpha={0.38} />
        <Glow x={960} y={760} r={340} color={brand.colors.macros.kcal} frame={frame} phase={2} alpha={0.22} />
        <Glow x={300} y={1500} r={420} color={brand.colors.macros.weight} frame={frame} phase={4} alpha={0.16} />
        <Glow x={900} y={1650} r={360} color={brand.colors.brand_light} frame={frame} phase={1} alpha={0.2} />
      </AbsoluteFill>
      <CardStack tagline={tagline} accent={accent} address={address} kicker ring={cameoOf("clean", cameo) === "ring"} />
    </AbsoluteFill>
  );
};
