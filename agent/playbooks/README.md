Prompts for the unattended agent runs (e.g. daily-produce.md, daily-learn.md); see GOAL.md §4.

`check-renders.md` (step 188c) is not scheduled: the worker's catch-up starts it a few
minutes after renders finish (src/agent/schedule.py check_run). It reviews each finished
video, re-renders or drops a broken one and submits the good ones; daily-produce no longer
waits for its renders.

`weekly-ads.md` (steps 096, 128) turns finished paid A/B tests into `ads` learnings and
proposes tests from organic winners; it never launches one: every launch is the owner's
Approve on the Ads page (the owner decides what is promoted: docs/DECISIONS.md). It is
not in the default
`AGENT_SCHEDULE`: once ads are set up (H6), add it with a weekday, e.g.
`AGENT_SCHEDULE=daily-learn@02:00,daily-produce@03:00,weekly-ads@mon 04:00`, then run
`ig-campaign agent install-schedule`. To run it **daily**, leave out the weekday:
`weekly-ads@04:00`. Its run is skipped while ads are not configured or there is nothing
to learn or propose.
