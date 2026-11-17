import type { ComponentType } from "react";
import { Composition } from "remotion";
import { z } from "zod";
import { FPS, HEIGHT, templates, WIDTH } from "./registry";

export const Root = () => (
  <>
    {Object.entries(templates).map(([id, t]) => (
      <Composition
        key={id}
        id={id}
        // ponytail: registry entries are typed one by one; the loop only sees the union.
        component={t.component as ComponentType<Record<string, unknown>>}
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
