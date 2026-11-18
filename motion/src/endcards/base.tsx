// The fixed base every end card draws in its own style (owner, 2026-11-18): the mB tile, the
// wordmark macro + Body (Body in emerald), the « 7 jours gratuits » pill and macrobody.fr.
import type { CSSProperties, ReactNode } from "react";
import { brand } from "../brand";
import { frenchSpaces } from "../lib/french";
import { type CardProps, DEFAULT_TAGLINE } from "./schema.ts";

/** The brand texts as drawn (French spacing). */
export const TRIAL = frenchSpaces(brand.cta.trial);
export const URL = brand.cta.url;
export const STORES = frenchSpaces(brand.cta.stores);

/** The tagline line: the video's own, else the app's in the video's address. */
export const taglineOf = ({ tagline, address }: Pick<CardProps, "tagline" | "address">) =>
  frenchSpaces(tagline ?? DEFAULT_TAGLINE[address]);

/** The name split at its second capital: ["macro", "Body"] (= brand-images.mjs). */
export const NAME_PARTS = (() => {
  const name = brand.name;
  const cut = [...name].findIndex((c, i) => i > 0 && c !== c.toLowerCase());
  return cut > 0 ? [name.slice(0, cut), name.slice(cut)] : [name, ""];
})();

/**
 * The wordmark one letter per span, so a card can stagger them: `letter(i, isBody)` gives
 * each letter's style (Body letters in emerald unless the style overrides the colour).
 */
export const Wordmark = ({ style, letter }: { style: CSSProperties; letter?: (i: number, body: boolean) => CSSProperties }) => {
  const head = NAME_PARTS[0].length;
  return (
    <div style={{ whiteSpace: "nowrap", ...style }}>
      {[...NAME_PARTS.join("")].map((ch, i) => (
        <span key={i} style={{ display: "inline-block", color: i >= head ? brand.colors.brand : undefined, ...letter?.(i, i >= head) }}>
          {ch}
        </span>
      ))}
    </div>
  );
};

/** The app mark (brand/logo.svg, same paths): a squircle with "mB", crisp at any size. */
export const MbTile = ({ size, fill = "#0B0B0B", ink = "#FFFFFF", style, children }: { size: number; fill?: string; ink?: string; style?: CSSProperties; children?: ReactNode }) => (
  <svg width={size} height={size} viewBox="0 0 512 512" style={{ display: "block", overflow: "visible", ...style }}>
    {children}
    <rect width="512" height="512" rx="113" fill={fill} />
    <g fill="none" stroke={ink} strokeWidth="44">
      <path d="M110 339V256A42 42 0 0 1 194 256V339M194 256A42 42 0 0 1 278 256" />
      <path d="M278 148V339" />
    </g>
    <rect x="88" y="192" width="44" height="80" fill={ink} />
    <g fill="none" stroke={ink} strokeWidth="36">
      <path d="M278 166H350A35 35 0 0 1 350 236H278" />
      <path d="M278 236H362A42.5 42.5 0 0 1 362 321H278" />
    </g>
  </svg>
);
