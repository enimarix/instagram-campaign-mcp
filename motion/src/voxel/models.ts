// The starter voxel library, all built in code (no third-party art). One voxel = one
// world unit; x right, y up, z toward the viewer (models face +z).
import { ISO, type Pose } from "./anim.ts";
import { cellNoise, VoxelGrid } from "./mesh.ts";
import { type ColorName, FORMS } from "./palette.ts";

type C = ColorName;

/** `a` or `b` per cell, `share` of the cells get `b` (stable texture, no Math.random). */
const speckle = (a: C, b: C, share: number, salt = 0) => (x: number, y: number, z: number): C => (cellNoise(x + salt, y, z) < share ? b : a);

/**
 * The mascot golem in its app level form (1 Étincelle … 6 Titan). Parts accumulate:
 * 2 arms, 3 core gem, 4 shoulders, 5 horns, 6 crown and wings.
 */
export const golem = (level: number): VoxelGrid => {
  const form = FORMS[Math.min(6, Math.max(1, Math.round(level))) - 1].id;
  const main = form as C;
  const dark = `${form}Dark` as C;
  const light = `${form}Light` as C;
  const g = new VoxelGrid();

  // Wings first: everything else paints over where they meet the back. Two cubes thick,
  // the top edge rising outward, scalloped feather tips, a darker line between feathers.
  if (level >= 6) {
    for (const s of [-1, 1])
      for (let dx = 0; dx <= 13; dx++) {
        const top = dx <= 9 ? 12 + Math.round(dx * 0.8) : [19, 20, 20, 19][dx - 10];
        const bottom = Math.round(9 + dx * 0.55) + (dx % 3 === 1 ? 0 : 1);
        for (let y = bottom; y <= top; y++) {
          const c: C = y === top ? light : y === bottom ? "white" : dx % 3 === 0 && y < (top + bottom) / 2 ? dark : main;
          g.set(s * (4 + dx), y, -4, c).set(s * (4 + dx), y, -5, c);
        }
      }
  }

  // Legs and feet (toes stick out in front).
  for (const s of [-1, 1]) {
    g.box(s * 2, 1, -2, s * 4, 2, 1, main);
    g.box(s * 2, 0, -2, s * 4, 0, 2, dark);
  }
  // Torso, vertical edges bevelled, lighter chest plate.
  g.box(-5, 3, -3, 5, 9, 2, main);
  for (let y = 3; y <= 9; y++) for (const x of [-5, 5]) g.remove(x, y, -3).remove(x, y, 2);
  g.box(-3, 4, 2, 3, 8, 2, light);

  if (level >= 2) {
    for (const s of [-1, 1]) {
      g.box(s * 6, 5, -1, s * 7, 8, 1, main); // upper arm
      g.box(s * 6, 2, -2, s * 8, 4, 1, dark); // fist
    }
  }
  if (level >= 4) {
    for (const s of [-1, 1]) {
      g.box(s * 6, 8, -2, s * 9, 9, 2, dark); // pauldron
      g.box(s * 6, 10, -1, s * 8, 10, 1, light);
    }
  }

  // Head: a big bevelled block (cute = head-heavy), dark visor with two white eye dots.
  g.box(-6, 10, -4, 6, 18, 3, main);
  for (let y = 10; y <= 18; y++) for (const x of [-6, 6]) g.remove(x, y, -4).remove(x, y, 3);
  for (let x = -6; x <= 6; x++) g.remove(x, 18, -4).remove(x, 18, 3);
  for (let z = -4; z <= 3; z++) g.remove(-6, 18, z).remove(6, 18, z);
  g.box(-5, 12, 4, 5, 16, 4, "ink");
  for (const x of [-5, 5]) g.remove(x, 12, 4).remove(x, 16, 4);
  g.box(-3, 14, 4, -2, 15, 4, "white").box(2, 14, 4, 3, 15, 4, "white");

  if (level >= 3) {
    // Core gem on the chest: a crystal diamond in a dark setting.
    g.box(-2, 4, 3, 2, 8, 3, dark);
    for (const [x, y] of [[-2, 4], [2, 4], [-2, 8], [2, 8]]) g.remove(x, y, 3);
    g.box(-1, 5, 3, 1, 7, 3, "crystal").set(-1, 5, 3, "crystalDark").set(1, 5, 3, "crystalDark");
    g.set(0, 6, 4, "white");
  }
  if (level >= 5) {
    for (const s of [-1, 1])
      for (const [x, y, c] of [[4, 19, "bone"], [5, 19, "bone"], [5, 20, "bone"], [6, 20, "bone"], [6, 21, "offWhite"], [7, 22, "offWhite"]] as const)
        g.box(s * x, y, -1, s * x, y, 0, c);
  }
  if (level >= 6) {
    // Crown: a hollow gold band, three spikes front and back, a red jewel in front.
    g.box(-3, 19, -3, 3, 20, 2, "fat").box(-2, 20, -2, 2, 20, 1, "fatDark");
    for (let x = -2; x <= 2; x++) for (let z = -2; z <= 1; z++) g.remove(x, 20, z);
    for (const x of [-3, 0, 3]) g.set(x, 21, 2, "fat").set(x, 21, -3, "fat");
    g.set(0, 20, 3, "protein");
  }
  return g;
};

