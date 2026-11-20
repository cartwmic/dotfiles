{{ $_ := includeTemplate "require_work_data" . -}}
## Work computer

Never merge or deploy without my explicit approval for that change.

## Agent seats and models

Each agent seat has a model. This is a rule, not a mechanism: there is no launch helper and no lookup.

| Seat | Model |
|---|---|
| Coordinator | Opus 5.5 medium, Claude Code (claude-opus-5-5) |
| Lead | Opus 5.5 medium, Claude Code (claude-opus-5-5) |
| Planner | GLM 5.3 Flash H200, Pi (work-glm/{{ .workGlmModelId }}) |
| Reviewer | Opus 5.5 medium, Claude Code (claude-opus-5-5) |
| Builder | GLM 5.3 Flash H200, Pi (work-glm/{{ .workGlmModelId }}) |
| Computer use | Sonnet 5.5 high, Pi (anthropic/claude-sonnet-5-5) |

- Every brief's first line names the seat and the model.
- Coordinator, leads and reviewers use Claude Code (Anthropic, `claude-opus-5-5`, `medium` effort); T3 provider claudeAgent. Planners and builders use Pi (`work-glm/{{ .workGlmModelId }}`). Computer use runs on Pi with `--provider anthropic --model claude-sonnet-5-5` at high thinking.
- Sessions I open myself are not covered by this table. Their default is set separately.
- No OpenAI models for now.
- If you are unsure of a model ID for a harness, use the human names above.

## Bar table

First match wins.

| Remote | Bar |
|---|---|
| `{{ .workGitHost }}/*`, `github.com/axon-*` | shared |

On this machine, never add a row for an employer repo to dotfiles (that would put its name in a public repo): after Michael answers, the answer holds for the session.
