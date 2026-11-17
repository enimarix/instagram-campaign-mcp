import type { ComponentType } from "react";
import type { z } from "zod";
import { Hello, helloSchema } from "./templates/Hello";
import { Preview8bit, preview8bitSchema } from "./templates/Preview8bit";

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
    },
    durationInFrames: (p) => Math.round(p.seconds * FPS),
  }),
};
