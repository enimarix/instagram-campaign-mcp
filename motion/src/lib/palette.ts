// Brand colours (brand/brand.json): the five named roles and the 16-colour palette.
import { brand } from "../brand";

const { palette: list, ...named } = brand.colors;

/** primary, secondary, accent, background, text. */
export const colors = named;
export const palette: readonly string[] = list;
