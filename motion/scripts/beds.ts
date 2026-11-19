// Studio beds (step 148): three composed, mixed and mastered music beds for the Cutaway style,
// built by make-assets.ts like every other sound (no samples, no downloaded music).
//
// Each bed: 2 intro bars, then an 8-bar body that loops seamlessly (the asset's loopStart_s in
// src/assets.ts = the intro length; components/MusicBed.tsx plays the intro once, then loops the
// body). Stereo, 32 kHz, 16-bit: a bar is a whole number of 30 fps frames and of samples, so
// Remotion's loop lands on the sample.
//
// How the loop stays seamless: the song renders intro + body + body in one pass (reverb, echo
// and compressor run through), the file keeps the intro and the SECOND body, whose start already
// carries the tails of a body end. The intro's last 30 ms fade into the first body's last 30 ms,
// so both joins (intro -> body, body end -> body start) continue the same waveform.
//
// Deterministic: plain arithmetic only (no Math.sin / exp / random / **): test/assets-licenses
// checks the committed WAVs still match this script byte for byte.

export const SR = 32000;
const TAU = 6.283185307179586;

// --- Maths ---------------------------------------------------------------------------------

/** sin(2πx), Taylor series on a quarter wave (error < 1e-9). */
export const sin2pi = (x: number): number => {
  let t = x - Math.floor(x);
  let s = 1;
  if (t >= 0.5) {
    t -= 0.5;
    s = -1;
  }
  if (t > 0.25) t = 0.5 - t;
  const a = t * TAU;
  const a2 = a * a;
  return s * a * (1 - (a2 / 6) * (1 - (a2 / 20) * (1 - (a2 / 42) * (1 - (a2 / 72) * (1 - (a2 / 110) * (1 - a2 / 156))))));
};

/** e^x: halve into |x| ≤ 0.5, Taylor, square back. */
export const exp = (x: number): number => {
  let n = 0;
  while (x > 0.5 || x < -0.5) {
    x /= 2;
    n++;
  }
  let r = 1 + x * (1 + (x / 2) * (1 + (x / 3) * (1 + (x / 4) * (1 + (x / 5) * (1 + (x / 6) * (1 + (x / 7) * (1 + x / 8)))))));
  while (n--) r *= r;
  return r;
};

const db = (d: number) => exp(d * 0.11512925464970229); // 10^(d/20)
/** Per-sample factor that decays to 1/e in `s` seconds. */
const decay = (s: number) => exp(-1 / (s * SR));
const tanpi = (x: number) => sin2pi(x / 2) / sin2pi(x / 2 + 0.25);
/** Soft saturation, tanh-like, unity slope at 0, ±1 beyond ±3. */
const soft = (x: number) => (x >= 3 ? 1 : x <= -3 ? -1 : (x * (27 + x * x)) / (27 + 9 * x * x));
const smooth = (x: number) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));
const frac = (x: number) => x - Math.floor(x);

/** Seeded white noise in [-1, 1) (xorshift32). */
const noise = (seed: number) => {
  let s = (seed >>> 0) || 1;
  return () => {
    s ^= s << 13;
    s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5;
    s >>>= 0;
    return s / 2147483648 - 1;
  };
};

