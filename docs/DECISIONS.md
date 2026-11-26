# Decisions

Decisions that change a default of [GOAL.md](../GOAL.md), or that later work depends on.
One entry per decision, newest first:

```
## YYYY-MM-DD: <decision>
Reason: <why>
```

## 2026-11-26: The « rea-video » route on Auto copies the Reel shot by shot in code
A « Reçus » order confirmed on the rea route with no style gets the style `lemo:rea-video`
(lemo.REA_FILM): the film runner (src/agent/film.py) makes it from the Reel and its rea-video
breakdown, in the Reel's own look (no library style), the same shots, framing, effects,
timing and ending, changing only what the owner's instruction changes. It never waits for a
new style. Nothing of the Reel is reused as it is (every shot redrawn in code); a shot code
cannot make (live footage, photoreal people) gets its closest coded version, and the video's
description starts « Pas fait comme demandé : ». A rea order with a style the owner picked
is still remade in that style by the light run. Orders 76 and 77 (parked on style requests
21 and 22) moved to this route.
Reason: owner 2026-11-26, after both rea orders waited for styles nobody built: « j'avais
sélectionné rea-video, normalement ça ne dépend pas du style mais ça recopie juste ! »

## 2026-11-25: Winners and learnings need more than one event (pipeline audit)
Scoring (`src/scoring.py`): a count signal (shares, saves, follows, ...) is no longer the
post's rate over the baseline's median rate (+0.0005, capped at 5x). It is observed events
over the events expected at the baseline's pooled rate (their events / their reach) for
this post's reach, both plus 3 pseudo-events (`PRIOR_EVENTS`). Watch time and watch ratio
keep the median. A baseline post read at over 2x (or under half) the scored post's age is
left out (`MAX_AGE_GAP`). Live, 2026-11-25: the 8 matured 48 h Reels were 0.66–0.81 or
3.35–3.51 (one share and one save on reach 321 and 468 made 2 "winners"); now they are
0.79–0.94 and the Reel with 10 shares and 11 saves (reach 1056) stays the winner at 2.43.
The two 30-day-old Reels are only compared with each other (16 shares: 1.85, 1 share: 0.77).
Experiments (`src/learning/experiments.py`): a do / dont also needs a seeded permutation
test over all variants at p < 0.05; with a variant under EVIDENCE_MIN_N_MEDIUM scored
posts, no learning is written (result `not_enough_data`). Template, hour and duration
experiments count each post under the value it really has.
Learnings (agent edits): rewording a learning or changing its kind or scope puts it back to
`low` (the evidence engine lifts it again when the numbers back it); evidence dicts must
name a post with insights, an ad test or a work order, duplicates are dropped and sources
counted once; an owner instruction the agent stores is scoped to what the commented video
is, or has no predicate.
Reason: audit 2026-11-25. On an account with reach in the hundreds, one share was a 5x
signal on a weight-3 metric, and that label fed ad-test candidates, daily facts, breakdowns,
evidence, the mix and slot weights. The owner: learning comes from real metrics and owner
feedback, not noise.

## 2026-11-25: The resource guard no longer pauses or stops running jobs
Gone: the watchdog's pause on low RAM and its kill after 3 min, the GPU heat pause (83/74 °C),
the GPU power pause, the CPU throttling pause, the 15-min duty cycle, and the 10-min startup
grace (settings GUARD_WATCHDOG, GUARD_STARTUP_GRACE_MIN, GUARD_SUSPEND_TEMP_C,
GUARD_RESUME_TEMP_C, GUARD_MAX_BUSY_MIN removed). Kept: the GPU lock, one render at a time,
the admission checks before a job starts (free RAM 8 GB, free VRAM, no game), the free disk
check, low priority and half the CPUs. guard.log still gets a state line every 30 s while
the GPU lock is held (GUARD_LOG). This reverses parts of 166 and 171 below.
Reason: the owner capped the GPU clock at 1500 MHz, which keeps the card at 50–67 °C, and
the RAM kill stopped the voice model mid-load (it takes ~8 GB while loading; paused, it can
never give that back) and failed a render on 2026-11-25. Owner: « remove the startup grace,
RAM pause and kill, duty cycle, GPU heat, GPU power, CPU throttle ».

## 2026-11-25: The website is in French (215)
Every page, nav label, sheet, toast and error of the website is written in French, with
« tu » and the French typography rule above (no-break space before ? ! : ; » and after «);
dates render fr-FR (« lun. 30 nov. »). Nav: Inbox, Créer, Planning, Trending, Calendrier,
Statistiques, Apprentissages, Styles, Voix, Pubs, Agent, Réglages, Plus. Technical words
stay English: Worker, token, `.env`, command names, ElevenLabs, Reel, DM. Done in steps
215–219 (shell and Inbox first).
Reason: the owner and the content are French, and the newer pages already were (UI audit
2026-11-25, Q1, owner « french »; Q5 for the technical words).

## 2026-11-25: Planning has a phone tab; Agent moves behind More (213)
The phone's bottom bar reads Inbox · Créer · Planning · Trending · Calendar · More; Agent is
in the More list. This reverses 185 (Planning behind More) and the Agent tab kept since 174.
Reason: Planning is the owner's third task of the day, while Agent runs are rare, manual and
each asks for confirmation (UI audit 2026-11-25, Q2, owner « ok »).

