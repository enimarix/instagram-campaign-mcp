# Growth Studio cinematic (Blender)

The `blender` style (label « Blender »): "PS2 cutscene" skits. A low-poly character with a
real face sits at a dining table in warm sunset light and says a few lines while the camera
cuts between a close and a wide shot. It is a second engine next to the Remotion templates in
`motion/`, and it plugs in behind the same door: template `CinematicSkit` in
`list_motion_templates` / `preview_motion` / `render_motion`, `kind: motion` recipes, the same
TTS voice, QC and end card (`src/studio/cinematic.py`).

- Setup (once, about 1.6 GB, git-ignored): `python cinematic/setup.py` downloads everything
  below into `cinematic/tools/`. `ig-campaign doctor` checks it. `CINEMATIC_TOOLS=<folder>`
  points the engine (and setup.py) at tools elsewhere: a git worktree sets it to the main
  checkout's `cinematic/tools` and never links to them (removing a worktree follows a link and
  deletes its target). The engine enables MPFB for each run itself (`kit.mpfb()`), so the
  portable Blender needs no saved preferences.
- Props (`CinematicSkit`): `hook` (the silent "POV: ..." text, on screen from frame 0 for
  `hookSeconds`), `character` (any of the troupe in `cast.json`), `lines`
  (1-6, spoken by the character), `shots` (auto | close | wide), `captions`, `outro` (end card
  tagline), `accent`, `citations`, `voice`.
- A render: TTS voice → Rhubarb mouth cues (phonetic, any language; mouth flaps without
  audio) → Blender (`engine/shot.py`, EEVEE, 720x1280 at 24 fps) → ffmpeg grade (bloom, warm
  balance, S-curve, vignette) → the shared recipe ops (hook text, captions, live end card,
  loudness). About 2.5 s per frame: a 15 s video takes about 15 minutes.
- Engine: `engine/kit.py` (shared PS2 materials, low-poly shapes, model props, rooms),
  `engine/dining.py` (the set: room, table, dinner, chairs, curtains, lamp, billboard trees,
  pixelated sunset sky), `engine/retarget.py` (CC0 clip onto the MPFB rig), `engine/people.py`
  (characters, lip-sync, faces, actions), `engine/stage.py` (render settings, lights, cameras),
  `engine/shot.py` (the skit's run). `engine/make_assets.py` redraws the small set textures in
  `engine/assets/`.

## The troupe: shot lists (step 163)

The shared engine of the troupe styles (164 « Sitcom 3D absurde », 165 « Toon Chaos 3D »):
`src/studio/troupe.py` validates a shot list and renders it (`engine/troupe.py`, one Blender run
for every shot not cached yet). Example: `shotlists/proof.json`.

- **Troupe** (`cast.json`): 16 looks from child to grandparent, skins, bodies, hair, outfits
  (gym outfits tagged `gym`). Any 1-8 per shot.
- **Sets** (`sets.json`, one `engine/<module>.py` each): `dinner` (a 3 m table, 8 seats),
  `living` (sofa, rug floor spot), `gym` (Polytoon: bench, rack, treadmill, bag...),
  `kitchen` (night: counters, glowing fridge, stools), `restaurant` (three tables for two, a
  waiter spot), `beach` (sunset sea, umbrella, towels). Each lists its named spots (seats,
  standing marks, floor), an establishing `wide` camera and a light preset (`sunset`, `night`,
  `gym`, `bistro`, `beach`; a shot may pick another).
- **Actions** (`actions.json`): every library clip by name (retargeted on demand; `_Loop` clips
  loop, others hold their end), and hand-keyed moves on top of a clip: `crunch` (lying on the
  floor), `fork_up` (fork frozen in the air), `faint` (slow fall), `cheer`, `shout`,
  `phone_photo`, `carry_plate`, `curl` (dumbbell). Faces: `jaw_drop`, `outraged`, `shout`,
  `smile`, `disgust` (MPFB face units), landing at `face_at`. Each actor's clock starts at its
  own offset, so a crowd never moves in sync. Sitting actions only go on seat spots.
- **Shot**: `set`, `cast` [{`who`, `at` (spot or [x, y]), `facing`, `to` (walk to a spot),
  `action`, `face`, `face_at`, `offset`}], `camera` {`kind`: wide | close | top | whip | crash |
  dolly, `on`: the actor it lands on}, `duration` (0.3-6 s), `speed` (x0.1-x10, or a [from, to]
  ramp), `freeze` (the last frame held, s), `seed`.
- **Wardrobe** (step 164): each character has its own `top` colour in `cast.json`;
  `engine/people.py` `dress()` repaints its garment's texture (`_garments`: `flat` = the
  logo-free AO shading of the garment in that colour, for the MakeHuman tees whose print shows
  the MakeHuman logo; `pattern` = the garment's own stripes in it; the `keep` regions, jeans and
  skirts, stay as they are). No MakeHuman logo shows, and `troupe.py` refuses a shot where two
  actors wear the same top.
