# Capability tiers

A standalone registry of capability tiers (low, medium, high) and a read-only resolver that previews which
model and effort a work role would get. **Stage 0:** it is wired into no harness. Nothing reads it yet except
the resolver you run by hand.

Decisions behind it (owner, 2026-10-20): the registry is its own config that any harness may read, Loop Engine
included; on quota exhaustion a role falls back to the next candidate **in the same tier** and never to a lower
one; reviewers may fall back too, and a same-model review is allowed but flagged; Loop Engine `model_bindings`
are not emitted; every model, order and provider is owner configuration. Research and sources:
`~/tmp/research-20261020/tiers/NOTES.md` (cartwmic/dotfiles#11).

## Files

| Source | Deploys to | Purpose |
| --- | --- | --- |
| [`tiers.toml.tmpl`](./tiers.toml.tmpl) | `~/.local/share/agent-harness/capability-tiers/tiers.toml` | The registry, rendered per chezmoi profile (`personal`, work). Edit the source, not the rendered file. |
| [`executable_resolve.py`](./executable_resolve.py) | `.../capability-tiers/resolve.py` | Read-only resolver. Python 3.11+ (`tomllib`), standard library only. |

Tests live in `tests/capability-tiers` and are source-only.

## Registry

- A **candidate** is `provider/model@effort`. The same model may appear in two tiers at different efforts
  (Sol at medium and at xhigh). A tier lists candidates in preference order.
- `[providers.<name>]` maps a Pi provider to a quota **pool** (the key in the pi-sub cache: `anthropic`,
  `codex`, `openrouter`) and may set `enabled = false`. Models in one pool share one account window, so one
  exhaustion removes all of them.
- `[roles]` gives each work role its default tier; `default_tier` covers roles not listed. `[peers].roles` are
  the roles that should get different models from each other.
- The personal example matches the owner's decisions: low = Haiku 5.5 xhigh, then Luna max; medium = Sonnet 5.5
  high, then Sol medium; high = **Opus 5.5 high first**, then Sol xhigh, then Astra high. The work profile is a
  TODO placeholder (Anthropic only); the owner will fill in the work tiers later, so do not rely on it.

## Resolution

Tier precedence: slot override, then `--run-tier`, then the role default, then `default_tier`. Effort precedence:
slot, then `--run-effort`, then the candidate's own effort. Each assignment records where its tier and effort came from.

Within the tier the resolver takes the first candidate whose provider is enabled and whose pool is not exhausted.
If the first candidate was skipped, the assignment records the fallback and why. Slots in peer roles that land in
the same tier get different models when enough are available. If not, a model is reused and the slot is marked
`same_model_review` (shown as "same-model review" and added to warnings). It is never blocked.

If a tier has no available candidate the slot is `unavailable`, the earliest known reset time is printed, and the
exit code is 2. It does not fall to a lower tier.

## Quota

Input is the pi-sub cache (`~/.pi/agent/cache/sub-core/cache.json`) or any file of the same shape. Pool status:

| Status | Meaning | Excludes the pool? |
| --- | --- | --- |
| `exhausted` | A window that has not yet reset is at 100%, or you passed `--exhausted POOL` (a failure you saw). | yes |
| `near-limit` | A window is at or above `near_limit_percent` (default 97). A hint only. | no |
| `unknown` | No data, or data older than `stale_after_seconds`. | no (warns) |
| `ok` | Fresh data, nothing near a limit. | no |

**Staleness default: 600 seconds (10 minutes).** Change it in the registry (`[quota] stale_after_seconds`) or per run
with `--stale-after`. The percentage is a hint and a reported provider failure is the truth, so low remaining quota
alone never moves a role. A window whose reset time has passed is ignored. Anthropic's usage endpoint that pi-sub
polls is undocumented and may change.

## Use

```sh
R=~/.local/share/agent-harness/capability-tiers
python3 "$R/resolve.py" \
  --slot driver --slot T1=implementer --slot T2=implementer \
  --slot "T3=implementer|tier=medium|reason=touches auth" \
  --slot ordinary-reviewer --slot challenge-reviewer
# add --json for the machine-readable plan, --exhausted anthropic to rehearse a failure,
# --known-models <(pi --list-models) to warn on ids Pi does not list
```

Exit codes: 0 resolved, 1 bad input or registry, 2 a slot has no available candidate.

## Not built (by decision)

No harness integration, no Pi virtual models, no automatic switching, no Loop Engine or eval-harness change, no
binding output, no model call. Those are later, separate approvals.
