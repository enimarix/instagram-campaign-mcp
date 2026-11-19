# Decisions

Decisions that change a default of [GOAL.md](../GOAL.md), or that later work depends on.
One entry per decision, newest first:

```
## YYYY-MM-DD: <decision>
Reason: <why>
```

## 2026-11-19: One heavy GPU job at a time; one render at a time (145)
A machine-wide OS file lock (`src/studio/gpu_lock.py`, `GPU_LOCK_PATH`, default
`~/.ig-campaign/gpu.lock`) lets one heavy GPU job run at a time across processes: every
Blender and Remotion render (worker, MCP previews, dev scratch studios) holds it while its
renderer runs, and the voice service holds it for as long as VoxCPM2 is loaded. The voice
service loads its models on the first request and drops them after `VOXCPM_IDLE_UNLOAD_S`
(120 s) idle, so a render waits at most that long after the last voice-over; each voice-over
after an idle spell pays a ~35 s load. `RENDER_CONCURRENCY` default goes from 2 (step 006a) to
1; the setting stays for a bigger machine.
Reason: the owner's laptop (RTX 3070 Laptop, 8 GB) froze hard on 2026-11-19 with the voice
model resident (6.2 GB VRAM) and two Blender renders at once; owner: "safety first". Holding
the lock while the model is loaded (not only during a take) is what keeps a render from
starting next to 6 GB of resident model.

## 2026-11-19: The voice is VoxCPM2, local, at the owner's settings (038)
The studio's voice-over is VoxCPM2 (OpenBMB, Apache-2.0) on the owner's GPU, served by
`vendor/voxcpm_tts` and called through the `http` TTS provider. Settings chosen by ear in
two casting rounds ("we use the computing power necessary to generate the best quality
audios"): the whole script in one take, `cfg_value` 1.6, 30 inference steps, cloned from a
voice card as continuation (card + its text) and as reference. Never lower by default; never
split below whole script lines (short takes garble short words). Each take is checked by
Whisper large-v3-turbo on the CPU (keeps VRAM under 8 GB) and redone up to 3 times under a
0.9 word-match score, best take kept. Voices: `conteur_grave` (default), `coach_energique`,
`douce_nuit` (`brand/voices/`); the agent picks one per video from `voices.json`. Numbers,
units, times and the brand are spelled out for speech only; "kcal" is said "calories".
OmniVoice was rejected; default VoxCPM2 settings were judged "really bad". `TTS_TIMEOUT_S`
default goes from 120 s to 3600 s: ~3.7 s of GPU per second of audio and up to 3 takes, one
request at a time, so parallel render_motion calls queue for minutes.
Reason: the owner's choice (H3, 2026-11-19) after listening to both engines and 8 voices.

## 2026-11-19: Trending means recent; Reels come from watched accounts (140)
The Tendances feed shows only what was posted within `TRENDING_MAX_AGE_DAYS` (default 21,
`.env`); older posts and posts without a date are hidden (counted in `hidden_old`) unless
`?include_old=1` ("Afficher les anciennes"). Inside the window the order is the outlier
score × freshness, 0.5^(age in days / 7) (half-life `FRESHNESS_HALF_LIFE_DAYS` = 7), then
newest; the card still shows the raw outlier. The suggested topics now include business
accounts Business Discovery answered for (2026-11-19): accounts spend no hashtag budget and
bring the Reels, while hashtag search returned 155 carousels, 38 images and 1 video out of
194 posts on the owner's live watchlist.
Reason: live data, 2026-11-19: the feed's first card was a #recettefit post from 2020
(2 272 days old) ranked on its outlier alone, and the owner asked for what is hot now.

## 2026-11-18: The AI runs the ads within the owner's caps (126)
Owner's words: "Let's leave the ad management to the AI. The app will all just validate
creations that gets to be published, and all the parameters … editable in the website."
The agent launches (`launch_ad_test`), stops (`stop_ad_test`) and judges paid A/B tests
on its own; there is no per-test approval. Any published post the owner approved whose
rights allow ads may be advertised. The agent's budget is the test's need, capped by
what the caps allow; it never launches an underpowered test and launches only its own
proposals. Refused before any request: kill switch on, a cap reached, `ads_max_running_tests`
already running, a post not published or no longer advertisable. Every action is audited
with `actor = "agent"`. The owner keeps Stop all ads and an Approve button for proposed
tests, now without the password; the password stays for raising a cap and for turning ads
back on. Replaces GOAL.md §3.6 "nothing spends money without the owner's approval in the
UI" and §5.4 "approving a budget asks for the website password again".
Reason: the owner's answer of 2026-11-18; the caps, the kill switch and Meta's account
spending limit (H6) bound the money, and a source test proves the agent's tools reach
money only through `tests.launch` and `tests.cancel`.

## 2026-11-18: Settings editable on the website, over .env (124)
Owner's answer: the ad settings (caps, currency, objective, test length, tests at once,
EU DSA fields, ad account and Page ids) are edited on the website, Settings > Ads. They
are stored in the database over the `.env` values and validated by the same rules; every
process (API, worker, MCP server, agent runs) picks a change up within 30 s, the budget
guard at its next check. Secrets stay in `.env` only. Raising a money cap asks the
website password again; so does changing the currency while a cap is above 0 (it changes
what every cap means). Audience and placement presets stay read-only for now. Every
change to an ads setting writes an `ads_audit` row.
Reason: the owner steers from the website; a cap must never rise without the password.

