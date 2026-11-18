Prompts for the unattended agent runs (e.g. daily-produce.md, daily-learn.md); see GOAL.md §4.

`weekly-ads.md` (step 096) proposes paid A/B tests from organic winners and turns finished
tests into `ads` learnings; it never approves or launches anything. It is not in the
default `AGENT_SCHEDULE`: once ads are set up (H6), add it with a weekday, e.g.
`AGENT_SCHEDULE=daily-learn@02:00,daily-produce@03:00,weekly-ads@mon 04:00`, then run
`ig-campaign agent install-schedule`. Its run is skipped while ads are not configured or
there is nothing to propose or learn.
