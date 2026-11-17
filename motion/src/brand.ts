// The brand kit (brand/brand.json, step 037), read at bundle time.
import brandJson from "../../brand/brand.json";

export type Brand = typeof brandJson;
export type SafeZone = Brand["safe_zone"];

export const brand: Brand = brandJson;
