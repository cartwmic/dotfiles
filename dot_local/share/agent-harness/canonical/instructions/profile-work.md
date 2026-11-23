{{ $_ := includeTemplate "require_work_data" . -}}
## Work computer

Never merge or deploy without my explicit approval for that change.

## Agent seats and models

Each agent seat has a model. This is a rule, not a mechanism: there is no launch helper and no lookup.

| Seat | Model |
|---|---|
| Coordinator | GLM 5.3 Flash H200 high, Pi (work-glm/{{ .workGlmModelId }}) |
| Lead | GLM 5.3 Flash H200 high, Pi (work-glm/{{ .workGlmModelId }}) |
| Planner | GLM 5.3 Flash H200 high, Pi (work-glm/{{ .workGlmModelId }}) |
| Reviewer | GLM 5.3 Flash H200 high, Pi (work-glm/{{ .workGlmModelId }}) |
| Builder | GLM 5.3 Flash H200 high, Pi (work-glm/{{ .workGlmModelId }}) |
| Computer use | GLM 5.3 Flash H200 high, Pi (work-glm/{{ .workGlmModelId }}) |

- Every brief's first line names the seat and the model.
- Every seat uses Pi (`work-glm/{{ .workGlmModelId }}`, `high` thinking); T3 provider pi.
- Sessions I open myself are not covered by this table. Their default is set separately.
- No OpenAI models for now.
- If you are unsure of a model ID for a harness, use the human names above.

## Bar table

First match wins.

| Remote | Bar |
|---|---|
| `{{ .workGitHost }}/*`, `github.com/axon-*` | shared |

On this machine, never add a row for an employer repo to dotfiles (that would put its name in a public repo): after Michael answers, the answer holds for the session.
