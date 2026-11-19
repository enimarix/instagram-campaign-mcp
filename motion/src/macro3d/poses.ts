// Marco's poses (step 154): ids and the pose a line calls for. Pure, so `node --test` runs it.

/**
 * explain (an open hand in front), point (index up beside the head), stop (palm out), think
 * (hand on the chin), temple (finger to the temple), shrug (both palms up), thumbs (thumbs-up),
 * wow (both hands up, open).
 */
export const POSES = ["explain", "point", "stop", "think", "temple", "shrug", "thumbs", "wow"] as const;
export type Pose = (typeof POSES)[number];

const norm = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

/** The pose a line calls for, else the `n`-th of a calm rotation. */
export const poseFor = (line: string, n: number): Pose => {
  const l = norm(line);
  if (/\?\s*$/.test(line)) return /\b(pourquoi|comment)\b/.test(l) ? "think" : "shrug";
  if (/\b(pas|jamais|non|arrete|stop|evite)\b/.test(l)) return "stop";
  if (/!\s*$/.test(line)) return "wow";
  if (/\d/.test(l)) return "point";
  if (/\b(retiens|souviens|astuce|secret|cerveau|tete)\b/.test(l)) return "temple";
  return (["explain", "point", "thumbs", "explain", "temple"] as const)[n % 5];
};

/** The pose of the second half of a long scene: a reaction that differs from the first. */
export const reactionTo = (pose: Pose, n: number): Pose => {
  const next: Record<Pose, Pose> = { explain: "point", point: "explain", stop: "explain", think: "temple", temple: "point", shrug: "explain", thumbs: "explain", wow: "point" };
  return n % 3 === 2 ? "thumbs" : next[pose];
};