- Each shot renders at 720x1280 24 fps (EEVEE, the skit's look), is graded like the skit, held
  for its freeze and cached under `<media root>/troupe/shots/<key>.mp4` (the key hashes the
  resolved shot and the engine's files); the shots end to end are the track
  (`<media root>/troupe/tracks/`). Cost: `shotlists/proof.json` (8 shots, 28 actors built,
  11 s of video) took 18.6 min, about 1.7 minutes per second of video (a one-actor 1 s shot:
  ~1.1 min). Cached shots cost nothing on a re-render. Each uncached shot is its own Blender
  call (step 177): a crash loses one shot.
- VRAM (step 177): every scene image is shared (one copy per file) and crushed to 1024 px for
  faces and outfits (`cinematic.TEXTURE_PX`), 512 for the rest; the shadow pool is 256 MB.
  `python -m src.studio.troupe measure <shots.json> <out> [shot] [frame]` renders one frame
  (default: the shot with the most actors, its middle frame) and reports Blender's peak VRAM
  (nvidia-smi, minus the baseline) and the scene's texture MB (`<out>/measure.json`, the
  still beside it). Proof dinner of 7: 2.29 GB -> 1.20 GB, textures 601 -> 121 MB.

## The physique look (« Physique Scan », owner order 75)

Troupe shots with `look: blueprint` (`engine/bands.py`), the template `PhysiqueScan`
(`src/studio/physique.py` turns its timed shots into the shot list):

- The room, its walls and tall decor go; the world is cream to the camera and lights nothing
  (the key light alone shapes the toon ramps), the floor a drafting grid with orange measuring
  rings round each actor; the props are cream with an ink edge (inverted hull).
- The actors are statues: a three-tone navy toon skin, orange shorts (and a sports top on a
  woman) drawn by the shader from the body's rest height (`rest_z`, arms excluded), hair and
  eyes in ink. Only the cast entries tagged `physique` (`hero`, `hero_b`, `hero_f`, no clothes
  mesh) play here, and only here (`troupe.py` refuses them elsewhere).
- `bands` (up to 4 a shot): `{who, on (chest, abs, arm_r/l, forearm_r/l, thigh_r/l), text,
  tone (light, dark, orange), turns, slide}`. A band is an open cylinder round the part's bone
  (its girth from the vertices weighted to it, plus 2.5 cm) with ink rims and tape ticks, and
  the type: the text mesh repeated round it, wrapped onto the cylinder (letters stand on the
  band, face out, read left to right). Its ride along the bone is baked each frame in world
  space; it rolls `turns` times over the shot.
- Cameras: `orbit` (round the part, pushing in), and `close` / `dolly` with `part` aim at a
  muscle instead of the head.

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

## Sitcom 3D (style `sitcom`, step 164)

« Sitcom 3D absurde », the style the content agent invented (style request #2): the troupe in
absurd skits under a French voice-over. Remotion template `SitcomSkit` (`motion/README.md`)
times the skit; `src/studio/sitcom.py` turns its parts into a shot list: a cut every 1-2 s, at
least three angles a scene (the scene opens wide, the skit on a crash zoom into the first
action, or wide when that actor lies on the floor; then reaction close-ups on the others,
top-down, wide, close, whip, dolly), x10 for repeated gestures, a slow-mo ramp into falls, a
whip onto the punchline's actor frozen on its last frame (camera `aim: end`: aimed where the
actor's head is on the shot's last frame, from ~50 degrees above, so a faint or a fall stays in
frame; any on-actor camera looks from above at a head on the floor), a close-up
built with its actor and the two nearest only. Every garment sits `people.CLOTH_GAP` (1.5 cm)
off the body (`people.cover`), so no skin pokes through at the neckline in a close-up. The
moves `bar_strain` and `barbell_fall` hold a barbell in both hands (`people.barbell`: it follows
the middle of the hands and the line between them). The light is a `sitcom*` preset of `sets.json`
(saturated warm key, pink fill, a turquoise / emerald side light) and the grade adds
saturation to the PS2 look (`sitcom.GRADE`). The characters' lines get their own approved
voice (`say_voice`: by gender, never the narrator's). Cost: about 1.7 min of Blender per second
of video, cached per shot.

## Macro 3D plates (style `macro3d`, step 154)

The `macro3d` style (template `Macro3D`, « Macro 3D ») is Remotion over Blender: Blender renders
the photoreal plates, `motion/src/templates/Macro3D/` composes the word-by-word captions, Marco
(the coach), the labels, the counter and the end card on top (`src/studio/macro3d.py`).

- Engine: `engine/macro.py` (`python -m src.studio.cinematic -b -P cinematic/engine/macro.py --
  plates.json`: never `blender.exe` directly, the wrapper takes the GPU lock, step 166). Each shot is its own
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


GPU backend: every Blender launch uses `--gpu-backend vulkan` (step 176; OpenGL powered the laptop off). Override with `CINEMATIC_GPU_BACKEND`.

GPU clock cap (step 177): the RTX 3070 Laptop boosts to ~2100 MHz (rated ~1600) and that
boost was what powered the PC off (and the DPC_WATCHDOG bluescreen) under Blender, not VRAM.
The owner's admin logon task `GPUClockCap` runs `nvidia-smi -lgc 210,1500` at every logon
(the cap lasts until a reboot). With it the 8-shot proof (`shotlists/proof.json`, diet on)
passed: 12.9 min, 130.8 W peak, 3.1 GB VRAM. guard.log lines show the graphics clock
(`clock 1500 MHz`) beside the VRAM: a clock above ~1600 means the cap is missing. The studio
never sets clocks itself (a Windows / NVIDIA setting: the owner's).
