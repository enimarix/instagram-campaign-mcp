# Feature map — Growth Studio web app — 2026-11-25

Commit audited: `d6f09e2` · built `web/dist` served by `ig-campaign serve` (API only, no worker,
no renders, no agent runs) on 127.0.0.1 with a throw-away database seeded by
`dev seed --days 14 --seed 7`, a fake Instagram token and the Graph base URL pointed at a dead
local port. Nothing reached Instagram, ElevenLabs or Claude from the studio.

## Purpose
A private studio where the owner reviews the short videos the AI made, approves what goes to
Instagram, asks for new videos, and watches what works.

## Persona
**The owner** (one person, French-speaking, runs a fitness/nutrition brand). Uses it mostly on
the phone, often between other things; also at a desk for Settings, Styles and Voices.
Knows the product well, not a developer.

## Primary tasks (ranked)
1. Review today's videos in **Inbox**: approve, change, decline, save for later (phone).
2. Ask for a new video in **Créer**.
3. See what is scheduled (**Calendar**) and what the studio will do next (**Planning**).
4. Glance at **Analytics**.
5. Secondary: Styles, Voix, Trending, Ads, Agent, Settings.

## Navigation
Desktop (≥1024 px): left sidebar, 12 entries. Phone: bottom tab bar Inbox · Créer · Trending ·
Calendar · Agent · More; the other 7 pages behind **More**.

## Feature inventory

| # | Screen | Route | What it should do | API behind it | Tested |
|---|---|---|---|---|---|
| 1 | Inbox feed | `/inbox` | Full-screen feed of today's batch; Approve / Change / Decline / Save, 5 s undo, keyboard keys | `/api/assets`, `/proposed-slot`, `/approve-and-queue`, `/decline`, `/verdict`, `/bench` | yes: happy, double-tap, 500, slow, offline, keyboard, light |
| 2 | Inbox Saved tab | `/inbox` › Saved | Saved-for-later bench | `/api/bench` | viewed |
| 3 | Video detail | `/assets/:id` | Player, verdict buttons, caption edit, comments with reason chips | `/api/assets/:id`, `/feedback`, `/context` | viewed d/t/m |
| 4 | Créer | `/create` | Request a video (text, styles, address, length), the pile | `/api/work-orders` | yes: empty, 400+ chars, script text, emoji, double-submit |
| 5 | Planning | `/planning` | Supply gauge, next-24 h strip, chain of next jobs, launch selection, pause all | `/api/planning` | viewed d/t/m, light, a11y; launch not clicked (would start runs) |
| 6 | Trending | `/trending` | Watched topics, refresh, Mes envois | `/api/research/*` | viewed; Actualiser not clicked (calls Meta) |
| 7 | Calendar | `/calendar` | Week of scheduled posts, reschedule, release | `/api/calendar` | viewed, week navigation d/t/m |
| 8 | Analytics | `/analytics` | Report, KPIs, trends, funnel, like-rate | `/api/analytics/*`, `/api/reports/latest` | viewed d/t/m, light |
| 9 | Posts | `/analytics/posts` | Filterable posts list | `/api/posts…` | viewed (empty) |
| 10 | What works | `/analytics/breakdowns` | Tag breakdowns, A/B tests | `/api/analytics/breakdowns` | viewed (empty) |
| 11 | Daily report | `/reports` | Latest report | `/api/reports/latest` | viewed (none yet) |
| 12 | Trends | `/trends` | Inspirations + trends | `/api/research/*` | viewed (empty) |
| 13 | Learnings | `/learnings` | Rules the studio learned, filters, add a rule | `/api/learnings` | viewed (empty) |
| 14 | Styles | `/styles` | Gallery of ~108 styles, search, families, favourites | `/api/styles` | viewed d/t/m |
| 15 | Voix | `/voices` | Voice cards, engine priority, previews | `/api/voices` | viewed d/t/m, light, a11y |
| 16 | Ads | `/ads` | Budget, kill switch, tests | `/api/ads/*` | viewed; kill switch not clicked |
| 17 | Agent | `/agent` | Run playbooks now, style requests, runs | `/api/agent/*` | viewed; runs not clicked (would start Claude) |
| 18 | Settings | `/settings` | Theme, worker, Instagram, studio limits, styles shares, ads caps, clips, permissions, DM picks, downloader | `/api/settings`, … | viewed d/t/m, light |
| 19 | More | `/more` | Phone list of the pages without a tab | — | viewed |
| 20 | Not found | `/nope` | Not-found page | — | viewed |
| 21 | Login | (gate) | Password when `UI_PASSWORD` is set | `/api/session` | not tested: no password set in the audit run; the gate's loading state was tested (slow API) |

## Design reference
No separate design system doc; tokens live in `web/src/index.css` (`@theme`):
`--color-accent #ffcd75` (primary), `--color-muted #a3bccb` (AA on surface-2), surfaces
`bg / surface / surface-2`, `line`, `danger / warn / success / info / explore`; light theme
overrides under `[data-theme=light]`. Shared pieces: `ui/Button` (variants primary / default /
ghost / danger, `loading` spinner), `ui/Card`, `ui/Chip`, `ui/PageHeader`, `ui/Sheet`,
`ui/Tabs`, `ui/Toast`, `EmptyState` (dashed card). Radius tokens `rounded-control`,
`rounded-card`; touch targets `min-h-11` (44 px).
