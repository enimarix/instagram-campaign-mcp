Brand kit: logo, palette, fonts, BIBLE.md (channel bible) and taxonomy.json.

`brand.json` (loader `src/studio/brand.py`): name, handle, logo, colours, font families and Reels safe-zone insets. All placeholders until step 050.

`logo-placeholder.png` (256 px) is the same placeholder as a PNG for the ffmpeg brand ops (`logo` in `src/studio/recipe.py`): the local ffmpeg build cannot read SVG. The real logo (gate H1, step 050) must ship a PNG too, set as `logo_png`.