const NOTE: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
/** "C5", "F#3" → Hz (A4 = 440), rounded to 0.01 Hz. */
export const hz = (note: string): number => {
  const m = /^([A-G])(#?)(\d)$/.exec(note);
  if (!m) throw new Error(`bad note ${note}`);
  const midi = 12 * (Number(m[3]) + 1) + NOTE[m[1]] + (m[2] ? 1 : 0);
  return Math.round(440 * exp(((midi - 69) / 12) * 0.6931471805599453) * 100) / 100;
};

// --- Filters -------------------------------------------------------------------------------

/** Zavalishin's TPT state-variable filter: lp() returns low-pass and sets .bp / .hp. */
class Svf {
  ic1 = 0;
  ic2 = 0;
  a1 = 0;
  a2 = 0;
  a3 = 0;
  k = 1;
  bp = 0;
  hp = 0;
  constructor(fc: number, q = 0.707) {
    this.set(fc, q);
  }
  set(fc: number, q = 0.707) {
    const g = tanpi(Math.min(fc, SR * 0.45) / SR);
    this.k = 1 / q;
    this.a1 = 1 / (1 + g * (g + this.k));
    this.a2 = g * this.a1;
    this.a3 = g * this.a2;
  }
  lp(x: number) {
    const v3 = x - this.ic2;
    const v1 = this.a1 * this.ic1 + this.a2 * v3;
    const v2 = this.ic2 + this.a2 * this.ic1 + this.a3 * v3;
    this.ic1 = 2 * v1 - this.ic1;
    this.ic2 = 2 * v2 - this.ic2;
    this.bp = v1;
    this.hp = x - this.k * v1 - v2;
    return v2;
  }
}

/** One-pole TPT low-pass (hp = x - lp). */
class OnePole {
  s = 0;
  G: number;
  constructor(fc: number) {
    const g = tanpi(fc / SR);
    this.G = g / (1 + g);
  }
  lp(x: number) {
    const v = (x - this.s) * this.G;
    const y = v + this.s;
    this.s = y + v;
    return y;
  }
}

// --- Oscillators ---------------------------------------------------------------------------

const blep = (t: number, dt: number) => {
  if (t < dt) {
    t /= dt;
    return t + t - t * t - 1;
  }
  if (t > 1 - dt) {
    t = (t - 1) / dt;
    return t * t + t + t + 1;
  }
  return 0;
};
/** Band-limited saw / pulse (polyBLEP): no aliasing fizz. */
const saw = (t: number, dt: number) => 2 * t - 1 - blep(t, dt);
const pulse = (t: number, dt: number, duty: number) => saw(t, dt) - saw(frac(t + 1 - duty), dt);
const tri = (t: number) => 1 - 4 * Math.abs(t - 0.5);
const cents = (c: number) => exp(c * 0.0005776226504666211);

// --- Instruments ---------------------------------------------------------------------------
// Each returns the note as a mono buffer (or [L, R]) from its start, release tail included.
// `gate` = held samples, `vel` 0..1, `at` = the note's start in song samples (for song-clock LFOs).

type Out = Float64Array | [Float64Array, Float64Array];
/** Song-clock pitch drift (tape wow), as a ratio offset. */
type Drift = (at: number) => number;
const still: Drift = () => 0;

/** FM electric piano (DX-style tine): bright on the hit, mellow as it rings. */
const keys = (f: number, gate: number, vel: number, at: number, drift: Drift = still): Out => {
  const n = gate + Math.round(0.3 * SR);
  const out = new Float64Array(n);
  const kA = decay(1.6);
  const kM = decay(0.28);
  const kR = decay(0.07);
  let a = 1;
  let m = 1;
  let ph = 0;
  for (let i = 0; i < n; i++) {
    ph += (f * (1 + drift(at + i))) / SR;
    const idx = 0.2 + 1.3 * m * vel;
    const att = Math.min(1, i / (0.004 * SR));
    out[i] = att * a * (sin2pi(ph + (idx * sin2pi(ph)) / TAU) + 0.18 * m * sin2pi(ph * 7));
    a *= i >= gate ? kA * kR : kA;
    m *= kM;
  }
  return out;
};

/** Warm chip pulse lead: 25 % pulse low-passed at 2.4 kHz, delayed vibrato. */
const chip = (f: number, gate: number, at: number, drift: Drift = still): Out => {
  const n = gate + Math.round(0.2 * SR);
  const out = new Float64Array(n);
  const lp = new Svf(2400, 0.75);
  const lp2 = new Svf(3200, 0.6);
  const kS = decay(3);
  const kR = decay(0.05);
  let a = 1;
  let ph = 0;
  const dt = f / SR;
  for (let i = 0; i < n; i++) {
    const v = i > 0.15 * SR ? 0.0045 * sin2pi((i * 5.2) / SR) * smooth((i - 0.15 * SR) / (0.25 * SR)) : 0;
    ph = frac(ph + dt * (1 + v + drift(at + i)));
    const x = 0.7 * pulse(ph, dt, 0.25) + 0.3 * tri(ph);
    out[i] = lp2.lp(lp.lp(x)) * a * Math.min(1, i / (0.008 * SR));
    a *= i >= gate ? kS * kR : kS;
  }
  return out;
};

/** Round bass: sine, a little triangle and saturation for phone speakers. */
const roundBass = (f: number, gate: number): Out => {
  const n = gate + Math.round(0.08 * SR);
  const out = new Float64Array(n);
  const kD = decay(1.4);
  const kR = decay(0.025);
  let a = 1;
  let ph = 0;
  for (let i = 0; i < n; i++) {
    ph += f / SR;
    const x = sin2pi(ph) + 0.22 * tri(frac(ph));
    out[i] = (soft(2.2 * x) / 2.2) * a * Math.min(1, i / (0.006 * SR));
    a *= i >= gate ? kD * kR : kD;
  }
  return out;
};

/** Kick: falling sine thump and a short click. */
const kick = (low: number, punch: number, length: number, seed: number): Out => {
  const n = Math.round(length * 1.6 * SR);
  const out = new Float64Array(n);
  const kP = decay(0.032);
  const kA = decay(length / 3);
  const kC = decay(0.0018);
  const rnd = noise(seed);
  let p = 1;
  let a = 1;
  let c = 1;
  let ph = 0;
  for (let i = 0; i < n; i++) {
    ph += (low + punch * p) / SR;
    out[i] = soft(1.6 * (sin2pi(ph) * a + 0.25 * rnd() * c)) / 1.3;
    p *= kP;
    a *= kA;
    c *= kC;
  }
  return out;
};

/** Snare: tuned body and band-passed noise; `lo` darkens it (lo-fi). */
const snare = (seed: number, bright: number, length = 0.14): Out => {
  const n = Math.round(length * 3 * SR);
  const out = new Float64Array(n);
  const rnd = noise(seed);
  const bp = new Svf(1900 * bright, 0.6);
  const kT = decay(0.055);
  const kN = decay(length);
  let t = 1;
  let a = 1;
  let ph = 0;
  for (let i = 0; i < n; i++) {
    ph += (180 + 40 * t) / SR;
    bp.lp(rnd());
    out[i] = 0.55 * sin2pi(ph) * t + 1.1 * (bp.bp + 0.35 * bp.hp) * a;
    t *= kT;
    a *= kN;
  }
  return out;
};

/** Hand clap: three quick bursts then a tail. */
const clap = (seed: number): Out => {
  const n = Math.round(0.5 * SR);
  const out = new Float64Array(n);
  const rnd = noise(seed);
  const bp = new Svf(1400, 1.1);
  const kN = decay(0.16);
  let a = 1;
  for (let i = 0; i < n; i++) {
    const ms = (i / SR) * 1000;
    const burst = ms < 30 ? (ms % 10 < 1.5 ? 1 : 1 - (ms % 10) / 10) : a;
    bp.lp(rnd());
    out[i] = 1.6 * bp.bp * burst;
    if (ms >= 30) a *= kN;
  }
  return out;
};

/** Hi-hat: high-passed noise, closed (short) or open. */
const hat = (seed: number, length: number, fc = 7000): Out => {
  const n = Math.round(length * 5 * SR);
  const out = new Float64Array(n);
  const rnd = noise(seed);
  const f = new Svf(fc, 0.7);
  const k = decay(length);
  let a = 1;
  for (let i = 0; i < n; i++) {
    f.lp(rnd());
    out[i] = f.hp * a;
    a *= k;
  }
  return out;
};

/** Supersaw pad: three detuned saws a side, low-passed (cutoff on the song clock), slow swell. */
const pad = (f: number, gate: number, vel: number, at: number, cut: (at: number) => number, attack = 0.35): Out => {
  const n = gate + Math.round(0.8 * SR);
  const L = new Float64Array(n);
  const R = new Float64Array(n);
  const tunes = [[-11, 0, 7].map(cents), [-6, 3, 12].map(cents)];
  const ph = [0.13, 0.57, 0.81, 0.29, 0.66, 0.02];
  const flt = [new Svf(1000, 0.8), new Svf(1000, 0.8)];
  const kR = decay(0.28);
  let a = 1;
  for (let i = 0; i < n; i++) {
    if (i % 32 === 0) for (const s of flt) s.set(cut(at + i), 0.8);
    const sw = smooth(i / (attack * SR));
    for (let side = 0; side < 2; side++) {
      let x = 0;
      for (let o = 0; o < 3; o++) {
        const dt = (f * tunes[side][o]) / SR;
        const j = side * 3 + o;
        ph[j] = frac(ph[j] + dt);
        x += saw(ph[j], dt);
      }
      (side ? R : L)[i] = flt[side].lp(x / 3) * sw * a * vel;
    }
    if (i >= gate) a *= kR;
  }
  return [L, R];
};

/** Plucked synth (arpeggio): saw + square through a snappy filter envelope. */
const pluck = (f: number, gate: number, vel: number, base = 350, sweep = 2600): Out => {
  const n = gate + Math.round(0.25 * SR);
  const out = new Float64Array(n);
  const flt = new Svf(1000, 1.3);
  const kE = decay(0.09);
  const kA = decay(0.32);
  const kR = decay(0.05);
  let e = 1;
  let a = 1;
  let p1 = 0;
  let p2 = 0.5;
  const dt = f / SR;
  for (let i = 0; i < n; i++) {
    if (i % 16 === 0) flt.set(base + sweep * e * (0.6 + 0.4 * vel), 1.3);
    p1 = frac(p1 + dt);
    p2 = frac(p2 + dt * 1.003);
    out[i] = flt.lp(0.6 * saw(p1, dt) + 0.4 * pulse(p2, dt, 0.5)) * a * Math.min(1, i / (0.002 * SR)) * vel;
    e *= kE;
    a *= i >= gate ? kA * kR : kA;
  }
  return out;
};

/** Synth bass: saw + sine sub, filter blip on each note; `open` (0..1) brightens it. */
const synthBass = (f: number, gate: number, vel: number, open = 0.4): Out => {
  const n = gate + Math.round(0.06 * SR);
  const out = new Float64Array(n);
  const flt = new Svf(500, 1.1);
  const kE = decay(0.07);
  const kR = decay(0.02);
  let e = 1;
  let a = 1;
  let p = 0;
  const dt = f / SR;
  for (let i = 0; i < n; i++) {
    if (i % 16 === 0) flt.set(160 + (500 + 1400 * open) * e, 1.1);
    p = frac(p + dt);
    out[i] = (flt.lp(saw(p, dt)) * 0.75 + 0.55 * sin2pi(p)) * a * Math.min(1, i / (0.003 * SR)) * vel;
    e *= kE;
    if (i >= gate) a *= kR;
  }
  return out;
};

/** Soft saw lead: two detuned saws, gentle filter, delayed vibrato, legato-ish attack. */
const lead = (f: number, gate: number, vel: number): Out => {
  const n = gate + Math.round(0.4 * SR);
  const out = new Float64Array(n);
  const flt = new Svf(2300, 0.7);
  const flt2 = new Svf(3800, 0.6);
  const kR = decay(0.16);
  let a = 1;
  let p1 = 0;
  let p2 = 0.37;
  const d1 = cents(-6);
  const d2 = cents(6);
  for (let i = 0; i < n; i++) {
    const v = 1 + (i > 0.2 * SR ? 0.0038 * sin2pi((i * 5.4) / SR) * smooth((i - 0.2 * SR) / (0.3 * SR)) : 0);
    const dt1 = (f * d1 * v) / SR;
    const dt2 = (f * d2 * v) / SR;
    p1 = frac(p1 + dt1);
    p2 = frac(p2 + dt2);
    out[i] = flt2.lp(flt.lp(0.5 * saw(p1, dt1) + 0.5 * saw(p2, dt2))) * a * smooth(i / (0.03 * SR)) * vel;
    if (i >= gate) a *= kR;
  }
  return out;
};

/** Music-box / celesta bell (FM, inharmonic 3.5 ratio). */
const bell = (f: number, gate: number, vel: number): Out => {
  const n = gate + Math.round(1.4 * SR);
  const out = new Float64Array(n);
  const kA = decay(1.1);
  const kM = decay(0.35);
  const kR = decay(0.5);
  let a = 1;
  let m = 1;
  let pc = 0;
  let pm = 0;
  for (let i = 0; i < n; i++) {
    pc += f / SR;
    pm += (f * 3.5) / SR;
    out[i] = (sin2pi(pc + (1.6 * m * vel * sin2pi(pm)) / TAU) + 0.25 * sin2pi(pc * 2) * m) * a * Math.min(1, i / (0.001 * SR)) * vel;
    a *= i >= gate ? kA * kR : kA;
    m *= kM;
  }
  return out;
};

/** Staccato string-section ostinato voice: detuned saws, filter `fc`. */
const bowed = (f: number, gate: number, vel: number, fc: number): Out => {
  const n = gate + Math.round(0.12 * SR);
  const out = new Float64Array(n);
  const flt = new Svf(fc, 0.9);
  const kD = decay(0.18);
  const kR = decay(0.035);
  let a = 1;
  let p1 = 0.2;
  let p2 = 0.7;
  const dt1 = (f * cents(-5)) / SR;
  const dt2 = (f * cents(5)) / SR;
  for (let i = 0; i < n; i++) {
    p1 = frac(p1 + dt1);
    p2 = frac(p2 + dt2);
    out[i] = flt.lp(saw(p1, dt1) + saw(p2, dt2)) * 0.5 * (0.4 + 0.6 * a) * Math.min(1, i / (0.005 * SR)) * vel;
    a *= kD;
    if (i >= gate) a *= kR * kR;
  }
  return out;
};

/** Clockwork tick (wood + metal click) at pitch `f`. */
const tick = (f: number, seed: number): Out => {
  const n = Math.round(0.09 * SR);
  const out = new Float64Array(n);
  const rnd = noise(seed);
  const bp = new Svf(f * 2.3, 3);
  const kT = decay(0.016);
  const kN = decay(0.003);
  let t = 1;
  let c = 1;
  let ph = 0;
  for (let i = 0; i < n; i++) {
    ph += f / SR;
    bp.lp(rnd());
    out[i] = sin2pi(ph) * t * 0.7 + bp.bp * c * 1.2;
    t *= kT;
    c *= kN;
  }
  return out;
};

/** The "BANG": sub drop, noise burst and a metallic clang (inharmonic partials). */
const impact = (seed: number): Out => {
  const n = Math.round(2.6 * SR);
  const out = new Float64Array(n);
  const rnd = noise(seed);
  const lp = new Svf(1100, 0.7);
  const partials = [311, 743, 1187, 1663, 2391];
  const amps = [0.16, 0.1, 0.07, 0.05, 0.03];
  const kP = decay(0.12);
  const kA = decay(0.75);
  const kN = decay(0.2);
  const kM = decay(0.55);
  let p = 1;
  let a = 1;
  let nz = 1;
  let mt = 1;
  let ph = 0;
  for (let i = 0; i < n; i++) {
    ph += (30 + 46 * p) / SR;
    let metal = 0;
    for (let k = 0; k < partials.length; k++) metal += amps[k] * sin2pi((i * partials[k]) / SR);
    out[i] = soft(1.4 * (sin2pi(ph) * a + 0.55 * lp.lp(rnd()) * nz + metal * mt)) / 1.2;
    p *= kP;
    a *= kA;
    nz *= kN;
    mt *= kM;
  }
  return out;
};

/** Low drum (taiko-ish tom). */
const tom = (f: number, seed: number): Out => {
  const n = Math.round(0.7 * SR);
  const out = new Float64Array(n);
  const rnd = noise(seed);
  const lp = new Svf(700, 0.7);
  const kP = decay(0.08);
  const kA = decay(0.22);
  const kN = decay(0.03);
  let p = 1;
  let a = 1;
  let nz = 1;
  let ph = 0;
  for (let i = 0; i < n; i++) {
    ph += (f * (1 + 0.45 * p)) / SR;
    out[i] = soft(1.3 * (sin2pi(ph) * a + 0.5 * lp.lp(rnd()) * nz)) / 1.15;
    p *= kP;
    a *= kA;
    nz *= kN;
  }
  return out;
};

/** Noise riser: a band-pass sweep that swells into the next downbeat (`n` samples long). */
const riser = (n: number, seed: number): Out => {
  const out = new Float64Array(n);
  const rnd = noise(seed);
  const bp = new Svf(300, 2);
  for (let i = 0; i < n; i++) {
    const p = i / n;
    if (i % 32 === 0) bp.set(250 + 4200 * p * p, 2);
    bp.lp(rnd());
    out[i] = bp.bp * p * p * p * 1.6;
  }
  return out;
};

/** Low drone (two saws, dark), for the clockwork intro. */
const drone = (f: number, gate: number, vel: number, at: number, cut: (at: number) => number): Out => pad(f, gate, vel, at, cut, 1.2);

// --- Song engine ---------------------------------------------------------------------------

type Send = { gain: number; pan?: number; verb?: number; echo?: number; pump?: boolean };

class Mix {
  L: Float64Array;
  R: Float64Array;
  PL: Float64Array;
  PR: Float64Array;
  verb: Float64Array;
  echo: Float64Array;
  n: number;
  constructor(n: number) {
    this.n = n;
    this.L = new Float64Array(n);
    this.R = new Float64Array(n);
    this.PL = new Float64Array(n);
    this.PR = new Float64Array(n);
    this.verb = new Float64Array(n);
    this.echo = new Float64Array(n);
  }
  /** Mixes a note in at sample `at`: constant-power pan, sends to the reverb / echo. */
  add(at: number, v: Out, s: Send) {
    const angle = ((s.pan ?? 0) + 1) / 8;
    const gl = s.gain * sin2pi(angle + 0.25) * 1.4142135623730951;
    const gr = s.gain * sin2pi(angle) * 1.4142135623730951;
    const [l, r] = Array.isArray(v) ? v : [v, v];
    const L = s.pump ? this.PL : this.L;
    const R = s.pump ? this.PR : this.R;
    const end = Math.min(l.length, this.n - at);
    for (let i = Math.max(0, -at); i < end; i++) {
      const j = at + i;
      L[j] += l[i] * gl;
      R[j] += r[i] * gr;
      const mono = (l[i] + r[i]) * 0.5 * s.gain;
      if (s.verb) this.verb[j] += mono * s.verb;
      if (s.echo) this.echo[j] += mono * s.echo;
    }
  }
}

/** Freeverb (Jezar's), comb and all-pass lengths scaled to 32 kHz; stereo from a mono send. */
const reverb = (input: Float64Array, room: number, damp: number): [Float64Array, Float64Array] => {
  const scale = SR / 44100;
  const combs = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617];
  const alls = [556, 441, 341, 225];
  const pre = Math.round(0.018 * SR);
  const hp = new OnePole(220);
  const sides = [0, 23].map((spread) => ({
    c: combs.map((c) => ({ b: new Float64Array(Math.round((c + spread) * scale)), i: 0, f: 0 })),
    a: alls.map((a) => ({ b: new Float64Array(Math.round((a + spread) * scale)), i: 0 })),
  }));
  const out: [Float64Array, Float64Array] = [new Float64Array(input.length), new Float64Array(input.length)];
  for (let n = 0; n < input.length; n++) {
    const raw = n >= pre ? input[n - pre] : 0;
    const x = (raw - hp.lp(raw)) * 0.015;
    sides.forEach((side, s) => {
      let y = 0;
      for (const c of side.c) {
        const o = c.b[c.i];
        c.f = o * (1 - damp) + c.f * damp;
        c.b[c.i] = x + c.f * room;
        c.i = (c.i + 1) % c.b.length;
        y += o;
      }
      for (const a of side.a) {
        const o = a.b[a.i];
        a.b[a.i] = y + o * 0.5;
        a.i = (a.i + 1) % a.b.length;
        y = o - y;
      }
      out[s][n] = y;
    });
  }
  return out;
};