/** Chicken drumstick, meat end left, bone end up-right. */
export const drumstick = (): VoxelGrid => {
  const g = new VoxelGrid();
  g.capsule([1, 7, 0], [7, 10, 0], 1.1, 1.1, "bone");
  g.ellipsoid(8, 10.5, -1, 1.5, 1.5, 1.5, "bone").ellipsoid(8, 10.5, 1, 1.5, 1.5, 1.5, "bone");
  g.capsule([-5, 4.5, 0], [1, 7, 0], 4.3, 2.2, "roast");
  // Browned skin: lighter on top, darker underneath, speckled.
  g.repaint((x, y, z, c) => {
    if (c !== "roast") return null;
    if (y <= 2) return "roastDark";
    return cellNoise(x, y, z) < 0.18 ? "roastDark" : y >= 8 || cellNoise(z, x, y) < 0.15 ? "roastLight" : "roast";
  });
  return g;
};

/** Avocado half, cut face up, pit in; the round end toward the viewer. */
export const avocado = (): VoxelGrid => {
  const g = new VoxelGrid();
  // Pear outline seen from above: a round base (z 1.5, r 5.4) and a narrower neck (z -4, r 3.6).
  const half = (z: number) => {
    const disk = (c: number, r: number) => (Math.abs(z - c) <= r ? Math.sqrt(r * r - (z - c) ** 2) : 0);
    const hull = z >= -4 && z <= 1.5 ? 3.6 + ((z + 4) / 5.5) * 1.8 : 0;
    return Math.max(disk(1.5, 5.4), disk(-4, 3.6), hull);
  };
  for (let z = -8; z <= 7; z++) {
    const w = half(z);
    for (let x = -6; x <= 6; x++) {
      if (Math.abs(x) > w) continue;
      const depth = Math.round(3.6 * Math.sqrt(1 - (x / (w + 0.5)) ** 2));
      g.box(x, 4 - depth, z, x, 4, z, "avocadoSkin");
    }
  }
  // The cut face: skin at the edge, a lighter rim, then flesh.
  const inside = (x: number, z: number, k: number) =>
    [[k, 0], [-k, 0], [0, k], [0, -k]].every(([dx, dz]) => g.get(x + dx, 4, z + dz) !== undefined);
  g.repaint((x, y, z) => (y !== 4 ? null : !inside(x, z, 1) ? "avocadoSkin" : !inside(x, z, 2) ? "avocadoRim" : "avocadoFlesh"));
  g.ellipsoid(0, 3.4, 1.5, 2.5, 2.8, 2.5, "pit", (_x, y) => y >= 5);
  return g;
};

