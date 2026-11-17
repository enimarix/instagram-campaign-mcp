#!/usr/bin/env node
// Template schemas for Python (src/studio/motion.py), one JSON line on stdout:
//   node schemas.mjs                       {"templates": [{id, jsonSchema, defaultProps, description}]}
//   node schemas.mjs --validate <id>       props JSON on stdin ->
//     {"ok": true, props, durationInFrames, coverFrame} | {"ok": false, "error": <Zod's message>}
// Same parse and message as src/Root.tsx, without bundling for Chrome (a fraction of a second).
// The registry imports .tsx components, so it is bundled for Node first with esbuild (from
// @remotion/bundler); the font loader is stubbed: only schemas and timings run here.
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { build } from "esbuild";
import { z } from "zod";

const here = dirname(fileURLToPath(import.meta.url));

const loadRegistry = async () => {
  // Inside node_modules so the bundle's bare `zod` import resolves to this project's copy
  // (one zod instance: z.toJSONSchema must recognise the registry's schemas).
  const tmp = mkdtempSync(join(here, "node_modules", ".schemas-"));
  try {
    const file = join(tmp, "registry.mjs");
    const { outputFiles } = await build({
      entryPoints: [join(here, "src", "registry.ts")],
      bundle: true,
      platform: "node",
      format: "esm",
      write: false,
      outfile: file,
      jsx: "automatic",
      external: ["zod"],
      logLevel: "error",
      plugins: [
        {
          name: "no-fonts",
          setup(b) {
            b.onResolve({ filter: /^@remotion\/fonts$/ }, () => ({ path: "fonts", namespace: "stub" }));
            b.onLoad({ filter: /.*/, namespace: "stub" }, () => ({ contents: "export const loadFont = async () => {};" }));
          },
        },
      ],
    });
    writeFileSync(file, outputFiles[0].text);
    return await import(pathToFileURL(file).href);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
};

const print = (value) => process.stdout.write(JSON.stringify(value) + "\n");

try {
  const { values: a } = parseArgs({ options: { validate: { type: "string" } } });
  const { templates, FPS } = await loadRegistry();
  if (a.validate === undefined) {
    print({
      templates: Object.entries(templates).map(([id, t]) => {
        const jsonSchema = z.toJSONSchema(t.schema, { io: "input", unrepresentable: "any" });
        return { id, jsonSchema, defaultProps: t.defaultProps, description: jsonSchema.description ?? null };
      }),
    });
  } else {
    const t = Object.hasOwn(templates, a.validate) ? templates[a.validate] : null;
    const parsed = t?.schema.safeParse(JSON.parse(readFileSync(0, "utf8")));
    if (!t) {
      print({ ok: false, error: `unknown template ${a.validate} (have ${Object.keys(templates).join(", ")})` });
    } else if (!parsed.success) {
      print({ ok: false, error: `invalid props for ${a.validate}:\n${z.prettifyError(parsed.error)}` });
    } else {
      const props = parsed.data;
      print({ ok: true, props, fps: FPS, durationInFrames: t.durationInFrames(props), coverFrame: t.coverFrame?.(props) ?? null });
    }
  }
} catch (e) {
  process.stderr.write(`schemas: ${e instanceof Error ? e.message : String(e)}\n`);
  process.exitCode = 1;
}