/** Ping-pong echo, darkened in the feedback loop. */
const pingPong = (input: Float64Array, delay: number, feedback: number): [Float64Array, Float64Array] => {
  const L = new Float64Array(delay);
  const R = new Float64Array(delay);
  const lp = [new OnePole(2800), new OnePole(2800)];
  const out: [Float64Array, Float64Array] = [new Float64Array(input.length), new Float64Array(input.length)];
  for (let n = 0, i = 0; n < input.length; n++, i = (i + 1) % delay) {
    const yl = L[i];
    const yr = R[i];
    L[i] = input[n] + feedback * lp[1].lp(yr);
    R[i] = feedback * lp[0].lp(yl);
    out[0][n] = yl;
    out[1][n] = yr;
  }
  return out;
};

type Master = {
  /** Low-pass for the lo-fi colour (Hz), none = open. */
  lowpass?: number;
  /** High-shelf cut above `shelfHz` (dB, negative): no harsh highs. */
  shelfDb: number;
  shelfHz: number;
  /** Bus compressor: threshold (linear peak) and ratio. */
  threshold: number;
  ratio: number;
  /** Tape-style saturation drive (1 = off). */
  drive: number;
  /** Reverb room (0..1 feedback) and damping. */
  room: number;
  damp: number;
  /** Echo time in 16th steps and feedback. */
  echoSteps: number;
  echoFeedback: number;
  /** Sidechain pump depth on the `pump` bus (0 = none), one dip per beat. */
  pump: number;
};