/** Broccoli floret on its stem. */
export const broccoli = (): VoxelGrid => {
  const g = new VoxelGrid();
  g.capsule([0, 0, 0], [0, 6, 0], 1.9, 1.5, "stem");
  for (const s of [-1, 1]) g.capsule([0, 4, 0], [s * 3, 7, 0], 1, 1, "stem").capsule([0, 4, 0], [0, 7, s * 3], 1, 1, "stem");
  const crown = speckle("broccoli", "broccoliDark", 0.3, 7);
  g.ellipsoid(0, 10, 0, 3.8, 3.2, 3.8, crown);
  for (const [x, z] of [[-3.5, 0], [3.5, 0], [0, -3.5], [0, 3.5], [-2.5, 2.5], [2.5, -2.5], [2.5, 2.5], [-2.5, -2.5]])
    g.ellipsoid(x, 8.5, z, 2.6, 2.4, 2.6, crown);
  // Light catches the bumps on top.
  g.repaint((x, y, z, c) => (c === "broccoli" && g.get(x, y + 1, z) === undefined && cellNoise(x, z, y) < 0.45 ? "broccoliLight" : null));
  return g;
};

/** Fried egg: a wobbly white, a domed yolk with a highlight. */
export const egg = (): VoxelGrid => {
  const g = new VoxelGrid();
  g.cylinder(0, 0, 0, 0, 5.6, "eggWhite").cylinder(1.8, 1.4, 0, 0, 4.4, "eggWhite").cylinder(-2, 1.5, 0, 0, 3.6, "eggWhite");
  g.cylinder(0.3, 0.4, 1, 1, 4.2, "eggWhite");
  g.ellipsoid(-0.5, 1, -0.5, 2.7, 2.3, 2.7, "yolk", (_x, y) => y >= 1);
  g.set(-2, 2, -1, "yolkLight").set(-1, 3, -1, "yolkLight").set(-2, 2, 0, "yolkLight");
  return g;
};

/** Pizza slice, tip toward the viewer, crust at the back. */
export const pizza = (): VoxelGrid => {
  const g = new VoxelGrid();
  for (let z = -8; z <= 6; z++) {
    const half = Math.round((6 - z) * 0.42);
    for (let x = -half; x <= half; x++) {
      g.set(x, 0, z, "crustDark");
      const edge = Math.abs(x) === half;
      g.set(x, 1, z, edge && cellNoise(x, 1, z) < 0.5 ? "crust" : speckle("cheese", "cheeseLight", 0.25)(x, 1, z));
    }
  }
  g.box(-6, 1, -8, 6, 2, -7, speckle("crust", "crustDark", 0.25, 3));
  for (const [x, z] of [[-2.5, -4.5], [2.5, -4], [0, -0.5], [-1, 3.2]]) g.cylinder(x, z, 2, 2, 1.45, "pepperoni");
  g.set(3, 2, -1, "basil").set(-3, 2, -2, "basil").set(1, 2, 2, "basil");
  return g;
};

/**
 * Rice bowl: a navy glazed bowl (foot ring, flaring wall, white band under the rim) heaped
 * with white rice, loose grains on the dome, chopsticks resting across the rim.
 */
export const riceBowl = (): VoxelGrid => {
  const g = new VoxelGrid();
  // Wall radius per layer: a foot ring, then the bowl flares out to the rim (y 7).
  const radius = [3.2, 4.6, 5.8, 6.7, 7.4, 7.9, 8.3, 8.6];
  radius.forEach((r, y) => {
    const inner = y === 0 ? 2.2 : y === 1 ? 0 : r - 1.2; // y 1 is the bowl's floor
    for (let x = -9; x <= 9; x++)
      for (let z = -9; z <= 9; z++) {
        const d = Math.hypot(x, z);
        if (d <= r && (y === 1 || d > inner)) g.set(x, y, z, y === 0 ? "navyLight" : y === 6 ? "white" : "navy");
      }
  });
  // Rice: fills the bowl and heaps 3 layers above the rim.
  const rice = speckle("rice", "riceShade", 0.28, 11);
  for (let y = 2; y <= 10; y++) {
    const r = y <= 7 ? radius[y] - 1.2 : 7.3 - (y - 7) ** 1.6 * 1.4;
    g.cylinder(0, 0, y, y, r, rice);
  }
  // Loose grains standing proud on the dome (2 cells long, the way rice reads at this size).
  for (const [x, z, along] of [[-4, -2, 1], [3, -4, 0], [-1, 3, 0], [4, 2, 1], [-3, 4, 1], [1, -1, 0]] as const) {
    let top = 14;
    while (top > 0 && g.get(x, top, z) === undefined) top--;
    g.set(x, top + 1, z, "white").set(x + along, top + 1, z + (1 - along), "white");
  }
  g.capsule([-11, 9, 5], [10, 11.5, -3], 0.55, 0.55, "wood").capsule([-11, 9, 7], [10, 11.8, -1.2], 0.55, 0.55, "woodLight");
  return g;
};

