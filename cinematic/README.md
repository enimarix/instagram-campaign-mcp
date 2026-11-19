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

Props library (for new sets): `kit.prop("<path under tools/models>", loc, rot_z, height)` imports
a model (.glb/.gltf/.fbx), stands it on `loc` and scales it to `height` m (Kenney models come
small: give them a height), and finds FBX textures moved inside their pack. The lists are in
`setup.py` (`POLYHAVEN`, `KENNEY`, `ITCH`): add a name there and re-run it.