/** One bar of the song: write notes into `mix` from sample `t0`. */
type Play = (mix: Mix, part: "intro" | "body", bar: number, t0: number, song: Song) => void;

export type Song = {
  /** Frames (30 fps) per 4/4 bar: bpm = 7200 / barFrames, and a bar is whole samples. */
  barFrames: number;
  introBars: number;
  bodyBars: number;
  master: Master;
  play: Play;
  /** Final RMS level (dBFS, both channels). */
  rmsDb: number;
};

export const barSamples = (s: Song) => (s.barFrames * SR) / 30;
const step16 = (s: Song) => barSamples(s) / 16;

/** Renders the song: [L, R] = intro + one body, the body looping seamlessly onto itself. */
export const renderSong = (song: Song): [Float64Array, Float64Array] => {
  const bar = barSamples(song);
  const intro = song.introBars * bar;
  const body = song.bodyBars * bar;
  const mix = new Mix(intro + 2 * body);
  for (let b = 0; b < song.introBars + 2 * song.bodyBars; b++) {
    const inIntro = b < song.introBars;
    song.play(mix, inIntro ? "intro" : "body", inIntro ? b : (b - song.introBars) % song.bodyBars, b * bar, song);
  }
  const m = song.master;
  const beat = bar / 4;
  const [vl, vr] = reverb(mix.verb, m.room, m.damp);
  const [el, er] = pingPong(mix.echo, Math.round(m.echoSteps * step16(song)), m.echoFeedback);
  const chans = [mix.L, mix.R];
  const filters = chans.map(() => ({
    hp1: new OnePole(32),
    hp2: new OnePole(32),
    shelf: new OnePole(m.shelfHz),
    lp1: new OnePole(m.lowpass ?? 15000),
    lp2: new OnePole(m.lowpass ?? 15000),
  }));
  const shelf = db(m.shelfDb) - 1;
  const atk = decay(0.008);
  const rel = decay(0.18);
  let env = 0;
  for (let i = 0; i < mix.n; i++) {
    // Sidechain pump: a dip on every beat that swells back over half a beat.
    const pump = 1 - m.pump * (1 - smooth(frac(i / beat) / 0.5));
    const xs = [mix.L[i] + mix.PL[i] * pump + vl[i] + el[i], mix.R[i] + mix.PR[i] * pump + vr[i] + er[i]];
    for (let c = 0; c < 2; c++) {
      const f = filters[c];
      let x = xs[c];
      x -= f.hp1.lp(x);
      x -= f.hp2.lp(x);
      x += shelf * (x - f.shelf.lp(x));
      if (m.lowpass) x = f.lp2.lp(f.lp1.lp(x));
      xs[c] = x;
    }
    // Linked bus compressor (gentle, linear-domain ratio), then saturation.
    const level = Math.max(Math.abs(xs[0]), Math.abs(xs[1]));
    env = level > env ? level + (env - level) * atk : level + (env - level) * rel;
    const g = env > m.threshold ? (m.threshold + (env - m.threshold) / m.ratio) / env : 1;
    chans[0][i] = soft(xs[0] * g * m.drive) / m.drive;
    chans[1][i] = soft(xs[1] * g * m.drive) / m.drive;
  }
  // Level: the loop body at rmsDb, then a soft limiter keeps peaks under -1 dBFS.
  let sum = 0;
  for (let i = intro + body; i < mix.n; i++) sum += mix.L[i] * mix.L[i] + mix.R[i] * mix.R[i];
  const gain = db(song.rmsDb) / Math.sqrt(sum / (2 * body));
  const KNEE = 0.6;
  const limit = (x: number) => {
    const a = Math.abs(x * gain);
    const y = a <= KNEE ? a : KNEE + 0.29 * soft((a - KNEE) / 0.29);
    return x < 0 ? -y : y;
  };
  // Keep the intro and the second body; the intro's end fades into the first body's end.
  const X = Math.round(0.03 * SR);
  return chans.map((ch) => {
    const out = new Float64Array(intro + body);
    for (let i = 0; i < intro; i++) out[i] = ch[i];
    for (let k = 0; k < X; k++) {
      const w = smooth((k + 1) / X);
      const i = intro - X + k;
      out[i] = (1 - w) * ch[i] + w * ch[intro + body - X + k];
    }
    for (let i = 0; i < body; i++) out[intro + i] = ch[intro + body + i];
    return out.map(limit);
  }) as [Float64Array, Float64Array];
};

