// The cinema style's three sets (step 143) and their shot lists. Each set is a handful of
// views painted cell by cell (common.ts: the contract), each view one framing of the story
// with its own wide light; a shot = a view plus a camera move (zoom and focus, from → to).
// The template cuts to the next shot of the list on every scene (and halfway through a long
// one), so no two consecutive shots share a view, and the camera moves in every beat
// (src/templates/PixelCinema/layout.ts).
// - window: a rainy city at 21 h, the lit kitchen window as the hero (window.ts).
// - pier: dawn on the coast, a runner backlit by the sun, the lighthouse (pier.ts).
// - fridge: a dark kitchen at night, the fridge's light (fridge.ts).
// `paint` fills an RGBA buffer (GW x GH); `solid` cells turn black in the lightning frame
// (the reference's silhouette moment), the rest (sky, glass, light) turns white.
// Pure, so `node --test` runs it.
import { DIM, lit, type Paint, type View } from "./common.ts";
import { FRIDGE_VIEWS } from "./fridge.ts";
import { PIER_VIEWS } from "./pier.ts";
import { beamAt, clamp01, GH, GW, smooth } from "./pixel.ts";
import { WINDOW_VIEWS } from "./window.ts";

export { ANCHORS, type AnchorId, type Paint, type View } from "./common.ts";

export const SCENE_IDS = ["window", "pier", "fridge"] as const;
export type SceneId = (typeof SCENE_IDS)[number];

/** A camera key: zoom and the focus cell (it stays put on screen while zooming). */
export type Cam3 = readonly [zoom: number, fx: number, fy: number];
/** One shot: a view and the camera move across the beat. */
export type Shot = { view: string; from: Cam3; to: Cam3 };

type Set = {
  views: Record<string, View>;
  shots: Shot[];
  /** The lightning beat's shot: the view whose silhouette reads best. */
  flash: Shot;
  /** The end card's backdrop: a dark framing with room for the tile and wordmark. */
  card: Shot;
};

const shot = (view: string, from: Cam3, to: Cam3): Shot => ({ view, from, to });

/**
 * The shot lists, in order (the hook takes the first; never the same view twice in a row,
 * the last and the first differ too, so the list can loop).
 */
export const SETS: Record<SceneId, Set> = {
  window: {
    views: WINDOW_VIEWS,
    shots: [
      shot("block", [1, 100, 170], [1.3, 100, 166]), // wide: the city block in the storm
      shot("facade", [1, 90, 150], [1.28, 96, 140]), // push-in on the window
      shot("interior", [1.25, 100, 140], [1, 90, 160]), // close, through the glass
      shot("puddle", [1, 90, 120], [1.25, 90, 230]), // street level, tilt down to the puddle
      shot("facade", [1.45, 70, 110], [1.22, 110, 150]), // close on the window, drifting
      shot("interior", [1, 70, 120], [1.22, 110, 150]), // inside again, the lamp and the cupboard
    ],
    flash: shot("block", [1.08, 100, 150], [1.3, 100, 156]),
    card: shot("block", [1.4, 100, 166], [1.4, 100, 166]),
  },
  pier: {
    views: PIER_VIEWS,
    shots: [
      shot("wide", [1, 100, 200], [1.3, 120, 196]),
      shot("runner", [1, 92, 200], [1.25, 92, 180]),
      shot("waves", [1, 90, 160], [1.25, 60, 230]),
      shot("horizon", [1.3, 90, 200], [1, 90, 200]),
      shot("runner", [1.45, 92, 140], [1.2, 70, 180]),
      shot("waves", [1.4, 40, 250], [1.15, 120, 200]),
    ],
    flash: shot("wide", [1.05, 100, 210], [1.28, 120, 205]),
    card: shot("horizon", [1.1, 90, 200], [1.1, 90, 200]),
  },
  fridge: {
    views: FRIDGE_VIEWS,
    shots: [
      shot("kitchen", [1, 124, 184], [1.3, 124, 184]),
      shot("face", [1, 110, 150], [1.25, 120, 140]),
      shot("inside", [1.25, 90, 180], [1, 90, 170]),
      shot("window", [1, 90, 150], [1.25, 70, 120]),
      shot("kitchen", [1.45, 100, 230], [1.25, 130, 200]),
      shot("face", [1.4, 100, 120], [1.2, 100, 140]),
    ],
    flash: shot("inside", [1.3, 90, 185], [1.02, 90, 165]),
    card: shot("window", [1.1, 90, 150], [1.1, 90, 150]),
  },
};

export const viewOf = (set: SceneId, view: string): View => SETS[set].views[view];

/**
 * Paint view `view` of set `set` into `data` (RGBA, GW x GH). Under `dim` the picture sinks
 * toward night blue (text over it stays readable); the lightning frame ignores it.
 * Returns the view's beam (Stage colours the rain in it).
 */
export const paint = (set: SceneId, view: string, data: Uint8ClampedArray, p: Paint) => {
  const v = viewOf(set, view);
  const beam = v.beam(p);
  const dim = p.flash ? 0 : clamp01(p.dim) * 0.62;
  for (let y = 0; y < GH; y++) {
    // The top of the frame sinks a little toward night blue: the headlines stay readable over any shot.
    const top = p.flash ? dim : dim + (1 - dim) * smooth(115, 25, y) * 0.5;
    for (let x = 0; x < GW; x++) {
      let { c } = v.pixel(x, y, p, beam);
      if (p.extra) c = lit(c, beamAt(p.extra, x, y), x, y);
      const o = (y * GW + x) * 4;
      data[o] = c[0] + (DIM[0] - c[0]) * top;
      data[o + 1] = c[1] + (DIM[1] - c[1]) * top;
      data[o + 2] = c[2] + (DIM[2] - c[2]) * top;
      data[o + 3] = 255;
    }
  }
  return beam;
};

/** Is screen cell (x, y) solid (black in the lightning frame)? For tests. */
export const solidAt = (set: SceneId, view: string, x: number, y: number, p: Paint) => {
  const v = viewOf(set, view);
  return v.pixel(x, y, p, v.beam(p)).solid;
};