## 2026-11-18: The agent proposes ad tests weekly, never approves them (096)
Four agent-profile MCP tools: `list_ad_winners`, `propose_ad_test` (stored with
`proposed_by = "agent"`; at most `MAX_AGENT_PROPOSALS` = 3 waiting for the owner),
`list_ad_tests`, `get_ad_test_results`. None reaches approve, activate, cancel, the kill
switch, the caps or the writer (a test walks their calls). The `weekly-ads` playbook turns
finished tests into `ads` learnings whose evidence carries the `test_id`. Weekly runs:
`AGENT_SCHEDULE` entries take an optional weekday, `weekly-ads@mon 04:00` (Task Scheduler
`-Weekly -DaysOfWeek`, cron day of week); a missed weekly run waits for the next week.
`weekly-ads` is not in the default schedule: the owner adds it after H6. Its run is
skipped (no Claude launch) while ads are not configured or there is nothing to do.
Reason: a paid test is the owner's decision; a weekday in the schedule costs no empty run.

## 2026-11-18: A/B tests run at least 7 days; budgets from the account's rates (094)
`abtest.TestSpec.min_days` defaults to 7 (was 4): Meta's A/B testing best practices say
"we recommend a minimum of 7-day tests" (Business Help Center, article 290009911394576).
The budget a test needs uses the account's CPM and CTR over its last 90 days of insights,
else `ADS_DEFAULT_CPM` (5, a guess) and a 1 % CTR. Variants are separate equal-budget
campaigns, not a Meta `ad_studies` SPLIT_TEST (it needs a Business ID, not set before
H6). Approval asks the website password again; a failed approval pauses everything and
cancels the test. Cancelling a running test keeps its reservations until 095 reconciles.
Reason: shorter tests miss day-of-week swings; an unknown CPM must not block a proposal.

## 2026-11-18: Paused promotions: one reservation per ad set, spread over its days (092)
A promoted post (`ads.promote.create_paused_promotion`) reserves its lifetime budget once,
when its ad set is created. For `ADS_DAILY_CAP` the budget counts as budget / days (owner
-local days from today to the end date, rounded up to the cent) on each of those days;
the test and lifetime caps count it in full. The campaign, creative and ad only run the
guard's checks (kill switch, caps), so they never double-count. The campaign's spend cap
is the budget, raised to Meta's minimum (100 in the account currency, about 100 USD)
when the budget is smaller: the ad set's lifetime budget is then the binding Meta-side
limit. Default objective `ADS_OBJECTIVE=OUTCOME_AWARENESS` (reach, billed on
impressions); `OUTCOME_ENGAGEMENT` optimises ThruPlay. Every ad set carries the EU
Digital Services Act fields (`ADS_DSA_BENEFICIARY`, `ADS_DSA_PAYOR`, required), and the
creative needs `META_PAGE_ID`. A failure halfway leaves the created objects paused and
recorded and releases the reservation; activation (094) authorizes again.
Reason: GOAL §5.4 asks for a daily cap, and a whole lifetime budget counted on day one
would force the daily cap up to the largest promotion.