/** 16-bit stereo PCM WAV at SR. */
export const wavStereo = ([L, R]: [Float64Array, Float64Array]): Buffer => {
  const n = L.length;
  const out = Buffer.alloc(44 + n * 4);
  out.write("RIFF", 0);
  out.writeUInt32LE(36 + n * 4, 4);
  out.write("WAVEfmt ", 8);
  out.writeUInt32LE(16, 16);
  out.writeUInt16LE(1, 20);
  out.writeUInt16LE(2, 22);
  out.writeUInt32LE(SR, 24);
  out.writeUInt32LE(SR * 4, 28);
  out.writeUInt16LE(4, 32);
  out.writeUInt16LE(16, 34);
  out.write("data", 36);
  out.writeUInt32LE(n * 4, 40);
  const q = (v: number) => Math.round(Math.max(-1, Math.min(1, v)) * 32767);
  for (let i = 0; i < n; i++) {
    out.writeInt16LE(q(L[i]), 44 + i * 4);
    out.writeInt16LE(q(R[i]), 46 + i * 4);
  }
  return out;
};

// --- Score helpers -------------------------------------------------------------------------

/**
 * A pattern string, one token per 16th: a note ("E5") or a hit ("x" accent, "o" ghost) starts,
 * "-" holds it, "." rests. Calls `on(step, token, lengthInSteps)` for each start.
 */