/**
 * Phone standing up, showing the app: calorie ring in the macro colours and two bars, drawn
 * up to `fill` (0..1) so a scene can show the ring filling in steps.
 */
export const phone = (fill = 1): VoxelGrid => {
  const g = new VoxelGrid();
  const f = Math.min(1, Math.max(0, fill));
  g.box(-6, 0, -1, 6, 24, 0, "ink");
  for (const [x, y] of [[-6, 0], [6, 0], [-6, 24], [6, 24]]) g.remove(x, y, -1).remove(x, y, 0);
  g.box(-5, 2, 0, 5, 22, 0, "screen");
  g.box(-4, 21, 1, 4, 21, 1, "emerald"); // app header
  // Ring: protein, carbs, fat clockwise from the top over 76 % of it at full fill, the rest an empty track.
  for (let x = -5; x <= 5; x++)
    for (let y = 10; y <= 20; y++) {
      const r = Math.hypot(x, y - 15);
      if (r < 3 || r > 4.6) continue;
      const a = (Math.atan2(x, y - 15) / (2 * Math.PI) + 1) % 1; // 0 at the top, clockwise
      g.set(x, y, 1, a >= 0.76 * f ? "slate" : a < 0.3 ? "protein" : a < 0.58 ? "carbs" : "fat");
    }
  g.set(0, 15, 1, "kcal");
  const bar = (y: number, color: C, share: number) => {
    g.box(-4, y, 1, 4, y, 1, "slate");
    const cells = Math.round(9 * share * f);
    if (cells) g.box(-4, y, 1, -5 + cells, y, 1, color);
  };
  bar(7, "kcal", 0.75);
  bar(4, "emeraldLight", 0.45);
  g.box(-1, 1, 0, 1, 1, 0, "grey500"); // home bar
  return g;
};

/** 3x5 digits for voxel displays, top row first ("#" = lit). */
const DIGITS: Record<string, string[]> = {
  "0": ["###", "#.#", "#.#", "#.#", "###"],
  "1": [".#.", "##.", ".#.", ".#.", "###"],
  "2": ["###", "..#", "###", "#..", "###"],
  "3": ["###", "..#", ".##", "..#", "###"],
  "4": ["#.#", "#.#", "###", "..#", "..#"],
  "5": ["###", "#..", "###", "..#", "###"],
  "6": ["###", "#..", "###", "#.#", "###"],
  "7": ["###", "..#", ".#.", ".#.", ".#."],
  "8": ["###", "#.#", "###", "#.#", "###"],
  "9": ["###", "#.#", "###", "..#", "###"],
  ".": ["#"],
};

/**
 * Flat digital scale: a square glass platform on a white base, a dark LCD on the front strip
 * of the top showing `reading` (digits and "."), upright for a viewer in front. Wide and flat
 * so it reads as a scale, never as a toaster.
 */
