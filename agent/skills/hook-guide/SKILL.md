---
name: hook-guide
description: This channel's own hook constraints (on-screen length, recent hooks, sources) and how to pick an idea's hook_type from brand/taxonomy.json. Load it after the viral-hooks skill, before writing any idea's hook.
---

# Hook guide

**Write every hook with the `viral-hooks` skill first**: its rules, archetypes, formulas,
checklist and the lock-in lines after the hook. This guide adds what is specific to this
channel (length on screen, recent hooks, sources, `hook_type`). Where they differ, this
channel's constraint wins.

The hook is the text on screen in the first second, plus the first spoken line. Most
viewers decide in that second whether to keep watching, and many watch with the sound
off. One idea, one hook, one `hook_type`.

## Rules for every hook

- **≤ ~8 words on screen.** Short words, no subordinate clauses. If it needs a comma,
  it is probably two hooks: pick one.
- **Readable with the sound off.** The on-screen text alone must make sense; the voice
  may add to it, never complete it.
- **Concrete beats abstract.** A number, an object, a place or a person the viewer can
  picture ("Your fridge", "1 banana", "Roman soldiers") beats "this fact" or "something".
- **Curiosity, never a lie.** The video must pay off exactly what the hook promises, in
  this video, not in "part 2". No "you won't believe", no fake urgency, no claim the
  sources do not back. A hook that overpromises gets a dislike and teaches the audience
  to scroll past us.
- **One promise.** The viewer should be able to say what they will learn or laugh at.
- **Fits the 8-bit frame.** The pixel font is large: short lines wrap badly. Think of it
  as a game title screen, not a headline.
- **Not a recent hook.** Check the brief's `recent_hooks` and `bench.hooks`: a new angle
  on the same topic is fine, a reworded copy is not.

## By format

**8-bit facts** (FactQuest; pillar like fun facts). Lead with the surprising part, not
the topic. Weak: "Facts about octopuses". Better: "Octopuses taste with their arms". The
levels then deliver the facts; the first level must keep the hook's promise.

**Myths** (BossBattle; myth vs fact). Name the belief the viewer holds, then signal the
fight. "You only use 10% of your brain? Wrong." The verdict screen must state the
corrected fact with its source in the idea.

**Quiz** (QuizChest). Ask something the viewer thinks they know, with an answer that
surprises. "Which weighs more: a cloud or a car?" Choices must be fair: one right answer
the sources back, distractors that are plausible, not jokes.

**Story** (DialogStory). Start in the middle, at the moment of tension. "The king banned
forks. Here's why." No "Once upon a time", no setup the viewer must sit through.

**POV humour** (PixelSkit). A situation the viewer has lived, in their words. "POV: the
loading bar hits 99%". The punchline comes at the end, never in the hook; the hook only
sets the trap.

## One pattern per `hook_type`

| hook_type | Pattern | Example |
|---|---|---|
| `question` | A direct question with a non-obvious answer | "Why do cats hate closed doors?" |
| `bold_claim` | A short, sourced, surprising statement | "Honey never goes off." |
| `curiosity_gap` | Show the effect, hold back the cause | "This town has no traffic lights. On purpose." |
| `pov` | "POV:" + a relatable moment | "POV: you said 'you too' to the waiter" |
| `myth_bust` | The belief + a verdict word | "Goldfish forget in 3 seconds? False." |
| `number_list` | A small number + a concrete subject | "3 foods older than the pyramids" |
| `story` | A character at the turning point | "He sold the Eiffel Tower. Twice." |
| `challenge` | A dare with a time limit or a score | "Guess the country in 3 pixels" |

These are patterns, not templates to fill word for word: write each hook for its own
topic and keep the examples out of the videos.

## Choosing a hook_type

**Exploit idea** (most of the batch): use what the evidence says works.
- Start from learnings: an owner rule wins; then `do` learnings about hook types; then
  hook types of liked videos and of `rank_posts` winners.
- Avoid hook types tied to `dont` learnings or to dislikes with the reason "weak hook".
- Match the format: myths → `myth_bust` or `bold_claim`; quiz → `question` or
  `challenge`; humour → `pov` or `story`; facts → `bold_claim`, `curiosity_gap` or
  `number_list`.

**Explore idea** (a deliberate test): change one thing and say which in the hypothesis.
- Try a hook type the channel has used little or never on that format, keeping topic
  and template proven, so the result says something about the hook.
- Or keep the hook type and test something else, but never change everything at once.
- Write the hypothesis as a bet that can lose: "A `challenge` hook keeps quiz viewers
  past second 3 better than a `question` hook".

## Quick check before `create_idea`

1. ≤ ~8 words on screen, readable without sound?
2. Does the video deliver exactly this promise?
3. Is every fact in it sourced in `citations`?
4. Different from the recent and bench hooks?
5. Is the `hook_type` the one this hook actually uses?