const each = (pattern: string, on: (step: number, tok: string, len: number) => void) => {
  const t = pattern.trim().split(/\s+/);
  if (t.length !== 16) throw new Error(`a bar has 16 steps, got ${t.length}: ${pattern}`);
  t.forEach((tok, i) => {
    if (tok === "-" || tok === ".") return;
    let len = 1;
    while (t[i + len] === "-") len++;
    on(i, tok, len);
  });
};
const hit = (tok: string) => (tok === "o" ? 0.4 : 1);

// --- (a) Lo-fi chiptune hip-hop, F major, 85.7 bpm, swung 16ths, vinyl ----------------------
// Bbmaj9 Am7 Gm9 C7sus-C9 | Bbmaj9 Am7 Dm9 C7sus-C9: FM keys, a warm pulse lead singing the
// tune, round bass, boom-bap drums with swing, tape wow and vinyl crackle.

const A_CHORDS = [
  ["D4", "F4", "A4", "C5"],
  ["G3", "C4", "E4", "A4"],
  ["A#3", "D4", "F4", "A4"],
  ["A#3", "C4", "F4", "G4"],
  ["D4", "F4", "A4", "C5"],
  ["G3", "C4", "E4", "A4"],
  ["C4", "E4", "F4", "A4"],
  ["A#3", "C4", "F4", "G4"],
];
const A_C9 = ["A#3", "D4", "E4", "G4"];
const A_BASS = [
  "A#1 - - - - - - - - - A#1 - - - F2 -",
  "A1 - - - - - - - - - A1 - - - E2 -",
  "G1 - - - - - - - - - G1 - - - D2 -",
  "C2 - - - - - - - - - C2 - - - E2 -",
  "A#1 - - - - - - - - - A#1 - - - F2 -",
  "A1 - - - - - - - - - A1 - - - C2 -",
  "D2 - - - - - - - - - D2 - - - A1 -",
  "C2 - - - - - - - - - C2 - - - E2 -",
];
const A_TUNE = [
  ". . D5 - F5 - A5 - - - G5 - F5 - - -",
  "E5 - - - . . . . C5 - D5 - E5 - G5 -",
  "A5 - - - - - G5 - F5 - - - D5 - - -",
  "F5 - - - - - - - . . . . . . . .",
  ". . D5 - F5 - A5 - - - C6 - A5 - - -",
  "G5 - - - E5 - - - C5 - D5 - E5 - - -",
  "F5 - E5 - D5 - - - A4 - C5 - D5 - - -",
  "E5 - - - - - - - G5 - - - - - . .",
];
const A_KICK = ["x . . . . . . x . . x . . . . .", "x . . x . . . . . . x . . . o ."];
const A_SNARE = [". . . . x . . . . . . . x . . .", ". . . . x . . . . . . . x . . o"];
const A_HAT = "x . o . x . o . x . o . x . o x";

const lofi: Song = {
  barFrames: 84,
  introBars: 2,
  bodyBars: 8,
  rmsDb: -19,
  master: { lowpass: 10000, shelfDb: -3, shelfHz: 4500, threshold: 0.3, ratio: 2.5, drive: 1.6, room: 0.8, damp: 0.4, echoSteps: 3, echoFeedback: 0.3, pump: 0 },
  play: (mix, part, bar, t0, song) => {
    const step = step16(song);
    const swing = Math.round(0.17 * step);
    const at = (s: number) => t0 + s * step + (s % 2 ? swing : 0);
    const barN = barSamples(song);
    // Tape wow: one slow sway per 2 bars plus a faster flutter (both loop-synced).
    const drift: Drift = (x) => 0.0022 * sin2pi(x / (2 * barN)) + 0.0006 * sin2pi((x * 4) / barN);
    const chord = A_CHORDS[bar];
    const stab = (s: number, len: number, notes: string[], vel: number) =>
      notes.forEach((nt, k) => mix.add(at(s), keys(hz(nt), len * step, vel, at(s), drift), { gain: 0.085, pan: k % 2 ? 0.25 : -0.25, verb: 0.35 }));
    const sus = bar === 3 || bar === 7;
    if (part === "intro") {
      stab(0, 9, chord, 0.55);
      stab(10, 6, chord, 0.4);
      if (bar === 1) {
        each(A_BASS[1], (s, n, len) => mix.add(at(s), roundBass(hz(n), len * step - 300), { gain: 0.32 }));
        each(". . . . . . . . . . . . x o x x", (s, tok) => mix.add(at(s), snare(500 + s, 0.75), { gain: 0.16 * hit(tok) * (0.5 + s / 30), verb: 0.2 }));
        each(". . . . . . . . x . o . x . o x", (s, tok) => mix.add(at(s), hat(700 + s, 0.03, 6000), { gain: 0.25 * hit(tok), pan: 0.3 }));
      }
      return;
    }
    stab(0, 9, chord, 0.72);
    stab(10, 6, sus ? A_C9 : chord, 0.55);
    each(A_BASS[bar], (s, n, len) => mix.add(at(s), roundBass(hz(n), len * step - 300), { gain: 0.3 }));
    each(A_TUNE[bar], (s, n, len) => mix.add(at(s), chip(hz(n), len * step, at(s), drift), { gain: 0.15, pan: 0.05, verb: 0.3, echo: 0.22 }));
    // A second voice an octave down in the second half: the tune grows.
    if (bar >= 4) each(A_TUNE[bar], (s, n, len) => mix.add(at(s), chip(hz(n) / 2, len * step, at(s), drift), { gain: 0.06, pan: -0.3, verb: 0.2 }));
    each(A_KICK[bar % 2], (s, tok) => mix.add(at(s), kick(46, 85, 0.42, 1), { gain: 0.62 * hit(tok) }));
    each(A_SNARE[bar % 4 === 3 ? 1 : 0], (s, tok) => mix.add(at(s), snare(100 + bar * 16 + s, 0.75), { gain: 0.45 * hit(tok), verb: 0.18 }));
    each(A_HAT, (s, tok) => mix.add(at(s), hat(200 + bar * 16 + s, 0.03, 6000), { gain: 0.3 * hit(tok), pan: 0.3 }));
  },
};

