// The cutaway views by id (src/cutaway/views.ts lists them with their anchors and speed). A new
// mechanism: a component file here, its entry in views.ts and in this map.
import type { ViewId } from "../views";
import { arm } from "./arm";
import { type View, frac } from "./common";
import { fat, mito } from "./energy";
import { fibre, repair } from "./fibre";
import { muscle } from "./muscle";
import { leadCycle, sarcomere } from "./sarcomere";

export const VIEW_COMPONENTS: { [V in ViewId]: View<V> } = { arm, muscle, fibre, sarcomere, repair, fat, mito };

/** Where a view is in its cycle (0..1), for the numbered steps that follow the mechanism. */
export const cycleOf = (view: ViewId, phase: number) => (view === "sarcomere" ? leadCycle(phase) : frac(phase));
