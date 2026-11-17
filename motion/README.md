# Growth Studio motion (Remotion)

8-bit Track B templates, 1080×1920 at 30 fps. Templates live in `src/registry.ts`
(id → component, Zod props schema, default props, duration from props).

- Install: `npm ci` (the first render downloads Chrome Headless Shell into `node_modules/.remotion/`).
- Preview: `npm run studio`.
- Render: `node render.mjs --template Hello --props props/hello.json --out out/hello.mp4`
  (`--bundle <dir>` builds the bundle there once and reuses it; `--concurrency N`).
  Prints `{"out", "durationInFrames", "renderMs"}`; bad props exit 1 with every problem listed.
- Still: `npm run still` (= `--still --frame 45`, writes `out/hello.png`).
- Checks: `npm run lint`, `npm run typecheck`.