// --- (b) Dusk synthwave, D minor, 100 bpm --------------------------------------------------
// Dm Bb F C | Dm Bb Gm A: supersaw pads and an octave bass pumping on the kick, a 16th
// arpeggio through a dotted-8th ping-pong echo, a soft saw lead with the tune, gated clap.

const B_PAD = [
  ["D3", "A3", "D4", "F4"],
  ["F3", "A#3", "D4", "F4"],
  ["F3", "A3", "C4", "F4"],
  ["E3", "G3", "C4", "E4"],
  ["D3", "A3", "D4", "F4"],
  ["F3", "A#3", "D4", "F4"],
  ["G3", "A#3", "D4", "G4"],
  ["E3", "A3", "C#4", "E4"],
];
const B_ARP = [
  ["D4", "F4", "A4", "D5"],
  ["A#3", "D4", "F4", "A#4"],
  ["C4", "F4", "A4", "C5"],
  ["C4", "E4", "G4", "C5"],
  ["D4", "F4", "A4", "D5"],
  ["A#3", "D4", "F4", "A#4"],
  ["G3", "A#3", "D4", "G4"],
  ["A3", "C#4", "E4", "A4"],
];
const B_ROOT = ["D2", "A#1", "F2", "C2", "D2", "A#1", "G1", "A1"];
const B_ARP_ORDER = [0, 1, 2, 3, 1, 2, 3, 2, 0, 1, 2, 3, 1, 2, 3, 2];
const B_TUNE = [
  "A4 - - - - - - - D5 - - - E5 - F5 -",
  "D5 - - - - - - - - - - - . . . .",
  "C5 - - - - - A4 - C5 - - - F5 - E5 -",
  "E5 - - - - - - - - - - - . . . .",
  "A4 - - - - - - - D5 - - - E5 - F5 -",
  "G5 - - - F5 - - - D5 - - - - - . .",
  "F5 - - - E5 - - - D5 - - - A#4 - - -",
  "C#5 - - - - - - - E5 - - - - - . .",
];

const octave = (n: string) => n.replace(/\d$/, (d) => String(Number(d) + 1));

const synthwave: Song = {
  barFrames: 72,
  introBars: 2,
  bodyBars: 8,
  rmsDb: -18.5,
  master: { shelfDb: -3.5, shelfHz: 5000, threshold: 0.32, ratio: 2.2, drive: 1.35, room: 0.86, damp: 0.3, echoSteps: 3, echoFeedback: 0.42, pump: 0.6 },
  play: (mix, part, bar, t0, song) => {
    const step = step16(song);
    const barN = barSamples(song);
    const at = (s: number) => t0 + s * step;
    // Pad filter: breathes once per 4 bars; in the intro it opens from dark.
    const cut = part === "intro" ? (x: number) => 350 + 1500 * smooth(x / (2 * barN)) : (x: number) => 1500 + 500 * sin2pi(x / (4 * barN));
    B_PAD[bar].forEach((n, k) => mix.add(t0, pad(hz(n), barN, 0.55, t0, cut), { gain: 0.13, pan: k % 2 ? 0.15 : -0.15, verb: 0.3, pump: true }));
    const arpVel = part === "intro" ? (bar === 0 ? 0 : 0.6) : 0.9;
    if (arpVel)
      B_ARP_ORDER.forEach((k, s) => mix.add(at(s), pluck(hz(B_ARP[bar][k]), step * 0.7, arpVel * (s % 4 === 0 ? 1 : 0.75)), { gain: 0.17, pan: 0.2, echo: 0.35, verb: 0.15, pump: true }));
    if (part === "intro") {
      if (bar === 1) {
        mix.add(t0, riser(barN, 33), { gain: 0.22, verb: 0.3 });
        each(". . . . . . . . . . . . x x x x", (s) => mix.add(at(s), snare(900 + s, 1), { gain: 0.07 + 0.02 * (s - 12), verb: 0.3 }));
      }
      return;
    }
    for (let s = 0; s < 16; s += 2) mix.add(at(s), synthBass(hz(s % 4 ? octave(B_ROOT[bar]) : B_ROOT[bar]), step * 1.6, 1, 0.35), { gain: 0.3, pump: true });
    for (let s = 0; s < 16; s += 4) mix.add(at(s), kick(50, 110, 0.32, 7), { gain: 0.5 });
    for (const s of [4, 12]) {
      mix.add(at(s), clap(300 + bar * 16 + s), { gain: 0.22, verb: 0.5 });
      mix.add(at(s), snare(400 + bar * 16 + s, 1, 0.1), { gain: 0.14, verb: 0.4 });
    }
    each("o o x o o o x o o o x o o o x o", (s, tok) => mix.add(at(s), hat(600 + bar * 16 + s, tok === "x" ? 0.09 : 0.02), { gain: 0.13 * hit(tok), pan: -0.35 }));
    each(B_TUNE[bar], (s, n, len) => mix.add(at(s), lead(hz(n), len * step, 1), { gain: 0.16, verb: 0.4, echo: 0.25 }));
  },
};

