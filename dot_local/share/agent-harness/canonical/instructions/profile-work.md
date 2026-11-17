{{ $_ := includeTemplate "require_work_data" . -}}
## Work computer

Never merge or deploy without my explicit approval for that change.

## Agent seats and models

Each agent seat has a model. This is a rule, not a mechanism: there is no launch helper and no lookup.

| Seat | Model |
|---|---|
| Coordinator | Gemini 4 Hydrogen high, Cursor (gemini-4-hydrogen) |
| Lead | Gemini 4 Hydrogen high, Cursor (gemini-4-hydrogen) |
| Planner | GLM 5.3 Flash H200, Pi (work-glm/{{ .workGlmModelId }}) |
| Reviewer | Gemini 4 Hydrogen high, Cursor (gemini-4-hydrogen) |
| Builder | GLM 5.3 Flash H200, Pi (work-glm/{{ .workGlmModelId }}) |
| Browser work | GLM 5.3 Flash H200, Pi (work-glm/{{ .workGlmModelId }}) |

- Every brief's first line names the seat and the model.
- Coordinator, leads, and reviewers use Cursor (`gemini-4-hydrogen`, `high` reasoning effort). Planners, builders, and browser work use Pi (`work-glm/{{ .workGlmModelId }}`).
- Sessions I open myself are not covered by this table. Their default is set separately.
- No OpenAI models for now.
- If you are unsure of a model ID for a harness, use the human names above.
