// Owner rule (2026-11-18): never a price on screen. Every visible text prop of the brand
// templates and end cards refuses price-like wording with `.refine(noPrice, NO_PRICE)`.
// Pure (no imports) so `node --test` runs it directly (test/noPrice.test.ts).

const PRICE = [
  /[€$£]/,
  /\b(?:eur|euros?|usd|dollars?)\b/i,
  /\/\s*(?:mois|an|semaine|month|year)\b/i,
  /\bpar\s+(?:mois|an|semaine)\b/i,
  /\b(?:per\s+month|per\s+year|a\s+month)\b/i,
  // "9,99", "4.99" (an amount with cents) even without a currency sign.
  /\d[.,]\d\d(?!\d)\s*(?![%\s]*(?:kg|g|mg|kcal|cal|l|ml|m|cm|km|h|min|s)\b)/i,
];

/** True when `text` holds no price-like wording (currency signs or names, per month / year). */
export const noPrice = (text: string): boolean => !PRICE.some((re) => re.test(text));

export const NO_PRICE = "no price on screen (owner rule): remove the amount, currency or per-month wording";
