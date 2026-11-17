# Progress: Macrobody Growth Studio

> Roadmap for the `/team-up` loop. **Read [GOAL.md](GOAL.md) first**: it holds the vision,
> the architecture, the data model and the rules that never change. This file only
> says what to do next, in order.

## Goal

An AI-run, human-steered marketing studio on top of this Instagram MCP server: the
agent produces 20–30 short videos a day on two tracks (rights-clear remixes and
original 8-bit motion design), the owner reviews them on a website (like, dislike,
comment, approve), approved videos are published at smart hours, results are measured,
and the system learns every day from analytics and from the owner's comments. Paid ads
with real A/B tests come last. Full description: [GOAL.md](GOAL.md).

## Definition of done

The checklist lives in [GOAL.md §7](GOAL.md#7-definition-of-done). The project is done
when every box there is ticked and every roadmap step below is done or consciously
dropped (with a line under *Follow-ups* saying why).

## How to work this roadmap

- **One step = one PR**, one concern, about 400 changed lines or fewer, tests included,
  `main` stays green. If a step turns out bigger, the tech lead splits it (`012a`, `012b`).
- Steps run **top to bottom**. A step marked `[HUMAN Hn]` needs something from the
  owner (gate table in [GOAL.md §8](GOAL.md#8-what-only-the-owner-can-provide-human-gates)).
  If the gate is not open, move the step to *Blocked* and continue with the next step
  that does not depend on it. Never stop the loop while independent steps remain.
- Every step obeys [GOAL.md §5](GOAL.md#5-rules-that-never-change). In particular: no
  logic in MCP tool handlers or API routes (they call service functions), no network
  in tests, nothing publishes without `approved`, nothing with `rights_basis = unknown`
  is ever queued, no detection-evasion edits (mirror, speed, pitch tricks), and every
  new MCP tool is deliberately placed in or out of the `agent` profile.
- Where a step says **verify in docs**, the developer checks the current official
  documentation before coding (Graph API, Marketing API, Remotion, Claude Code
  headless). Do not code those from memory. What the docs said goes in the PR text.
- A decision that changes a default of GOAL.md goes in `docs/DECISIONS.md` in the same
  PR (`.team-up/lead-notes.md` is git-excluded and does not travel with the repo).
- Commands today: install `pip install -e ".[dev]"`, test `pytest -q` (no network).
  CI: `.github/workflows/ci.yml`, Python 3.10 / 3.12 / 3.13.
- **Before the first step** (state checked on 2026-11-17, after the third plan audit):
  PRs #4 (audit fixes) and #5 (`GOAL.md` + this roadmap) are merged and `main` is
  green. Dependabot PRs #1 (`actions/setup-python` 6 → 7) and #2 (`actions/checkout`
  5 → 7) are still open: merge or close them first so they do not collide with step
  006. `.team-up/` does not exist yet (`teamup init` creates and git-excludes it).
  Step 002 takes the schema **as it is on `main` that day** as migration 1.
- Steps with a letter suffix (`006a`, `023a`, …) were added by the third audit. They
  keep the numbers that GOAL.md and older notes already refer to stable.

### The owner's machine (checked on 2026-11-17; re-check, do not assume)

- Windows 11. Node 24 is installed. **ffmpeg is not installed** (step 031).
- The **`claude` CLI is not on PATH** (only the desktop app): gate H8, step 058.
- The Python on PATH is 3.9; the project needs ≥ 3.10. The installers use uv to get
  3.12, so always run through `.venv`.
- No NVIDIA GPU was detected: renders, local speech-to-text and probably the local
  TTS run on CPU. Step 034 records render time per video; plan batch size on it (step 062).

### Onboarding questions for the tech lead to ask (team-up Phase 0)

1. Channel basics (H9, H1): is "Macrobody" the right name, what is the niche in one
   sentence, which language(s) are the videos in, which countries are targeted, and
   what is the account for (followers, sales of something, leads)?
2. Are the stack defaults in [GOAL.md §4.1](GOAL.md#41-stack-decisions-defaults-change-only-with-a-written-reason-in-docsdecisionsmd) accepted?
3. Which clip sources does the owner have rights to (own files, stock accounts, creators
   who gave permission)? (H4)
4. Daily numbers: batch size (default 10 for the first week, then 25), track mix
   (default follows the clip inventory, up to 50 / 50), maximum posts per day
   (default 3), explore share (default 30 %).
5. Order of the tracks: this roadmap builds Track B (motion) and the agent **before**
   Track A (remix), because Track B needs no gate and gives a daily batch sooner. Say
   so if Track A should come first (then Phase 6 moves before Phase 4).
6. The machine: is it on at night and in the morning? When should the daily runs
   happen, and how much agent usage per day is acceptable? (H8)
7. Autonomy limits and merge strategy (default: squash; never alone: real publishing,
   ad spend, messages to people, repo settings).
8. Funny versus informative: what share of the batch should be humour (`PixelSkit`,
   in-app Remix briefs) and what share facts, quiz and stories? Default 50 / 50, then
   the batch-mix allocator (step 086a) adjusts it from likes and results.
9. In-app Remix: is the owner willing to record 1–2 Remixes a day on the phone from
   the agent's briefs (step 073a)? It is the legal way to react to other creators'
   viral Reels, which the studio cannot download and edit.
10. Mirror / flip, speed and pitch tricks on other people's videos are **not built**
    (GOAL.md §5.1): say so plainly during onboarding, since the original idea listed
    "mirror effect", and explain what replaces it (reaction, voice-over, commentary).

## Roadmap

<!-- small steps: one PR each, one concern, testable, leave the base branch green -->

### Phase 0 — Foundations

- [ ] 001 — Agent docs and layout — `CLAUDE.md` exists (commands, conventions, pointer to GOAL.md and progress.md); folders `agent/playbooks/`, `brand/`, `docs/` exist with a one-line README each; `docs/DECISIONS.md` exists with its format (date, decision, reason); `.gitignore` covers `data/`, `node_modules/`, `web/dist/`, `motion/out/`.
- [ ] 002 — Database migrations and safe access — `CampaignStore` applies numbered migrations tracked with `PRAGMA user_version`; migration 1 is today's schema; every connection sets WAL mode, a busy timeout and `foreign_keys=ON`; no connection is shared between threads (today one connection is opened with `check_same_thread=False`); tests: a database created by the current code upgrades with no data loss, and two store instances on the same file write at the same time without "database is locked".
- [ ] 003 — Controlled vocabularies — `brand/taxonomy.json` (tracks `remix` / `motion` / `inapp`, placeholder pillars, hook types, templates, feedback reason codes) with a loader and a validator; store methods that take a tag reject unknown values with the list of valid ones; tests.
- [ ] 004 — Tables `sources`, `ideas`, `assets` — migration plus store methods (create, get, list with filters); `assets` has `status` (including `publish_check`), a separate `verdict`, `parent_asset_id`, `duration`, `qc`, `preview_path`, `audio_name`, `self_score` + `self_score_reason`, `best_before`, `approved_at`; `ideas` has `citations` (JSON); `assets.status` changes only through one `transition()` function that follows the table in GOAL.md §4.3 and rejects every other move; tests cover every allowed move and one forbidden move per status.
- [ ] 005 — Tables `feedback`, `learnings`, `daily_reports`, `agent_runs` — migration plus store methods; feedback has text, reason codes, optional video time, `wants_changes` and `digested_at`; learnings have kind, scope, evidence (JSON), confidence, origin (owner taste / audience / ads), status; `agent_runs` has a usage field; tests.
- [ ] 006 — Python lint in CI — `ruff check` runs in CI and passes on the whole repo; rules recorded in `pyproject.toml`.
- [ ] 006a — Render-time spike — a throwaway Remotion hello-world, made **outside the repo**, renders a 30 s 1080×1920 composition with pixel text, a few sprites and a scanline overlay on the owner's CPU (no GPU); render time per video, peak RAM and the result of 2 renders in parallel go into `docs/DECISIONS.md`, which is the only file this PR changes. Why this early: batch size × render time decides whether a nightly batch fits at all, and the answer shapes steps 034, 039 and 062 (if 25 videos take 3 hours, the plan needs shorter templates, lower concurrency or a smaller batch before anything is built on it).

### Phase 1 — API and website shell

- [ ] 007 — FastAPI skeleton — `src/api/app.py` with `GET /api/health` and `GET /api/account` (profile, token validity, publishing limit, all through existing client methods); `ig-campaign serve` starts it on `127.0.0.1`; tested with the FastAPI test client and a mocked Graph client. **Setup mode:** today `instagram_access_token` is a required setting, so nothing starts without a token, yet the token is gate H5 and the website, the dev seed (014), the render pipeline and the CI smoke test (099) must all work before it. Make the token optional at load time: the API, worker and website start without it, Graph-backed routes answer `503 {"error": "instagram_not_configured"}`, the worker skips publishing and insight jobs with one clear log line, and the MCP server starts too, its Graph-backed tools returning the same clear "not configured" error instead of the server failing to start. Tests for both modes.
- [ ] 008 — Website password — optional `UI_PASSWORD`; when set, every `/api/*` route except health and login needs a session cookie (`HttpOnly`, `SameSite=Strict`, `Secure` when served over HTTPS); state-changing requests are refused when the `Origin` header is not the site's own; login compares in constant time and locks for a while after repeated failures; the server refuses to bind a non-loopback host without a password; tests for both modes, for a cross-site POST and for the lock.
- [ ] 009 — Website scaffold — `web/` (React, Vite, TypeScript, Tailwind) with app layout, navigation (Inbox, Calendar, Analytics, Learnings, Ads, Settings), typed API client, dev proxy to the API, Vitest set up with one test; a new CI job installs, lints, tests and builds `web/`.
- [ ] 010 — Serve the website from the API — the built `web/dist` is served by FastAPI with SPA fallback; `ig-campaign up` starts API and worker together; README gets a "Run the studio" section.
- [ ] 011 — Media storage and serving — helper for `data/media/<date>/<asset_id>/` paths; `GET /api/media/...` streams files with HTTP range support, needs the session like any other route, and rejects path traversal; tests for range, 404 and traversal.

### Phase 2 — Review inbox and publishing from local files

- [ ] 012 — Assets API — list (by batch date, status, verdict, track; default order: agent `self_score` high to low), get, like / dislike (sets `verdict` only), approve / unapprove, archive, edit caption and best-before; status moves go through `transition()`; tests.
- [ ] 013 — Feedback API — add, list, edit and delete comments on an asset, with reason codes from the taxonomy and an optional video time; a comment with `wants_changes` moves a `ready` asset to `revision_requested`; no comment ever publishes anything; tests.
- [ ] 014 — Dev seed — `ig-campaign dev seed` creates a fake batch (one tiny committed sample video under 50 KB that we generated ourselves, several statuses and verdicts, both tracks) so the website can be built before the pipeline exists; never runs against a non-empty production database without `--force`.
- [ ] 015 — Inbox page — phone-first feed of one day's batch, best agent score first: inline player that plays the light preview copy (`muted`, `playsinline`, so iOS Safari plays it inline), like / dislike (also by swipe on touch screens), a one-tap reason sheet after a dislike (skippable), status chips, explore badge, the agent's score and one-line reason, date picker, filters (track, status, verdict), counters ("12 of 25 reviewed"); large touch targets and keyboard shortcuts on desktop; component tests.
- [ ] 016 — Asset detail and comments — comment thread with reason chips and "pin to this moment", an "ask for changes" switch, caption editor, and a panel showing hook, hypothesis, track, recipe summary, rights basis, citations and QC result; older and newer versions of the same asset are linked.
- [ ] 017 — Reels from local files — `publish_reel` accepts a local `video_path` and uses the Graph API resumable upload (**verify in docs**: `upload_type=resumable`, `rupload.facebook.com`, and the current Reel limits for size, duration, codecs); the path must resolve inside the media root (a tool caller cannot upload an arbitrary file); the cover is set with `thumb_offset`; `audio_name` is passed through (the studio names its original audio, GOAL.md §3.1); payload validation and the scheduler accept it; respx tests for success, processing error, retry and a path outside the root.
- [ ] 018 — Rights rules — `src/studio/rights.py` implements the table in GOAL.md §5.1 as pure functions: `can_publish(source, confirmed)` and `can_advertise(source)`, the refused CC variants, and the attribution text each basis requires; tests cover every row of the table.
- [ ] 019 — Publish guard — one function `queue_asset(asset_id, publish_at)` is the only way an asset reaches `scheduled_posts` and checks: status `approved`, `can_publish` (so `commentary` also needs the owner's per-video confirmation), file exists, QC passed, caption valid; `scheduled_posts` and `post_labels` get a nullable `asset_id`; at publish time the worker checks again that the asset is still `scheduled` and cancels the row if not; after publishing it writes `media_id` back and links the label to the asset (tags are read through the asset, not copied); a publish that failed for good and **certainly did not reach Instagram** returns the asset to `approved`; a `maybe_published` failure moves it to `publish_check` instead (GOAL.md §4.3), and a reconcile job looks for the post on the account (the client already has `_container_published`; also match recent media by caption and time) and moves it to `published` when found; only the owner can send a `publish_check` asset back to `approved`. Tests prove unapproved and `unknown` assets cannot be queued by any API route, and that a `maybe_published` asset cannot be queued again before it is reconciled.
- [ ] 020 — MCP tool profiles — setting `IG_MCP_PROFILE`: `full` (default, today's behaviour, for the owner's interactive sessions) and `agent`, which registers only an allow-list and therefore none of `publish_*`, `schedule_post`, `reschedule_post`, `cancel_scheduled_post`, `run_due_posts`, `reply_to_comment`, `comment_on_media`, `hide_comment`, `delete_comment`, `send_dm`. Also kept out of `agent`: `get_conversations` and `get_conversation_messages` (private DMs of third parties, GOAL.md §5.2) and `label_post` (relabelling published posts would rewrite the data the learning loop trusts). The allow-list of today's tools is written out in the code: `validate_access_token`, `get_profile_info`, `get_account_insights`, `get_publishing_limit`, `get_media_posts`, `get_media_insights`, `get_comments`, `search_hashtag`, `get_competitor_profile`, `list_scheduled_posts`, `rank_posts`, `compare_variants` (and `collect_insights` only if the shared request budget of step 026 exists by then). A test lists the tools of each profile and fails when a tool not on the allow-list is visible to `agent`; README documents both profiles.
- [ ] 021 — Slot planner v1 (rules) — pure function: given a day, a number of posts and existing slots, returns times inside configurable windows with a minimum gap, a maximum per day and a few minutes of jitter; windows are in the owner's time zone and stored in UTC; settings `MAX_POSTS_PER_DAY`, `MIN_SLOT_GAP_MINUTES`, `POSTING_WINDOWS`; tests with fixed seeds, including a daylight-saving change day.
- [ ] 022 — Slot planner v2 (audience data) — client method for followers-online-by-hour (**verify in docs** that the `online_followers` metric still exists in the pinned API version and from how many followers it is available; fall back cleanly if not) stored daily; planner weights windows by it; falls back to v1 with no data; tests.
- [ ] 023 — Approve and schedule in the UI — approving shows the proposed slot with "accept" or "pick another time"; unapproving a scheduled asset cancels its slot; component tests.
- [ ] 023a — The bench — an Inbox tab listing liked, not yet published assets (`ready` + `liked`) from every past batch, freshest best-before first, with days of supply ("9 liked videos = 3 days at 3 a day"); approving from the bench works like approving from today's feed; when the calendar has an empty slot in the next 24 h and the bench is not empty, the Inbox shows a banner suggesting the freshest bench video for it (the owner still approves; nothing is auto-approved; the daily report repeats it once step 083 exists); `best_before` is editable in the asset detail; tests for the supply count and the expiry.
- [ ] 024 — Calendar page — scheduled and published posts by day with reschedule and cancel (existing queue functions), and failed posts with their error and a "re-plan" button.
- [ ] 025 — Worker core — `ig-campaign worker` runs due posts every minute with a heartbeat row; **late-slot policy**: a post more than `MAX_LATE_MINUTES` late is re-planned to the next free slot instead of published, and two publishes are never closer than the minimum gap; a `PUBLISHING_PAUSED` switch holds the queue; `GET /api/worker/status`; on Windows, after every change to the queue the worker (re)registers one one-shot Task Scheduler task with "wake the computer to run this task" a few minutes before the next slot (PowerShell `New-ScheduledTaskSettingsSet -WakeToRun`; no-op on other systems; README explains the "Allow wake timers" power setting); tests with a fake clock for late, burst and paused cases, and a test that the wake task command is built for the right time.
- [ ] 026 — Worker data jobs — insight collection on an age schedule (for example 1 h, 3 h, 6 h, 12 h, 24 h, 48 h, 7 d, 30 d; today `collect_insights` only snapshots when called) inside a Graph request budget kept in the database so the worker, the API and the MCP server share one count; a daily account snapshot in a new `account_snapshots` table (history starts accumulating now), including reach split by followers and non-followers when the API offers it (**verify in docs** the `follow_type` breakdown of account insights in the pinned version), since GOAL.md §2.1 tracks the share of reach from non-followers; a post that the API reports as deleted is marked `deleted_at` on its label and keeps its last snapshot, so analytics still count it (GOAL.md §3.4); tests.
- [ ] 027 — Worker housekeeping — `ready` assets never reviewed for N days are archived, liked ones only once past their `best_before` (the bench must not be emptied by age alone), and the files of archived assets are deleted after M days (published ones are kept; rough size: 25 videos a day at 10–20 MB plus previews is 8–15 GB a month before cleanup, shown on the Settings page); a nightly SQLite backup with rotation into `data/backups/`; a render is refused when free disk space is under a set floor; tests.
- [ ] 028 — Settings page — worker heartbeat, token expiry date, publishing limit, the pause switch, disk usage and last backup.
- [ ] 029 — Token care — `ig-campaign token status` and `token refresh` (exchange for a new long-lived token when the app id and secret are configured; **verify in docs**), a warning in the website from 10 days before expiry, and a README section on the system-user token option; the token is never printed or logged; respx tests.
- [ ] 030 — `[HUMAN H5]` Live check — with a real token: seed one real video, approve it in the UI, let the worker publish it from the local file, confirm it on Instagram; record the outcome and any API surprises in `docs/DECISIONS.md`.

### Phase 3 — Render core (shared by both tracks)

- [ ] 031 — ffmpeg wrapper — `src/studio/ffmpeg.py`: find the binary (`FFMPEG_PATH` or PATH), `probe()` (duration, size, fps, audio), `run()` with timeout and captured log; installers install or explain ffmpeg (Windows: `winget install Gyan.FFmpeg`); CI installs ffmpeg; tests use clips generated by ffmpeg itself (`lavfi`), no binary fixtures.
- [ ] 032 — Recipe model and executor — a typed, JSON-serialisable `Recipe` (ordered list of ops) stored on the asset; `render(recipe, out)` with an op registry; first op `fit_vertical` (1080×1920, 30 fps, H.264 + AAC, blur-fill or crop mode); the same recipe always gives the same output spec; tests.
- [ ] 033 — Audio ops — `voice_over` (mix a voice track, duck the original), `music` (bed at a set level), `mute_original`, and loudness normalisation to about −14 LUFS on every render; tests measure loudness with ffmpeg.
- [ ] 034 — Render queue — `render_jobs` table and worker loop (configurable concurrency, progress, retry, failure reason); a job has an idempotency key so a restarted run does not render the same asset twice, and jobs left "running" by a crash are picked up again; renders write the video, a light preview copy for the inbox (720p, low bitrate, fast start), a poster frame and a thumbnail into the asset folder; render time per job is recorded; while jobs run the machine is kept awake (Windows `SetThreadExecutionState`, no-op elsewhere) so a long batch is not cut by sleep; API to re-render an asset with an edited recipe.
- [ ] 035 — Quality check — after every render: spec (size, fps, codec), duration bounds (default 5–90 s), audio present and loudness, black / frozen stretches, caption length and hashtag count (reuse `caption_problem`, which allows 30 today: **verify in docs** whether Instagram now accepts fewer hashtags per post and make the cap a setting), and the claim-wording check of GOAL.md §5.6 (a warning, not a failure); result saved as `assets.qc`; an asset failing QC becomes `failed`, never `ready`; tests for each failure.
- [ ] 036 — Voice provider interface — `TTSProvider.synthesize(text, voice) → audio file (+ word timings when the engine gives them)`; providers `none` (no voice, captions only) and `http` (URL and request template from settings, mocked in tests); a timing estimator spreads caption lines over the audio when no timings exist; results cached by text hash.
- [ ] 037 — Brand kit file — `brand/brand.json` (logo path, colours, font, handle, safe zones for the Reels interface) with a placeholder logo; a Python loader with validation; the same file is readable by `motion/`; tests.
- [ ] 038 — `[HUMAN H3]` Plug in the local TTS — configure the owner's service in the `http` provider (or write a small adapter), render one sample, owner confirms the voice and the language. **Verify in docs** whether the publishing API can set Meta's AI label (GOAL.md §5.6) and write the answer in `docs/DECISIONS.md`.

### Phase 4 — Track B: 8-bit motion design

- [ ] 039 — Remotion scaffold — `motion/` project, 1080×1920 at 30 fps, template registry, props validated by a schema, `node motion/render.mjs --template <id> --props <file> --out <file>`; CI typechecks and renders one still. **Verify in docs**: current Remotion version, render API, the headless browser it downloads, and licence terms (write the licence conclusion in `docs/DECISIONS.md`).
- [ ] 040 — 8-bit foundations — palettes read from the brand kit, a pixel font with an open licence **whose glyphs cover the channel language(s)** (accents, or another script: check against H9, default Latin with accents), crisp integer scaling, components `PixelText` (typewriter) and `DialogBox`, the safe-zone guide, and a preview composition.
- [ ] 041 — 8-bit game kit — components `Sprite` (sprite-sheet animation), `HUD` (hearts, score, level bar), CRT / scanline overlay, transitions (wipe, flash); added to the preview composition.
- [ ] 042 — Sprites and sound — a CC0 sprite and tile pack, a placeholder mascot, CC0 or code-generated chiptune loops and sound effects, all loadable by id; every third-party file listed with its licence in `motion/ASSETS_LICENSES.md`; a test fails when a file in the assets folder is missing from that list.
- [ ] 043 — Script timeline and captions — a shared helper that turns script lines plus voice timings (or estimated timings with the `none` voice) into scene durations and a `Captions` component; every template starts with a clean hook frame at a fixed offset that is used as the Reel cover, and the hook text is on screen within the first second, readable with the sound off; an optional `loop` prop makes the last frames lead back into the first (seamless replay); unit tests on the timeline maths.
- [ ] 044 — Template `FactQuest` — hook screen, 3–5 facts as game levels, end card; length follows the timeline; props schema documented, with a `citations` field carried from the idea.
- [ ] 045 — Template `BossBattle` — A versus B, or myth versus fact, as a boss fight with health bars and a verdict.
- [ ] 046 — Template `QuizChest` — question, choices, countdown, reveal; built to invite comments.
- [ ] 047 — Template `DialogStory` — an RPG-style dialogue between the mascot and a character that tells a short story or explains one idea.
- [ ] 047a — Template `PixelSkit` — the humour template: a 10–20 s relatable "POV:" sketch acted by pixel characters, in 2–4 beats (setup, escalation, punchline, optional tag), with comic timing controls (a hold before the punchline, a freeze-frame, a sound-effect sting) and `loop` on by default; props are beats with a line and an action each, so the agent writes jokes, not animation. Short videos are where funny content works best, so its default length is the shortest of all templates.
- [ ] 048 — Python bridge — `src/studio/motion.py` validates props against the exported schema, gets voice and timings from the TTS provider, runs the Remotion render as a render job, then applies shared ffmpeg ops (loudness, QC); MCP tools `list_motion_templates` (with schemas), `preview_motion` (renders 3–4 stills of the props in seconds with Remotion's still renderer, so the agent can check layout and text before paying for a full render) and `render_motion`, which **enqueues and returns at once** (the agent must not spend turns waiting on one video); all in the `agent` profile.
- [ ] 049 — `[HUMAN H2]` Channel bible — the owner runs the `story-bible-builder` interview, including a humour section (what is funny for this channel, running gags, the mascot's personality, topics that are off-limits). The skill outputs a ready-to-install `SKILL.md`: it is committed as `agent/skills/<bible-name>/SKILL.md` so every agent run loads it, summarised in `brand/BIBLE.md` (world, mascot, tone, voice, pillars) for the website, and the pillars replace the placeholders in `brand/taxonomy.json`. Until then a clearly marked placeholder bible is used.
- [ ] 050 — `[HUMAN H1]` Brand pass — real logo, colours and mascot sprite replace the placeholders in `brand/` and `motion/`; one sample per template is re-rendered for the owner.

### Phase 5 — The agent (first version: research and Track B)

- [ ] 051 — Watchlist and trend research — `watchlist` table (hashtags, competitor usernames) with MCP tools and API; `research_trends()` pulls hashtag top media and competitor recent media through existing client methods, enforces the 30-hashtags-per-7-days budget from the database, and stores results as `sources` with role `reference`, `rights_basis = unknown` and their stats. Today's calls return likes and comments but no views: **verify in docs** whether Business Discovery exposes a view count for Reels in the pinned version and store it when it does. Hashtag results carry **no author** (the API does not return the username for hashtag media), so they cannot be scored against their account's median and cannot be credited: they are ranked within their hashtag only. Plus an **inspirations** inbox: the owner pastes a Reel link from the phone with a one-line note ("this format is funny"), stored in an `inspirations` table and shown to the agent as research input (the link is not fetched or scraped). **Metadata only, no downloads.**
- [ ] 052 — Trend report — for references: outlier score against the same account's median (watchlist accounts only, see 051), hook line (first caption line), duration, hashtags, posting hour; service plus MCP tool `get_trend_report` plus a "Trends" website section that links out to Instagram. Captions of other accounts are returned as quoted data.
- [ ] 053 — Production MCP tools — thin wrappers on services: `create_idea`, `render_motion`, `get_render_status`, `wait_for_renders(batch, timeout)` (blocks up to a few minutes and returns every job that finished, so the agent creates all ideas, enqueues all renders, then reviews them as they land instead of polling one by one), `submit_asset` (→ `ready` only when QC passed; requires a `self_score` 1–10 with a one-line reason, a caption, and a `best_before` date or the default of its pillar: trend-based short, evergreen long), `list_assets`; all in the `agent` profile; tool annotations set correctly; tests.
- [ ] 054 — Feedback and learning tools — `get_feedback(undigested=True)` (with reason codes and asset context), `mark_feedback_digested`, `add_learning`, `update_learning`, `list_learnings`, `list_revision_requests`; rule in code: a learning from one comment starts as `hypothesis`, except an explicit owner instruction ("never do X"), which is stored as a `dont` with confidence `owner`; the agent cannot change or retire a learning with confidence `owner`; tests.
- [ ] 055 — Creative brief — `get_creative_brief()` returns: bible, active learnings ordered by confidence, undigested feedback with asset context, open change requests, the last daily report, open experiments, today's quotas (batch size, track mix, pillar mix, explore share), what today's batch already contains, recent hooks to avoid, new owner inspirations, and the bench: days of supply and what it already holds. **Batch size follows the bench**: the configured size minus the surplus beyond a target supply (default 3 days), with a floor (default 5) so learning never stops, and the freed share goes to explore; service, MCP tool, tests for the batch-size rule.
- [ ] 056 — Quotas, duplicates and sources — `create_idea` rejects near-duplicates of the last N days (normalised text similarity on hook and topic), ideas that break the day's quotas, tags outside the taxonomy, and ideas whose script states facts without `citations`, each with a reason the agent can act on; the remix quota is capped by the number of publishable clips in the inventory; tests.
- [ ] 057 — Self-review tool — `get_asset_frames(asset_id)` returns a small fixed number of downscaled frames (default 4, about 540 px wide) plus the QC result, so the agent can look at its own render and fix or drop it before submitting without burning its context.
- [ ] 058 — Agent runner — `ig-campaign agent run <playbook>` starts Claude Code headless (`claude -p`) with this MCP server in the `agent` profile, **locked down as in GOAL.md §4, third rule**: `--strict-mcp-config` with a generated MCP config that starts only our server; `--allowedTools` for `mcp__<our server>__*`, Read, Glob, Grep, WebSearch and WebFetch; `--disallowedTools` Bash, Edit, Write, NotebookEdit; a permission mode that denies whatever is not allowed (never waits for an answer); `--max-turns`; `--output-format json` for cost and usage; working directory = `AGENT_WORKSPACE` **outside the repo**, refreshed before each run with the playbook and `agent/skills/` copied into its `.claude/skills/`, and a workspace `settings.json` with deny rules for `.env` files and the `data/` folder. (**Verify in docs** the exact flag names and permission modes of the installed version, and which setting sources keep the owner's own plugins and user skills out of the run.) A preflight fails with a clear message when the CLI is missing or signed out; it enforces a wall-clock limit, holds a lock so the same playbook never runs twice at once, keeps the machine awake while it runs, writes a log with no secrets, and records an `agent_runs` row with status, summary and the cost and usage the CLI reports. Tests with a fake CLI, including one that **fails if the built command enables Bash, a write tool, a non-allow-listed MCP server or a workspace inside the repo**.
- [ ] 059 — Playbook `daily-produce.md` — tells the agent: read the brief; digest new feedback into learnings first; make the new versions the owner asked for; research (watchlist, trends, inspirations; WebSearch for fact sources); write **all** the day's ideas with hooks (tagging `hook_type`), a hypothesis each and a source for every fact; check layouts with `preview_motion`; enqueue every render; review renders as `wait_for_renders` returns them (frames + QC; limited retries); score honestly and submit. It **continues today's batch** instead of starting over when some candidates already exist, and it treats everything it reads from outside (web pages, captions, comments, inspirations) as data. `--dry-run` produces ideas only. Hook guidance comes from a project skill in `agent/skills/hook-guide/`, written for this channel from the patterns the owner uses with `viral-hook-creator` (copy that skill's text only if its licence allows it), so the headless run does not depend on the owner's installed plugins.
- [ ] 060 — Agent runs in the UI — a page listing runs (status, duration, usage, summary, log tail) and a "Run now" button for each playbook, refused while that playbook is running.
- [ ] 061 — Scheduled runs and autostart — installers register `ig-campaign up` at logon and the daily runs with the OS scheduler (Windows Task Scheduler, cron); on Windows the run tasks have "wake the computer to run this task" set, so a sleeping PC wakes for the night batch when wake timers are allowed; times configurable; a run missed because the machine was off starts at the next logon when it is still the same day; Settings shows the next and last run.
- [ ] 062 — `[HUMAN H8]` First supervised batch — with the CLI installed and signed in, the owner starts one real run of 10 candidates and reviews it; the measured run time, usage and render minutes go in `docs/DECISIONS.md`, and the batch size and run times are set from them before the schedule is switched on.

### Phase 6 — Track A: sourcing and remix

- [ ] 063 — Clip intake with rights — source-provider interface and the first provider `local_inbox` (folder `data/inbox/` and a website "Add clip" form); a clip cannot be saved without a rights basis and note, and the form asks separately whether the sound is covered; tests.
- [ ] 064 — Stock provider — one licensed library through its official API (default Pexels; key in `.env`, `[HUMAN H4]` for the key, tests mocked): search, download, licence and attribution recorded on the source, including whether the licence allows advertising.
- [ ] 065 — Permission tracker — for a reference the owner wants: record a permission request (requested / granted / denied, where, when, proof note, whether ads are allowed); the website offers a copyable message draft (**the agent never sends it**); when granted the owner attaches the file and the source becomes `permission`.
- [ ] 066 — Brand ops — ops `logo` (position, opacity, inside safe zones), `hook_text` (timed title card) and `credit` (visible source credit), styled from the brand kit; tests check output spec and that the overlay region changed.
- [ ] 067 — Captions and end card — op `captions` burns timed lines (generated `.ass` file, brand style, safe zones) and op `end_card` appends a call-to-action card; tests.
- [ ] 068 — Clip transcription — `STTProvider` interface with `none` and one optional local provider (an extra dependency, CPU, mocked in tests) that returns timed lines for the `captions` op; the owner can correct the lines in the asset detail before a re-render.
- [ ] 069 — Remix builder — service `build_remix(source, hook, script, captions, credit)` returns a recipe from the ops; attribution is mandatory for `cc`, `permission` and `commentary`; third-party sound is muted and replaced unless the source says it is covered; MCP tools `list_sources` (publishable clips only) and `render_remix`, both in the `agent` profile; tests.
- [ ] 070 — Reaction collage op — layouts split (clip top, reaction bottom) and picture-in-picture, sync by offset, mixed audio; tests.
- [ ] 071 — Reaction recorder (website) — a page that plays the clip while recording webcam and microphone (MediaRecorder), uploads the take, lets the owner redo it, and enqueues the `reaction_collage` render. Camera access only works on `localhost` or HTTPS: the page explains this when the browser refuses (gate H7).
- [ ] 072 — "To record" flow — asset status `needs_reaction` with its own Inbox tab; after compose the asset becomes `ready`; approving a `commentary` asset shows the rights confirmation checkbox required by step 019.
- [ ] 073 — Both tracks in the playbook — `daily-produce.md` and the quotas use Track A when publishable clips exist (reaction ideas go to `needs_reaction`), and fall back to Track B for the rest of the batch; dry-run test with an empty and a filled inventory.
- [ ] 073a — In-app Remix briefs — an idea of track `inapp` (added to the taxonomy) is a **brief, not a render**: link to the reference Reel (a watchlist post or an owner inspiration), the reaction angle, the hook to say or show in the first second, a 3–5 line script, the proposed slot. Briefs appear in their own Inbox tab ("To record in the app", at most `MAX_REMIX_BRIEFS_PER_DAY`, default 2, counted in the batch quotas); the owner records the Remix with Instagram's own Remix feature on the phone (only possible when the creator allows remixing) and publishes it there; then, in the website, "link the published post" picks it from the account's recent media and sets `post_labels.idea_id`, so its results are measured and tagged like any studio post. MCP tool `create_remix_brief` in the `agent` profile; tests for the quota and the linking.

### Phase 7 — Analytics

- [ ] 074 — Analytics API — overview series from `account_snapshots`, posts table (latest snapshot, score, verdict, tags) and post detail (snapshot time series, hypothesis, source asset); reuses `src/scoring.py`; queries are indexed and per post (today `snapshot_history()` loads every snapshot into memory, which the age schedule of step 026 makes too heavy); tests.
- [ ] 075 — Retention metrics — the video length is known for our assets: add watch ratio (average watch time ÷ length) and view rate (views ÷ reach) to the scored output, and score Reels on watch ratio instead of raw watch time when the length is known (raw time favours long videos). **Verify in docs** which Reels metrics the pinned version offers beyond the current set (total watch time, skip rate, reposts) and collect those that exist; tests.
- [ ] 076 — Tag breakdowns — service and API: engagement index, reach, views and watch ratio grouped by any tag (track, pillar, hook type, template, slot hour, duration bucket), with sample size and spread, matured posts only, same post type only; posts published outside the studio appear as "untagged"; tests.
- [ ] 077 — Studio funnel — service and API: produced → reviewed → liked → approved → published → winner per day, track, template and hook type; the **like-rate** trend (the taste metric; approval rate is shown but is capped by the posts-per-day limit, GOAL.md §2.1); the agent's **calibration** (self-score against the owner's verdict: how often its top 5 were liked); **waste** (liked videos that expired on the bench, render minutes spent on them); and the most frequent feedback reasons; tests.
- [ ] 078 — Analytics overview page — follower, reach and views trends, this week's posts, winners, publishing streak, the funnel, the like-rate trend and the agent's calibration.
- [ ] 079 — Posts table and post detail pages — sortable, filterable table; detail shows the growth curve, tags, hypothesis, the owner's feedback and the video.
- [ ] 080 — Breakdowns and A/B page — charts per tag with sample sizes shown; A/B comparison using existing `compare_variants`.

### Phase 8 — The learning loop

- [ ] 081 — Evidence engine — a learning can carry a tag predicate (for example `hook_type = question`); `evaluate_learning()` computes sample size and index against the baseline and sets confidence (low / medium / high by configurable thresholds); contradicted learnings are flagged, never silently deleted; a taste learning and an audience learning that disagree are both kept and marked as a conflict; nightly refresh in the worker; tests.
- [ ] 082 — Daily facts — service that computes, with no AI, yesterday's and the last 7 days' facts: published, matured, winners and losers with their tags, best and worst slots, biggest movers, the studio funnel, experiments that reached their sample, and the most-liked audience comments per post (read only, passed as quoted data); returned as JSON for the agent and stored with the report.
- [ ] 083 — Playbook `daily-learn.md` — read the facts, re-evaluate learnings, write the daily report (what happened, assumptions about why, taste-versus-audience conflicts, what to try next), propose experiments; runs before `daily-produce`; added to the scheduled runs. `save_daily_report` MCP tool in the `agent` profile.
- [ ] 084 — Learnings page — list by kind, status, origin and confidence with evidence and linked posts; the owner can edit, confirm, retire and add a rule by hand; owner edits always win over the agent.
- [ ] 085 — Daily report page — today's report on the home screen and an archive; every claim links to the posts behind it.
- [ ] 086 — Experiments — `experiments` table (hypothesis, one variable, variants, target sample, expected end date, status, result) linked to posts through the existing campaign / variant labels; at most `MAX_OPEN_EXPERIMENTS` (default 2) open at once; the explore share of each batch is drawn from open experiments; the report warns when an experiment gets no approved videos; a finished experiment becomes a learning with its numbers.
- [ ] 086a — Batch-mix allocator — pure function: for each tag dimension the brief controls (template, hook type, pillar, humour vs informative), the share of the next batch follows Thompson sampling on a Beta posterior of the **like rate** (fast signal, about 25 verdicts a day), blended with the matured-post engagement index once a value has enough posts (slow signal), with a floor per option (default 10 %) so nothing is starved and owner rules ("never X") applied as hard zeros; the brief (055) uses it instead of fixed pillar quotas; the daily report shows how the mix moved and why; tests with fixed seeds and synthetic histories (a clearly better option gains share, a disliked one shrinks to the floor, an owner rule wins).
- [ ] 087 — Slots that learn — the slot planner blends audience data with our own results per hour, mostly using the best hours and reserving a small share for testing new ones; tests with synthetic history.
- [ ] 088 — Trial Reels for experiments — approving an explore item offers "publish as trial Reel" (existing `trial_graduation`), recorded as a tag so trial and normal posts are never compared with each other.

### Phase 9 — Paid ads and A/B tests

- [ ] 089 — `[HUMAN H6]` Ads access — ad account id, payment method, `ads_management` + `ads_read` on the token, an account spending limit set by the owner in Meta, and the ad objective; ids go in `.env`.
- [ ] 090 — Marketing API client, read only — ad accounts, campaigns, ad sets, ads, insights (**verify in docs** for the pinned API version); same error and rate-limit handling as `InstagramClient`; respx tests.
- [ ] 091 — Budget guard — caps per day, per test and lifetime in settings, a spend ledger in the database, `authorize_spend()` called by every function that can spend, and a kill switch that pauses everything and blocks new spend; tests prove no write path skips it.
- [ ] 092 — Create ads, always paused — campaign, ad set and ad from an existing Instagram post (a winner whose asset passes `can_advertise`), with objective, audience and placement presets; every ad set has a lifetime budget and an end date and every campaign a spend cap, so Meta itself stops the spend; **verify in docs** the fields Meta requires for ads shown in the EU (who benefits, who pays) and the creative fields for promoting an existing post; ids stored in `ad_entities`; nothing is ever created active; tests.
- [ ] 093 — A/B test model — `ad_tests`: one variable (creative, audience or placement), equal budgets, minimum duration and sample, a primary metric, a significance test, stop rules, and a **sample-size estimate** (the budget needed to detect a given lift at the account's usual cost), as pure functions with tests; use Meta's native split test if the docs confirm it fits, otherwise equal separate ad sets.
- [ ] 094 — Approve and launch — API and Ads page: "propose a test" from eligible winners, the owner sees the needed budget, sets it and approves **after typing the website password again**; only then are the ads activated; kill switch button; audit log of what was approved and when.
- [ ] 095 — Ad results — worker job collects ad insights, spend and Meta's review status (an ad that Meta rejects or limits is shown with the reason); the ledger is reconciled with the spend Meta reports; results page with spend, primary metric, significance and the declared winner; warning when spend nears a cap.
- [ ] 096 — Ads for the agent — MCP tools to propose tests and read results, in the `agent` profile (no tool there can activate, approve or raise a budget); playbook `weekly-ads.md` proposes tests from organic winners with a hypothesis each and turns finished tests into learnings.

### Phase 10 — Hardening and handover

- [ ] 097 — Restore and retention — `ig-campaign restore <backup>` tested end to end on a copy; old insight snapshots are thinned (keep the age-schedule points, drop the rest) so the database stays small; retention settings documented.
- [ ] 098 — Alerts — a notification area in the website for failed publishes, re-planned late slots, a token expiring within 10 days, failed or over-budget agent runs, QC failure spikes, a stale worker heartbeat and ad caps.
- [ ] 099 — End-to-end smoke test — Playwright: seed, open inbox, like, comment, approve, slot appears in the calendar, worker "publishes" against a mocked Graph API; runs in CI.
- [ ] 100 — One-command setup and README — installers set up Python, Node dependencies, the website build, the ffmpeg check, the Claude Code CLI check and the scheduled tasks on Windows, macOS and Linux; README rewritten: setup, a normal day (including the AI label if it must be set by hand), recovery (expired token, failed publish, stuck render, restore from backup).
- [ ] 101 — Final review — walk the checklist in GOAL.md §7 on the owner's machine with the owner, fix or file what fails.

### Milestones (what the owner can do after each phase)

| After | The owner can |
|---|---|
| Phase 0 | Know whether the machine can render a daily batch at all (step 006a) |
| Phase 2 | Review seeded or hand-added videos on the phone, approve them, keep liked leftovers on the bench, and have them published at planned hours, with late slots handled, no double posts and a nightly backup |
| Phase 4 | Get original 8-bit videos rendered from a script |
| Phase 5 | Wake up to a daily batch of motion videos made by the agent, which already learns from likes, reasons and comments |
| Phase 6 | Add rights-clear clips, get branded remixes and reaction collages in the same batch, and record in-app Remixes from the agent's briefs |
| Phase 7 | See what works: trends, winners, tag breakdowns, the like-rate trend and how well the agent predicts the owner's taste |
| Phase 8 | Read a daily report and watch the agent change behaviour from results as well as comments |
| Phase 9 | Run capped, approved ad tests on proven winners |

## Done
<!-- - [x] 000 — <title> — PR #<n> (<date>) — <one-line outcome> -->

## Blocked / needs human
<!-- - <step> — <what is needed> — see .team-up/BLOCKED.md -->
Gates not yet opened by the owner (details in GOAL.md §8). The steps that depend on
them are marked `[HUMAN Hn]` above; everything else can proceed against placeholders.

- H1 — brand kit (logo, colours, niche)
- H2 — channel bible interview (`story-bible-builder`)
- H3 — local TTS service details
- H4 — licensed clip sources and API keys
- H5 — live Instagram token and first real publish test
- H6 — Meta ad account, payment method, ads permissions, account spending limit, objective
- H7 — how the website is reached from the phone (HTTPS needed to record on the phone)
- H8 — Claude Code CLI installed and signed in, accepted budget per run
- H9 — content language(s), target countries, what the account is for

## Follow-ups (parked from reviews)
<!-- - <idea> (from step <id>) -->
- Other networks (TikTok, Shorts) reusing the same assets and review flow.
- A third track with AI-generated footage.
- More motion styles after 8-bit (the template registry already allows it).
- Idea-level approval: the owner approves hook and storyboard cards before anything is rendered. Worth doing if the like rate stays low after a few weeks, because most renders are then wasted.
- Carousels and Stories made from the same 8-bit templates (stills are cheap to render and the publishing tools already exist).
- Reply drafts for audience comments: the agent drafts, the owner approves each one in the website before it is sent (never unattended, GOAL.md §5.2).
- Installable website (PWA) with a notification when the daily batch is ready (needs HTTPS, gate H7).
- The same video in a second language (new voice-over and captions on the same recipe).
