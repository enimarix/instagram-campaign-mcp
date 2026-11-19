# Growth Studio cinematic (Blender)

The `blender` style (label « Blender »): "PS2 cutscene" skits. A low-poly character with a
real face sits at a dining table in warm sunset light and says a few lines while the camera
cuts between a close and a wide shot. It is a second engine next to the Remotion templates in
`motion/`, and it plugs in behind the same door: template `CinematicSkit` in
`list_motion_templates` / `preview_motion` / `render_motion`, `kind: motion` recipes, the same
TTS voice, QC and end card (`src/studio/cinematic.py`).

- Setup (once, about 1.6 GB, git-ignored): `python cinematic/setup.py` downloads everything
  below into `cinematic/tools/`. `ig-campaign doctor` checks it.
- Props (`CinematicSkit`): `hook` (the silent "POV: ..." text, on screen from frame 0 for
  `hookSeconds`), `character` (a preset of `cast.json`: dad, mum, grandma, teen), `lines`
  (1-6, spoken by the character), `shots` (auto | close | wide), `captions`, `outro` (end card
  tagline), `accent`, `citations`, `voice`.
- A render: TTS voice → Rhubarb mouth cues (phonetic, any language; mouth flaps without
  audio) → Blender (`engine/shot.py`, EEVEE, 720x1280 at 24 fps) → ffmpeg grade (bloom, warm
  balance, S-curve, vignette) → the shared recipe ops (hook text, captions, live end card,
  loudness). About 2.5 s per frame: a 15 s video takes about 15 minutes.
- Engine: `engine/kit.py` (shared PS2 materials and low-poly shapes), `engine/dining.py` (the
  set: room, table, dinner, chairs, curtains, lamp, billboard trees, pixelated sunset sky),
  `engine/retarget.py` (CC0 clip onto the MPFB rig), `engine/shot.py` (character, lip-sync,
  cameras, render). A new set is a new file like `dining.py`; `engine/make_assets.py` redraws
  the small set textures in `engine/assets/`.

| Piece | Source | License |
|---|---|---|
| 3D + render | Blender 5.2.4 portable (EEVEE) | GPL (a tool, nothing of it ships in the video) |
| People | MPFB 2.0.18 + MakeHuman system assets, visemes02, faceunits01 | GPL add-on / CC0 assets |
| Animation | Quaternius Universal Animation Library (`Sitting_Talking_Loop`) | CC0 |
| Lip-sync | Rhubarb Lip Sync 1.14 | MIT |
| Sky | Poly Haven `belfast_sunset_puresky` HDRI, gradient-mapped and pixelated | CC0 |
| Surfaces | ambientCG `WoodFloor051`, `Wood049`, `Fabric061`, `Wallpaper001A` | CC0 |
| Kitchen + food props | Poly Haven models (stove, microwave, kettle, cabinets, pans, bowls, fruit, cake...) in `tools/models/polyhaven/`; Kenney Furniture Kit (fridges, stoves, sink, cabinets, coffee machine...) and Food Kit (200 foods) in `tools/models/kenney/` | CC0 |
| Gym props | Polytoon Gym (comphonia): dumbbell + rack, plates, bars, bench, squat station, treadmill, bike, punching bag, plyo box) in `tools/models/polytoon-gym/Assets/Polytoon Gym/Gym/Models/` | CC0 |
| Set textures | `engine/assets/` (damask, tree cards, food, wall art), drawn by `make_assets.py` | ours |
| Macro 3D subjects | egg (whole, cut), salt and sugar crystals, water / oil gel drops, glycogen, protein chain, fibres, stomach (whole, cut), muscle fascicles, fat cells, bathroom scale, plate: built in code by `engine/macro.py`; the scanned foods are the Poly Haven models above | ours / CC0 |

Props library (for new sets): `kit.prop("<path under tools/models>", loc, rot_z, height)` imports
a model (.glb/.gltf/.fbx), stands it on `loc` and scales it to `height` m (Kenney models come
small: give them a height), and finds FBX textures moved inside their pack. The lists are in
`setup.py` (`POLYHAVEN`, `KENNEY`, `ITCH`): add a name there and re-run it.

## Macro 3D plates (style `macro3d`, step 154)

The `macro3d` style (template `Macro3D`, « Macro 3D ») is Remotion over Blender: Blender renders
the photoreal plates, `motion/src/templates/Macro3D/` composes the word-by-word captions, Marco
(the coach), the labels, the counter and the end card on top (`src/studio/macro3d.py`).

- Engine: `engine/macro.py` (`blender -b -P engine/macro.py -- plates.json`). Each shot is its own
  scene: a black studio void (a dark floor dissolving into black, a soft top key, two cool rim
  lights, out-of-focus dust near the lens), one subject at real size, a 60 mm lens with a
  macro depth of field (about half the subject sharp), and one camera move: `push`, `pull`,
  `orbit`, `rise`, `slide` (close along the surface), `top` (overhead, turning), `whip` (fast,
  with motion blur). The subject sits a little below the frame's centre and fills about 78 % of
  its width, so the top 22 % (the captions) stays dark. Looks: `plain`, `heat` (« Énergie en
  couleur »: a smooth thermal gradient, indigo to yellow, travelling along the subject during
  the shot, along the fibres for the muscle), `section` (egg and stomach cut open).
- Subjects (`SUBJECTS`, = `motion/src/macro3d/subjects.ts`, a test keeps them equal): the
  scanned Poly Haven foods (apple, avocado, banana, lemon, lime, onion, sweet_potato,
  croissant, buns, cake) and the procedural ones listed in the table above (scale shows the
  scene's counter on its display). A new subject = a function in `macro.py` + its id in
  `subjects.ts`.
- The template lists the shots (`layout.ts` `shotsOf`: a cut every 1-3 s, never the same move
  twice in a row, the scene's `cut` subject halfway); `schemas.mjs --validate` hands them to
  Python as `plates`. Shots render at 720x1280 and 30 fps, are graded (lanczos to 1080x1920, a
  soft highlight glow, fine grain) and cached per shot under `<media root>/macro3d/shots/`, the
  key hashing the shot and the engine's source; all shots end to end are the plate track
  (`<media root>/macro3d/plates/`). Previews render only the stills they need.
- Cost (RTX laptop GPU, EEVEE 48 samples): about 0.6 s per frame, so a 40 s video is about
  12-15 minutes of Blender plus the Remotion pass; re-renders reuse the cached shots.

