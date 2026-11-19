// One frame of a cinema set's view (step 143): the pixel painting (180 x 320 cells, drawn on a canvas
// and scaled up 6x without smoothing) and the rain over it at full resolution: thin slanted
// streaks, amber where they cross a beam (the reference's lit rain), black in the lightning
// frame. `whiteout` lays the flash's white over everything.
import { useLayoutEffect, useRef } from "react";
import { AbsoluteFill } from "remotion";
import { beamAt, CELL, GH, GW, hash, toWorld } from "./pixel.ts";
import { type Paint, paint, type SceneId, viewOf } from "./scenes.ts";

const W = GW * CELL;
const H = GH * CELL;
/** Streaks at rain = 1, and how far they lean (x per y). */
const DROPS = 190;
const SLANT = -0.26;

export const Stage = ({ scene, view, whiteout = 0, ...p }: Paint & { scene: SceneId; view: string; whiteout?: number }) => {
  const cells = useRef<HTMLCanvasElement>(null);
  const rain = useRef<HTMLCanvasElement>(null);
  useLayoutEffect(() => {
    const ctx = cells.current?.getContext("2d");
    const rctx = rain.current?.getContext("2d");
    if (!ctx || !rctx) return;
    const img = ctx.createImageData(GW, GH);
    const beam = paint(scene, view, img.data, p);
    ctx.putImageData(img, 0, 0);
    rctx.clearRect(0, 0, W, H);
    const n = Math.round(DROPS * viewOf(scene, view).rain);
    rctx.lineCap = "round";
    for (let i = 0; i < n; i++) {
      const near = hash(i, 3, 91);
      const speed = 1500 + near * 1100;
      const len = 26 + near * 50;
      const span = H + 300;
      const y = ((hash(i, 1, 91) * span + p.t * speed) % span) - 150;
      const x = hash(i, 0, 91) * (W + 700) - 100 + y * SLANT;
      const [wx, wy] = toWorld(p.cam, x / CELL, y / CELL, 1);
      const inBeam = !p.flash && (beamAt(beam, wx, wy) > 0.12 || (p.extra ? beamAt(p.extra, x / CELL, y / CELL) > 0.12 : false));
      rctx.strokeStyle = p.flash ? "rgba(10, 10, 16, 0.85)" : inBeam ? "rgba(255, 190, 90, 0.9)" : `rgba(200, 208, 255, ${0.28 + near * 0.32})`;
      rctx.lineWidth = 2 + near * 2;
      rctx.beginPath();
      rctx.moveTo(x, y);
      rctx.lineTo(x + SLANT * len, y + len);
      rctx.stroke();
    }
  });
  return (
    <AbsoluteFill>
      <canvas ref={cells} width={GW} height={GH} style={{ width: W, height: H, imageRendering: "pixelated" }} />
      <canvas ref={rain} width={W} height={H} style={{ position: "absolute", inset: 0 }} />
      {whiteout > 0 && <AbsoluteFill style={{ background: "#F6F4EE", opacity: whiteout }} />}
    </AbsoluteFill>
  );
};
