import type { ComponentType } from "react";
import type { z } from "zod";
import { Hello, helloSchema } from "./templates/Hello";
import { Preview8bit, preview8bitSchema } from "./templates/Preview8bit";
import { TimelineDemo, timelineDemoSchema, timelineOf } from "./templates/TimelineDemo";

export const WIDTH = 1080;
export const HEIGHT = 1920;
export const FPS = 30;

export type Template<S extends z.ZodType> = {
  component: ComponentType<z.infer<S>>;
  schema: S;
  defaultProps: z.infer<S>;
  durationInFrames: (props: z.infer<S>) => number;
  /** Frame to use as the Reel cover (thumb_offset); script templates use timeline.hookFrame. */
  coverFrame?: (props: z.infer<S>) => number;
};

/** Key under which Root passes the cover frame out through the resolved props (render.mjs reads it). */
export const COVER_FRAME_PROP = "__coverFrame";

// Ties component, schema and defaults to one schema type per entry.
const template = <S extends z.ZodType>(t: Template<S>) => t;

// Template id (= composition id, PascalCase like brand/taxonomy.json templates) -> template.
export const templates = {
  Hello: template({
    component: Hello,
    schema: helloSchema,
    defaultProps: { title: "Hello", subtitle: "8-bit pipeline online", seconds: 3, safeZone: false },
    durationInFrames: (p) => Math.round(p.seconds * FPS),
  }),
  Preview8bit: template({
    component: Preview8bit,
    schema: preview8bitSchema,
    defaultProps: {
      title: "8-BIT KIT",
      text: "Café, crème brûlée, ñandú, Straße",
      name: "Señor Müller",
      dialog: "Où est la crème brûlée? Ça alors, Œdipe l'a mangée!",
      speed: 15,
      seconds: 8,
      safeZone: false,
      hud: true,
      sprites: true,
      crt: true,
      transitions: true,
    },
    durationInFrames: (p) => Math.round(p.seconds * FPS),
  }),
  TimelineDemo: template({
    component: TimelineDemo,
    schema: timelineDemoSchema,
    defaultProps: {
      lines: ["Your gut has more bacteria than you have cells?", "Not quite: about the same number.", "Roughly 38 trillion of them."],
      loop: true,
      safeZone: false,
    },
    durationInFrames: (p) => timelineOf(p, FPS).totalFrames,
    coverFrame: (p) => timelineOf(p, FPS).hookFrame,
  }),
};
