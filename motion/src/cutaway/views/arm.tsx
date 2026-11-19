// Arm view (step 142, hero art in review round 1): a muscular arm in side view, lit by the
// sunset from the upper right, curling a dumbbell. The skin of the upper arm is cut away in a
// window that shows the biceps: fascicle bundles, the fat layer at the cut, the tendon down to
// the forearm. The biceps shortens, bulges and sparkles as it fires; the forearm and dumbbell
// leave smear trails when they move fast. One curl per cycle.
import { C } from "../palette";
import { blobD, ellipseD, LIGHT, RAMPS, Shade } from "../shade";
import { type View, type ViewState, pulse, rad, Sparkles } from "./common";

const E = [-20, 190] as const; // elbow
const FORE = 270;

type V2 = readonly [number, number];
const add = (a: V2, b: V2, k = 1): V2 => [a[0] + b[0] * k, a[1] + b[1] * k];

/** The curl starts part-way up, so the Reel cover (0.4 s in) shows the biceps flexed. */
const START = 0.22;

const geometry = (phase: number) => {
  const c = pulse(phase + START);
  const a = rad(14 + 116 * c);
  const dir: V2 = [Math.sin(a), Math.cos(a)];
  const wrist = add(E, dir, FORE);
  // The cutaway window over the biceps: it bulges forward and shortens as the arm curls.
  const win = { cx: 14 + 16 * c, cy: -6 + 12 * c, rx: 66 + 20 * c, ry: 168 - 18 * c };
  return { c, a, dir, wrist, win };
};

/** Upper arm outline: deltoid at the top, triceps behind, biceps in front (bulging with `c`), the elbow. */
const upperArm = (c: number) =>
  blobD([
    [-140, -200],
    [-158, -70],
    [-140, 70],
    [-92, 190],
    [-40, 250],
    [28, 222],
    [52 + 16 * c, 120],
    [86 + 38 * c, 0 + 10 * c],
    [72 + 18 * c, -130],
    [20, -200],
    [-70, -215],
  ]);

const torso = blobD([
  [-520, -430],
  [-250, -430],
  [-200, -320],
  [-225, -100],
  [-275, 200],
  [-300, 560],
  [-520, 560],
]);
/** The torso is in the shade of the arm: the skin ramp shifted dark. */
const SHADOW_SKIN = [RAMPS.skin[0], RAMPS.skin[0], RAMPS.skin[1], RAMPS.skin[1], RAMPS.skin[2]] as const;
const DELTOID = blobD([
  [-150, -200],
  [-140, -280],
  [-60, -310],
  [30, -270],
  [60, -170],
  [10, -120],
  [-90, -130],
]);

/** Forearm, hand and dumbbell in forearm space: u along the forearm from the elbow, v across (front = -v). */
const FOREARM = blobD([
  [-40, -62],
  [50, -80],
  [150, -66],
  [255, -50],
  [265, 0],
  [255, 48],
  [140, 62],
  [30, 70],
  [-45, 52],
]);
const FIST = blobD([
  [250, -58],
  [318, -64],
  [352, -30],
  [356, 28],
  [322, 62],
  [258, 54],
  [238, 0],
]);

const Dumbbell = ({ light }: { light: V2 }) => (
  <>
    <Shade d={`M318 -175h24v350h-24z`} c={[330, 0]} size={40} ramp={RAMPS.steel} light={light} spec={false} />
    {[-1, 1].map((s) => (
      <g key={s}>
        <Shade d={`M${330 - 92} ${s * 112}h184v${s * 34}h-184z`} c={[330, s * 129]} size={120} ramp={RAMPS.steel} light={light} />
        <Shade d={`M${330 - 70} ${s * 148}h140v${s * 26}h-140z`} c={[330, s * 161]} size={90} ramp={RAMPS.steel} light={light} />
      </g>
    ))}
  </>
);

/** The forearm group at curl angle `a`, in world space. */
const Forearm = ({ a, opacity = 1 }: { a: number; opacity?: number }) => {
  const phi = Math.atan2(Math.cos(a), Math.sin(a));
  // The sun stays in world space: turn it into forearm space.
  const light: V2 = [LIGHT[0] * Math.cos(phi) + LIGHT[1] * Math.sin(phi), -LIGHT[0] * Math.sin(phi) + LIGHT[1] * Math.cos(phi)];
  return (
    <g transform={`translate(${E[0]} ${E[1]}) rotate(${(phi * 180) / Math.PI})`} opacity={opacity}>
      <Shade d={FOREARM} c={[110, 0]} size={160} axis={0} ramp={RAMPS.skin} light={light}>
        {/* The brachioradialis ridge along the top of the forearm. */}
        <path d="M20 -50Q110 -64 210 -36" fill="none" stroke={RAMPS.skin[3]} strokeWidth={10} />
        <path d="M30 30Q120 44 220 30" fill="none" stroke={RAMPS.skin[1]} strokeWidth={8} />
      </Shade>
      <Dumbbell light={light} />
      <Shade d={FIST} c={[300, 0]} size={110} ramp={RAMPS.skin} light={light}>
        {[-34, -6, 22].map((v) => (
          <path key={v} d={`M${340} ${v}h18`} stroke={RAMPS.skin[1]} strokeWidth={6} />
        ))}
      </Shade>
      <Shade d={blobD([[250, -60], [300, -86], [334, -70], [300, -40]])} c={[295, -64]} size={50} ramp={RAMPS.skin} light={light} spec={false} />
    </g>
  );
};

