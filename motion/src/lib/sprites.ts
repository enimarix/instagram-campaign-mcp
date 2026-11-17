// Sprites drawn in code (ours, no licence to track). scripts/make-assets.ts writes them to
// public/sprites/ as SVG sheets for the asset registry (src/assets.ts).
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

const mascotBody = [
  "................",
  ".....KKKKKK.....",
  "...KKOOOOOOKK...",
  "..KOOYYOOOOOOK..",
  "..KOYOOOOOOOOK..",
  ".KOOOWKOOWKOOOK.",
  ".KOOOKKOOKKOOOK.",
  ".KOOOOOOOOOOOOK.",
  ".KORROOKKOORROK.",
  ".KOOOOOOOOOOOOK.",
  "..KOOOOOOOOOOK..",
  "...KKOOOOOOKK...",
  ".....KKKKKK.....",
];
// Legs and shoes avoid K (= the brand background), so they show on dark scenes.
const legs = {
  stand: [".....DD..DD.....", ".....DD..DD.....", "....RRR..RRR...."],
  left: ["....DD....DD....", "...DD......DD...", "..RRR......RRR.."],
  right: [".....DD..DD.....", "......DDDD......", ".....RRRRRR....."],
};

/**
 * PLACEHOLDER mascot (replaced by the real one at gate H1 / step 050): a round orange buddy,
 * 4-frame walk (stand, stride, stand, legs together).
 */
export const mascot: PixelArt = {
  colors: { K: 0, O: 3, Y: 4, W: 12, R: 2, D: 1 },
  frames: [legs.stand, legs.left, legs.stand, legs.right].map((l) => [...mascotBody, ...l]),
};

/** Level tiles, one per frame: 0 grass top, 1 dirt, 2 brick, 3 "?" block. */
export const tiles: PixelArt = {
  colors: { L: 5, G: 6, P: 1, S: 2, K: 0, R: 2, O: 3, Y: 4, W: 12 },
  frames: [
    ["LLLLLLLL", "LGLLLGLL", "GGGGGGGG", "PGPPPGPP", "PPPPPPPP", "PPSPPPPP", "PPPPPSPP", "PPPPPPPP"],
    ["PPPPPPPP", "PPSPPPPP", "PPPPPPSP", "PPPPPPPP", "PSPPPPPP", "PPPPSPPP", "PPPPPPPP", "PPPPPPPS"],
    ["ORRKORRR", "RRRKRRRR", "RRRKRRRR", "KKKKKKKK", "ORRRRRRK", "RRRRRRRK", "RRRRRRRK", "KKKKKKKK"],
    ["KKKKKKKK", "KYWWWYOK", "KYYYWYOK", "KYYWYYOK", "KYYYYYOK", "KYYWYYOK", "KYYYYYOK", "KKKKKKKK"],
  ],
};
