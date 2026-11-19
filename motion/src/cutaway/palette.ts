// The cutaway style's dusk palette (step 142): deep violet / indigo sky, warm orange-peach
// sunset clouds, teal and copper accents, cream outlines, a yellow "crank" and HUD colours.
// Pure (no imports).

export const C = {
  /** Box fill and the darkest outline. */
  ink: "#120E24",
  night: "#1D173F",
  night2: "#251D4D",
  cloudDark: "#2F255C",
  cloud: "#3D3072",
  violet: "#4A3A84",
  mauve: "#78509B",
  pink: "#C2638F",
  peach: "#F0906F",
  orange: "#F6B26B",
  sun: "#FFD99C",
  cream: "#F7DCAE",
  white: "#FFF5E6",
  teal: "#2AB0A6",
  tealDark: "#1B6A74",
  tealLight: "#8EE8D8",
  copper: "#CF5E3A",
  copperDark: "#8A3224",
  copperLight: "#F39C6C",
  steel: "#8F9BE0",
  steelDark: "#5762AA",
  steelDeep: "#353B78",
  yellow: "#F7C948",
  yellowDark: "#C2861F",
  hot: "#F2689B",
  hudBlue: "#5BB8F5",
  hudOrange: "#F59E3B",
  green: "#63D471",
  red: "#E8504A",
} as const;

/** Sky bands from the top, as [colour, share of the height]: dusk (title, payoff) and night (inside). */
export const SKIES = {
  dusk: [
    [C.night2, 0.12],
    [C.violet, 0.14],
    [C.mauve, 0.14],
    [C.pink, 0.12],
    [C.peach, 0.12],
    [C.orange, 0.1],
    [C.mauve, 0.12],
    [C.violet, 0.14],
  ],
  night: [
    [C.night, 0.22],
    [C.night2, 0.26],
    [C.cloudDark, 0.2],
    [C.cloud, 0.14],
    [C.cloudDark, 0.18],
  ],
} as const satisfies Record<string, readonly (readonly [string, number])[]>;
export type Sky = keyof typeof SKIES;
