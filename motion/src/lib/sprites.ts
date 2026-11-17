// Sprites drawn in code (ours, no licence to track) until the CC0 pack lands (step 042).
// Pure data: colours are brand palette indices (brand/brand.json colors.palette).
import type { PixelArt } from "./game";

/** Green slime, 2-frame idle bounce. */
export const slime: PixelArt = {
  colors: { G: 6, L: 5, K: 0 },
  frames: [
    [
      "..........",
      "...GGGG...",
      "..GLLGGG..",
      ".GLGGGGGG.",
      ".GGKGGKGG.",
      "GGGKGGKGGG",
      "GGGGGGGGGG",
      ".GGGGGGGG.",
    ],
    [
      "..........",
      "..........",
      "...GGGG...",
      ".GLLGGGGG.",
      "GLGKGGKGGG",
      "GGGKGGKGGG",
      "GGGGGGGGGG",
      "GGGGGGGGGG",
    ],
  ],
};

const coinFace = [
  "..YYYY..",
  ".YWYYYY.",
  "YWYYYYOY",
  "YWYYYYOY",
  "YYYYYYOY",
  "YYYYYYOY",
  ".YYYYOY.",
  "..YYYY..",
];
const coinTurn = [
  "...YY...",
  "..YWYY..",
  "..WYYO..",
  "..WYYO..",
  "..YYYO..",
  "..YYYO..",
  "..YYYO..",
  "...YY...",
];
const coinEdge = [
  "...YY...",
  "...YO...",
  "...YO...",
  "...YO...",
  "...YO...",
  "...YO...",
  "...YO...",
  "...YY...",
];

/** Spinning coin, 4 frames. */
export const coin: PixelArt = {
  colors: { Y: 4, O: 3, W: 12 },
  frames: [coinFace, coinTurn, coinEdge, coinTurn],
};

/** HUD heart: frame 0 full, frame 1 empty. */
export const heart: PixelArt = {
  colors: { R: 2, W: 12, D: 15, K: 0 },
  frames: [
    [
      ".KK.KK.",
      "KRWKRRK",
      "KWRRRRK",
      "KRRRRRK",
      ".KRRRK.",
      "..KRK..",
      "...K...",
    ],
    [
      ".KK.KK.",
      "KDDKDDK",
      "KDDDDDK",
      "KDDDDDK",
      ".KDDDK.",
      "..KDK..",
      "...K...",
    ],
  ],
};
