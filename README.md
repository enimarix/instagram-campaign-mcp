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
- A post is judged after **48h** (Stories after 20h), only against posts **of the same
  type**, and needs a minimum reach (default 300) before it can be called a winner.
- `engagement_index` = weighted average of per-reach rates divided by your median:
  follows ×4, shares ×3, saves ×3, profile visits ×2, comments ×1.5, likes ×0.5,
  Reels avg watch time ×2. `1.0` = typical post. Winner = ≥ 1.5 (configurable).

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

Options: `-Dev` / `--dev` also installs test dependencies and runs the 37 tests
(no network); `-Name` / `--name` changes the server name (default `instagram`).
Re-running the installer is safe and upgrades the install.

Then fill in `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_BUSINESS_ACCOUNT_ID` in `.env`.
Don't know your account ID? Set only the token, connect the server, and call
`get_account_pages`.

<details><summary>Manual install</summary>

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scriptsctivate
pip install -e ".[dev]"
cp env.example .env
pytest -q
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

### 4. Run the scheduler (only if you schedule posts)
The Graph API publishes immediately — it has no "post at 18:00". Keep this running
on a machine that's on at posting time:
```bash
.venv/bin/ig-campaign daemon   # Windows: .venv\Scripts\ig-campaign.exe daemon
# or, with the venv activated:
ig-campaign daemon            # checks every 60s
# or from cron / Task Scheduler every 5 min:
ig-campaign run-due
```
Also run `ig-campaign collect` once a day (or ask Claude to call `collect_insights`).

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

## Limits to know
- Media must be at a **public HTTPS URL**; Instagram downloads it.
- Feed images: 4:5, 1:1 or 1.91:1. Reels: MP4/MOV H.264 + AAC, 9:16 recommended.
  Carousels crop every slide to the first slide's ratio.
- ~100 API-published posts per rolling 24h (`get_publishing_limit` shows usage).
- Stories via API: no stickers, links or text overlays — bake them into the media.
- 30 unique hashtag searches per 7 days.
- Tokens expire after 60 days; regenerate before then.
- Insights count organic interactions only; ad interactions are excluded.

## Configuration
See [env.example](env.example). Most useful: `TIMEZONE` (default Europe/Paris, used
for schedule times without an offset), `WINNER_MIN_AGE_HOURS`, `WINNER_MIN_REACH`,
`WINNER_THRESHOLD`, `DATABASE_PATH`.

## Roadmap
- Paid side: promote winning posts as ads (existing post as creative), A/B tests,
  budget caps enforced in code.
- Resumable upload for local video files (no public URL needed).

## License
MIT — original work © José Luis Badano; campaign extensions © Amine El Kerzazi.
