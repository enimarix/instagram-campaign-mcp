import { Composition } from "remotion";
import { z } from "zod";
import { COVER_FRAME_PROP, FPS, HEIGHT, type Template, templates, WIDTH } from "./registry";
import { EndCard } from "./endcards/EndCard";
import { endCardSchema } from "./endcards/schema";
import { SCENES, VOXEL_PREVIEW_DEFAULTS, VoxelPreview, voxelPreviewSchema } from "./templates/VoxelPreview";

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
          // Remotion's metadata has no free field: the cover frame rides along in the props.
          const resolved = t.coverFrame ? { ...parsed.data, [COVER_FRAME_PROP]: t.coverFrame(parsed.data) } : parsed.data;
          return { props: resolved, durationInFrames: t.durationInFrames(parsed.data) };
        }}
      />
    ))}
    {/* Engine showcase (step 129), not in the template registry: the studio never picks it. */}
    <Composition
      id="VoxelPreview"
      component={VoxelPreview}
      schema={voxelPreviewSchema}
      defaultProps={VOXEL_PREVIEW_DEFAULTS}
      width={WIDTH}
      height={HEIGHT}
      fps={FPS}
      durationInFrames={SCENES.end}
    />
    {/* End-card preview (step 130): one card alone, 3.5 s. */}
    <Composition
      id="EndCard"
      component={EndCard}
      schema={endCardSchema}
      defaultProps={endCardSchema.parse({})}
      calculateMetadata={({ props }) => ({ props: endCardSchema.parse(props) })}
      width={WIDTH}
      height={HEIGHT}
      fps={FPS}
      durationInFrames={105}
    />
  </>
);
