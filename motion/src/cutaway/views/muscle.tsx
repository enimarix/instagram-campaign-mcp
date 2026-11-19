// Muscle view (step 142): a muscle belly cut open. Its tendon on the left, striations along it,
// the cut section full of fascicles (each a bundle of fibres), one fascicle pulled out to the
// right. A nerve signal runs out from the motor end plate every cycle (teal sparkles); `stage`
// grows the muscle (hypertrophy).
import { C } from "../palette";
import { type View, type ViewState, frac, LINE, Sparkles } from "./common";

const geometry = (stage: number) => {
  const g = 1 + 0.35 * stage;
  const R = 165 * g;
  const cx = 170;
  const rx = 0.42 * R;
  const rf = 0.2 * R;
  const fasc = { y: -0.32 * R, x0: cx + 0.3 * rx, len: 230 };
  return { g, R, cx, rx, rf, fasc };
};

// Fascicle centres in the unit disc (a hex grid inside radius 0.8).
const CELLS: [number, number][] = [];
for (let row = -3; row <= 3; row++) {
  for (let col = -3; col <= 3; col++) {
    const u = (col + (row % 2 ? 0.5 : 0)) * 0.27;
    const v = row * 0.235;
    if (u * u + v * v <= 0.66) CELLS.push([u, v]);
  }
}
const L = [-430, 30] as const;

const Draw = ({ phase, stage, f }: ViewState) => {
  const { R, cx, rx, rf, fasc } = geometry(stage);
  const wave = frac(phase);
  const plate = -120;
  const body = `M${L[0]} ${L[1]}Q${-190} ${-R * 1.3} ${cx} ${-R}L${cx} ${R}Q${-190} ${R * 1.3} ${L[0]} ${L[1]}Z`;
  return (
    <g>
      <path d={`M-560 ${L[1] - 16}L${L[0] + 20} ${L[1] - 26}L${L[0] + 20} ${L[1] + 26}L-560 ${L[1] + 16}Z`} fill={C.white} stroke={C.ink} {...LINE} />
      <path d={body} fill={C.copper} stroke={C.ink} {...LINE} />
      {[0.12, 0.26, 0.4, 0.54, 0.68, 0.82].map((k) => (
        <path key={k} d={`M${L[0] + 10} ${L[1]}Q${-190} ${-R * 1.3 + 2.6 * R * k} ${cx} ${-R + 2 * R * k}`} fill="none" stroke={k % 0.28 < 0.1 ? C.copperLight : C.copperDark} strokeWidth={8} />
      ))}
      {/* The nerve signal runs both ways from the end plate. */}
      {[1, -1].map((d) => (
        <Sparkles key={d} cx={plate + d * wave * 330} cy={0} rx={34} ry={R * 0.75 * (1 - 0.5 * wave * (d < 0 ? 1 : 0.3))} n={22} seed={d > 0 ? 31 : 37} f={f} color={C.tealLight} on={1 - wave * 0.6} />
      ))}
      <path d={`M${plate - 40} ${-R - 230}Q${plate - 60} ${-R - 90} ${plate} ${-R * 1.04}`} fill="none" stroke={C.ink} strokeWidth={22} />
      <path d={`M${plate - 40} ${-R - 230}Q${plate - 60} ${-R - 90} ${plate} ${-R * 1.04}`} fill="none" stroke={C.yellow} strokeWidth={10} />
      <ellipse cx={plate} cy={-R * 1.04} rx={30} ry={14} fill={C.yellow} stroke={C.ink} {...LINE} />
      {/* The cut section: fascicles in their sheaths. */}
      <ellipse cx={cx} cy={0} rx={rx} ry={R} fill={C.copperDark} stroke={C.cream} {...LINE} />
      {CELLS.map(([u, v], i) => (
        <g key={i}>
          <ellipse cx={cx + u * rx} cy={v * R} rx={rf * 0.42} ry={rf * 0.92} fill={C.copper} stroke={C.cream} strokeWidth={4} />
          {[-0.3, 0.3].map((d) => (
            <rect key={d} x={cx + u * rx + d * rf * 0.3 - 4} y={v * R + d * rf * 1.2 - 4} width={8} height={8} fill={C.copperLight} />
          ))}
        </g>
      ))}
      {/* One fascicle pulled out to the right: its fibres run along it. */}
      <path d={`M${fasc.x0} ${fasc.y - rf}L${fasc.x0 + fasc.len} ${fasc.y - rf - 40}L${fasc.x0 + fasc.len} ${fasc.y + rf - 40}L${fasc.x0} ${fasc.y + rf}Z`} fill={C.copper} stroke={C.ink} {...LINE} />
      {[-0.6, -0.2, 0.2, 0.6].map((k) => (
        <line key={k} x1={fasc.x0} y1={fasc.y + k * rf} x2={fasc.x0 + fasc.len} y2={fasc.y + k * rf - 40} stroke={C.copperLight} strokeWidth={5} />
      ))}
      <ellipse cx={fasc.x0 + fasc.len} cy={fasc.y - 40} rx={rf * 0.42} ry={rf} fill={C.copperDark} stroke={C.cream} strokeWidth={5} />
      {[-0.5, 0, 0.5].map((k) => (
        <rect key={k} x={fasc.x0 + fasc.len - 5} y={fasc.y - 40 + k * rf - 5} width={10} height={10} fill={C.tealLight} />
      ))}
    </g>
  );
};

export const muscle: View<"muscle"> = {
  Draw,
  anchors: ({ stage }) => {
    const { R, cx, rx, fasc } = geometry(stage);
    return {
      muscle: [-170, -R * 0.55],
      faisceau: [cx + 0.1 * rx, R * 0.35],
      fibre: [fasc.x0 + fasc.len, fasc.y - 40],
      tendon: [-500, L[1]],
      nerf: [-120, -R * 1.04],
    };
  },
};