// --- (c) Cinematic clockwork, C minor, 109 bpm ---------------------------------------------
// Cm Ab Eb Bb | Cm Ab Fm G: tick-tock clock and gear ratchets, a staccato string ostinato and
// pulse bass that open up over the 8 bars, low strings, a music-box tune, taiko drums that
// thicken in the second half, and a BANG (sub drop + metal clang) after a riser every 4 bars.

const C_STRINGS = [
  ["C3", "G3", "C4", "D#4"],
  ["G#2", "D#3", "G#3", "C4"],
  ["D#3", "G3", "A#3", "D#4"],
  ["D3", "F3", "A#3", "D4"],
  ["C3", "G3", "C4", "D#4"],
  ["G#2", "D#3", "G#3", "C4"],
  ["F3", "G#3", "C4", "F4"],
  ["D3", "G3", "B3", "D4"],
];
const C_OSTINATO = [
  ["C3", "G3", "C4"],
  ["G#2", "D#3", "G#3"],
  ["D#3", "A#3", "D#4"],
  ["A#2", "F3", "A#3"],
  ["C3", "G3", "C4"],
  ["G#2", "D#3", "G#3"],
  ["F2", "C3", "F3"],
  ["G2", "D3", "G3"],
];
const C_ORDER = [0, 0, 1, 0, 2, 0, 1, 0, 0, 0, 1, 0, 2, 1, 0, 1];
const C_BASS = ["C2", "G#1", "D#2", "A#1", "C2", "G#1", "F1", "G1"];
const C_TUNE = [
  "G5 - - - D#5 - - - C5 - - - D5 - D#5 -",
  "C5 - - - - - - - G#4 - - - - - - -",
  "A#4 - - - - - D#5 - G5 - - - F5 - D#5 -",
  "D5 - - - - - - - - - - - . . . .",
  "G5 - - - D#5 - - - C5 - - - D5 - D#5 -",
  "F5 - - - D#5 - - - C5 - - - G#5 - - -",
  "G5 - - - F5 - - - D#5 - - - C5 - - -",
  "D5 - - - - - - - B4 - - - - - . .",
];
const C_TOMS = ["x . . . . . . . x . . . . . . .", "x . . x . . x . x . . x . . x .", "x . . x . . x . x . x . x x x x"];

const clockwork: Song = {
  barFrames: 66,
  introBars: 2,
  bodyBars: 8,
  rmsDb: -19,
  master: { shelfDb: -3, shelfHz: 5500, threshold: 0.3, ratio: 2.5, drive: 1.4, room: 0.88, damp: 0.35, echoSteps: 2, echoFeedback: 0.3, pump: 0 },
  play: (mix, part, bar, t0, song) => {
    const step = step16(song);
    const barN = barSamples(song);
    const at = (s: number) => t0 + s * step;
    // The clock: tick on the beat 8ths, tock between, a quiet gear ratchet on the 16ths.
    for (let s = 0; s < 16; s += 2) mix.add(at(s), tick(s % 4 ? 1180 : 1760, 50 + s), { gain: s % 4 ? 0.1 : 0.14, pan: s % 4 ? 0.35 : -0.35, verb: 0.08 });
    for (let s = 1; s < 16; s += 2) mix.add(at(s), hat(80 + bar * 16 + s, 0.006, 5200), { gain: 0.06, pan: 0.55 });
    if (part === "intro") {
      const cut = (x: number) => 180 + 500 * smooth((x - t0 + bar * barN) / (2 * barN));
      if (bar === 0) for (const n of ["C2", "G2"]) mix.add(t0, drone(hz(n), 2 * barN, 0.5, t0, cut), { gain: 0.2, verb: 0.3 });
      if (bar === 1) {
        mix.add(at(8), bell(hz("G5"), 8 * step, 0.7), { gain: 0.12, pan: 0.2, verb: 0.45, echo: 0.25 });
        mix.add(t0, riser(barN, 77), { gain: 0.26, verb: 0.3 });
      }
      return;
    }
    const build = bar / 7; // 0 → 1 over the loop: the pulse opens up
    const phrase = (bar % 4) / 3;
    C_STRINGS[bar].forEach((n, k) => mix.add(t0, pad(hz(n), barN, 0.5, t0, () => 700 + 500 * build, 0.25), { gain: 0.1, pan: k % 2 ? 0.3 : -0.3, verb: 0.35 }));
    C_ORDER.forEach((k, s) =>
      mix.add(at(s), bowed(hz(C_OSTINATO[bar][k]), step * 0.6, (s % 4 === 0 ? 1 : 0.7) * (0.6 + 0.4 * phrase), 900 + 2200 * build), { gain: 0.24, pan: -0.1, verb: 0.15 }),
    );
    for (let s = 0; s < 16; s += 2) mix.add(at(s), synthBass(hz(C_BASS[bar]), step * 1.4, 0.8 + 0.2 * phrase, 0.15 + 0.5 * build), { gain: 0.28 });
    each(C_TOMS[bar === 7 ? 2 : bar >= 4 ? 1 : 0], (s) => mix.add(at(s), tom(s % 4 ? 82 : 62, 900 + bar * 16 + s), { gain: 0.24, verb: 0.25 }));
    each(C_TUNE[bar], (s, n, len) => mix.add(at(s), bell(hz(n), len * step, 0.85), { gain: 0.13, pan: 0.2, verb: 0.45, echo: 0.22 }));
    // BANG on bars 1 and 5, after a riser through bars 4 and 8.
    if (bar % 4 === 0) mix.add(t0, impact(1234 + bar), { gain: 0.45, verb: 0.4 });
    if (bar % 4 === 3) mix.add(t0, riser(barN, 4321 + bar), { gain: 0.24, verb: 0.3 });
  },
};

/** The beds make-assets.ts writes to public/audio/<id>.wav. */
export const BEDS: Record<string, Song> = {
  "music-cutaway-a": lofi,
  "music-cutaway-b": synthwave,
  "music-cutaway-c": clockwork,
};
