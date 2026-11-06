## Work computer

Never merge or deploy without my explicit approval for that change.

## Agent seats and models

Each agent seat has a model. This is a rule, not a mechanism: there is no launch helper and no lookup.

| Seat | Model |
|---|---|
| Coordinator | Opus 5.5 medium |
| Lead | Sonnet 5.5 high |
| Planner | Sonnet 5.5 high |
| Reviewer | Opus 5.5 medium |
| Builder | Haiku 5.5 xhigh; escalate to Sonnet 5.5 high on failure, or when the work is ambiguous |
| Browser work | Sonnet 5.5 high |

- Every brief's first line names the seat and the model.
- The builder executes a plan. Workers default to Haiku 5.5 xhigh and escalate to Sonnet 5.5 high on failure or when the work is ambiguous. Opus plans and reviews; it does not build.
- Sessions I open myself are not covered by this table. Their default is set separately.
- No OpenAI models for now.
- If you are unsure of a model ID for a harness, use the human names above. Agents read this table; nothing parses it.