export const kitchenScale = (reading = "72.4"): VoxelGrid => {
  const g = new VoxelGrid();
  g.box(-9, 0, -9, 9, 1, 9, "offWhite");
  for (const x of [-9, 9]) for (const z of [-9, 9]) g.remove(x, 0, z).remove(x, 1, z);
  g.box(-8, 2, -8, 8, 2, 8, "glassTop");
  for (const x of [-8, 8]) for (const z of [-8, 8]) g.remove(x, 2, z);
  const chars = [...reading].filter((c) => DIGITS[c]);
  const width = chars.reduce((w, c) => w + DIGITS[c][0].length + 1, -1);
  const x0 = -Math.floor(width / 2);
  g.box(x0 - 1, 2, 1, x0 + width, 2, 7, "lcd");
  let x = x0;
  for (const c of chars) {
    const rows = DIGITS[c];
    // Rows run back (top of the digit) to front; "." sits on the bottom row.
    rows.forEach((row, r) => [...row].forEach((ch, i) => ch === "#" && g.set(x + i, 2, 2 + r + (5 - rows.length), "lcdOn")));
    x += rows[0].length + 1;
  }
  return g;
};

/**
 * The kitchen set (step 130): a room corner seen from the front right. Floor x/z -20..19
 * (surface y = 0), walls along the back (z = -21) and the left (x = -21), white units with a
 * dark worktop along the back (top surface y = 11, front edge z = -12), a fridge in the
 * corner, a window above the worktop and two shelves with jars on the left wall.
 */
export const kitchen = (): VoxelGrid => {
  const g = new VoxelGrid();
  // Floor: 4x4 tiles in two warm tones, on a plinth.
  g.box(-22, -3, -22, 20, -3, 20, "plinth");
  g.box(-20, -2, -20, 19, -1, 19, (x, _y, z) => ((Math.floor(x / 4) + Math.floor(z / 4)) % 2 ? "floorA" : "floorB"));
  // Walls, 2 thick, 30 high: subway tiles up to y 14 (grout every third row, staggered joints), mint paint above.
  const wall = (along: number, y: number): C => {
    if (y > 14) return y === 15 ? "wallPaintDark" : "wallPaint";
    if ((y + 3) % 3 === 2) return "grout";
    return (((along + (Math.floor((y + 3) / 3) % 2) * 2) % 4) + 4) % 4 === 0 ? "grout" : "wallTile";
  };
  g.box(-22, -2, -22, 19, 29, -21, (x, y) => wall(x, y));
  g.box(-22, -2, -20, -21, 29, 19, (_x, y, z) => wall(z, y));
  // Window in the back wall above the worktop: white frame, two sky panes.
  const pane = (_x: number, y: number): C => (y > 22 ? "skyLight" : "sky");
  g.box(1, 15, -21, 13, 26, -21, "white");
  g.box(2, 16, -21, 6, 25, -21, pane).box(8, 16, -21, 12, 25, -21, pane);
  g.box(1, 15, -20, 13, 15, -19, "white"); // sill
  // Base units along the back wall: doors (a shaded groove between them), kick plate, worktop.
  g.box(-10, 0, -20, 19, 9, -13, "unit");
  g.box(-10, 0, -13, 19, 1, -13, "unitShade");
  for (let x = -3; x <= 19; x += 7) g.box(x, 2, -13, x, 9, -13, "unitShade");
  for (let x = -6; x <= 19; x += 7) g.box(x, 7, -12, x + 1, 7, -12, "grey300"); // handles
  g.box(-10, 10, -20, 19, 10, -12, "worktop");
  // Fridge in the corner: tall white box, freezer split, two handles.
  g.box(-20, 0, -20, -11, 26, -11, "unit");
  g.box(-20, 18, -10, -11, 18, -10, "unitShade");
  g.box(-12, 10, -10, -12, 16, -10, "grey300").box(-12, 20, -10, -12, 24, -10, "grey300");
  // Shelves on the left wall with jars (lids in the macro colours).
  for (const y of [15, 22]) g.box(-20, y, -6, -17, y, 10, "wood");
  for (const [z, y, lid] of [[-4, 16, "protein"], [0, 16, "fat"], [4, 16, "carbs"], [8, 16, "kcal"], [-3, 23, "carbs"], [2, 23, "protein"], [7, 23, "fat"]] as const) {
    g.box(-19, y, z, -18, y + 2, z + 1, "skyLight").box(-19, y + 3, z, -18, y + 3, z + 1, lid);
  }
  return g;
};

