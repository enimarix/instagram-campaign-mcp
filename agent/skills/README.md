Project skills for the agent runs (hook guide, brand voice: CTA and tu/vous), copied into the agent workspace outside the repo before each run.

`viral-hooks` is a snapshot. The live skill keeps learning from videos in the video-skills repo
(`learn-from-videos`); the runner copies the live one from HOOK_SKILL_DIR (default
`~/.claude/skills/viral-hooks`) and falls back to this snapshot only when it is missing.
Its text is also appended to every run's and film's system prompt
(`--append-system-prompt-file`), so the agent writes with it even if it never opens the skill.
