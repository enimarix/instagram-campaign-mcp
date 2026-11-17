import type { ComponentType } from "react";
import type { z } from "zod";
import { Hello, helloSchema } from "./templates/Hello";

export const WIDTH = 1080;
export const HEIGHT = 1920;
export const FPS = 30;

export type Template<S extends z.ZodType> = {
  component: ComponentType<z.infer<S>>;
  schema: S;
  defaultProps: z.infer<S>;
  durationInFrames: (props: z.infer<S>) => number;
};

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
};
