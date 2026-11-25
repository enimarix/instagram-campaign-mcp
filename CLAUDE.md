# CLAUDE.md

Developer instructions for this repo (humans and Claude Code dev sessions). The
unattended content agent never loads this file: it runs in a workspace outside the repo
(GOAL.md §4, third rule).

**Project:** an Instagram MCP server (Python) growing into Macrobody Growth Studio, an
AI-run, owner-steered video studio. Spec: [GOAL.md](GOAL.md). Roadmap and step status:
[progress.md](progress.md).

## Commands

- Install: `pip install -e ".[dev]"`
  (or `uv venv .venv --python 3.12 && uv pip install --python .venv/Scripts/python.exe -e ".[dev]"`)
- Test: `pytest -q` (no network; single test: `pytest -q tests/test_x.py::test_y`)
- CI: `.github/workflows/ci.yml`, ruff lint + pytest on Python 3.10 / 3.12 / 3.13
- Lint: `ruff check .` (rules in `pyproject.toml` `[tool.ruff]`; or `uvx ruff check .`)

## Layout

```
src/instagram_mcp_server.py  MCP server (tools)
src/instagram_client.py      Instagram Graph API client (async httpx)
src/store.py                 SQLite store (CampaignStore)
src/campaign.py, scoring.py  campaign logic, variant ranking
src/scheduler.py             `ig-campaign` CLI / worker
src/config.py                settings (pydantic-settings, .env)
src/models/                  pydantic models
tests/                       pytest (respx mocks, in-memory SQLite)
agent/playbooks/             prompts for the agent runs
agent/skills/                project skills copied into the agent workspace
brand/                       logo, palette, fonts, BIBLE.md, taxonomy.json
docs/                        DECISIONS.md and deeper docs
motion/                      Remotion templates (pixel, voxel, paper styles)
cinematic/                   Blender engine (blender style; tools via cinematic/setup.py)
data/                        runtime only, git-ignored
```

Coming later (GOAL.md §4.2): `src/api/`, `src/studio/`, `src/learning/`, `src/ads/`,
`web/`, `motion/`, `vendor/`.

## Rules you must never break (GOAL.md §5)

- MCP tools and API routes are thin doors onto service functions: no business logic in
  a tool handler or a route.
- Tests never touch the network or a real account: mock external services (respx).
- Nothing is published without `approved` status for that exact video.
- A clip with `rights_basis = unknown` is never queued.
- No detection-evasion edits (mirror / flip, speed or pitch shifts, re-crops to dodge
  duplicate or copyright detection). Never built.
- Every new MCP tool is deliberately placed in or out of the `agent` profile.
- Every hook, script or on-screen text (scripts, batches, remakes, reworks) is written with
  the `viral-hooks` skill; the owner's own words win over it.
- Where a step says **verify in docs**, check the current official docs for the
  external API before coding and write what they said in the PR.
- A decision that changes a GOAL.md default goes in [docs/DECISIONS.md](docs/DECISIONS.md)
  in the same PR.
- Secrets live in `.env` only, never in the repo, logs, URLs or the database.
