## Work computer

Never merge or deploy without my explicit approval for that change.

## Agent seats and models

Each agent seat has a model. This is a rule, not a mechanism: there is no launch helper and no lookup.

| Seat | Model |
|---|---|
| Coordinator | Opus 5.5 medium |
| Lead | Opus 5.5 medium |
| Planner | Sonnet 5.5 high |
| Reviewer | Opus 5.5 medium |
| Builder | Sonnet 5.5 high; Haiku 5.5 xhigh when steps are tightly bounded |
| Browser work | Sonnet 5.5 high |

- Every brief's first line names the seat and the model.
- The builder executes a plan. Use Haiku when each step is well bounded and Sonnet when there is some ambiguity. Escalate to a stronger model on failure. Opus plans and reviews; it does not build.
- Sessions I open myself are not covered by this table. Their default is set separately.
- No OpenAI models for now.
- If you are unsure of a model ID for a harness, use the human names above. Agents read this table; nothing parses it.
