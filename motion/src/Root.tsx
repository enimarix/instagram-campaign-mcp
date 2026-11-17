import { Composition } from "remotion";
import { z } from "zod";
import { FPS, HEIGHT, type Template, templates, WIDTH } from "./registry";

// ponytail: registry entries are typed one by one; the loop only sees them as plain-props templates.
const entries = Object.entries(templates) as unknown as [string, Template<z.ZodType<Record<string, unknown>>>][];

export const Root = () => (
  <>
    {entries.map(([id, t]) => (
      <Composition
        key={id}
        id={id}
        component={t.component}
        schema={t.schema}
        defaultProps={t.defaultProps}
        width={WIDTH}
        height={HEIGHT}
        fps={FPS}
        durationInFrames={t.durationInFrames(t.defaultProps)}
        calculateMetadata={({ props }) => {
          // Remotion does not check props against the schema at render time: do it here,
          // so render.mjs (selectComposition) fails with every problem listed.
          const parsed = t.schema.safeParse(props);
          if (!parsed.success) {
            throw new Error(`invalid props for ${id}:\n${z.prettifyError(parsed.error)}`);
          }
          return { props: parsed.data, durationInFrames: t.durationInFrames(parsed.data) };
        }}
      />
    ))}
  </>
);
