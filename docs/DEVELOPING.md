# Developing

The owner's guide is the [README](../README.md). This file holds the technical details:
how the code is laid out, how to run the tests, the MCP server and its tools, and the
rules the campaign code follows. The rules for changing the code are in
[CLAUDE.md](../CLAUDE.md), the plan in [GOAL.md](../GOAL.md), and decisions that changed a
default in [DECISIONS.md](DECISIONS.md).

## Install and test

```bash
./install.sh --dev        # Windows: .\install.ps1 -Dev  (test dependencies + pytest)
```
or by hand:
```bash
uv venv .venv --python 3.12 && uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
# or: python -m venv .venv && .venv/bin/pip install -e ".[dev]"
pytest -q                 # no network; respx mocks, in-memory SQLite
ruff check .              # rules in pyproject.toml [tool.ruff]
( cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run build )
( cd motion && npm ci && npm run lint && npm run typecheck && npm test )
bash -n install.sh        # the CI lint job checks the installer's syntax
```
End-to-end smoke test (seed → Inbox → Calendar → publish against a local Graph API stub,
no network, fake token; needs the `.venv` above or `PYTHON=<path>`):
```bash
cd web && npm ci && npx playwright install chromium   # once
npm run e2e                                           # builds the website, runs web/e2e/
```
Optional extras: `.[download]` (yt-dlp fallback, Python 3.11+; the installers add it),
`.[stt]` (local transcription with faster-whisper; never installed in CI).

`ig-campaign dev seed --db x.db --days 3` fills a scratch database with a fake batch for
website work. Its media go to `media/` next to `x.db`, so point `MEDIA_ROOT` there when
you open that seed in the website. `npm --prefix web run dev` serves the website with a
proxy to the API on 127.0.0.1:8765.

CI (`.github/workflows/ci.yml`): ruff + `bash -n install.sh`, pytest on Python 3.10 /
3.12 / 3.13 (with ffmpeg), the website checks, the e2e smoke test (step 099) and the motion checks with test renders.

## Layout

| Path | What |
|---|---|
| `src/instagram_mcp_server.py` | MCP server: the tools, and the `full` / `agent` profiles |
| `src/instagram_client.py` | Instagram Graph API client (async httpx, v25.0) |
| `src/store.py` | SQLite store, append-only migrations |
| `src/campaign.py`, `src/scoring.py` | Queue, insights, winner scoring |
| `src/scheduler.py` | The `ig-campaign` CLI |
| `src/worker.py` | Publishing, renders, data jobs, housekeeping |
| `src/api/` | FastAPI routes (thin) and the website server |
| `src/studio/` | Production: assets, recipes and renders (ffmpeg), motion bridge, QC, publishing guard, sources, downloader, `doctor` |
| `src/learning/` | Analytics, slots, quotas, creative brief, learnings, reports, experiments |
| `src/agent/` | The locked-down Claude Code runner, work packets, OS schedule |
| `web/` | The website (React, Vite, Tailwind) |
| `motion/` | 8-bit templates (Remotion) |
| `vendor/instagram-reels-downloader` | The Reel downloader (git submodule) |
| `agent/` | Playbooks and skills for the agent runs |
| `brand/` | Brand kit, bible, taxonomy |

## The MCP server

