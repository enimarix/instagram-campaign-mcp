// The brand kit (brand/brand.json, step 037), read at bundle time.
import brandJson from "../../brand/brand.json";

export type Brand = typeof brandJson;
export type SafeZone = Brand["safe_zone"];

export const brand: Brand = brandJson;

/** The area no Reels UI covers; the right inset honours right_rail (= src/studio/brand.py safe_area). */
export const safeArea = (z: SafeZone = brand.safe_zone) => {
  const right = Math.max(z.right, z.right_rail ?? 0);
  return { left: z.left, top: z.top, width: z.width - z.left - right, height: z.height - z.top - z.bottom };
};