/** The kitchen set's establishing shot (iso): the whole room in the lower middle of a Reel. */
export const KITCHEN_WIDE: Pose = { ...ISO, azimuth: 45, distance: 160, target: [-5, 18, -5], lens: 18.5 };
/** Where the golem stands in the kitchen set: left of the floor's middle, the worktop on its right. */
export const KITCHEN_SPOT: [number, number, number] = [-8, 0, -2];

/** Rows of the bold "mB" on the app tile, top first ("#" = a raised white cube): 2-cube strokes. */
const MB = [
  "............#######.",
  "............########",
  "#########...##....##",
  "##########..##...##.",
  "##..##..##..#######.",
  "##..##..##..########",
  "##..##..##..##....##",
  "##..##..##..##....##",
  "##..##..##..########",
  "##..##..##..#######.",
];

/**
 * The macroBody app tile as voxels: a black rounded square (corners cut in steps), 26 x 26
 * cubes and 2 deep, with a bold white "mB" standing one cube proud; faces +z, centred on x,
 * standing on y = 0.
 */
export const mbTile = (): VoxelGrid => {
  const g = new VoxelGrid();
  const N = 26;
  const cut = [5, 3, 2, 1, 1]; // cells cut at each end of the outer rows: a squircle outline
  for (let y = 0; y < N; y++) {
    const edge = Math.min(y, N - 1 - y);
    const c = edge < cut.length ? cut[edge] : 0;
    for (let x = c; x < N - c; x++) g.box(x - N / 2, y, -1, x - N / 2, y, 0, "ink");
  }
  const x0 = -MB[0].length / 2;
  const y0 = Math.round((N - MB.length) / 2) - 1;
  MB.forEach((row, r) => [...row].forEach((ch, i) => ch === "#" && g.set(x0 + i, y0 + MB.length - 1 - r, 1, "white")));
  return g;
};

/** Empty dinner plate: a white disc with a raised rim and a navy band inside it. */
export const plate = (): VoxelGrid => {
  const g = new VoxelGrid();
  g.cylinder(0, 0, 0, 0, 4.5, "unitShade").cylinder(0, 0, 1, 1, 7.4, "white");
  g.repaint((x, y, z) => (y === 1 && Math.hypot(x, z) > 4.6 && Math.hypot(x, z) < 5.6 ? "navyLight" : null));
  for (let x = -8; x <= 8; x++) for (let z = -8; z <= 8; z++) if (Math.abs(Math.hypot(x, z) - 6.9) < 0.75) g.set(x, 2, z, "white");
  return g;
};

/** Round grass diorama base with dirt sides; its top is y = 0 when placed at y = -depth - 1. */
export const platform = (radius: number, depth = 3): VoxelGrid => {
  const g = new VoxelGrid();
  g.cylinder(0, 0, 0, depth, radius, speckle("dirt", "dirtDark", 0.3, 5));
  g.repaint((x, y, z) => (y === depth ? (cellNoise(x, z, 9) < 0.3 ? "grassDark" : "grass") : y === depth - 1 && cellNoise(x, z, 4) < 0.5 ? "grassDark" : null));
  return g;
};

/** Floating grass island: grass top at y = depth, dirt tapering to a point below. */
export const island = (radius: number, depth = 5): VoxelGrid => {
  const g = new VoxelGrid();
  for (let k = 0; k <= depth; k++) {
    const r = radius * Math.sqrt(1 - k / (depth + 1));
    g.cylinder(0, 0, depth - k, depth - k, r, k === 0 ? speckle("grass", "grassDark", 0.3, 9) : speckle("dirt", "dirtDark", 0.3, 5));
  }
  g.repaint((x, y, z, c) => (y === depth - 1 && c === "dirt" && cellNoise(x, z, 4) < 0.5 ? "grassDark" : null)); // grass edge hangs over
  return g;
};

/** Every prop in the library, for previews and tests. */
export const PROPS = { drumstick, avocado, pizza, egg, broccoli, riceBowl, phone: () => phone(), kitchenScale: () => kitchenScale() } as const;