The project began as a fork of [jlbadano/ig-mcp](https://github.com/jlbadano/ig-mcp)
(MIT), rebuilt for Graph API v25 and MCP SDK 2.x. Compared with upstream it adds
carousels, Reels, trial Reels and Stories with container polling; a local queue and
scheduler; per-type insights with a fallback when Meta rejects a metric; comment
moderation; hashtag and competitor research; daily snapshots, scoring against the
account's median and A/B comparison; and the token in the `Authorization` header,
never in URLs or logs. On top of that come the studio tools (ideas, renders, sources,
learnings, reports).

**Connect it.** The installer writes `mcp-config.json` with this machine's paths.
- Claude Code: `-RegisterClaudeCode` / `--register-claude-code`, or
  `claude mcp add --scope user instagram -- <path>/.venv/bin/ig-campaign-mcp`.
- Claude Desktop: merge `mcp-config.json` into `claude_desktop_config.json`
  (Windows: `%APPDATA%\Claude\`, macOS: `~/Library/Application Support/Claude/`), then
  restart it. The `.env` in the project folder is found automatically.

**Tool profiles.** `IG_MCP_PROFILE` picks which tools the server registers (an unknown
value stops it):
- `full` (default): every tool, for the owner's own sessions.
- `agent`: the allow-list `AGENT_TOOLS` in `src/instagram_mcp_server.py`, for the
  unattended runs. Nothing that publishes, schedules, comments, hides, deletes, approves,
  spends, sends or reads DMs is registered, so it can be neither listed nor called.
  `tests/test_mcp_profiles.py` pins both lists: every new tool goes into one of them
  on purpose.

The Instagram tools of the original server:
**Account** `validate_access_token`, `get_account_pages`, `get_profile_info`,
`get_account_insights`, `get_publishing_limit` ·
**Content** `get_media_posts`, `get_media_insights` ·
**Publish now** `publish_image`, `publish_carousel`, `publish_reel`, `publish_story` ·
**Schedule** `schedule_post`, `list_scheduled_posts`, `reschedule_post`,
`cancel_scheduled_post`, `run_due_posts` ·
**Comments** `get_comments`, `reply_to_comment`, `comment_on_media`, `hide_comment`,
`delete_comment` ·
**Research** `search_hashtag`, `get_competitor_profile` ·
**Winners and A/B** `collect_insights`, `rank_posts`, `compare_variants`, `label_post` ·
**DMs** (needs `instagram_manage_messages`, see INSTAGRAM_DM_SETUP.md)
`get_conversations`, `get_conversation_messages`, `send_dm`.

## How posts are judged

- A post is judged after **48 h**, only against posts **of the same type**, read at a
  **similar age** (a 2-day-old post isn't compared with posts measured at 30 days), and
  needs a minimum reach (default 300) before it can be called a winner.
- `engagement_index` = weighted average of per-reach rates divided by the account's
  median: follows ×4, shares ×3, saves ×3, profile visits ×2, comments ×1.5, likes ×0.5,
  watch ratio (or Reels average watch time) ×2. `1.0` = a typical post.
- **Winner** = enough reach and either engagement ≥ 1.5× (`WINNER_THRESHOLD`) **or**
  reach ≥ 2× the median with at least median engagement.
- **Trial Reels** (`trial_graduation`) are shown to non-followers first. `SS_PERFORMANCE`
  lets Instagram share them to followers if they perform; `MANUAL` leaves it to the app.
- **Stories** are judged on a snapshot taken 20–24 h after posting (they expire at 24 h).
  The worker snapshots live Stories every hour (`--stories-every 0` turns it off).

## Worker and publishing

The Graph API publishes immediately: something must be awake at the slot. `ig-campaign
up` (or `worker`) checks the queue every minute. A post more than `MAX_LATE_MINUTES`
(30) late is moved to the next free slot, two posts never go out closer than
`MIN_SLOT_GAP_MINUTES`, and `PUBLISHING_PAUSED=true` or the website's pause switch holds
the queue. On a quota error a post waits an hour without using a retry. When Instagram
might have published it anyway (a timeout, or an error while the post shows as
published), the asset goes to `publish_check` instead of risking a double post. A
reconcile job looks for it on the account; the owner can release it from Calendar.

On Windows the worker registers `IGCampaignWake`, which wakes the PC 5 minutes before the
next queued post. Windows honours it only when wake timers are allowed: Power Options →
Change advanced power settings → Sleep → Allow wake timers → Enable (on battery too).

`ig-campaign agent install-schedule` registers `IGCampaignUp` (at logon) and
`IGCampaignAgent-<playbook>` (daily, wakes the PC) as tasks of the current user on
Windows; elsewhere it writes a block between `# ig-campaign begin/end` in the crontab.
Before each run the studio writes a work packet (`work/` in the agent workspace,
`src/agent/packet.py`) and skips the run when it is empty.

**Reel downloader.** The submodule [Okramjimmy/Instagram-reels-downloader](https://github.com/Okramjimmy/Instagram-reels-downloader)
(Next.js, MIT) is pinned to a known commit, logged out, and never gets a credential of
ours. The worker runs it on `127.0.0.1:DOWNLOADER_PORT` (3711, never exposed) and
restarts it if it dies; its output goes to `data/logs/downloader.log`. Only its
`/api/video` route is called. `download_reel` and the Trends button try the service
first, then `yt-dlp` if installed. Limits: `MAX_DOWNLOADS_PER_DAY` (30),
`DOWNLOAD_DELAY_S` (5), `MAX_DOWNLOAD_MB` (200). `DOWNLOADER_COOKIES_FILE` (yt-dlp only)
must belong to a separate personal account, never the brand account. The installers run
`git submodule update --init` only while the submodule is missing, so a re-run never
undoes `ig-campaign downloader update`.

**Backups.** Every night the worker copies the database to `data/backups/studio-<date>.db`
(`BACKUP_DIR`, SQLite online backup) and keeps 14 (`BACKUP_KEEP`). `ig-campaign restore`
refuses while the worker runs, when the file fails `PRAGMA integrity_check`, or when it
was written by newer code; the current database is kept as
`<db>.before-restore-<UTC time>` and pending migrations run on the restored one. Insight
snapshots older than 45 days (`SNAPSHOT_THIN_AFTER_DAYS`) keep only the age-schedule
points and the latest; the file is compacted weekly.

## Token

`INSTAGRAM_ACCESS_TOKEN` is a long-lived user token (about 60 days). When it expires,
every Graph call fails: nothing publishes and insights stop. `ig-campaign token status`
asks Meta's `debug_token` (the token itself is never printed or logged). `token refresh`
uses `fb_exchange_token` and rewrites only the `INSTAGRAM_ACCESS_TOKEN=` line of `.env`.
It needs `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET` and the token set in `.env` (not in the
shell environment).

No expiry at all: a **system-user token**. In Meta Business Suite → Business settings →
Users → System users, add an admin system user, assign it the Page, the Instagram
account and the app, then "Generate new token" with the scopes from env.example and no
expiry. Status then shows "never". Treat it like a password.

## Limits to know

- Images must be **JPEG**; feed images 4:5 to 1.91:1. Reels: MP4/MOV H.264 + AAC, 9:16.
  Carousels crop every slide to the first slide's ratio. Checked before anything is sent
  (`VALIDATE_IMAGE_RATIO=false` skips it). Studio videos are uploaded from local files
  (resumable upload); the original tools still take public HTTPS URLs.
- About 100 API-published posts per rolling 24 h (`get_publishing_limit`).
- Stories via the API: no stickers, links or text overlays.
- 30 unique hashtag searches per 7 days.
- Client-side cap of 200 Graph calls per hour (`RATE_LIMIT_REQUESTS_PER_HOUR`); data jobs
  stop at 80 % of it.
- Insights count organic interactions only.

## Where files live

`.env`, the database and `data/` live in the project folder for a clone or the
installer's editable install. With a plain `pip install .` they go to
`~/.instagram-campaign-mcp` instead. `IG_MCP_HOME` overrides both, `IG_MCP_ENV_FILE`
the `.env` path.
