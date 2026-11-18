Brand kit: logo, palette, fonts, BIBLE.md (channel bible) and taxonomy.json.

`brand.json` (loader `src/studio/brand.py`): name, handle, logo, colours (brand, macros, light and dark surfaces), fonts, the call to action (`cta`), tu/vous per template family (`address`) and Reels safe-zone insets. The owner's macroBody identity since step 050.

`logo.svg` is the app mark drawn in-repo; `logo.png` (512 px) is the same file as a PNG and `wordmark.png` the name in Inter Tight 900 ("Body" in emerald), for the ffmpeg brand ops (`logo` and `end_card` in `src/studio/recipe.py`): the local ffmpeg build reads neither SVG nor WOFF2. Re-render both with `node scripts/brand-images.mjs` (from `motion/`) after editing the SVG, the name, the colours or the fonts.

Templates pick their own style: the 8-bit templates keep their own palette and pixel font in `motion/src/lib/palette.ts` and `font.ts`.
