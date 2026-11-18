# Instagram Campaign MCP

An MCP server that lets Claude (or any MCP client) run **organic Instagram campaigns**
on the official Instagram Graph API: publish, schedule, moderate, measure, and find
the posts that beat your own average — the ones worth turning into ads.

Fork of [jlbadano/ig-mcp](https://github.com/jlbadano/ig-mcp) (MIT), rebuilt for
Graph API v25 and MCP SDK 2.x.

## What it adds over upstream

| Area | Upstream | This fork |
|---|---|---|
| Publishing | single image/video (video broke: no processing wait) | image, **carousel** (2–10), **Reels**, **trial Reels**, **Stories**, with container polling |
| Scheduling | – | local queue + scheduler (`daemon`, `run-due`), retries, crash-safe |
| Insights | v19 metrics incl. deprecated ones | per-type metrics (feed / Reels / Stories), auto-fallback when Meta rejects one |
| Comments | – | list, reply, comment, hide/unhide, delete |
| Research | – | hashtag top/recent posts, competitor stats (Business Discovery) |
| Winners | – | daily insight snapshots, scoring vs **your account's median**, A/B variant comparison |
| Auth | token in URL query | `Authorization: Bearer` header (token never in URLs/logs) |

## The campaign loop

```
plan ─► publish / schedule_post (tag campaign + variant + hypothesis)
          │
          ▼
   collect_insights (daily) ─► rank_posts ─► winners = ad candidates
          │                         │
          └──── compare_variants ◄──┘   (which hook / format / CTA wins)
```

- **Trial Reels** (`trial_graduation`) show a Reel to non-followers first — a clean way
  to test hooks without spamming followers. `SS_PERFORMANCE` lets Instagram share it
  to followers if it performs; `MANUAL` leaves that to you in the app.
- A post is judged after **48h**, only against posts **of the same type**, read at a
  **similar age** (a 2-day-old post isn't compared with posts measured at 30 days),
  and needs a minimum reach (default 300) before it can be called a winner.
- **Stories** are judged on a snapshot taken 20–24h after posting (they expire at
  24h). The scheduler daemon snapshots live Stories every hour; without it, run
  `ig-campaign collect --stories-only` hourly. A Story that expired without such a
  snapshot is reported as `incomplete`.
- `engagement_index` = weighted average of per-reach rates divided by your median:
  follows ×4, shares ×3, saves ×3, profile visits ×2, comments ×1.5, likes ×0.5,
  Reels avg watch time ×2. `1.0` = typical post.
- **Winner** = enough reach and either engagement ≥ 1.5× (`WINNER_THRESHOLD`) **or**
  reach ≥ 2× the median with at least median engagement (a post that travelled far
  without diluting engagement).

## Setup

### 1. Meta prerequisites
- Instagram **Business or Creator** account linked to a Facebook Page.
- A Meta developer app with the Instagram Graph API.
- A **long-lived user token** (60 days) with: `instagram_basic`,
  `instagram_content_publish`, `instagram_manage_insights`, `instagram_manage_comments`,
  `pages_show_list`, `pages_read_engagement`, `business_management`.
  As the app's admin you can use these on your own account without App Review.
  See [AUTHENTICATION_GUIDE.md](AUTHENTICATION_GUIDE.md).
- Hashtag search needs the *Instagram Public Content Access* feature on the app.

### 2. Install (one command)
```bash
git clone https://github.com/enimarix/instagram-campaign-mcp.git
cd instagram-campaign-mcp
```
**Windows** (PowerShell):
```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -RegisterClaudeCode
```
**macOS / Linux**:
```bash
./install.sh --register-claude-code
```
The installer:
- creates `.venv` with Python 3.12 using [uv](https://docs.astral.sh/uv/) if it is
  installed (uv downloads Python itself, so a new machine only needs uv), otherwise
  with any installed Python 3.10+;
- installs the package, and creates `.env` from `env.example` (never overwrites it);
- writes `mcp-config.json` with this machine's paths, ready to paste into
  Claude Desktop;
- with `-RegisterClaudeCode` / `--register-claude-code`, runs `claude mcp add`
  (user scope) so Claude Code sees the server right away.

Options: `-Dev` / `--dev` also installs test dependencies and runs the 67 tests
(no network); `-Name` / `--name` changes the server name (default `instagram`);
`-Schedule` / `--schedule` starts the studio by itself (see "Run the studio").
Re-running the installer is safe and upgrades the install.

Then fill in `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_BUSINESS_ACCOUNT_ID` in `.env`.
Don't know your account ID? Set only the token, connect the server, and call
`get_account_pages`.

<details><summary>Manual install</summary>

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp env.example .env
pytest -q
```

End-to-end smoke test (seed → Inbox → Calendar → publish against a local Graph API stub,
no network, fake token; needs the `.venv` above or `PYTHON=<path>`):
```bash
cd web && npm ci && npx playwright install chromium   # once
npm run e2e                                           # builds the website, runs web/e2e/
```
</details>

### 3. Connect to Claude

**Claude Code**: use `--register-claude-code` above, or run the `claude mcp add`
command the installer prints.

**Claude Desktop**: merge the generated `mcp-config.json` into
`claude_desktop_config.json` (Windows: `%APPDATA%\Claude\`, macOS:
`~/Library/Application Support/Claude/`), then restart Claude Desktop. It looks like:
```json
{
  "mcpServers": {
    "instagram": {
      "command": "/path/to/instagram-campaign-mcp/.venv/bin/ig-campaign-mcp"
    }
  }
}
```
The `.env` in the project folder is found automatically.

### 4. Run the scheduler (if you schedule posts or measure Stories)
The Graph API publishes immediately — it has no "post at 18:00". Keep this running
on a machine that's on at posting time (it also snapshots live Stories hourly;
`--stories-every 0` turns that off):
```bash
.venv/bin/ig-campaign worker   # Windows: .venv\Scripts\ig-campaign.exe worker
# or, with the venv activated:
ig-campaign worker            # checks every 60s (`daemon` is the old name, still works)
# or from cron / Task Scheduler every 5 min:
ig-campaign run-due
```
A post more than `MAX_LATE_MINUTES` (default 30) late, for example because the PC was
asleep, is moved to the next free slot instead of being published late, and two posts
never go out closer than `MIN_SLOT_GAP_MINUTES`. `PUBLISHING_PAUSED=true` holds the whole
queue; the website's pause switch (`POST /api/worker/pause` / `resume`) overrides it.

On Windows the worker registers one Task Scheduler task, `IGCampaignWake`, that wakes
the PC 5 minutes before the next queued post. Windows only honours it when wake timers
are allowed: Control Panel → Power Options → Change plan settings → Change advanced
power settings → Sleep → Allow wake timers → Enable (on battery too, for a laptop).
Also run `ig-campaign collect` once a day (or ask Claude to call `collect_insights`).
If a publish fails because the daily quota is reached, the post waits an hour and
tries again without using up its retries. If Instagram might have published it
anyway (timeout, or an error while the post shows as published), it is marked
failed for you to check instead of risking a double post.

### 5. Run the studio (website + API + scheduler)
Needs Node 22.12+ once, to build the website:
```bash
npm --prefix web ci && npm --prefix web run build   # again after each website update
ig-campaign up                                      # API, website and the daemon above
```
Open http://127.0.0.1:8765. Ctrl+C stops everything. Without an Instagram token it
starts in setup mode: the website works, publishing idles until the token is in `.env`.

To review from your phone, set `UI_PASSWORD` in `.env`, then
`ig-campaign up --host 0.0.0.0` and open `http://<pc-ip>:8765`. Without a password
the studio only answers on 127.0.0.1 / localhost. Plain `http://` on Wi-Fi is enough
to watch and approve; recording on the phone needs HTTPS (Tailscale serve or a
tunnel, gate H7).

**Autostart and daily agent runs.** `ig-campaign agent install-schedule` (or the
installer's `-Schedule` / `--schedule`) starts `ig-campaign up` at logon and runs the
playbooks of `AGENT_SCHEDULE` (default `daily-learn@02:00,daily-produce@03:00`,
comma-separated `playbook@HH:MM` in `TIMEZONE`) every day with `ig-campaign agent run-due`:
`daily-learn` analyses yesterday's best and worst Reels, updates the learnings and writes
the daily report the night batch then builds on (skipped when nothing was published or
matured); add `daily-revise@14:00` for the light afternoon run (change requests and
feedback only).
Before each run the studio writes its work packet (`work/` in the agent workspace) and
skips the run when there is nothing to do (see `src/agent/packet.py`). On Windows
these are Task Scheduler tasks of your user (`IGCampaignUp`, `IGCampaignAgent-<playbook>`;
the run tasks wake the PC when wake timers are allowed, see above); elsewhere a block
between `# ig-campaign begin/end` in your crontab. A run missed while the PC was off
starts when the studio comes up the same day. Re-run after changing `AGENT_SCHEDULE`;
`--remove` takes it all out. The Settings page shows each playbook's next and last run.

### 6. Reel downloader (Track A reactions)
Public Reels for reactions are downloaded with the owner's chosen
[Okramjimmy/Instagram-reels-downloader](https://github.com/Okramjimmy/Instagram-reels-downloader)
(Next.js, MIT), a git submodule in `vendor/instagram-reels-downloader` pinned to a
known commit. It is logged out, so it never touches the brand account.
```bash
git submodule update --init vendor/instagram-reels-downloader
ig-campaign downloader setup    # npm ci + build; npm audit advisories are logged
ig-campaign downloader status   # built?, port, commit, last health check
ig-campaign downloader update   # latest upstream commit, kept only if healthy (stop `up` first)
```
Once built, the worker (`up` / `worker`) runs it on `127.0.0.1:DOWNLOADER_PORT`
(default 3711, never exposed), restarts it if it dies and stops it on exit; its output
goes to `data/logs/downloader.log`. Only its `/api/video` API is called, never its
pages (they carry ads), and it gets no credential of ours. Set `DOWNLOADER_HEALTH_URL`
to a public Reel permalink for the daily health check (`up` / `down` / `broken`,
`GET /api/downloader/status`); `update` needs it.

`download_reel` (MCP, agent profile) and the "Download for reaction" button on Trends
(`POST /api/sources/download`) save a public Reel to `data/media/sources/<id>/` as a
`commentary` clip with its creator: the service first, then `yt-dlp` if installed
(`pip install -e ".[download]"`, Python 3.11+). Limits: `MAX_DOWNLOADS_PER_DAY` (30),
`DOWNLOAD_DELAY_S` (5), `MAX_DOWNLOAD_MB` (200). `DOWNLOADER_COOKIES_FILE` (yt-dlp only)
must be a separate personal account, never the brand account. When both fail, the source
says why; save the video yourself and drop it into `data/inbox/`.

### 7. Backups and restore
Every night the worker copies the database to `data/backups/studio-<date>.db`
(`BACKUP_DIR`) with SQLite's online backup and keeps the newest 14 (`BACKUP_KEEP`). Media
files are not backed up. To get the studio back from one, stop `up` / `worker` first:
```bash
ig-campaign restore data/backups/studio-2026-11-17.db   # asks first; --yes when scripted
```
It refuses while the worker runs, when the file fails `PRAGMA integrity_check`, or when it
was written by newer code. The current database is kept as
`<db>.before-restore-<UTC time>`, then pending migrations run on the restored one.

To keep the database small, insight snapshots of posts older than 45 days
(`SNAPSHOT_THIN_AFTER_DAYS`) keep only the age-schedule points (1 h, 3 h, 6 h, 12 h, 24 h,
48 h, 7 d, 30 d: the snapshot nearest each) and the latest; the rest are dropped daily and
the file is compacted (`VACUUM`) once a week. Scores and post pages read only those.

## Tools (30)

**Account** `validate_access_token`, `get_account_pages`, `get_profile_info`,
`get_account_insights`, `get_publishing_limit`
**Content** `get_media_posts`, `get_media_insights`
**Publish now** `publish_image`, `publish_carousel`, `publish_reel`, `publish_story`
**Schedule** `schedule_post`, `list_scheduled_posts`, `reschedule_post`,
`cancel_scheduled_post`, `run_due_posts`
**Comments** `get_comments`, `reply_to_comment`, `comment_on_media`, `hide_comment`,
`delete_comment`
**Research** `search_hashtag`, `get_competitor_profile`
**Winners & A/B** `collect_insights`, `rank_posts`, `compare_variants`, `label_post`
**DMs** (needs `instagram_manage_messages`, see INSTAGRAM_DM_SETUP.md)
`get_conversations`, `get_conversation_messages`, `send_dm`

### Tool profiles
`IG_MCP_PROFILE` picks which tools the server registers (an unknown value stops it):
- `full` (default): all 30 tools, for the owner's interactive sessions.
- `agent`: only a read-only allow-list (`AGENT_TOOLS` in `src/instagram_mcp_server.py`)
  for unattended runs; the agent runner (step 058) uses it. Nothing that publishes,
  schedules, comments, hides, deletes, relabels, sends or reads DMs is registered, so
  it can neither be listed nor called. New tools stay out until added on purpose.

## Limits to know
- Media must be at a **public HTTPS URL**; Instagram downloads it.
- Images must be **JPEG** (the publishing API rejects PNG). Feed images: any ratio
  from 4:5 to 1.91:1. Reels: MP4/MOV H.264 + AAC, 9:16 recommended.
  Carousels crop every slide to the first slide's ratio. These checks run before
  anything is sent to Meta (`VALIDATE_IMAGE_RATIO=false` skips them).
- ~100 API-published posts per rolling 24h (`get_publishing_limit` shows usage).
- Stories via API: no stickers, links or text overlays — bake them into the media.
- 30 unique hashtag searches per 7 days.
- Client-side cap of 200 API calls/hour (`RATE_LIMIT_REQUESTS_PER_HOUR`): when it is
  reached, calls fail at once with "next slot in N min" instead of hanging.
- Tokens expire after 60 days unless you use a system-user token (see Token below).
- Insights count organic interactions only; ad interactions are excluded.

## Token
`INSTAGRAM_ACCESS_TOKEN` is a long-lived user token: it lasts about 60 days. When it
expires every Graph call fails, so **nothing publishes** (queued posts wait, then show
as failed) and insights stop until a new token is in `.env`.
- `ig-campaign token status`: valid or not, expiry date, days left and scopes (asks
  Meta's `debug_token`). The website shows the same on Settings and a banner on every
  page from 10 days before expiry. The token itself is never printed or logged.
- `ig-campaign token refresh`: swaps the token for a new 60-day one and rewrites only
  the `INSTAGRAM_ACCESS_TOKEN=` line of `.env`. Needs `FACEBOOK_APP_ID` and
  `FACEBOOK_APP_SECRET`, a token that has not expired yet, and the token set in `.env`
  (not in the shell environment). Restart `ig-campaign up` and the MCP server afterwards.
- No expiry at all: a **system-user token**. In Meta Business Suite → Business settings →
  Users → System users, add an admin system user, assign it your Page, Instagram account
  and app, then "Generate new token" with the scopes from env.example and no expiry. Put
  it in `.env`; status then shows "never". Treat it like a password: it never expires.

## Configuration
See [env.example](env.example). Most useful: `TIMEZONE` (default Europe/Paris, used
for schedule times without an offset), `WINNER_MIN_AGE_HOURS`, `WINNER_MIN_REACH`,
`WINNER_THRESHOLD`, `DATABASE_PATH`, `MEDIA_ROOT` (asset files, served at `/api/media`;
`ig-campaign dev seed --db x.db` puts them in `media/` next to `x.db`, so point `MEDIA_ROOT`
there too if you open that seed in the website).

`.env` and the database live in the project folder for a clone or the installer's
editable install. With a plain `pip install .` they go to `~/.instagram-campaign-mcp`
instead (the code then sits in site-packages). `IG_MCP_HOME` overrides both.

## Roadmap
- Paid side: promote winning posts as ads (existing post as creative), A/B tests,
  budget caps enforced in code.
- Resumable upload for local video files (no public URL needed).

## License
MIT — original work © José Luis Badano; campaign extensions © Amine El Kerzazi.