const Draw = ({ phase, rate, f }: ViewState) => {
  const { c, a, win } = geometry(phase);
  // Smear: where the forearm was a moment ago, fading, when it swings fast.
  const swing = Math.abs(Math.sin(2 * Math.PI * (phase + START))) * rate;
  const trail = swing > 0.25 ? [0.025, 0.05] : [];
  const fibres = [-0.62, -0.32, 0, 0.32, 0.62];
  return (
    <g>
      <Shade d={torso} c={[-330, 40]} size={380} ramp={SHADOW_SKIN} spec={false} rim={null} />
      {trail.map((dp, i) => (
        <Forearm key={dp} a={geometry(phase - dp).a} opacity={0.22 - 0.1 * i} />
      ))}
      <Shade d={upperArm(c)} c={[-35, 10]} size={240} axis={83} ramp={RAMPS.skin}>
        {/* The cut: skin edge, the yellow fat layer, then the biceps inside. */}
        <path d={ellipseD(win.cx, win.cy, win.rx + 14, win.ry + 14)} fill={RAMPS.skin[0]} />
        <path d={ellipseD(win.cx, win.cy, win.rx + 8, win.ry + 8)} fill={RAMPS.fat[3]} />
        <Shade d={ellipseD(win.cx, win.cy, win.rx, win.ry)} c={[win.cx, win.cy]} size={win.rx * 2} ramp={RAMPS.muscle} rim="#FF9B6A">
          {fibres.map((k) => {
            const x = win.cx + k * win.rx;
            const h = win.ry * Math.sqrt(1 - k * k);
            return (
              <g key={k}>
                <path d={`M${x} ${win.cy - h}Q${x + 10 * c + 6} ${win.cy} ${x} ${win.cy + h}`} fill="none" stroke={RAMPS.muscle[0]} strokeWidth={7} />
                <path d={`M${x + 9} ${win.cy - h * 0.9}Q${x + 10 * c + 15} ${win.cy} ${x + 9} ${win.cy + h * 0.9}`} fill="none" stroke={RAMPS.muscle[3]} strokeWidth={4} opacity={0.8} />
              </g>
            );
          })}
          <Sparkles cx={win.cx} cy={win.cy} rx={win.rx * 0.8} ry={win.ry * 0.8} n={34} seed={11} f={f} on={0.15 + 0.85 * c} color={C.tealLight} size={8} />
          <Sparkles cx={win.cx} cy={win.cy} rx={win.rx * 0.7} ry={win.ry * 0.7} n={14} seed={17} f={f} on={c} color={C.sun} size={10} />
        </Shade>
        {/* The tendon from the biceps down across the elbow crease. */}
        <Shade d={blobD([[win.cx - 18, win.cy + win.ry - 30], [win.cx + 20, win.cy + win.ry - 26], [34, 232], [10, 240]])} c={[win.cx, win.cy + win.ry + 20]} size={50} ramp={RAMPS.tendon} spec={false} />
        {/* Triceps line on the back of the arm. */}
        <path d="M-150 -120Q-175 40 -110 170" fill="none" stroke={RAMPS.skin[1]} strokeWidth={10} />
      </Shade>
      <Shade d={DELTOID} c={[-50, -215]} size={200} ramp={RAMPS.skin}>
        <path d="M-120 -160Q-40 -110 40 -150" fill="none" stroke={RAMPS.skin[1]} strokeWidth={8} />
      </Shade>
      <Forearm a={a} />
    </g>
  );
};

export const arm: View<"arm"> = {
  Draw,
  anchors: ({ phase }) => {
    const g = geometry(phase);
    return {
      biceps: [g.win.cx + g.win.rx * 0.5, g.win.cy - g.win.ry * 0.25],
      triceps: [-150, 20],
      tendon: [g.win.cx, g.win.cy + g.win.ry + 10],
      os: [-60, -40],
      coude: [-70, 230],
      haltere: add(g.wrist, g.dir, 60),
      avantbras: add(E, g.dir, FORE / 2),
    };
  },
};

