# Growth Studio motion (Remotion)

8-bit Track B templates, 1080×1920 at 30 fps. Templates live in `src/registry.ts`
(id → component, Zod props schema, default props, duration from props).

- Install: `npm ci` (the first render downloads Chrome Headless Shell into `node_modules/.remotion/`).
- Preview: `npm run studio`.
- Render: `node render.mjs --template Hello --props props/hello.json --out out/hello.mp4`
  (`--bundle <dir>` builds the bundle there once and reuses it; `--concurrency N`).
  Prints `{"out", "durationInFrames", "renderMs"}` plus `"coverFrame"` (the Reel cover,
  `thumb_offset`) for templates that set one; bad props exit 1 with every problem listed.
- Still: `npm run still` (= `--still --frame 45`, writes `out/hello.png`).
- Still of the 8-bit kit: `npm run still:preview` (`Preview8bit`, writes `out/preview8bit.png`).
- Still of the script timeline: `npm run still:timeline` (`TimelineDemo`, writes `out/timeline-demo.png`).
- Script templates: `src/lib/timeline.ts` `buildTimeline({lines, timings?, fps, hookSeconds,
  outroSeconds, loop})` turns script lines (line 0 = the hook) plus voice timings, or reading-speed
  estimates without a voice, into scenes in frames. Each script template starts with `HookCard`
  (the hook, whole from frame 0, in the top half of the safe area; cover frame `HOOK_FRAME`),
  shows the other lines with `Captions` (band below it), and with `loop` fades the hook back in
  over the outro so the last frame matches frame 0. Its registry entry sets `coverFrame`.
- Checks: `npm run lint`, `npm run typecheck`, `npm test` (`node --test`, pure helpers in `test/`).
- 8-bit kit: `src/lib/` (palette, pixel scale helpers, typewriter maths, font loading,
  game maths in `game.ts`, code-drawn sprites in `sprites.ts`), `src/components/` (`PixelText`,
  `DialogBox`, `SafeZoneGuide`, `Sprite` (sheet image or code-drawn art), `HUD`, `CRTOverlay`,
  `Wipe` / `Flash` in `Transitions.tsx`). Everything animates from `useCurrentFrame()` only;
  noise comes from `seeded(seed, frame)`, never `Math.random`. Pixel font sizes are whole
  multiples of 8 px. Third-party files in `public/` are listed in `ASSETS_LICENSES.md`.
