// The 8-bit style's colours (the brand kit no longer carries them since step 050: styles
// are per template). Sweetie 16, the free 16-colour palette by GrafxKid; the five named
// roles are picked from it. Standalone (no imports): scripts/make-assets.ts runs it in Node.

/** primary, secondary, accent, background, text. */
export const colors = {
  primary: "#FFCD75",
  secondary: "#38B764",
  accent: "#EF7D57",
  background: "#1A1C2C",
  text: "#F4F4F4",
};

export const palette: readonly string[] = [
  "#1A1C2C", "#5D275D", "#B13E53", "#EF7D57",
  "#FFCD75", "#A7F070", "#38B764", "#257179",
  "#29366F", "#3B5DC9", "#41A6F6", "#73EFF7",
  "#F4F4F4", "#94B0C2", "#566C86", "#333C57",
];
