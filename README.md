# Macrobody Growth Studio

A video studio for one Instagram account, run by an AI agent and steered by you. Every
night the agent studies what worked, writes and renders a batch of short vertical videos
(8-bit motion videos and reaction remixes of viral Reels), and puts them in a review feed
on a website. In the morning you scroll the feed on your phone and decide on each video:
approve, decline, ask for a change, or save it for later.

The studio publishes what you approve at good, spread-out hours, measures how each post
does, and learns from both the numbers and your comments. Nothing is published without
your approval. Everything runs on your own computer; the website is local. The full plan
is in [GOAL.md](GOAL.md). The project began as an Instagram MCP server for Claude, and
that server is still included (see [docs/DEVELOPING.md](docs/DEVELOPING.md)).

## 1. Setup

You need Git, [uv](https://docs.astral.sh/uv/) (or Python 3.10+), Node.js 22.12+ and
ffmpeg. The installer checks for each one and tells you how to install what is missing.

```bash
git clone https://github.com/enimarix/instagram-campaign-mcp.git
cd instagram-campaign-mcp
```

| | One command |
|---|---|
| Windows (PowerShell) | `powershell -ExecutionPolicy Bypass -File .\install.ps1 -Schedule` |
| macOS / Linux | `./install.sh --schedule` |

The installer sets up Python, builds the website, installs the video packages, builds
the Reel downloader, creates `.env` (an existing one is never changed) and ends with
`ig-campaign doctor`. Each line shows ✔ or ✖, and every ✖ says what to do. Fix those
lines and run the installer again: you can re-run it safely.

`-Schedule` / `--schedule` makes the studio start by itself at logon (Windows) or
reboot (macOS / Linux) and adds the nightly agent runs. Leave it out to try the studio
first; you can add it later with `ig-campaign agent install-schedule`.

**Then:**
1. Fill in `.env`: at least `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_BUSINESS_ACCOUNT_ID`
   (see the Meta prerequisites below). Set `UI_PASSWORD` if you want to review from your
   phone.
2. Sign in to Claude Code once: `claude auth login`.
3. Start the studio: `ig-campaign up` (in `.venv\Scripts\` on Windows, `.venv/bin/`
   elsewhere), then open http://127.0.0.1:8765.
4. Run `ig-campaign doctor` whenever you want to check that everything is in place.

Without an Instagram token the studio starts in setup mode: the website and the renders
work, and publishing waits until the token is in `.env`.

**Meta prerequisites.** An Instagram Business or Creator account linked to a Facebook
Page, and a Meta developer app. The token is a long-lived user token from **Facebook
Login** (about 60 days), with `instagram_basic`, `instagram_content_publish`,
`instagram_manage_insights`, `instagram_manage_comments`, `pages_show_list`,
`pages_read_engagement` and `business_management`. DM picks also need
`instagram_manage_messages`, and hashtag search needs the app's *Instagram Public Content
Access* feature. As the app's admin you can use all of this on your own account without
App Review. Step by step: [AUTHENTICATION_GUIDE.md](AUTHENTICATION_GUIDE.md).
You don't know your account ID? Set only the token and ask Claude to call
`get_account_pages`.

**What only you can provide.** Some parts wait for you. The studio still runs without
them, using placeholders. Details are in [GOAL.md §8](GOAL.md#8-what-only-the-owner-can-provide-human-gates).

| Gate | You provide | Until then |
|---|---|---|
| H1 | Logo, colours, niche in one sentence | Placeholder brand |
| H2 | Channel bible (the `story-bible-builder` interview) | Placeholder bible |
| H3 | A local text-to-speech service | Captions only, no voice-over |
| H4 | Clip sources and creators' permissions | Downloaded Reels and your own clips only |
| H5 | A valid Instagram token and a first real publish test | Setup mode: nothing publishes |
| H6 | Meta ad account, payment method, spending limit | No paid ads |
| H7 | How you reach the website from your phone (Wi-Fi or HTTPS) | Use it on the PC |
| H8 | Claude Code signed in, and a budget per run | No nightly batch |
| H9 | Language, target countries, what the account is for | Defaults |

## 2. A normal day

**At night.** The agent runs by itself (setting `AGENT_SCHEDULE`). At 02:00
`daily-learn` looks at yesterday's best and worst Reels, explains why they did well or
badly, updates what the studio has learned and writes the daily report. At 03:00
`daily-produce` makes the new batch: first the DM picks, then remixes of viral Reels,
then 8-bit videos. A run is skipped when there is nothing to do. If the PC was off, a
missed run starts when the studio comes up the same day. The Agent page shows each run
and its log.

**In the morning: the feed** (Inbox). One video per screen, like Reels. The best
candidates come first (the agent scores each one). On each video you can:
- **Approve**: it gets the next good slot and is published then. You have a few seconds
  to undo.
- **Decline**: it is archived. Pick a reason chip, because the agent learns from it.
- **Change**: pick reasons, write what to change, and optionally mark a moment in the
  video. The agent makes a new version in its next run.
- **Save for later**: it goes to the Saved tab, where you can approve it on another day
  until its best-before date.

Tap a video to open its page: sources for any facts, the creator credit, comments and
older versions. Reaction remixes ask you to confirm the rights when you approve them.

**DM picks.** On Settings → DM picks, pin the accounts you trust. When one of them sends
you a Reel by DM, the studio downloads it and the agent makes a commentary remix from it
first. The agent never reads your DMs. Only Reels from pinned accounts are used.

**The daily report** is at the top of Analytics (older ones are under Reports). It shows
the night's analysis, the best and worst Reels with the reasons, and ideas to try.
Learnings lists what the studio believes works. You can edit, confirm or retire any of
them, and your own rules always win.

**The calendar** shows what is queued and published this week. You can move or cancel a
post there. A post more than 30 minutes late (the PC was asleep, for example) moves to
the next good slot. It is never published late. The pause switch on Settings holds all
publishing without losing the queue.

**The AI label.** Our voice-overs are synthetic, so Meta asks for its "AI info" label on
those videos. Meta's publishing API can now set this label: the `is_ai_generated`
parameter, added on 22 June 2026
([Instagram Platform changelog](https://developers.facebook.com/docs/instagram-platform/changelog),
[media reference](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media)).
**The studio does not send it yet.** Until it does, open each AI-voiced Reel in the
Instagram app after it is published and add the label if the app offers it
(**⋯ → Edit**). If the app doesn't offer it, report this so the label is added to the
publish step.

## 3. When something goes wrong

Problems show up under the bell at the top of the website, and on Settings.

| Problem | What to do |
|---|---|
| **Token expired or expiring** (banner on every page from 10 days before) | `ig-campaign token status` shows the expiry date. `ig-campaign token refresh` gets a new 60-day token and rewrites it in `.env`. This needs `FACEBOOK_APP_ID` and `FACEBOOK_APP_SECRET`, and the old token must still be valid. Then restart `ig-campaign up`. Once it has expired, make a new one (AUTHENTICATION_GUIDE.md). For a token that never expires, use a system-user token (see [docs/DEVELOPING.md](docs/DEVELOPING.md#token)). |
| **A publish failed** | Calendar shows the post in red with Meta's message. Fix the cause (often the token), then press **Re-plan** to give it a new slot. If the daily quota was reached, it waits an hour and tries again by itself. |
| **"Did these reach Instagram?"** (Calendar) | The publish may have gone through. The studio looks for the post on the account and marks it published if it finds it. If it is not on Instagram, press **Not on Instagram → release** so it can be queued again. It is never posted twice. |
| **A render seems stuck** | Settings → Worker must say it is running. If not, restart `ig-campaign up`. A render cut off by a crash or a restart is queued again after 10 minutes, and a render that fails 3 times is marked failed. To get a new version, ask for a **Change** on the video. `ig-campaign doctor` checks ffmpeg and Node.js. |
| **The Reel downloader is down** | `ig-campaign downloader status` shows its last health check. Stop the studio, then `ig-campaign downloader update` moves it to the newest version, and keeps that version only if it works. If downloads still fail, save the video yourself and drop it into `data/inbox/`. |
| **The database needs restoring** | Every night the studio keeps a copy in `data/backups/`. Stop the studio, then run `ig-campaign restore data/backups/studio-<date>.db`. The current database is kept aside. Media files are not part of the backup. |
| **Something else** | Run `ig-campaign doctor`. Logs are in `data/logs/`. |

## 4. Commands

Run them from the project folder. `ig-campaign` lives in `.venv\Scripts\` (Windows) or
`.venv/bin/`. Add `--help` to any command for its options.

| Command | What it does |
|---|---|
| `ig-campaign up` | Starts the studio: website, API and worker (`--host 0.0.0.0` for your phone, needs `UI_PASSWORD`) |
| `ig-campaign doctor` | Checks everything the studio needs and says how to fix what is missing |
| `ig-campaign token status` / `refresh` | Shows the token's expiry, or swaps it for a new 60-day one |
| `ig-campaign agent check` | Checks that Claude Code is installed and signed in |
| `ig-campaign agent run <playbook>` | Runs one agent playbook now, for example `daily-produce` (`--dry-run` makes ideas only) |
| `ig-campaign agent run-due` | Runs the playbooks that are due under `AGENT_SCHEDULE` |
| `ig-campaign agent install-schedule` | Adds autostart and the nightly runs to the OS (`--remove` takes them out) |
| `ig-campaign downloader setup` / `status` / `update` | Builds the Reel downloader, shows its health, or updates it |
| `ig-campaign restore <backup>` | Puts a nightly backup back (stop the studio first) |
| `ig-campaign facts` | Prints yesterday's numbers as JSON |
| `ig-campaign learnings refresh` | Checks every learning against the numbers now (normally done nightly) |
| `ig-campaign worker` | Runs only the worker, without the website |
| `ig-campaign run-due` / `collect` / `rank` | Runs one publish pass, takes one insights snapshot, or prints the winners |

## 5. Configuration

Settings live in `.env`. [env.example](env.example) lists the common ones with
comments, and `src/config.py` has all of them with their defaults. Useful ones:
`TIMEZONE` (default Europe/Paris), `AGENT_SCHEDULE` (default
`daily-learn@02:00,daily-produce@03:00`; add `daily-revise@14:00` for an afternoon pass
on change requests), `MAX_POSTS_PER_DAY`, `POSTING_WINDOWS`, `UI_PASSWORD`,
`DOWNLOADER_HEALTH_URL` (a public Reel used for the downloader's daily check) and
`PUBLISHING_PAUSED`. Restart `ig-campaign up` after changing `.env`, and re-run
`ig-campaign agent install-schedule` after changing `AGENT_SCHEDULE`.

`.env` holds your secrets. It never leaves your computer and is never committed.

## 6. For developers

Architecture, the MCP tools and tool profiles, the scoring rules, API limits, tests and
CI are in [docs/DEVELOPING.md](docs/DEVELOPING.md). The rules for working on the code are
in [CLAUDE.md](CLAUDE.md), the plan in [GOAL.md](GOAL.md) and the roadmap in
[progress.md](progress.md).

## License

MIT. Original work © José Luis Badano; campaign extensions © Amine El Kerzazi.