## 2026-11-23: Only a failed or dropped new version gives the old one back; a removed Claude card frees its place (199)
An unsubmitted version stays out of the check list and the Inbox for good once a newer
version of it exists, up the chain, archived included (the owner declined it, the worker or a
restyle retired it, or the owner sent it back and its own new one is ready: a decision was
taken on the idea). When the newer version failed (past its retries) or was dropped by the
check run, the old one is back in the check list (and the Inbox once checked or after the
grace), so its order or DM pick is never parked behind a hidden video; `drop_render` counts
no hidden old version as one that carries the order on. A day's places for Claude's
ideas are fixed by that day's first producing packet; a later packet may only lower them
(the owner's items it made no longer count, the batch stays the batch). « Retirer » on a
planned Claude card (or the Inbox's « Archiver ») gives its place back for its batch day; a
released card keeps it. The re-check clock (193) starts at the newest check run, whatever
started it (catch_up, the owner's launch, the Agent page). A launch request whose start
fails is dropped with a website alert, never a stale scope.
Reason: audit 2026-11-23 (b) #4 #5 #9 #14 #17; owner: the cap is how many of Claude's ideas
wait or get made.

## 2026-11-23: A film waits for its render through the machine's backoff (198)
The film runner waits RENDER_WAIT_S (1 h) for its own render to be judged, and each
machine failure of that render (`render.machine_wait`) starts the hour again: the machine's
backoff (5 + 15 + 45 × 4 min) never runs the film out of time, and the wait stays bounded
because the job fails for good after its 6 machine retries (the film then sees the failed
video and stops at once). A video failure ends the wait as before. While the studio is
paused, the film's render is claimed only once its machine timer is past, and the film's
exemption (pause, hold, timer, remove) needs the film's run alive (its process): a dead
film's render is an ordinary one. A relaunch after a machine failure is not a re-render
(`requeues` unchanged), and the « La machine n'arrive pas… » alert goes once the video is no
longer failed for the machine.
Reason: audit 2026-11-23 (b) #1 #2 #13 #15 #16: three machine failures (65 min) outlasted
the film's hour, the order was skipped and the video later rendered with its order never in
the feed.

## 2026-11-23: A machine failure waits and retries, never counts against the video (197)
`render.machine_failure` is the one place that tells the machine from the video. Machine:
the voice service down or not answering in time, or answering HTTP 5xx (503: its engine
died, was stopped by the resource guard, or is loading), `gpu_lock.LockTimeout`,
`guard.Stopped` (the guard killed the render for free RAM). Everything else (QC, a bad
recipe or props, a render tool's error, a TTS 4xx) is the video's, as before. A machine
failure puts the job back in the line at its place (arrival, line_pos and `requeues`
untouched, the claim's attempt given back) behind a timer of 5, 15, then 45 min
(`not_before`); the asset stays `rendering`, so the check run never lists it and its
re-render count does not move. After 6 machine retries in a row (MACHINE_RETRIES) the job
fails with « machine: … » and one website alert per video (« La machine n'arrive pas à
faire la voix / le rendu »); the check run re-renders such a video unchanged, never drops
it. Planning: `waits_on: machine`, « En attente de la machine — nouvel essai vers HH:MM ».
No migration: the count lives in the waiting job's `failure` (« machine n/6: … »).
Reason: 2026-11-23 12:31–12:57 free RAM fell to 0.6 GB, the guard stopped the voice
engine four times, the voice service answered 503, the re-renders of #68 / #69 used up
their budget and the check run dropped two good scripts.

## 2026-11-23: The owner's « Lancer » bypasses the grace, « seen » and the daily cap (196)
Planning's « Lancer maintenant », « Lancer la sélection » and « Tout lancer »: renders, Lemo
films and Claude's ideas go to the head of the heavy line in on-screen order (as « start
now »). Owner orders, change requests (one the AI left « en attente » too) and the AI's runs
become launch requests (worker_state `launch_requests`), started by the catch-up before
anything else as soon as nothing else runs (`schedule.busy`: no AI run, no render running or
queued), never while the studio is paused. They skip ORDER_RUN_DEBOUNCE_MINUTES, the « a run
saw it » rule and MAX_ORDER_RUNS_PER_DAY, and do not count in that cap; no separate
preflight (the run's own fails it, like the Agent page's start). The light run launched on a
selection works on those orders / change requests only (its packet is cut to them, their
comments, no DM pick); it does not count as having « seen » the others, which keep their own
path.
Reason: the owner (2026-11-23): « I want to be able to launch a generation … I can select
all of them … I can select some of them », not wait for 03:00.

## 2026-11-23: The check run never parks a video (193)
A check run gives every waiting video a decision (a fix, `drop_render` or `submit_asset`;
unsure: submit with a note). One it left anyway is offered again CHECK_RECHECK_HOURS
(default 4) after that run started, still within MAX_CHECK_RUNS_PER_DAY; before, « a check
run started since » kept it waiting until a newer render finished (live: #68 / #69). A
setting rather than « the next check run, whatever starts it »: a check run only starts for
finished renders, so a quiet day would never bring that next run. An unsubmitted version a
re-render replaced stays out of the Inbox for good (was: 24 h), whether or not the check run
can run: its newer version carries on. Claude's places are counted per batch day, minus the
cards already planned for that day (a retried packet or a second run of the day never plans
past the batch).
Reason: the owner: the AI never parks a video silently.

## 2026-11-23: The night run plans, renders nothing of its own; a check run submits (188c)
The owner (2026-11-22): the 03:00 daily-produce must not launch renders directly; Claude's new
ideas come as cards of their own colour he reviews first, and they only fill the rest of the
batch. daily-produce now never waits (`wait_for_renders` and its review / submit phases left
the playbook). The owner's items it handles (scheduled work orders, change requests, DM picks)
still render at once: they go straight into the FIFO line, where Planning can hold, move or
remove them (lead decision, reversible: the owner asked for them). Claude's own ideas (viral
finds and Track B) are `plan=True` cards (188b) with caption, description and sources, only
for the places left: BATCH_SIZE minus the owner's items, counted by the packet
(`quotas.json` `places`, the same number as the Planning placeholder's `picks_up`). The packet
opens those places for the day and every plan call takes one (`planned.take_place`, under the
write lock): past them `render_motion` / `render_remix` refuse with « no place left », so the
rule does not rest on the prompt; a day no packet opened gets the same count at its first plan.
After renders finish, a light check run (`check-renders.md`, kind `light`, packet section
`checks`) reviews each one: frames and QC for cut text, an unreadable first frame, voice vs
picture, the remix credit; at most 2 re-renders per video (the render jobs of the idea's
versions nobody submitted or judged, minus the first: in place, a child or a new remix whose
old version it drops; each re-render joins the line and the next check run sees it), else
`drop_render(asset_id, why)` (a new tool, in the `agent` profile: a local write that only
marks the video `dropped` with the reason, skips its work order with it, shown in the Inbox as
« Écartée par l'IA : … » and in Mes envois; only the owner archives), and `submit_asset` for
the good ones. The catch-up starts it as a fourth step after the orders (CATCH_UP_ORDER film →
playbook → orders → checks, listed by Planning): CHECK_RUN_DEBOUNCE_MINUTES (default 5) after
the newest finished render, not while renders wait in the line (busy(): one on a timer or held
does not count) or any run runs, not when a check run started since (it had them), at most
MAX_CHECK_RUNS_PER_DAY (default 8), the preflight asked again 10 min after a failure, nothing
while paused. The Inbox hides a `ready` video waiting for its check until it is submitted,
and an unsubmitted version a re-render replaced; fallback: it shows anyway CHECK_INBOX_GRACE_HOURS (default 3) after its render finished, or at
once while the check run cannot run (its preflight fails or its last run failed), and renders
older than 24 h are never held back. Lemo films keep today's path (the film runner checks its
own film; shown when ready), and so does the owner's own re-render of a submitted video
(next reaction piece, fixed transcript); everything else (agent and owner-order videos,
released Claude cards, change-request versions) goes through the check. daily-revise keeps its own wait and
review (a follow-up may move it to the check run); daily-learn and `--dry-run` (ideas only, no
plan or render call) are unchanged.
Reason: the owner reviews Claude's ideas before any GPU time is spent on them, and his own
items are never delayed by Claude's.

## 2026-11-23: The agent no longer scores its own videos (189)
The owner: an AI scoring its own render makes no sense; a video is good by its real numbers
(views, comments, shares) and the owner's verdict. GOAL.md §2.1 dropped the agent's
« calibration » metric. `submit_asset` (service and MCP tool, still in the `agent` profile)
takes no `self_score` / `self_score_reason` any more: caption, best_before and description
as before, plus an optional one-line `note` (a new version: what was changed; a work order or
DM pick: its "Work order #<id>: " / "DM pick from @<sender>: " prefix). The note is stored in
the existing `self_score_reason` column rather than a new one, so no migration: daily-learn's
`approved_changes.changed` keeps reading the same column, and old revisions keep their
« what I changed » text. A submit without a note stores '' there, so NULL still means « never
submitted » and `list_assets` gives the agent `submitted` (and `note`) in place of the score it
used to read as that marker. Re-submitting clears an old `self_score`; the columns stay, old
scores are kept but nothing reads them. Replacement orders: `list_assets` (the Inbox, the
agent's list) is newest batch first, then best_before soonest (none last), then id; the bench
and its slot suggestion are best_before soonest (none last), then oldest first (lowest id, so
a liked video does not go stale behind newer ones). The funnel's calibration block is gone
from `taste`, the daily facts (and so the agent's packet and daily-learn) and the Analytics
page. The Inbox card shows no score; a revised video's card shows the agent's note under the
owner's request (a legacy score reason on other videos is not shown).

## 2026-11-23: Claude plans a video; the owner releases it from the Planning page (188b)
A new asset status, `planned`, starts a video Claude plans instead of queueing:
`render_motion` / `render_remix` take `plan=True` (and a `description`) rather than a new
`plan_video` tool, so the plan goes through the very checks a render gets (props, style, voice
on, Instagram track, rights) and the agent profile keeps the two tools it already had. A
planned video has its full recipe (the voice still a `voice_todo`), caption and description,
and no render job, no TTS, no file, no reaction piece; its sources are the idea's citations.
It is not in the line and has no ETA. The Planning page lists them first, in their own colour
(token `idea`: Sweetie lime `#a7f070` dark, `#3f6212` light, AA on every surface), newest
batch first. The owner can edit the voice, the music (a bed, none, or a fetched Instagram
track), the spoken lines (those that are one prop text; a line joined from several, such as
PaperStory strips, is shown locked), caption and description, each re-checked on save.
« Valider » checks it all again (a remix: its rights, then it claims its reaction piece) and
moves it `planned` → `rendering` (owner only) with its render arriving in the line now;
« Lancer maintenant » and « Minuteur » release it the same way plus `line.start_now` /
`line.set_timer`; « Retirer » moves it `planned` → `archived` after the 5 s client undo.
`list_assets` (the Inbox, the agent's list) leaves planned assets out unless asked by status;
the funnel and the QC-spike alert ignore them; housekeeping and the bench only ever look at
`ready` / `archived`, so a planned video never expires. The status is added by editing the
assets table's CHECK in place (SQLite's documented procedure for a widened CHECK, migration
27): rebuilding it is refused by the tables that reference it.
Reason: owner request 2026-11-22 (« a new idea made from Claude must be in a widget with
another color, and I can review it before it runs »); 188c points the night run at it.

## 2026-11-23: The voice-over is made by the render job, not when a video is queued (188a)
`render_motion` / `render_remix` (and an owner re-render) check the props and the voice (on,
known) and return at once: the recipe keeps the lines unvoiced plus `voice_todo` (the voice,
the sitcom's character voices, the Instagram track to cut on; a remix's script and clip
length). The render job makes the voice first (`render.voice_first`, same TTS cache), stores
the voiced recipe in place of the queued one (a retry or re-render never synthesises twice),
then renders. While the model is warm, that job also makes the voices of the next
`VOICE_AHEAD` (6) waiting voiced renders in line order (films, timers and held items passed
over), so a batch loads the model once and waits for its idle unload once. A voice-service failure is retried like any render error; a voice that does
not fit (a remix voice-over longer than its clip, an Instagram track shorter than the video)
fails the job at once with the reason, where it used to be refused at queue time.
`TTS_PROVIDER=none` still fills its reading estimate at queue time (nothing to wait for).
`TTS_TIMEOUT_S` default goes from 3600 s to 1200 s: one request now comes from the one render
job running (`RENDER_CONCURRENCY` 1), so it covers a 90 s script's three takes and the model
load, not a queue of agent calls. `preview_motion` stills stay voice-less (reading timings).
Reason: queueing must be instant and every heavy step in line order (186), for the Planning
page's Claude cards (188b) and a night run that synthesises nothing at 03:00 (188c).

## 2026-11-23: The owner can remove, hold and reorder the line, and pause the studio (187)
On the Planning page each waiting render or film can be moved up or down (swapped with its
neighbour; the whole line's order is then written as `line_pos` 1..n, so new arrivals still go
behind and « Lancer maintenant » still goes ahead), held (« Mettre en pause »: a timer with no
end, it blocks nothing behind it) and removed; an owner order or change request still waiting
for the light run can be removed too. Remove follows the Inbox rule: the card leaves at once
and nothing is sent before the 5 s undo ends, so an undo leaves the item exactly where it was.
A removed render job ends `failed` (« retiré du planning »), the claim never takes it, and its
asset moves `rendering` → `archived` (a new lifecycle move, owner only) unless another job of
it is queued or running; a removed order is skipped with that reason. Running or finished
items are refused. One « Tout mettre en pause » switch (worker_state `studio_paused`, survives
a restart) stops everything heavy from starting: the render loop claims nothing, the catch-up
and `agent run-due` start no film and no run (missed runs stay due for the same day); what is
running finishes, never killed. An alert shows on every page while it is on. It is separate
from the publishing pause: posts still publish.
Reason: owner request 2026-11-23 (« switch order, remove them completely »), and the laptop's
GPU is shared with the owner's own work.

## 2026-11-23: Heavy work goes in one line, first in first out; start now and timers (186)
Renders and Lemo films wait in one line (`src/studio/line.py`), by arrival: a render job's
`created_at`, a film order's `scheduled_at` (old rows sort exactly as before). `next_in_line`
decides the head: the render loop claims it when it is a render, the catch-up starts it when it
is a film, the Planning page lists the line the same way. A film that arrived first goes before
the renders queued after it (queued renders no longer hold films back: only a running render
does), and no render starts while an earlier film waits. A film the runner could not take now
(an agent run is running, today's `LEMO_FILMS_PER_DAY` are made, the preflight just failed) is
skipped, so it never blocks the renders behind it; a film's own final render goes to the front
(the film waits for it). On the Planning page each waiting render or film can « Lancer
maintenant » (ahead of every waiting item, the latest press first; the running item is never
stopped; its timer is cleared) or get a « Minuteur » (`not_before`, stored UTC, shown in the
owner's time): it is skipped until then without blocking the line. The catch-up now tries the
film before a due playbook. What stays as before: agent runs (due playbooks, the light run for
orders) are not in the line and still start only when no run is running and no render is
queued or running; one render at a time; one film at a time.
Reason: owner decision 2026-11-22: a queued render blocked every film, and films only went
after the due playbooks: the order was decided by rules, not by arrival.

## 2026-11-22: Voices are designed recipes, picked on the Voix page (owner's re-casting)
The owner found the cloned voices robotic ("AI slop"). Six casting rounds by ear
(`data/voice-trials/`, rated on a phone page) settled it: a voice is a VoxCPM2 **recipe**, not a
cloned clip: `(style description)` before the text, a seed, cfg 2.0, 30 steps, an optional
reference wav for the timbre, and a tempo played after (ffmpeg atempo, pitch unchanged). Each
retake uses the next seed (seed + 1000). Three voices are on: `souriante` (the new default),
`energique_femme`, `energique_homme`; the cloned `conteur_grave`, `coach_energique`,
`douce_nuit` stay in `voices.json`, turned off. `<id>.wav` is now a sample to hear for a
designed voice. The owner turns voices on / off on the new Voix page (`/voices`, stored in the
studio state like the styles); only voices on are used: the agent's `voices.json` lists them
alone, and `render_motion` / `render_remix` refuse another one (no voice = the default if on,
else the first on); a re-render that keeps its voice-over is not re-checked. At least one
stays on. The Lemo film agent gets the same list (by instruction: it calls the service
itself). The sitcom narrates with an energetic tu voice that is on (`energique_femme` first); its characters speak in voices on,
picked by each voice's `gender`. A designed voice's recipe is part of the TTS cache key, so
re-tuning a voice under the same id makes new audio. Bracketed parts of a script are shown in
the captions but never said (a stage direction read aloud sounds wrong, and a leading bracket
would be read as a voice instruction).
Reason: in the rounds, cloning a liked take onto a new script lost its energy and sounded
robotic (round 5); re-running the same recipe on a new script was rated top on two seeds
for all three voices (round 6). OmniVoice (VoiceStudio) was tried and rated "super bad".

## 2026-11-21: Blender's VRAM diet, heavy jobs off CPU 0, one Blender call per shot (177)
Every Blender scene's images are shared (one copy per file) and crushed: faces and outfits to
1024 px (`cinematic.TEXTURE_PX`), the rest 512; the EEVEE shadow pool is 256 MB (default
512). Measured with `python -m src.studio.troupe measure` on the proof's dinner of 7 (one
frame): Blender's VRAM 2.29 GB -> 1.20 GB, textures 601 MB -> 121 MB, same picture. Outfit
textures had stayed at 4096 px: the old "skin" rule matched "male" in `male_casualsuit`.
`guard.VRAM_GB["blender"]` stays 3. Heavy children run on CPUs 1..n (`guard.cpu_set`), never
CPU 0; guard.log lines show the used VRAM and the graphics clock. The troupe renders each
uncached shot in its own Blender call (a crash loses one shot). The GPU runs clock-capped:
the owner's admin logon task `GPUClockCap` runs `nvidia-smi -lgc 210,1500` at every logon;
the studio never sets clocks itself.
Reason: a bluescreen (DPC_WATCHDOG_VIOLATION, current DPC in nvlddmkm) and six power-offs
under Blender troupe scenes. VRAM over-commit was the first suspect, but the full proof with
the diet still powered the PC off at 21:47 (1.2 GB measured). Root cause: the GPU boosts to
~2100 MHz (a 3070 Laptop is rated ~1600). With the 1500 MHz cap the 8-shot proof with the
diet passed: 12.9 min, 130.8 W peak, 3.1 GB VRAM. A guard.log clock above ~1600 MHz shows a
missing cap.

## 2026-11-21: A job waits for RAM / VRAM without holding the GPU lock (175)
`gpu_lock.hold` used to take the lock, then wait in `guard.admit`. Now it waits for
admission with the lock free, takes the lock, and checks `guard.blockers` again under it:
still blocked (another job took the VRAM meanwhile), it lets the lock go and waits again.
Same API and logs; the voice service (stdlib, loaded by path) included. Of two waiters
admitted at once, the one that started waiting first goes first: each admitted waiter keeps
a ticket file `<lock>.queue/<start ns>-<pid>-<n>`, touched every poll; a ticket older than
10 s belongs to a dead waiter and is removed. Not a strict queue: a younger job whose need is
met may still go while an older one waits for more VRAM.
Reason: 2026-11-21 00:10-00:57 the voice load waited 47 min for VRAM while holding the lock,
so even small Remotion renders queued behind it (the film agent's report).

## 2026-11-21: The Lemo film runner is the one agent run with a shell (173)
A work order in a Lemo-Opuscar style (`lemo:<slug>`, owner-mode orders only) is made by
`ig-campaign agent film <order_id>` (src/agent/film.py), started by the worker's catch-up:
Claude Code headless with Bash, Read/Glob/Grep, Write/Edit (pre-approved inside its
workspace only) and the lemo-opuscar plugin skill (copied into the workspace). Everything
else stays locked: its workspace `<AGENT_WORKSPACE>/films/<order id>/` passes the content
agent's checks (outside the repo and APP_HOME, in no git repo), `--setting-sources project`,
`--strict-mcp-config` with no MCP server at all (it never sees the studio's tools or the
database), no web tools or subagents, an environment without any .env name or secret
value, the Read deny rules on .env and the data folders, LEMO_FILM_MAX_MIN (90) with the
process tree killed after it, one film at a time (it holds the `lemo-film` agent-run lock
until its render is judged, and no other agent run starts meanwhile), LEMO_FILMS_PER_DAY
(3) started per owner-local day, and every heavy command through the GPU lock
(`src/studio/gpu_run.py`). The delivered `final.mp4` goes through the normal render + QC
(normalised like an edit; the motion freeze limit) into the Inbox as an own-rights motion
idea; any failure skips the order with the reason. The content agent never sees Lemo
orders and they never wake its light run.
Reason: the owner wants to order videos in any of the library's ~100 styles (2026-11-21).
A Lemo film is code the session writes, renders and mixes (headless Chrome, ffmpeg): it
cannot be made without a shell. A shell can read any file the user can (the deny rules only
cover the Read tool), so the protection is what the process holds: no secret in its
environment, no MCP server, no publishing path, a workspace outside the repo, a time cap
and the token cap.

## 2026-11-21: A heat budget: heavy jobs use half the CPUs and the watchdog cools the laptop (171)
Every heavy child (Blender, Remotion, ffmpeg, the voice service and its model worker) runs on
the first `GUARD_CPU_SHARE` (0.5) of the logical CPUs (affinity, inherited by its children:
8 of 16 = 4 physical cores) with matching thread counts (Blender `-t`, ffmpeg `-threads`,
Remotion `--concurrency` <= half, torch / Whisper threads). The resource guard's watchdog
(166) now also pauses the processes under whoever holds the GPU lock (a dev script,
`gpu-run.py`; checked on the lock itself, never the stale `.holder` file) and pauses to cool:
GPU >= 83 °C until <= 74 °C (was 88 / 80); 60 s at >= 95 % of the GPU power limit or with
the CPU throttled (Windows `% Performance Limit` < 80: no CPU temperature without admin
drivers) -> 3 min; after `GUARD_MAX_BUSY_MIN` (15) minutes of continuous GPU work -> 3 min
(duty cycle). Heat never kills a job any more (paused, it cools); only RAM still short after
3 min does. Time spent paused does not count against a render's timeout. The watchdog writes
`data/logs/guard.log` (a state line every 30 s while heavy work runs, one per action, each
synced to disk, rotated at 4 MB). Windows power plans stay the owner's.
Reason: 2026-11-21 01:41 the laptop (i7-11800H + RTX 3070 Laptop at 130 W, High performance
plan, 230 W adapter) cut its own power (Kernel-Power 41, bugcheck 0) under ONE Blender render
correctly alone under the GPU lock for 18 min: 16 CPU threads + the GPU flat out. The old
watchdog watched only the studio's own children, at 88 °C, with no CPU signal and no log
that survived the crash.

## 2026-11-20: A Meta block pauses the studio's Graph calls, posts wait (167)
A Graph error that means Meta blocked the studio, not one request (code 200 subcode 5258005
"API access blocked.", code 368 temporarily blocked for policy, code 190 subcode 460/463/467 on
the studio's own token), trips a circuit breaker in `GraphClient._make_request`: every Graph
call is then refused at once (`AccessBlocked`, no network call, no request-budget slot) for
30 min, then one call goes through as the probe. A probe blocked again doubles the pause (60,
120, 240 min, cap 6 h); any other answer from Meta resets it. The state is one worker_state
value (`graph_blocked`) shared by the worker, the API, the MCP server and agent runs; a new
token in .env starts clean. A blocked post goes back to pending until the next try without
counting an attempt (like the publishing quota); data jobs and the Stories snapshot skip; the
token status caches a failed check for 10 min instead of raising; the website shows one alert
until the breaker resets. A post that already failed is put back with the Calendar's Replan
(no new command).
Reason: 2026-11-19 and 2026-11-20 Meta flagged the owner's developer account (« Account
confirmation needed »): post #13 burned its 3 attempts in a second and failed, the worker kept
calling a blocked account every few minutes and every website page called debug_token. Only
the owner can unblock it (Confirm Account on developers.facebook.com); a 6 h cap keeps a long
block quiet while the post still goes out the same day once access returns.

## 2026-11-20: A resource guard keeps the studio from freezing the PC (166)
Every heavy child the studio starts (Blender, Remotion's node and Chrome, ffmpeg, the voice
service and its model worker, agent CLI runs) runs at low priority (Windows
BELOW_NORMAL_PRIORITY_CLASS, POSIX nice 10). A heavy GPU job, once it holds the GPU lock (145),
also waits until free RAM >= `GUARD_MIN_FREE_RAM_GB` (8), free VRAM >= its need (voice 6 GB (measured ~5.8; 7 never fit beside the desktop apps, step 170),
Blender 3 GB, Remotion 1.5 GB; when nvidia-smi answers) and the card is not busy above 40 %
(a game, a Blender started by hand; 2026-11-23, was "no other program uses more than 1 GB of
VRAM": Windows' per-process counters gave Discord 3.4 GB and dwm 1.5 GB while the whole card
used 0.9 GB, so every voice waited forever and each render failed « machine »); it logs "waiting for RAM / VRAM / a game". A
watchdog in the worker of `up` checks free RAM and the GPU temperature every 10 s: under 3 GB
or above 88 °C it suspends the studio's own heavy processes, resumes them above 6 GB and under
80 °C, and after 3 min still bad kills the newest (its render is retried later, the voice
model is just unloaded), with an alert on the website each time; it never touches a process
that is not the studio's. For `GUARD_STARTUP_GRACE_MIN` (10) minutes after `up` starts no
render, agent run or voice model load starts, and the catch-up starts one agent run at a time,
the next only once that run and its renders are done. Blender is launched only through
`cinematic.blender()` (dev runs: `python -m src.studio.cinematic <blender args>`); a test fails
on a launch anywhere else. `GUARD_WATCHDOG=false` turns the watchdog off.
Reason: the owner's laptop (RTX 3070 Laptop 8 GB, 32 GB RAM) froze hard twice (2026-11-19 and
2026-11-20, Kernel-Power 41): the voice model and a Blender started outside the lock on the
GPU at once, everything at normal priority, and heavy work began within a minute of logon.
Owner: « try and do something for the computer to prevent it from stopping and surcharging
like this ».

## 2026-11-20: A voiced video is loudness-normalised by its voice, and the voice is peak-limited before the mix (161)
The target stays -14 LUFS integrated, true peak <= -1 dBTP. A video with a voice (motion
templates, Blender skits, remixes with a voice-over) no longer goes through the mix's two-pass
`loudnorm`: one linear gain puts the voice's gated loudness at -14 LUFS (the mix may land up
to 0.5 LU off it), then the true-peak limiter. Every render mixes the voice as
`recipe.dialogue_voice()`: its peaks limited to 10 LU over its loudness, at the same loudness
(a `<voice>.dialogue-<hash>.wav` next to the TTS file). The QC hears that same file. Videos
without a voice keep the loudnorm finish.
Reason: the VoxCPM2 voices peak ~19-22 dB over their loudness. At -14 LUFS that is 5+ dB over
the -1 dBTP ceiling: `loudnorm` went dynamic and squeezed the voice into the bed (voice 7-11 LU
over it after the finish, 14-15 before), and a linear gain with the mix limiter rode the bed
with every syllable and still ended at -14.4 to -14.9 LUFS. Limiting the voice alone keeps the
bed steady: measured on all 10 Remotion templates, the finish now takes at most 0.5 LU off the
voice's margin (it took up to 4.1), at -14.2 to -14.6 LUFS and <= -1.8 dBTP.

## 2026-11-20: The agent never parks a change request; it asks for styles, invented ones too (156)
Every video the owner sends back gets a decision the Inbox shows (`assets.agent_decision`):
remade in its style, restyled (a « même vidéo, autre style » work order the agent makes at
once; the old video is archived when the new one is submitted), a style requested
(`request_style`, new `style_requests` table) or waiting with a reason. Style requests are
`reference` (from a Reel) or `invented` (an original concept: look, palette, motion,
typography, sound, 3 scenes, why); the owner says « Construire » / « Non » on the Agent page
and the lead's dev loop builds the accepted ones (`ig-campaign style-requests list --status
accepted`, then `mark ID building|live`): the agent never writes code. The weekly invented
style is folded into `daily-learn` (it runs when `invent_due`, i.e. no invented request in 7
days, even on a quiet day) instead of a new `weekly-styles` schedule entry, so no schedule
default and no OS task change. A new enabled style or template (compared with a copy in
worker_state) starts the light run again while any video waits for changes or an order is
scheduled.
Reason: owner 2026-11-20: run 9 read 10 change requests and remade none (« re-rendering would
only give the same videos »), and nothing said why. Folding into daily-learn keeps one
nightly analysis run that already reads the style breakdowns.

## 2026-11-19: Macro 3D is Remotion over Blender plates (154)
The `macro3d` style renders in two passes: Blender (`cinematic/engine/macro.py`) renders the
photoreal shots the Remotion template lists (`plates` from `schemas.mjs --validate`), cached per
shot, then the Remotion template `Macro3D` composes the captions, the presenter and the end
card over them. Both passes take the GPU lock one after the other (step 145). A 40 s video costs
about 12-15 minutes of Blender the first time.
Reason: photoreal macro plates need a real renderer (light, depth of field, subsurface), while
the word-by-word captions, the presenter and the end card are motion design Remotion already
does; one direction (the shot list in TypeScript) keeps the cuts and the overlays in step.

## 2026-11-19: The batch mix's floors take at most half the batch (142)
Each allowed option's floor in the batch mix (`MIX_FLOOR`, 0.10) is now capped at 0.5/k for
k options (was 1/k): the floors never take more than half the batch, so likes and the
engagement index still split the other half. Up to 5 options nothing changes.
Reason: the new style templates (Cutaway, then PixelCinema and Editorial) bring the template
dimension to 8-10 options; with 0.10 floors the learned part fell to 20 % at 8 templates
and to nothing at 10 (every template equal, likes ignored).

## 2026-11-19: The voice models run in a worker process; takes are checked by faster-whisper (146)
The voice service keeps the HTTP API in a light process (no torch, ~40 MB) and runs VoxCPM2 +
Whisper in a worker process it terminates at idle unload, so the OS gets all its memory back.
A worker that dies or fails = HTTP 503, GPU lock released, a fresh worker on the next request.
The take check (step 038's Whisper large-v3-turbo on the CPU) now runs through faster-whisper
int8 (`mobiuslabsgmbh/faster-whisper-large-v3-turbo`, or `VOXCPM_WHISPER`) instead of the
transformers fp32 pipeline: on the same take it heard the same words (score 1.0 both),
word times within ~0.3 s, in 10 s instead of 22 s, with a ~4 GB peak instead of ~13 GB. The
voice itself (VoxCPM2, settings, voices) is unchanged.
Reason: after step 145's idle unload the one-process service still held 19.6 GB of committed
RAM (torch's CPU allocator keeps freed memory) and the machine had 2.6 GB free; a take peaked
at ~22 GB, most of it Whisper's word timestamps.

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

## 2026-11-21 — Blender renders through Vulkan, not OpenGL (step 176)
The owner's laptop (AORUS 15P XD, RTX 3070 Laptop, driver 596.49 then 621.24) powered off six times (Kernel-Power
41, no bugcheck) the instant a Blender EEVEE render took the GPU to full load through OpenGL, also after a cleaning
and a driver update, also 30 s into a test at 53 °C. The owner's DirectX games run for hours, and the same shots
through Blender's Vulkan backend rendered clean at the same load (126 W, 71 °C, the 8-shot proof in 13.1 min vs
18.6 min). `cinematic.blender()` (the one launch point) passes `--gpu-backend vulkan`;
`CINEMATIC_GPU_BACKEND=""` goes back to Blender's default.

## 2026-11-21 — Trending Instagram music, attached by id, the video cut on its beat (step 178)
GOAL.md §5.1 says the Graph API cannot attach Instagram's music library, so every bed is ours.
That changed: Meta's Instagram Audio API (changelog 2026-06-01, Facebook Login tokens) lists
the trending audio (`GET /ig_audio?audio_type=music|original_sound`, a search with
`search_query`), gives one track with a `download_url` to the full file (~1.5 days), and a
Reel container takes `audio_configuration={audio_id, audio_volume, video_volume}`
(developers.facebook.com/docs/instagram-platform/content-publishing/audio-api; no start offset
is documented). Checked live on macrobody.fr (business): `music` is the royalty-free library
(little-known tracks, the owner's wish), the chart hits only come as `original_sound`.
Decision: a voiced motion video may take an Instagram track (`ig_audio` in the recipe) instead
of the template's bed (music-only videos later: the clean master must pass QC on its own). The track is never in our file: the local copy only gives the beat map
(src/studio/music.py) and the owner's review preview; publish attaches it by
id. The voice lines move onto the beats, downbeats and the drop, so every template's scene
cuts land on the beat. A fixed `audio_volume` replaces the ducking (the track set 15 LU under
the -14 LUFS voice). Our own beds stay the default and the fallback.
Beats come from CPJKU/beat_this (MIT, model final0, CPU only, ~8 s a track) in its own venv
`data/tools/beats` (603 MB, torch CPU; install lines in music.py), not the studio's venv,
which keeps torch out (as for Earshot, step 149). Measured on 12 trending tracks against
beat_this, a stdlib finder scored beats F 54 and downbeats F 37, librosa 58: half the cuts
would land off the beat. The stdlib finder stays as the fallback when the venv is missing.
Open: whether Instagram plays an attached track from 0:00 (the sync assumes it) needs one
test publish the owner approves; Instagram's mixing level is unknown, so the preview mirrors
the volumes literally.
Reason: the owner (2026-11-21): trending, unknown music, and the cuts on the beat and the drop.

## 2026-11-23: A sent-back Lemo film is remade by the film runner; half-made orders come back (202)
A Lemo-Opuscar film has no template, so when the owner sent one back the AI could only answer
« waiting » ("the night run will re-cut it"). The night run had no film path either: video
43 stayed parked through runs 45, 46, 50 and 51. Now `decide_revision(asset_id, "remade", why)`
on a film makes a change order in the film's own Lemo style with `why` (what to change) in
its instruction. The film runner makes it like any Lemo order, and the old video is archived
once the remake is in the Inbox. The agent still never makes films itself (173). A new
decision on a video skips the order of its earlier decision when nothing was made for it yet,
so one video never gets two remakes.
An order a dead agent run left `in_production` with nothing made (run 34 was killed between
`create_idea` and the render: order 51 stayed there for a day) goes back to `scheduled`, with
the idea unlinked, when the next work packet is built, once it has been untouched for the
agent's time cap (`AGENT_TIMEOUT_MINUTES`). If it was a change order and its video got
another decision since (still sent back, or archived meanwhile: order 31, replaced by order
37), it is skipped instead. Lemo orders keep
`film.close_orphans`.
Reason: « AI never parks » (156): the owner relaunched a run for video 43 and nothing came of it.

## 2026-11-24: The AI never makes or skips a Lemo film order (203)
The 03:00 run of 24/11 restyled videos 2, 3, 4 and 5 into Lemo-Opuscar styles (orders 63–66)
and then, as the playbooks said for every restyle, wrote their ideas itself with
`create_idea(work_order_id=…)`. Two were refused as near-duplicates of earlier remakes of the
same scripts and the AI skipped them; the other two were `in_production` with no film running,
so the film runner's `close_orphans` closed them as interrupted. No film was made and the four
videos went back to waiting. Now `create_idea(work_order_id=…)` and `skip_work_order` refuse a
Lemo order (« the studio's film runner makes it »), and both playbooks say to make nothing for a
restyle into a Lemo style. The film runner writes the idea itself (no duplicate check: a remake
reuses its script on purpose), as it already did for a remade film (202).
Reason: the AI's decision must be carried out (« AI never parks », 156).


## 2026-11-24: ElevenLabs speaks first, the local voice takes over (204)
GOAL.md §4.1 / H3 planned one local TTS service. The owner added ElevenLabs: with
`ELEVENLABS_API_KEY` set, every voice-over goes through two engines in the owner's order (Voix
page: « ElevenLabs d'abord » by default, or « Voix locale d'abord »), the other one taking over
on any failure (no credits, an HTTP error, no answer). ElevenLabs voices are their own cards
(owner's choice over one twin per local card), added from the Voice Library on the Voix page;
each names a local relay voice, so a fallback keeps the gender and the role the AI picked. The
model is the owner's pick (default `eleven_v4`). Credits are checked before each call: too few
is a fallback, never a cut-off voice. Scripts carry ElevenLabs audio tags (`[excited]`,
`[laughs]`): the studio strips them from all on-screen text and from the local engine's text,
so only ElevenLabs hears them. A video whose voice fell back shows it on its card, and the bell
says so once per new failure. ElevenLabs' error bodies are not in docs we could read: every
non-2xx falls back, whatever its code.
Reason: owner 2026-11-24 (« first ElevenLabs, then if there's no credits or a bug, the local
audios »; « super important to use the ElevenLabs emotion tags »).

## 2026-11-24: The Lemo film limit is the owner's, 0 = no limit (205)
`LEMO_FILMS_PER_DAY` (default 3) is now in Studio settings, where the owner can change it.
0 means no limit (it used to mean no films). A film the studio restart killed
(`DEAD_RUN`) no longer counts toward the limit; a timed-out film still does, since its tokens
were spent. "Videos made per day" (`BATCH_SIZE`) keeps its 1..50 range: it is how many ideas
the AI makes on its own each night, not a cap on the owner's orders (they already pass a
full batch, 134), so "no limit" has no meaning there.
Reason: owner 2026-11-24. A hidden limit blocked an order as « quota du jour atteint »;
two of that day's three films had died (one timeout, one restart).

## 2026-11-24: "Videos made per day" 0 = no limit (206)
`BATCH_SIZE` 0 means no limit, like `LEMO_FILMS_PER_DAY` (205, whose note that it keeps
1..50 this replaces). The night run then makes as many good ideas as its turn budget allows:
`limits.ideas`, `effective_batch_size` and `places.ideas_left` are null, the mix's `count`
is null (the agent follows each option's `share`), and there is no bench brake (BATCH_FLOOR
and the bench surplus only shrink a set size). The shares still hold, measured on the
batch so far with the next idea included: explore at most ceil(n x EXPLORE_SHARE), the
humour / informative split within ±1 of its target, the owner's style shares. A day whose
places were opened with a limit keeps it until midnight. "Most posts per day" stays
1..25: the publishing slots and the bench's supply days divide by it.
Reason: owner 2026-11-24 (« Videos made per day must do the same… where 0 can be
unlimited »).

## 2026-11-24: Lemo films speak through the studio's voice engines (207)
204 left Lemo films on the local voice service (`voices.json` without the ElevenLabs cards,
the brief pointing at the service), because a film holds no secret and could not call
ElevenLabs. So a film sent back with « new voice » could only pick another local voice
(video 78). Now the film runner serves the studio's own engines (`tts.get_provider`:
ElevenLabs and the local voice in the owner's order, each taking over for the other) on a
loopback port behind a one-run token, for as long as the film runs (`src/agent/film_voice.py`).
The brief points the film there with the same request and answer as the local service
(base64 WAV), plus `take.engine` and `take.fallback`. The film gets the ElevenLabs cards in
its `voices.json` and may write audio tags. The key stays in the runner process.
Reason: owner 2026-11-24 (« it should be generating the same video, only with the 11 Labs
voice »).

## 2026-11-25: The Voix page casts, ElevenLabs is retried, one engine per video (audit)
Changes 204's "the other engine takes over on any failure". With ElevenLabs first, the
cards on are the voices the AI, the films and the sitcom cast pick from, and a local voice
with no card of its own (the default « souriante ») speaks in a card of its gender: the
local voices are relays only. ElevenLabs' passing faults (no answer, 429, 5xx) are retried
twice with a short backoff; a bad text (400 / 422) fails that line for a rewrite, not the
engine. An engine failing before any line spoke hands over as before; one failing after
lines already spoke stops the video as a machine error (it is voiced again later in one
engine), never a switch of voice mid-video. A card's relay must be of its gender. Films
record their takes, so their fallback shows on the card and rings the bell like a video's.
Reason: owner 2026-11-25 (« voices follow what is checked and preferred from the UI »);
video 76 / 78 spoke VoxCPM, and one 429 could turn ElevenLabs off for a whole video.

## 2026-11-25: A style the owner bans is swapped for its closest alternative
An owner `dont` rule on a style (or a template) no longer refuses the work: the studio
remakes it in the closest style he keeps (styles.alternative: same address tu / vous, then
the most words the two descriptions share; a Lemo style first tries its own category).
Orders and ideas asked in it get the alternative (check_style), a send-back remake in it is
restyled in it (decide_revision, the decision's why says so), an idea already in it moves
to it at render (check_template), and the AI's style list leaves it out. A banned template
alone sends the AI to another template of the same style.
Reason: owner 2026-11-25 (« If I ban a style, then it should automatically choose the best
suiting styles alternative that can be used »).

## 2026-11-25: An owner's order is made exactly as asked, or waits for the style built for it
The AI watches the Reel of a work order (`download_reel`, frames, timeline) before it writes
anything, to understand it only (an inspired video still reuses nothing). It picks the style
that can make every part of the instruction; when none can, it requests the style
(`request_style(..., unblocks_order_ids=[id])`) and makes nothing. A style request that
unblocks a work order starts `accepted` (no « Construire » needed: the order is the owner's
ask), goes to the build list, and holds the order (`work_orders.held_by_style`): the agent
does not see it until the style is live or declined; the Planning page shows it « attend son
nouveau style ». Only the safety and rights rules change what was asked, and the video's
description then starts « Pas fait comme demandé : ».
Reason: owner 2026-11-25: DM order 75 asked for a band rolling over a jacked man's muscles
with the Reel's music. Run 73 requested « Physique Scan » and left the order open; run 74 saw
it open and made it in Sitcom 3D with library music, without watching the Reel.
« The AI should literally do what I tell it to do. »

## 2026-11-25: A DM'd Reel waits on « Reçus »; nothing starts before the owner's « Lancer »
Replaces step 136's « a DM with a note is scheduled at once ». Every Reel a pinned account
sends by DM is a work order `received`, listed on the new « Reçus » page (its note is the
draft instruction). The owner picks the route (`work_orders.method`): `style` (the same video
in an existing style, or Auto), `new_style` (the agent requests a style built from the Reel,
held for it as above) or `rea` (rea-video breaks the Reel down shot by shot, the agent remakes
it from that breakdown in the chosen style), then « Confirmer » -> `confirmed`: on the Planning
page, no time, « attend ton « Lancer » ». His « Lancer » schedules it (the light run on that
order); « Écarter » / « Retirer » drop it. A DM order still waiting for an instruction
(needs_instruction) moves to « Reçus »; one already scheduled keeps its old path. A route takes
any style of the catalog: a Lemo-Opuscar film gets the Reel in its workspace (`reference/reel.mp4`,
and on the rea route its breakdown in `reference/rea/`; owner 2026-11-26: « I don't see all the
styles »). A card stays on « Reçus », in the order the Reels came, until its video is in the Inbox;
one that failed after « Lancer » shows why, with « Relancer » (back to confirmed) or « Retirer »
(marked cancelled). The agent never sees, skips,
marks or holds a received / confirmed order; for `new_style`, the lead marks the request
live with the style id it became (`style-requests mark <id> live --style <id>`) and the
order is then made in that style only.
rea-video (JuneYaooo/rea-video, Apache-2.0) is cloned into vendor/rea-video (git-ignored) with
its own venv (`ig-campaign rea setup`), runs offline on CPU (no vision model, no key) with the
downloader's env allow-list, and only reads: the agent gets its VIDEO.md through the
`breakdown_reel` tool (agent profile: local, publishes and renders nothing).
Reason: owner 2026-11-25: « When a video is sent in the messenger, it shouldn't go directly
into the planning. It should go into this new page. Then I confirm it [...] Then I can launch
the work of this video or not. »

## 2026-11-25: « Physique Scan », the style built for the owner's DM order 75
The style requests « Muscle Scan » (4), « Scan 3D Athlète » (5) and « Physique Scan » (19) all
asked for the same Reel (https://www.instagram.com/reel/DetQ8tOOEkg/): it is 3D kinetic type on
rolling bands over a cream drafting grid (navy, orange, teal), not a realistic body scan. The
owner's words: the same effect, the bands rolling over a jacked person's muscles while he
trains and eats, macro and calorie texts, ending on macroBody. Built as one style `physique`:
template `PhysiqueScan` (motion/src/templates/PhysiqueScan) over the troupe engine in a new
`blueprint` look (cinematic/engine/bands.py): a flat navy statue (three looks tagged
`physique` in cast.json, orange shorts and a sports top drawn by the shader, no clothes
mesh), the room and its decor removed for a cream world and grid floor, the set in cream
with ink edges, and up to 4 bands per shot whose type is wrapped onto a cylinder round a
body part's bone and rolls. Cuts fall on the bed's beat (three studio beds measured with
music.measure); no voice; its own end card. The statues are refused in any other look.
The Reel's song cannot be reused (a famous track, rights rules): the template keeps its own
beds, and an Instagram track is not attached (music.apply needs a voice).
Reason: owner 2026-11-25 (« reopen and build »); render cost like the sitcom's (8 shots of
1 s: ~9 min, then cached).

## 2026-11-25: « Physique Scan » rebuilt round a 3D muscle (the statue dropped)
The owner rejected the first build: « there is only one band », « there is a 3D model of a
person, and I said 3D objects [...] a super detailed 3D mesh object of a muscle », « the colors
are really bad. Have some more freedom with the colors », « a lot of bands going over it and
maybe, squeezing it », then « the band, the tilt, and whoosh, and go up and down, and do
different squeezes on different parts ». Replaces the entry above's engine: the troupe's
`blueprint` look, bands.py and the three statues are gone (troupe, cast and sitcom back as they
were). `cinematic/engine/anatomy.py` (standalone, ~1.5 s a frame) draws a muscle of 40 fibre
bundles cut open, a tendon and veins, in a palette per scene (lab, neon, candy), with 2-6 bands
per scene that pull tight, rock, whoosh between stops (up or down together, the leading band
first, never through each other) and squeeze the flesh under them by Geometry Nodes, each stop
its own grip. The template's scenes are now {palette, bands [{text, tone, squeeze}], label,
beats, camera (orbit, push, top, glide)}; a whoosh plays as the bands fly. Cached per shot under
media/physique.
Reason: owner review in chat 2026-11-25.

## 2026-11-25: « Physique Scan »: five objects and a motion design layer
The owner on the muscle version: « It needs to be dynamic. It needs to treat all other [...]
objects, not show only muscles, and [...] there isn't a lot of effects. Maybe we add a layer of
node of motion design over the render in Blender. » A scene now picks its `subject`: muscle,
dumbbell, kettlebell, heart (it beats) or bone (a femur), built in cinematic/engine/anatomy.py.
The bands whoosh twice a shot (three stops, a whoosh sound on each), and the engine adds by
itself: shockwave rings where a band clamps down, orbiting halo rings, floating specks, the
object turning and popping in, motion blur, camera punches and shake, and a Blender compositor
(bloom, colour fringes and lens bulge kicking on every whoosh, a vignette). The owner asked for
no video render with it: it was checked on one low-res still per object only.
Reason: owner review in chat 2026-11-25.
