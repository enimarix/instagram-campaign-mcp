// The Macro 3D style's vocabulary (step 154): what Blender can put in front of the macro camera
// (= SUBJECTS in cinematic/engine/macro.py; a test keeps them equal), the camera moves and the
// looks. Pure, so `node --test` runs it (test/macro3d.test.ts).

/** Scanned Poly Haven foods (CC0) and procedural foods / body pieces, real size. */
export const SUBJECTS = [
  "apple", "avocado", "banana", "lemon", "lime", "onion", "sweet_potato", "croissant", "buns", "cake",
  "egg", "salt", "sugar", "water", "oil", "glycogen", "protein", "fibre",
  "stomach", "muscle", "fatcell", "scale", "plate",
] as const;
export type Subject = (typeof SUBJECTS)[number];

/** What is not a real-size photo of a thing: drawn bigger than life, so the label says so. */
export const MAGNIFIED: readonly Subject[] = ["salt", "sugar", "water", "oil", "glycogen", "protein", "fibre", "stomach", "muscle", "fatcell"];
/** Subjects with an inside the `section` look cuts open (others show as plain). */
export const SECTIONED: readonly Subject[] = ["egg", "stomach"];

/**
 * Slow macro moves (= MOVES in macro.py): push in, pull back, orbit, rise (crane up), slide
 * along the surface close up, top (overhead, turning), whip (a fast pass with motion blur).
 */
export const MOVES = ["push", "pull", "orbit", "rise", "slide", "top", "whip"] as const;
export type Move = (typeof MOVES)[number];

/** plain; heat (a thermal gradient travelling along the subject, « Énergie en couleur »); section (cut open). */
export const LOOKS = ["plain", "heat", "section"] as const;
export type Look = (typeof LOOKS)[number];

/** The small honest label bottom-left: what the picture is, never a claim. */
export const LABELS = {
  agrandie: "Illustration agrandie",
  couleur: "Énergie en couleur",
  coupe: "Vue en coupe",
  illustration: "Illustration",
} as const;
export type LabelId = keyof typeof LABELS | "none";

/** The label a scene gets when it names none: what its look or subject is. */
export const autoLabel = (subject: Subject, look: Look): LabelId => {
  if (look === "heat") return "couleur";
  if (look === "section" && SECTIONED.includes(subject)) return "coupe";
  return MAGNIFIED.includes(subject) ? "agrandie" : "none";
};