## 2026-11-18: Ad spend caps default to 0 and re-enabling spend needs UI_PASSWORD (091)
`ADS_DAILY_CAP`, `ADS_TEST_CAP` and `ADS_LIFETIME_CAP` default to 0, so nothing can be
authorized until the owner sets them (in `ADS_CURRENCY`, default EUR until H9 names the
account's currency; it must match the ad account). Turning the kill switch off
(`POST /api/ads/unkill`) asks the website password again; without `UI_PASSWORD` it is
refused (`password_not_set`), and 094's budget approval uses the same check
(`auth.reauth_error`). Turning it on needs no password. Amounts are Decimals: floats are
refused. While a test runs its authorization and Meta's reported spend both count against
the caps (over-counting) until 095 reconciles.
Reason: money is the one thing a bug can lose for good; every unsure case refuses.

## 2026-11-18: AI-made videos are published with Instagram's AI label, or not at all (120)
Replaces GOAL §5.6's fallback ("set the label by hand in the app"): the Graph API can set
it (`is_ai_generated`, changelog 2026-06-22). `studio.publish.ai_generated(asset, idea)`
says yes for a motion render, a remix with a voice-over, an idea with a script, and
anything unsure; no only for an ffmpeg edit without a voice-over of an idea without a
script. The flag is stored in the queued post's payload. When Meta refuses the parameter
(an error naming it at container creation), the post fails for good with the reason and
the publish-failed alert, and the asset goes back to `approved`. No setting for "publish
without the label" yet: add one only if the owner asks. The owner's MCP tools
`publish_reel` and `schedule_post` (reel) take `ai_generated`, default true (121); any
queued Reel whose payload predates the flag is labelled.
Reason: posting AI content unlabelled is the worse outcome; the label can't be added
later through the API (IG Media updates take only `comment_enabled`).

## 2026-11-18: Experiments link to posts through the idea, not post labels (086)
Changes the roadmap's "linked to posts through the existing campaign / variant labels".
An idea joins an experiment variant with `ideas.experiment = 'exp:<id>:<variant>'` (no new
column; older free-text values are kept and count as no experiment); a post reaches it
through post_labels.asset_id → asset → idea. `create_idea` refuses any other experiment
value. The variable must be a tag dimension of the evidence engine, so a finished
experiment becomes a learning with a checkable predicate. `EXPERIMENT_MIN_SAMPLE` is gone:
each experiment has its own `target_per_variant` (default 5 matured Reels).
Reason: the idea already carries the tags being tested and exists before the post, so the
explore ideas can be planned and counted while they are made; campaign / variant labels
are set only at publish time and are free text.

## 2026-11-18: DM picks may exceed the batch cap, up to 3 a day (073)
A remix idea whose source is a DM pick being made (`downloaded` or `in_production`) may be
created when today's batch is already full, up to `MAX_DM_PICK_EXTRAS_PER_DAY` (default 3,
owner-local batch day) such extras. They sit outside the batch's humour / informative
split; the explore quota and the reaction quota (`MAX_REACTIONS_PER_DAY` + margin) still
apply, and picks still come first in the night run's `reactions_plan`. Checked in
`src/studio/production.py` (create_idea).
Reason: the owner's request 2026-11-17: a Reel a pinned account sends by DM is reworked
promptly ("when somebody sends you reels from that account… rework it so we can repost
it"), so the afternoon run (`daily-revise`) can make a morning pick although the night run
filled the batch.

## 2026-11-18: A remix's uncovered clip speech is shown as captions, not kept ducked (069)
Changes GOAL.md §3.1 Track A step 6 ("the clip's speech stays, ducked under the reaction").
When a source's `audio_rights` is not `covered`, `src/studio/remix.py` mutes the whole
original track (`mute_original`), may lay our own music bed under it, and shows the clip's
speech as captions from its 068 transcript (the trimmed span). Covered audio stays, ducked
under the reaction and the voice-over (`reaction_collage` `clip_gain_db`, `voice_over`).
A remix uses only the trimmed part being reacted to, at most `REMIX_MAX_CLIP_S` (45 s).
Reason: speech and background music share one track; separating them needs an ML source
separation model we do not ship, and keeping the track keeps the music that can get the
post muted or blocked.

## 2026-11-17: Reel downloads: rules in code, yt-dlp fallback, field check pending (063b)
`src/studio/downloader.py` asks the local service first, then yt-dlp (optional extra
`download`, pinned `yt-dlp==2026.10.26`, which needs Python 3.11+, so the extra is
skipped on 3.10). Either one only finds the video URL; our code fetches it from
`*.cdninstagram.com` / `*.fbcdn.net` over https (no redirects), at most `MAX_DOWNLOAD_MB`
(200). `MAX_DOWNLOADS_PER_DAY` (30, owner-local day, counted from `sources.downloaded_at`)
and `DOWNLOAD_DELAY_S` (5) between downloads. Only yt-dlp may read
`DOWNLOADER_COOKIES_FILE` (a separate personal account, never the brand account). A
downloaded Reel is a `clip` with `rights_basis = commentary`, the creator's username as
author and `audio_rights = not_covered` (its music is never ours). The service's 401
"not public" also appears when Instagram blocks it, so it falls through to yt-dlp; a
private account or a post with no video is final. A failure is kept on the source
(`stats.download_error`, no new column) and the owner can drop the file into the inbox.
DM picks of that Reel are marked `downloaded` (with the source) or `skipped` on a
refusal; a failure leaves them `new` for the next run. The file is not probed (duration
and size come from the answer).
**Pending (owner, H4/H5):** the field check of how many of 20 recent viral Reels each
provider downloads needs the owner's machine and real network; not run yet.
Reason: GOAL.md §5.1, step 063b.

## 2026-11-17: Reel downloader vendored as a loopback-only service (063a)
Okramjimmy/Instagram-reels-downloader (owner's choice, MIT licence) is a git submodule in
`vendor/instagram-reels-downloader`, pinned to `c36c205` (upstream's latest commit on
2026-11-17; it exists, no history rewrite). The worker runs `next start -H 127.0.0.1`
on `DOWNLOADER_PORT` (default 3711) with `USE_UPSTASH=false` and an allow-listed
environment (no secret of ours reaches it), only once `ig-campaign downloader setup`
built it (`.next/BUILD_ID`), so no separate on/off setting. Only `/api/video` is called.
`downloader update` refuses while the service port is in use (a rebuild under a running
server is unsafe) and needs `DOWNLOADER_HEALTH_URL`, since an update is kept only when
the health check passes. CI does not check the submodule out: it is never built or run
in tests.
Reason: GOAL.md §5.1 (never the brand account, nothing exposed), step 063a.

## 2026-11-17: Default agent schedule is `daily-learn@02:00,daily-produce@03:00`
The late-night analysis (step 083) runs an hour before the night batch, so the batch reads
fresh learnings and the report's proposed experiments. A day with nothing published or
matured skips the analysis (no Claude run, no summary); the creative brief then shows the
last report that has one.
Reason: the owner asked for a nightly analysis the next batch builds on (2026-11-17).

## 2026-11-17: Owner priorities: reaction reel, DM picks, scroll-and-decide inbox, video timelines, work packets
The owner asked mid-build for six changes (progress.md Phase 5b, steps 110–116, plus 071/072/073 re-planned):
- **Reaction reel** (replaces the per-clip recorder and the "To record" wait): the owner
  records one long reaction video; each reaction video gets the next consecutive piece,
  looping back to the start. Commentary then rests on a clip-specific voice-over and the
  credit, so a `commentary` recipe needs a reel piece **and** that voice-over. In-app
  Remix briefs (old 073a) stay parked.
- **DM picks**: Reels sent to the brand account by DM from accounts the owner pins are
  downloaded and turned into reaction remixes first. Only pinned senders are read, the
  agent never sees DMs (only the picked link + note), nothing is sent back. "Rework to
  repost" means the commentary remix, never a re-upload or an evasion edit.
- **Scroll-and-decide inbox**: full-screen feed with one-tap Approve (approve + queue in
  the proposed slot, undo), Decline (dislike + archive, undo) and Change (revision
  request with reasons and a moment of the video). Approval stays owner-only.
- **A real UI design system** across the website, phone first.
- **Every video stores a description and a compressed event timeline**, written while it
  is made; the late-night analysis lines retention numbers up with it to say why a
  video lost viewers (hook vs middle vs payoff), using only metrics the API provides.
- **Work packets**: the server prepares validated JSON work for each scheduled agent run
  and skips the run when there is nothing to do; the agent still acts only through MCP
  tools.
Reason: the owner's own words, 2026-11-17 ("I will record a big long reaction, and you
will cut pieces in a loop"; "pin an Instagram account … when somebody sends you reels
from that account … download it"; "approve directly a video without clicking on it";
"a really smart pipeline between the server and the automated task"; "timestamps on
each event … so if the drop rate is at 2 seconds it's the hook").

## 2026-11-17: Reactions come from one long pre-recorded reel
Replaces GOAL.md §3.1 Track A steps 3–4 (the asset waits in "To record", the owner records a
reaction per clip in the browser). The owner records one long reaction video and uploads it
in Settings (`POST /api/reactions/upload`, the raw file as the request body, streamed to
disk; cap `REACTION_UPLOAD_MAX_MB`). `src/studio/reactions.py next_reaction_piece()` cuts the
next consecutive piece of the needed length (re-encoded, frame-accurate) and moves a stored
cursor in the same write transaction; a piece that would pass the end starts over at 0 (a
loop, never stitched across the end). The start snaps forward to a silence within 1.5 s
(found once at upload with `silencedetect`) so a piece rarely starts mid-word. Several reels
may be kept; one is active. No mood tags, no per-clip recording, no `needs_reaction` wait
(072). The upload is a raw body, not multipart: no temporary spool copy of a multi-GB file
and no dependency on python-multipart.
Reason: owner decision (2026-11-17), "i will record a big long reaction, and you will cut
pieces in a loop from the long video". Recording per clip does not fit the owner's day.
Risk: a generic reaction weakens the `commentary` basis, so the agent's voice-over must
comment on the specific clip (069/072).

## 2026-11-17: A clip counts as available for a reaction idea once downloaded, rights known and unused
The reaction quota (`src/learning/quotas.py`) is MAX_REACTIONS_PER_DAY + REACTION_MARGIN
(default 3 + 2) and never more than the available clips: sources with a `local_path`,
`rights_basis` other than `unknown`, and no idea using them yet. Ideas without a pillar count
as informative in the humour/informative mix.
Reason: no column marks a downloaded clip yet (063 will fill `local_path`); a clip with
unknown rights is never queued, so planning a reaction on it wastes the batch.

## 2026-11-17: The agent runner pre-approves only MCP and web tools; reads stay in the workspace
`ig-campaign agent run` (src/agent/runner.py) keeps the built-ins to Read, Glob, Grep,
WebSearch, WebFetch, Skill and ToolSearch (`--tools`), disallows every shell, write,
subagent, publish and message tool by name, and pre-approves (`--allowedTools`) only
`mcp__studio__*`, WebSearch and WebFetch. Read, Glob and Grep are not pre-approved: in
`dontAsk` mode they run inside the workspace and are denied everywhere else.
`--setting-sources project` keeps the owner's user settings, user CLAUDE.md, user skills and
user-enabled plugins out; auto memory is off. Workspace default `~/.ig-campaign-agent`; it is
refused inside the repo, APP_HOME or any git repository.
Reason: GOAL.md §4 lists Read/Glob/Grep as allowed; a bare `Read` allow rule would approve
reads anywhere on disk (other repos, `~/.claude`). Skill is needed for the project skills;
ToolSearch for MCP tools Claude Code defers.

## 2026-11-17: Motion videos get a music bed and an 8 s freeze limit
Every script template (FactQuest, BossBattle, QuizChest) plays a background music loop
(`music`, default `music-overworld`, `none` to opt out), so a video without a voice still has
an audio track. The quality check allows still stretches up to `QC_MAX_FREEZE_S_MOTION`
(default 8 s) for motion renders (`recipe.kind == "motion"`); other renders keep
`QC_MAX_FREEZE_S` (3 s), and black detection is the same for both.
Reason: a motion hook card or end card holds still on purpose; at 3 s every FactQuest failed QC.

## 2026-11-17: Captions carry at most 5 hashtags; QC fails what Instagram would punish
`MAX_HASHTAGS` (default 5) caps hashtags per caption everywhere `caption_problem` runs (caption
edits, publish guard, MCP scheduling, the quality check). Instagram's @creators account announced
in December 2025 that captions of posts and Reels go from 30 to 5 hashtags; the Graph API
reference for `POST /<IG_USER_ID>/media` still says "30 hashtags". The quality check after every
render fails a video outside 1080x1920 / 30 fps / H.264, shorter than 5 s or longer than 90 s,
without audio, more than 2 LU from -14 LUFS, with 1.5 s of black or 3 s frozen, or with a caption
Instagram would refuse (all `QC_*` settings). Health, medical or income wording is only a warning.
Reason: the app rule is stricter than the API docs, and a refused or stuffed caption costs reach.

## 2026-11-17: `assets.recipe` is an envelope; renders run in a queue, two at a time
`assets.recipe` stores `{"kind": "ffmpeg", "recipe": <Recipe>, "inputs": {"source": <media
path>, ...}}` for Track A edits and `{"kind": "motion", "template": <id>, "props": {...}}` for
Track B (rendered through Remotion from step 048; until then a motion job fails), plus an optional
`thumb_offset_ms` (cover frame). Input paths are relative to `MEDIA_ROOT`. Renders go through the
`render_jobs` queue: one job per idempotency key (asset id + recipe hash), `RENDER_CONCURRENCY`
at once (default 2), 3 attempts, a running job without heartbeat for 10 min is re-queued. Each
render writes `video.mp4`, `preview.mp4` (720×1280, 1.5 Mbps, faststart), `poster.jpg` and
`thumb.jpg` into the asset folder. Re-rendering a `failed` asset renders it again in place; a
`ready` one gets a new child asset (`parent_asset_id`), so the version under review stays.
Reason: one shape for both tracks; 2 renders at once fit the CPU (006a spike).

## 2026-11-17: One Graph request budget in the database; data jobs stop at 80 % of it
`RATE_LIMIT_REQUESTS_PER_HOUR` (default 200) is now one sliding hour shared by the worker, the
API and the MCP server: every Graph request adds a row to `graph_requests` (count + insert in one
write transaction). The worker's data jobs (publish-check reconcile every 10 min, insight age
schedule every 15 min, daily account snapshot and followers online) start nothing once 80 % of
the hour is used, so publishing always has the last 20 %. Insights follow an age schedule
(1 h, 3 h, 6 h, 12 h, 24 h, 48 h, 7 d, 30 d; each point once, nothing after 30 d + 1 day).
Reason: three processes with their own in-memory caps could together exceed Meta's limits.

## 2026-11-17: Website password: in-memory sessions, Origin check on every state change
`UI_PASSWORD` (optional) guards every `/api/*` route except health, login, logout and session.
Sessions are random tokens stored hashed in memory (a restart logs out); the login lock
(5 failures in 15 min → 15 min) is one global counter. POST/PUT/PATCH/DELETE are refused (403
`bad_origin`) when `Origin` (else `Referer`) is not the request's own scheme+host+port, and when
both are missing on a request that carries the session cookie. `serve` refuses a non-loopback
`--host` without a password. `X-Forwarded-Proto` is not trusted: HTTPS through a proxy (H7) will
need an explicit setting for the cookie `Secure` flag and the own-origin check.
Reason: single owner, stdlib only; browsers always send `Origin` on cross-site POSTs.

## 2026-11-17: Render-time spike: ~0.4 min per 30 s video on CPU; a nightly batch easily fits
Throwaway Remotion 4.0.544 project (`npx create-video --yes --blank`, outside the repo, deleted
afterwards): 30 s, 1080×1920, 30 fps (900 frames), Courier New bold typewriter text, 6 blocky
4×4-cell sprites moving per frame, full-screen `repeating-linear-gradient` scanlines with flicker.
Output H.264 MP4 (default codec), ~6.3 MB, checked with ffprobe (900 frames).

Machine: Intel Core i7-11800H (8 cores / 16 threads), 32 GB RAM, no NVIDIA GPU, Windows 11,
Node 24.16. Other developers' test suites ran at the same time (CPU load 6–23 % before each run).

Method: PowerShell starts `npx remotion render` (one or two at once) and samples once per second
the summed working set of every node / chrome-headless-shell process of the spike; wall time is
process start → exit. Working-set sums count shared pages twice, so RAM is an upper bound.

| Setting | Wall time per video | Total wall | Peak RAM |
|---|---|---|---|
| 1 render, default (`8x` = half of 16 threads, cap 8), incl. bundling, run 1 | 23.5 s | 24.1 s | 3.0 GB |
| 1 render, default, incl. bundling, run 2 | 24.4 s | 25.2 s | 3.0 GB |
| 1 render, default, prebuilt bundle | 23.8 s | 24.3 s | 2.8 GB |
| 1 render, `--concurrency=16` | 24.8 s | 25.7 s | 4.0 GB |
| 1 render, `--concurrency=4` | 29.3 s | 29.9 s | 2.1 GB |
| 2 renders at once, default, prebuilt bundle | 38.5 s / 38.3 s | 39.2 s (19.6 s per video) | 5.5 GB |
| 2 renders at once, `--concurrency=4`, prebuilt bundle | 38.0 s / 37.9 s | 39.0 s (19.5 s per video) | 4.1 GB |

Findings:
- 2 renders started at once from the source entry (`src/index.ts`) crash: both run rspack bundling
  on the same `node_modules/.cache` and the second panics ("State lock mismatch … race condition").
  Bundle once (`npx remotion bundle` or `@remotion/bundler`), then render from the bundle.
- Concurrency above the default buys nothing (16 threads: +1 s, +1 GB); 4 is 23 % slower alone.
  Two parallel renders give ~20 % more throughput than one at a time; `2 × --concurrency=4` matches
  `2 × default` with 1.4 GB less RAM.

Extrapolation (best: 2 at once, ~20 s per 30 s video): 10 videos ≈ 3.3 min, 25 videos ≈ 8.2 min
(one at a time: 4 / 10 min). Templates of 10–45 s scale with frame count: 25 × 45 s ≈ 12 min.
Real templates (custom pixel font, images, audio mux, more layers) may be several times slower and
still fit a 4 h nightly window (today's worst case, 25 × 45 s, leaves ~20× headroom).

Remotion docs (remotion.dev, read 2026-11-17): current version 4.0.544; scaffold
non-interactively with `npx create-video --yes --blank <dir>` (fails inside a git repo); render with
`npx remotion render <entry-or-bundle> <comp-id> <out>`; `--concurrency` = parallel browser tabs,
1 … CPU threads or a percentage, default "half of the CPU threads available, capped at 8"
(renderMedia docs); default codec H.264; it downloads and uses Chrome Headless Shell
(`--chrome-mode=chrome-for-testing` is the alternative). Licence
(https://www.remotion.dev/docs/license/pricing, https://www.remotion.dev/docs/license/faq): the Free
License covers "individuals and companies of up to 3 people" (headcount includes contractors on the
same project), may be used commercially and for automated rendering; bigger companies need a
Company License (Automators $0.01/render, min $100/month; Creators $25/seat/month). The owner is an
individual / small business, so the Free License applies; re-check if the team grows past 3.

Recommendation: 034/039 render from a prebuilt bundle (bundle once per batch, never bundle in
parallel), 2 renders at a time with `--concurrency=4` (or default) and no tuning beyond that; 062
needs no batch-size cap for render time: 25 videos of up to 45 s fit in well under 30 min, so a
nightly batch fits a 4 h window with room for retries.
Reason: step 006a spike measurements above.

## 2026-11-17: Stack defaults accepted; Track B before Track A
The owner accepted the stack defaults of GOAL.md §4.1 at onboarding, and chose to build
Track B (motion + agent, Phases 4–5) before Track A (Phase 6), keeping roadmap order.
Reason: owner's answers at team-up onboarding.

## 2026-11-18: The owner decides what is promoted (128)
Owner's words: "let me only me decide what to push and what to publish, because I have
the artistic eye". This reverses the launch part of "The AI runs the ads within the
owner's caps (126)" above: the agent may still **propose** paid A/B tests, read results,
judge them into learnings and **stop** a test (a pause spends nothing), but every launch
is the owner's Approve on the Ads page, where waiting proposals show with Approve /
Cancel. The MCP tool `launch_ad_test` is removed (no agent tool launches, activates or
spends; tests/test_ads_agent.py lists the agent's ads tools and walks their calls), and
`tests.launch` refuses any actor but `owner` (`owner_only`), as defence in depth. The
weekly-ads playbook proposes and never launches; its work packet drops `launches_left`.
Kept from 126: the caps, the kill switch, no password for Approve (password for raising
a cap and turning ads back on), at most 3 agent proposals waiting. Promotions are only
created paused, inside `tests.launch`. Publishing is unchanged (per-video approval).
GOAL.md §3.6 and §5.4 updated.
Reason: the owner's instruction of 2026-11-18; the owner has the artistic eye and
decides what is pushed with money.

## 2026-11-18: Owner art direction: the real macroBody brand kit (050)
The placeholder kit (H1) is replaced by the owner's own identity. Sources the owner
pointed to: the macroBody app (docs/DESIGN.md, the mobile theme, the website fonts and
llms.txt) and the owner's own Reels (macrobody-video: README, logo, drawing code).
- Palette (`brand/brand.json colors`): brand emerald #10B981 (light #34D399), the app's
  macro colours (kcal #3E8EF7, protein #FF6F61, fat #F5C242, carbs #3FBF7F, weight
  #A78BFA), light surfaces (#F5F7F8 / #FFFFFF / ink #111827 / muted #6B7280) and dark
  (#0E1117 / #1C1C1E / #FFFFFF / #98989F). ffmpeg overlays draw dark.text on dark.bg;
  the end card is the light surface with the logo.
- Fonts: Inter Tight 900 (display) and Inter (body), the variable WOFF2 files from the
  owner's website. The local ffmpeg cannot read WOFF2 (drawtext segfaults), so the ffmpeg
  ops use a static Inter Tight Black TTF derived from that WOFF2 (OFL, no Reserved Font
  Name).
- Logo: the app mark drawn in-repo (black #0B0B0B squircle, radius 22 %, white "mB"),
  flat: no glow, no gradient. `brand/logo.svg` + `brand/logo.png` (512 px).
- CTA (`cta`): "7 jours gratuits" + "macrobody.fr" (+ "Dispo sur App Store & Google
  Play"); never a price; never "lien en bio" unless the owner asks.
- End card (`end_card` op): centred like the owner's end cards: logo tile, wordmark
  ("macro" ink + "Body" emerald), optional tagline, "7 jours gratuits" in an emerald
  pill, "macrobody.fr". Its `text` became an optional tagline (the CTA comes from the kit).
- French typography: a no-break space before ? ! : ; » and after « in every text the
  studio draws (ffmpeg ops and motion hook/captions), so a line never starts with a mark.
- Address (`address`): "vous" by default (brand films, paper, informative), "tu" for
  humour and live-action. Agent skill `agent/skills/brand-voice`.
- Styles are per template: the brand kit is no longer the 8-bit look. The 8-bit templates
  keep Sweetie 16 and Press Start 2P as their own constants (`motion/src/lib/palette.ts`,
  `font.ts`).
- The first 8-bit sample (FactQuest) was declined by the owner ("not good at all"):
  samples go to `data/samples/`, never the inbox, and new styles (voxel, paper, clean brand
  film) come as their own templates.
Reason: owner's art direction, 2026-11-18.

## 2026-11-18: End cards are animated motion design, one per style, never a price (137)

Owner: "the end card must be animated; depending on the style of the video we need a
different card; all motion graphics, motion design. The kit is a small base adapted for
each scenario, and never show the price."
- One shared `EndCard` (`motion/src/endcards/`, `style` prop) with a card per style:
  `voxel` (the podium, 130), `paper` (kraft cover tearing open on the cream sheet, cut-out
  pieces, stepped 12 fps), `clean` (the v5 light surface, soft accent glows, kicker pill,
  `cubic-bezier(.22,1,.36,1)`), `pixel` (PRESS START, then the tile assembles cell by
  cell) and `live` (the video's last frame freezes, blurs and dims, the card animates
  over it). Each settles in about 2-3 s and holds at least 1 s; every card lasts at least
  2.5 s (`CARD_S`).
- Fixed base everywhere: the mB tile, the wordmark macro**Body**, « 7 jours gratuits »,
  macrobody.fr. Adapted per video through props the agent fills from the story: `tagline`
  (the payoff, else the app's tagline in the video's address), `accent` (the topic's macro
  colour, default emerald), `cameo` (a character / prop of the style) and the backdrop
  (the voxel kitchen; live: the last frame).
- Every motion template ends on its style's card (the five 8-bit templates on `pixel`,
  VoxelQuest on `voxel`); their outro / cta became the card's tagline, BossBattle,
  DialogStory and PixelSkit gained an optional unspoken `tagline`. Voice scripts are
  unchanged.
- Track A: the `end_card` recipe op appends a pre-rendered `live` card (or `clean`),
  cached under `<media root>/endcards/` by its props and the backdrop's bytes. The static
  drawtext card (050) is only the fallback when Remotion is unavailable, and QC then adds a
  warning. The op's default length is 3.5 s; shorter values are raised to 2.5 s.
- Never a price: the same patterns in `motion/src/lib/noPrice.ts` and
  `src/studio/brand.py` (`has_price`). Zod refuses a price in every end-card text and the
  8-bit templates' outro / cta / tagline / sources note; the recipe ops refuse one in the
  hook, credit and end card; QC fails any render whose on-screen texts carry one
  (captions included: they are the clip's speech).
- The paper card's display font is a prop (`font`, default Fredoka) falling back to
  Inter Tight, and its url uses Caveat falling back to Inter italic, until step 131 adds
  Fredoka and Caveat.
Reason: owner's art direction, 2026-11-18.

## 2026-11-18: Work-order videos may pass a full batch, like DM picks (134, 136)
A video the owner ordered (a Trending work order, or a Reel a pinned account sent by DM,
which is now a work order too) is made even when today's batch is full:
`create_idea(work_order_id=...)` skips the batch cap; the explore and reaction quotas
still apply. A DM order with no note waits (`needs_instruction`) until the owner writes
one in the app.
Reason: an order is the owner's clearest instruction; the batch cap exists to stop the
agent over-producing on its own, not to delay what the owner asked for (134's review).

## 2026-11-18: The owner's sends start a run at once, within a daily cap (136)
Owner's words (translated): "when I send a Reel in the Instagram chat with a description
under it, that description does exactly what I would have done in the app: you start the
work directly". A work order that becomes `scheduled` (a DM with a note, an instruction
written in the app, a Trending order) starts the light run (`daily-revise`) after
ORDER_RUN_DEBOUNCE_MINUTES (default 3, so several sends batch into one run), one run at a
time, at most MAX_ORDER_RUNS_PER_DAY (default 6) such runs per owner-local day, and only
when the agent preflight passes; otherwise the order waits for the next scheduled run and
its `blocked_reason` says why. DMs are read every DM_POLL_MINUTES (default 5, was 15).
GOAL.md's 1-2 scheduled runs a day stay the default; these runs come on top.
Reason: the owner's instruction of 2026-11-18; the cap bounds the agent's usage.

## 2026-11-19: A second video engine: Blender for the `blender` style
Owner's words (translated): "we are trying to have a second video generator like the 3D 8-bit
engine, so the user generates videos using different styles", then "so that the app can use
the 3D voxel engine and our new engine whenever". The `blender` style (label « Blender »,
"PS2 cutscene" skits) renders with Blender 5.2 + free CC0 assets (`cinematic/`), not
Remotion. It sits behind the motion door: template `CinematicSkit` in the same tools,
recipes (`kind: motion`) and render queue, so step 138's style buttons pick it up from its
`style`. The tools (about 1.6 GB) are downloaded by `cinematic/setup.py`, never committed.
No AI video model: everything renders locally at no cost per video, about 1 minute of
machine time per second of video.
Reason: the owner's request; local rendering keeps the cost at zero and the result repeatable.
