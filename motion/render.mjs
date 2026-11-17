#!/usr/bin/env node
// Render one template: node motion/render.mjs --template <id> --props <file> --out <file>
//   [--still --frame N] [--bundle <dir>] [--concurrency N]
// Prints one JSON line {out, durationInFrames, renderMs[, coverFrame]} on stdout (coverFrame when
// the template has one: the Reel cover, thumb_offset); errors go to stderr, exit 1.
import { existsSync, readFileSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { bundle } from "@remotion/bundler";
import { renderMedia, renderStill, selectComposition } from "@remotion/renderer";

const here = dirname(fileURLToPath(import.meta.url));

const report = (msg) => process.stderr.write(`render: ${msg}\n`);
const fail = (msg) => {
  report(msg);
  process.exit(1);
};

const { values: a } = (() => {
  try {
    return parseArgs({
      options: {
        template: { type: "string" },
        props: { type: "string" },
        out: { type: "string" },
        still: { type: "boolean", default: false },
        frame: { type: "string", default: "0" },
        bundle: { type: "string" },
        concurrency: { type: "string" },
      },
    });
  } catch (e) {
    return fail(e.message);
  }
})();

if (!a.template || !a.out) fail("--template and --out are required");
const frame = Number(a.frame);
if (!Number.isInteger(frame)) fail(`--frame must be an integer, got ${a.frame}`);
const concurrency = a.concurrency === undefined ? null : Number(a.concurrency);
if (concurrency !== null && !(Number.isInteger(concurrency) && concurrency > 0)) {
  fail(`--concurrency must be a positive integer, got ${a.concurrency}`);
}

let inputProps = {};
if (a.props) {
  try {
    inputProps = JSON.parse(readFileSync(a.props, "utf8"));
  } catch (e) {
    fail(`cannot read props ${a.props}: ${e.message}`);
  }
  if (typeof inputProps !== "object" || inputProps === null || Array.isArray(inputProps)) {
    fail(`props ${a.props} must hold a JSON object`);
  }
}

const started = Date.now();
const out = resolve(a.out);

let tempBundle = null;
try {
  // Bundle once per batch: reuse --bundle when it holds a bundle, otherwise build it there
  // (or in a temp dir). Never bundle in parallel (docs/DECISIONS.md, step 006a).
  const bundleDir = a.bundle && resolve(a.bundle);
  const serveUrl =
    bundleDir && existsSync(join(bundleDir, "index.html"))
      ? bundleDir
      : await bundle({ entryPoint: join(here, "src", "index.ts"), outDir: bundleDir ?? null });
  if (!bundleDir) tempBundle = serveUrl; // ~40 MB per render otherwise left in the temp dir

  // Throws on an unknown id or props that fail the template's Zod schema
  // (calculateMetadata in src/Root.tsx); composition.props are the parsed props.
  const composition = await selectComposition({ serveUrl, id: a.template, inputProps, logLevel: "error" });
  // src/Root.tsx adds the template's cover frame to the resolved props under this key
  // (= COVER_FRAME_PROP in src/registry.ts); the strict schemas must not see it.
  const { __coverFrame: coverFrame, ...props } = composition.props;
  const common = { composition: { ...composition, props }, serveUrl, inputProps: props, logLevel: "error" };
  if (a.still) {
    await renderStill({ ...common, output: out, frame });
  } else {
    await renderMedia({ ...common, codec: "h264", outputLocation: out, concurrency });
  }
  const result = { out, durationInFrames: composition.durationInFrames, renderMs: Date.now() - started, coverFrame };
  process.stdout.write(JSON.stringify(result) + "\n");
} catch (e) {
  report(e instanceof Error ? e.message : String(e));
  process.exitCode = 1;
} finally {
  if (tempBundle) rmSync(tempBundle, { recursive: true, force: true });
}
