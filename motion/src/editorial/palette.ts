// The editorial style's constants (step 144): black editorial ground, white grotesk, one hot
// pink, the blossom tree's pinks and the anatomy cards' deep blue. Pure (no imports) so the
// schema and `node --test` use it directly.

export const BLACK = "#000000";
export const WHITE = "#F7F5F2";
/** Secondary text: chapter totals, scrubber labels. */
export const GREY = "#8A8790";
/** The accent, used sparingly: the key word, the playhead, chips, brackets. */
export const PINK = "#FF3D8B";
export const PINK_DEEP = "#C81E6A";
/** Highlighted words in the anatomy cards' pixel captions. */
export const YELLOW = "#FFD23F";
/** Anticipation range on the scrubber. */
export const CYAN = "#2FD6D9";

/** Blossom pinks, dark to light, and the trunk's plum. */
export const BLOSSOM = ["#7A1747", "#B8286C", "#E2448A", "#FF6FA8", "#FF9CC4", "#FFD0E3"] as const;
export const BARK = ["#2E0F25", "#4A1A3A", "#6B2A55", "#8E4373"] as const;

/** The anatomy cards: deep blue ground, soft wavy shapes. */
export const DEEP = { ground: "#1B1E5C", shape: "#2B2F86", shapeLight: "#3B3FA6", rim: "#0C0E33" } as const;

/** The anatomy kit: soft glossy body parts with a face (base, shade, light). */
export const CHARACTERS = {
  stomach: { name: "Estomac", base: "#FF8BA0", shade: "#D9506F", light: "#FFD3DC", aura: "#FF9A3D" },
  muscle: { name: "Muscle", base: "#F0545F", shade: "#B42C3B", light: "#FFB0B4", aura: "#FFB23D" },
  heart: { name: "Cœur", base: "#FF4D6D", shade: "#C21F45", light: "#FFB3C1", aura: "#FF7A3D" },
  bone: { name: "Os", base: "#F3E1BE", shade: "#C9A774", light: "#FFF6E3", aura: "#FF8A3D" },
  fat: { name: "Cellule de graisse", base: "#F7C948", shade: "#C9971E", light: "#FFF0B8", aura: "#FF6F9C" },
} as const;
export const CHARACTER_IDS = Object.keys(CHARACTERS) as [keyof typeof CHARACTERS, ...(keyof typeof CHARACTERS)[]];
export type CharacterId = keyof typeof CHARACTERS;

/** Faces of the anatomy kit. */
export const MOODS = ["neutral", "happy", "surprised", "tired", "sore"] as const;
export type Mood = (typeof MOODS)[number];
