# OpenRouter keys

Michael's OpenRouter account has one API key per application, so spend can be tracked per app on [openrouter.ai/activity](https://openrouter.ai/activity).

Keys live in the 1Password `developer` vault as items titled `OpenRouter key - <name>`, field `credential`. Never put a key value in this repo. Read keys at runtime with `op read`.

State as of 2026-11-06:

| Key | Caller | How the caller gets it |
|---|---|---|
| `pi-daily` | Pi interactive and subagent use | Stored in `~/.pi/agent/auth.json` as `openrouter-stashed` (machine-local). Written with `/openrouter stash`; read by the openrouter-gate extension. To rotate: `op read "op://developer/OpenRouter key - pi-daily/credential"`, then `/openrouter stash`. |
| `eval-system-one` | System One / Jev classifier evals and calibration runs | Set `OPENROUTER_API_KEY` for the run from `op://developer/OpenRouter key - eval-system-one/credential`. |
| `probe` | One-off probes and smoke tests | Same pattern: set `OPENROUTER_API_KEY` from `op://developer/OpenRouter key - probe/credential`. |
| `hindsight-rerank` | Hindsight reranker | Unused. Hindsight reranks locally (homelab `k8s/hindsight`). The key is ready if reranking moves back to OpenRouter. |
| `budget-steward` | Deployed budget-steward service (homelab `k8s/budget-steward` sealed secret) | Not switched yet. The deployment still uses the older key until the sealed secret is regenerated. |
| `pi-coding-agent` | Old shared key, also used by the deployed budget-steward and Hindsight's sealed secret | Kept working until every caller has switched. Retiring it is Michael's call. |

The management key is item `OpenRouter management key`. It creates keys and reads `/api/v1/activity`. Keys have no credit limit.
