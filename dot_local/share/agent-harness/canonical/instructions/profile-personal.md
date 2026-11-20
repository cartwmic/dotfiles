## Personal computer

Merging and deploying approved work is yours to do: if checks pass and it keeps the product requirements, ship it and tell me after.

## Scheduled work

A schedule is agent work if a run starts or messages a model. Agent work on a clock is a kit job in the coordinator (`coordinator jobs`), and I approve it first unless it is a one-off less than 24 hours out. A system job (no model) stays on the machine's own scheduler, is defined in the homelab or dotfiles repo, and gets an approval row. `coordinator schedules check` lists and checks them all.

## Agent seats and models

Each agent seat has a model. This is a rule, not a mechanism: there is no launch helper and no lookup.

| Seat | Model |
|---|---|
| Coordinator | Opus 5.5 medium |
| Lead | Opus 5.5 medium |
| Planner | Sonnet 5.5 high |
| Reviewer | Opus 5.5 medium |
| Builder | Haiku 5.5 xhigh for small mechanical builds; Sonnet 5.5 high for anything long or ambiguous, and on any failure |
| Computer use | Sonnet 5.5 high |

- Every brief's first line names the seat and the model.
- The builder executes a plan. Haiku 5.5 xhigh builds small mechanical work. Sonnet 5.5 high builds anything long or ambiguous, and takes over on any failure. Opus plans and reviews; it does not build.
- Computer use runs through my cli proxy, like the other seats.
- Sessions I open myself are not covered by this table. Their default is set separately.
- No OpenAI models for now.
- If you are unsure of a model ID for a harness, use the human names above. Agents read this table; nothing parses it.

## Bar table

First match wins.

| Remote | Bar |
|---|---|
| `github.com/StoryCraftTW/storycraft` | shared |
| `github.com/cartwmic/*`, `gitea.internal.cartwmic.com/cartwmic/*` | personal |
