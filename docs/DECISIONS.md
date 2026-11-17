# Decisions

Decisions that change a default of [GOAL.md](../GOAL.md), or that later work depends on.
One entry per decision, newest first:

```
## YYYY-MM-DD: <decision>
Reason: <why>
```

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
