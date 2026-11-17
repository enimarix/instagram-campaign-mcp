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
  over the outro so the last frame matches frame 0. Its registry entry sets `coverFrame`.
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
  25 %), `loop`,
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
  with `<Html5Audio loop>`; `sfx-jump`, `sfx-coin`, `sfx-hit`, `sfx-select`, `sfx-confirm`). All are
  generated by `node scripts/make-assets.ts` (re-run after editing `src/lib/sprites.ts`, the songs or
  the palette; a test fails when the committed files are stale or a file in `public/` is unlisted).
