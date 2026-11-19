# Growth Studio motion (Remotion)

8-bit Track B templates, 1080×1920 at 30 fps. Templates live in `src/registry.ts`
(id → component, Zod props schema, default props, duration from props).

- Install: `npm ci` (the first render downloads Chrome Headless Shell into `node_modules/.remotion/`).
- Preview: `npm run studio`.
- Render: `node render.mjs --template Hello --props props/hello.json --out out/hello.mp4`
  (`--bundle <dir>` builds the bundle there once and reuses it; `--concurrency N`).
  Prints `{"out", "durationInFrames", "renderMs"}` plus `"coverFrame"` (the Reel cover,
  `thumb_offset`) for templates that set one; bad props exit 1 with every problem listed.
  `--bundle-only --bundle <dir>` only builds the bundle (Python bundles once per process, under
  the file lock `node_modules/.growth-studio-bundle.lock` shared by all processes: never two
  bundles at once).
- Schemas for Python (`src/studio/motion.py`): `node schemas.mjs` prints every template's JSON
  Schema and default props; `node schemas.mjs --validate <id>` checks props JSON from stdin with
  the template's Zod schema (no Chrome, well under a second).
- Still: `npm run still` (= `--still --frame 45`, writes `out/hello.png`).
- Still of the 8-bit kit: `npm run still:preview` (`Preview8bit`, writes `out/preview8bit.png`).
- Still of the script timeline: `npm run still:timeline` (`TimelineDemo`, writes `out/timeline-demo.png`).
- Script templates: `src/lib/timeline.ts` `buildTimeline({lines, timings?, fps, hookSeconds,
  outroSeconds, loop})` turns script lines (line 0 = the hook) plus voice timings, or reading-speed
  estimates without a voice, into scenes in frames. Each script template starts with `HookCard`
  (the hook, whole from frame 0, in the top half of the safe area; cover frame `HOOK_FRAME`),
  shows the other lines with `Captions` (band below it), and with `loop` fades the hook back in
  over the outro so the last frame matches frame 0. Its registry entry sets `coverFrame`, and
  `events` (what happens when, `src/lib/events.ts` `scriptEvents`: one per scene with the
  template's meaning, music bed, voice-over, outro, plus extras such as the countdown) which
  `--validate` returns for the asset's timeline (step 110).
- `FactQuest` (`src/templates/FactQuest/`): hook card, 3–5 facts as "LEVEL n" scenes (HUD level
  bar n/N, a hopping sprite, the fact typed into the caption band), wipes between them, end card
  with the outro. Props schema in `schema.ts` (example `props/factquest.json`): `hook`, `facts`
  [{title?, text}], `outro`, `citations` [{url, title?}] (required, may be empty; not shown, kept
  with the asset; `sourcesNote` shows on the end card when there are some), `voice` {audioSrc?,
  lines?: one timing per line: hook, each fact, outro}, `music` (as QuizChest), `loop` (default
  true), `palette`,
  `safeZone`. Length = script timeline. Still: `npm run still:factquest` (mid level 1).
- `BossBattle` (`src/templates/BossBattle/`): A vs B (or myth vs fact) as an 8-bit fight. Hook card
  with "A VS B" under it, 2–4 "ROUND n" scenes (the attacker dashes in, hit flash + `sfx-hit`, the
  foe's HUD health bar drops; the argument types into the caption band), then the verdict (the
  winner knocks the loser out, or "DRAW!", `sfx-confirm`; verdict text in the band, `sourcesNote`
  under it when there are citations). Props in `schema.ts` (example `props/bossbattle.json`):
  `hook`, `left`/`right` {name ≤16, sprite?: mascot|slime|coin|heart}, `rounds` [{attacker:
  left|right, text}], `verdict` {winner: left|right|draw, text}, `citations`, `sourcesNote?`,
  `voice` {audioSrc?, lines?: hook, each round, verdict}, `music` (as QuizChest), `loop`, `palette`,
  `safeZone`. Health per
  scene: `healthSteps()` (each hit takes 1/(rounds+1)). Still: `npm run still:bossbattle` (round 2).
- `QuizChest` (`src/templates/QuizChest/`): a quiz that invites comments. Hook card, then the
  question (top) over 2–4 choice buttons (band), a countdown ticking next to a closed chest
  (`sfx-select` each second, the chest shakes), the reveal (flash + `sfx-confirm`, the chest opens
  and a coin pops out with `sfx-coin`, the right choice lights up, the others dim), the explanation
  typed into the band under the open chest and the right answer, then the end card with the `cta`
  (`sourcesNote` under it when there are citations). Props in `schema.ts` (example
  `props/quizchest.json`): `hook`, `question`, `choices` [{label ≤3, text ≤40}], `answer` (index),
  `countdownSeconds` (3–10, default 5), `explanation`, `cta` (default "Comment your answer!"),
  `citations`, `sourcesNote?`, `voice` {audioSrc?, lines?: hook, question, explanation, cta}, `music`
  (`music-overworld` default, `music-cave` or `none`; `MusicBed` loops it under everything at
  25 %, ducked under the voice: see Assets), `loop`,
  `palette`, `safeZone`. `withCountdown()` inserts countdown + 1.5 s reveal after the question line;
  the voice track plays in two parts around it, so its timings are those of the plain audio. Still:
  `npm run still:quizchest` (countdown).
- `DialogStory` (`src/templates/DialogStory/`): an RPG-style dialogue that tells a short story or
  explains one idea. Hook card with both portraits under it, then one scene per line: the two
  portraits in the top half (the speaker's frame lit, bouncing and animating while it talks, the
  listener dimmed), the line typed into a `DialogBox` with the speaker's name tag after a short
  beat (`sfx-select`), then the optional moral in a box without a tag (`sfx-confirm`, `sourcesNote`
  under it when there are citations). Props in `schema.ts` (example `props/dialogstory.json`):
  `hook`, `characters` (2 × {name ≤16, sprite?: mascot|slime|coin|heart, side: left|right}, one per
  side; default portraits mascot, slime), `lines` (3–8 × {speaker: 0|1, text ≤100}, both speak),
  `moral?`, `citations`, `sourcesNote?`, `voice` {audioSrc?, lines?: hook, each line, moral when
  given}, `music` (as QuizChest), `loop`, `palette`, `safeZone`. Scene roles: `sceneRoles()`; talk
  span: `talkSpan()` (typed or voiced, whichever is later). Still: `npm run still:dialogstory`.
- `PixelSkit` (`src/templates/PixelSkit/`): the humour template, a 10–20 s "POV:" sketch. Hook
  card with the cast standing on grass under it (the cover), then one scene per beat: the cast on
  stage in the top half, the beat's actor playing its action while the line types into a
  `DialogBox` (speaker's name tag, if any). Comic timing (`comicTiming()`): the beat before the
  punchline holds `holdBeforePunchline_s`, the `sting` sfx plays when the punchline lands (typed or
  voiced, whichever is later) and, with `freezeOnPunchline`, the picture freezes there for 1 s
  behind a flash; an optional tag beat follows. Props in `schema.ts` (example
  `props/pixelskit.json`): `hook`, `cast` (1–2 × {name ≤16, sprite?: mascot|slime|coin|heart};
  first left, second right), `beats` (2–4 × {speaker?: 0|1 (none = no tag, cast[0] acts), line ≤80,
  action: idle|walk_in|jump|shake|fall|stare|facepalm (default idle), sfx?:
  hit|jump|select|confirm|coin}), `tag` (default false: the last beat is a tag after the
  punchline, 3+ beats), `holdBeforePunchline_s` (0–2, default 0.6), `freezeOnPunchline` (default
  true), `sting` (sfx or `none`, default `hit`), `citations` (usually empty), `sourcesNote?`,
  `voice` {audioSrc?, lines?: hook, then one per beat; played in parts around the hold and the
  freeze, so its timings are those of the plain audio}, `music` (as QuizChest), `loop` (default
  true), `palette`, `safeZone`. Still: `npm run still:pixelskit` (beat 2, stare).
- `VoxelQuest` (`src/templates/VoxelQuest/`, style `voxel`, « 3D 8-bit »): a 20–30 s story in
  the voxel kitchen set (`kitchen()` in `src/voxel/models.ts`). Hook (Inter Tight 900 on the light
  background, whole from frame 0, while the set pops in; the golem on a scale or by an empty plate),
  1–2 problem beats (foods pop onto the worktop with their numbers in macro-coloured pills pinned
  with `projectIso`; a beat without foods goes close on the golem and the hook's prop), 1–2 app
  beats (the voxel phone fills its calorie ring in 8 steps, push-in), the payoff (hop, white flash,
  the golem pops into `toForm`, « Niveau n · Name » pill, `sfx-chime`), then the animated end card.
  Staging and camera live in `layout.ts` (pure): every shot is fitted (`fitShot`) so the golem
  and its props stay inside the safe area under the captions (a test checks every frame of the
  examples), a beat longer than 3.5 s swings to a second shot halfway, numbers count up.
  One iso camera eases between shots and drifts slowly within them; captions are dark text on a
  white rounded card at the top of the safe area, numbers in the accent colour. Props in `schema.ts`
  (examples `props/voxelquest*.json`): `hook`, `hookProp` (scale|plate), `beats` [{kind:
  problem|app|payoff, line, foods? (problem only, 1–3 × {prop, label, macro}), value? (app only:
  the big number on the phone, counting up; default the ring's %), form?}] (1–2
  problem, 1–2 app, one payoff), `outro?` (= the end card's tagline), `address` (vous|tu, default
  brand), `fromForm`/`toForm` (form ids, toForm higher), `accent`, `cameo?`, `citations`, `voice`
  {audioSrc?, lines?: hook, each beat, outro when given}, `music` (`music-marimba`|none), `loop`
  (default false), `pixelate` (default 2), `safeZone`. Every visible text refuses prices
  (`src/lib/noPrice.ts`). Still: `npm run still:voxelquest`.
- `PaperStory` (`src/templates/PaperStory/`, style `paper`, « Papier »): the owner's house style
  (paper cut-out, after `macrobody-video` p1–p3 and s1), a 20–30 s story. Each scene is a sheet of
  paper on a kraft frame (navy night sheet with paper stars and moon, sky, mint, cream, peach),
  Fredoka strips on cut paper (cream; `brand` = the green highlight bar; yellow, red, ink, sky),
  a Caveat aside, and a named cut-out character (`src/paper/Character.tsx`: Inès, Paul, Sam, Léa;
  moods neutral / worried / happy / surprised, gestures wave / phone / shrug / cheer). Hook (1–3
  strips, the first there from frame 0, all landed by the cover frame ≤ 1.1 s; a clock ticking to
  `time`, the fridge, a plate of foods or the phone), 1–2 problem beats (foods fly out of the
  fridge one at a time with their number on a receipt slip, crossed out or checked), 1–2 app
  beats (the phone with the app's day screen in vectors: ring counting up, macro bars, the
  green button tapped; or the app's list: rows fly in, padlocks close, grams solve, the total
  lands), the payoff (the ring counts up in the accent, a stamp slams down, paper confetti), then
  the paper end card with the story's character as cameo. Scene cuts alternate tear (the old
  sheet torn in two) and wipe (a coloured sheet swept across); everything moves on 12 fps
  steps (`stepped()` in `src/paper/palette.ts`); paper grain, flicker and a warm vignette over
  every frame. Kit: `src/paper/` (`kit.tsx` sheets, strips, transitions; `props.tsx` foods,
  fridge, clock, phone, plate, lock, marks, slip, confetti). Props in `schema.ts` (examples
  `props/paperstory*.json`): `character`, `hook` {labels, aside?, sheet?, mood?, gesture?, prop
  clock|fridge|plate|phone|none, time, foods?}, `beats` [problem {labels, …, prop, time,
  options [{food, label, note, verdict too_much|too_little|ok|none}]} | app {labels, …, value?,
  unit, button, rows? [{food, name, from?, to, locked}], total?} | payoff {labels, …, value?,
  of?, stamp?, foods?}] (1–2 problem, 1–2 app, one payoff), `outro?` (= the end card's
  tagline), `address`, `accent`, `cameo?`, `citations`, `voice` {audioSrc?, lines?: hook, each
  beat (its strips joined: `sceneLine`), outro when given}, `music` (`music-kalimba`|none),
  `loop` (default false), `safeZone`. Every visible text refuses prices. Still:
  `npm run still:paperstory`.
- `Cutaway` (`src/templates/Cutaway/`, style `cutaway`, « Pixel explicatif », step 142): a
  pixel-art mechanism explainer, the body as a machine (after a radial-engine explainer Reel:
  its look, not its frames). A cutaway diagram drawn in code that really moves, under a game
  HUD: mode chip « ▶ VITESSE RÉELLE » / « ‖ RALENTI 1/84 » / « ▶▶ ACCÉLÉRÉ ×1000 » with its
  dashes (the mechanism's clock eases between speeds), « ×2 » badge, a top-right gauge with a
  green-to-red bar (its number counts between scenes), a framed title box (hook and payoff
  big, white and yellow lines), a numbered steps row (lit step follows the mechanism's cycle
  unless `current`), callouts in boxed labels with elbow leader lines, « BANG »-style bursts
  with a dithered flash. Same view: the camera glides (zoom, focus on a named point); new view:
  the old picture zooms through (in to a deeper view, out to a shallower one) while the new
  one dithers in. Kit `src/cutaway/`: `kit.tsx` (the P = 5 px grid: an SVG mosaic filter over
  the vector art, Bayer dither masks, dusk / night skies with drifting pixel clouds, HUD
  boxes), `pixelfont.ts` (a 5x7 capitals bitmap font drawn as paths, regular and bold, French
  accents above the capital), `palette.ts`, `views.ts` + `views/` (one file per mechanism:
  `arm` curling a dumbbell, `muscle` belly with fascicles and a nerve signal, `fibre` with
  striated myofibrils, `sarcomere` with myosin heads cycling on actin and ATP sparks, `repair`
  micro-tears healed by satellite cells, `fat` cell emptying into the blood, `mito`
  mitochondrion burning fatty acids into ATP, CO₂ and water). **A new subject = a new view**:
  its component in `views/`, its entry in `views.ts` (anchors, hz at real speed, depth) and in
  `views/index.tsx`. Props in `schema.ts` (examples `props/cutaway*.json`): `hook`, `beats`
  (4–6), `payoff`, each a scene {title, sub?, view, speed, x2, zoom, focus?, stage? (the view's
  slow change), callouts [{text, at}] ≤ 3, steps? {items, current?}, gauge? {label, value?,
  fill}, bang?, sky? dusk|night}; `outro?` (= the end card's tagline), `address`, `accent`,
  `cameo?` (a view id), `citations`, `voice` {audioSrc?, lines?: hook, each beat, payoff,
  outro; a scene's line = title + sub}, `music` (`music-dusk` default, the step-148 candidates `music-cutaway-a|b|c`, or none), `loop`, `safeZone`. Every
  visible text refuses prices. Still: `npm run still:cutaway`.
- `Editorial` (`src/templates/Editorial/`, style `editorial`, « Éditorial », step 144): black
  editorial art direction, ~25–40 s with the voice. Type-only hook (a « • MACROBODY » chip, the
  `lead` in white Inter Tight 900 there from frame 0, the `key` rising in pink Instrument Serif
  Italic, an optional `strike` drawn through a word of the lead; a push and petals at depth from
  frame 0; cover once key and strike are in, ≥ 1.2 s), 3–5 chapters
  counted « 01 / 04 » with a pink-playhead scrubber running with the video, then the `payoff` in
  duo type over the tree in full bloom and the editorial end card. Chapters: `tree` (the pixel
  blossom tree, `src/editorial/blossom.ts` + `Tree.tsx`, seeded, on a 4 px grid, petals at three
  depths; each action is its own shot with a camera move, `layout.ts` `cameraOf`: `bloom` = crane
  up as it grows from the last tree chapter's `bloom`, `wind` = wide, anticipation then a gust
  with wind lines and a cyan scrubber range, `petals` = macro close-up, `frame` = viewfinder
  brackets then a zoom into them, `loop` = a pink ring, dolly out; up to 3 `tags` or one `stat`),
  `type` (a type-only beat, the title big and kinetic),
  `split` (before / after: a flat pastel tree « sans méthode » over the rich one « avec
  méthode ») and `anatomy` (a deep blue card sliding up: a cute body part from
  `src/editorial/Character.tsx`, stomach / muscle / heart / bone / fat, moods neutral / happy /
  surprised / tired / sore, `then` = the mood it turns to halfway, pixelated by the `px` SVG
  filter; a Press Start 2P caption in capitals without accents, `highlight` in yellow; optional
  `stat`). No two chapters in a row share a composition (`compositionOf`; the schema refuses
  it) and the first is not type-only. `stat` = the social-proof number (big value, pink italic unit, note): kcal, grams,
  minutes, never a price. Voice lines: hook (lead + key), each chapter (its caption, or title +
  key: `joinLine`), payoff, `outro?`. Music `music-lounge`. Examples `props/editorial*.json`.
  Still: `npm run still:editorial`.
- End cards (`src/endcards/`, steps 130, 137): `<EndCard style=…>` picks the style's animated
  card; every template ends on its style's card. Fixed base (`base.tsx`: mB tile, wordmark,
  « 7 jours gratuits », macrobody.fr) adapted per video by the props in `schema.ts`: `tagline?`,
  `accent`, `cameo?` (per style, `CAMEOS`), `address`, `backdrop` (live only), `font` (paper; default Fredoka, loaded with Caveat since step 131),
  `note` (pixel), `pixelate` (voxel), `seconds` (standalone clip; default `CARD_S`). Never a
  price. Each card settles by `SETTLE_S` and holds ≥ 1 s. `voxel`: crane up to a podium where
  the tile assembles from falling cubes. `paper`: kraft cover tears open on the cream sheet,
  cut-out pieces slide in at 12 fps steps, a cut-out character waves. `clean`: v5 light
  surface, drifting accent glows, kicker pill, tile scales up, wordmark rises from a mask.
  `pixel`: PRESS START, the tile dissolves in cell by cell, the texts type in. `live`: the last
  frame freezes, blurs and dims under the clean stack in light text. `cutaway` (step 142): the HUD's
  level-complete screen, the tile dithers in on the pixel grid beside a small running mechanism. `editorial`: black,
  pixel petals drifting, the stores chip, the tagline in duo type (last word pink italic), the
  tile with a pink rim beside its cameo (the tree or an anatomy character), the wordmark rises,
  « 7 jours *gratuits* » pops in pink. Composition `EndCard`
  (`EndCardClip`) renders one card alone; Track A recipes use it (src/studio/motion.py
  `render_end_card`). Stills: `npm run still:endcard`, `npm run still:endcards`.
- Checks: `npm run lint`, `npm run typecheck`, `npm test` (`node --test`, pure helpers in `test/`).
- 8-bit kit: `src/lib/` (palette, pixel scale helpers, typewriter maths, font loading,
  game maths in `game.ts`, code-drawn sprites in `sprites.ts`), `src/components/` (`PixelText`,
  `DialogBox`, `SafeZoneGuide`, `Sprite` (sheet image or code-drawn art), `HUD`, `CRTOverlay`,
  `Wipe` / `Flash` in `Transitions.tsx`). Everything animates from `useCurrentFrame()` only;
  noise comes from `seeded(seed, frame)`, never `Math.random`. Pixel font sizes are whole
  multiples of 8 px. Third-party files in `public/` are listed in `ASSETS_LICENSES.md`.
- Assets: `src/assets.ts` `assetById(id)` → `{src, kind, licence, frameWidth/frameHeight/frames}`
  for our sprite sheets (`public/sprites/`: mascot (placeholder until 050), slime, coin, heart,
  tiles) and chiptune audio (`public/audio/`: `music-overworld`, `music-cave` seamless loops, play
  with `<Html5Audio loop>`; `sfx-jump`, `sfx-coin`, `sfx-hit`, `sfx-select`, `sfx-confirm`), plus
  the brand styles' warm `music-marimba` bed (104 bpm) and soft `sfx-pop` / `sfx-chime`, and the paper
  style's `music-kalimba` bed (kalimba + glockenspiel, 100 bpm) with `sfx-rip` / `sfx-swish`, and
  three mastered stereo Cutaway candidates `music-cutaway-a|b|c` (`scripts/beds.ts`: lo-fi
  chiptune hip-hop, dusk synthwave, cinematic clockwork; a 2-bar intro, then a seamless 8-bar
  loop: `loopStart_s`). `MusicBed` (every template) plays a bed's intro once then loops it, and
  with a heard voice (`voice.audioSrc`) ducks it (`src/lib/duck.ts`): -5 dB between lines,
  -15 dB while one is spoken, 200 / 250 ms ramps, gaps under 0.6 s stay down. All are
  generated by `node scripts/make-assets.ts` (re-run after editing `src/lib/sprites.ts`, the songs or
  the palette; a test fails when the committed files are stale or a file in `public/` is unlisted).
