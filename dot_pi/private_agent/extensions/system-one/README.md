# System One in Pi

## Purpose and delivery

The `personal` and `axon-work-computer` settings include one
[System One Git package](https://github.com/cartwmic/system-one-tools).
This directory is docs-only: no local `index.js` or `index.ts` loader.
Termux excludes `.pi`. Native first-delivery targets are macOS with Pi
0.99.2+ and Node.js 22.19+. Source checks are not runtime delivery proof;
no new Linux Pi proof is claimed. The independent standalone CLI retains
its Node.js 20+ macOS/Linux contract and shared connection catalog.

[AGENTS.md](AGENTS.md) covers maintenance; repo-root `AGENTS.md` owns
chezmoi, secrets and apply approval. Source reconciliation alone does not
install or update the package or apply these files. The Git URL is unpinned;
updates, deployment and paid tests require separate approval. After an approved
deployment/restart, `pi list` checks configuration and `/so status` checks
command loading, not provider callability.

## Native setup and selection

Pi owns classifier providers, authentication, transport and pricing. Configure
native providers/models in Pi's `models.json`, using Pi `/login` or provider
runtime environment variables as appropriate. `/so settings` offers persistent
classifier selection and agent defaults, guidance, and Provider/auth setup;
it neither edits credentials nor reads or migrates the CLI `connections.json`.
Do not put credential values in this public tree or transcripts.

Selection is an explicit provider/id pair, independent of the chat model and
CLI default. `/so use` offers available native classifiers; `/so use <provider>
<id>` sets a session override and `/so use default` restores the persistent
default. `/so ask` chooses a classifier for one owner-only call without changing
either selection. Missing, removed or unauthenticated selection fails clearly;
there is no arbitrary fallback. Persistent settings edits leave session overrides
unchanged. Reload/resume/tree restore active-branch controls; new sessions clear
overrides; `/so reset` restores persistent defaults. `/so status` shows effective,
persistent and session values.

On personal machines the OpenRouter gate/plus composition remains personal-only.
Allowed native classifier discovery still follows its enabled/allowlist policy;
this reconciliation does not add allowed ids or credentials. Work uses its own
Pi provider configuration, not the personal gate. A URL alone is not native
classifier setup or proof that a provider is callable. For the separately
configured local Winnow service, see [winnow-local](../winnow-local/README.md).
This migration does not start or reconfigure that service.

## Usage and native request

Agent access starts off. `/so on` enables `system_one` for the session;
`/so off` disables only that tool, not direct native codemode classification,
which follows Pi provider/model access. `/so mode` retains explicit, selective,
proactive and custom guidance. Missing, empty or unreadable custom guidance
blocks agent use, not manual use; fixed evidence/data/action boundaries remain.

Submit only explicit relevant evidence for an atomic judgment. The tool accepts
object state and named typed questions, never a model/destination override or
automatic transcript attachment. Probabilities are advisory, not authority to
act. Factual lookup, exact calculations, generation and substantial multi-step
reasoning need other tools. Native Pi forms differ from the unchanged CLI forms:

```json
{
  "state": { "evidence": "The sample is blue." },
  "questions": {
    "color": { "type": "choice", "instructions": "Choose the supported color", "criteria": { "blue": "Blue evidence", "red": "Red evidence" } },
    "blue": { "type": "bool", "instructions": "Is it blue?", "criteria": { "true": "Blue", "false": "Not blue" } },
    "support": { "type": "score", "instructions": "Rate support", "criteria": ["Evidence supports blue"] }
  }
}
```

`/so ask` edits this JSON and selects a classifier before the evaluation starts.
Cancelling either step makes no evaluation call. Manual use works with agent
access off. Request/result are terminal-only, never agent context, transcript
or control entries; result-editor edits are discarded. Manual reported usage
and estimated catalog cost are separate from agent totals. Missing usage/price
is labelled unavailable, not free. Agent results forward reported native usage
into Pi totals, including billed failures. Error/aborted results have no usable
answers.

One logical evaluation has a shared 30-second deadline starting before
classifier resolution/authentication, covering all native preparation/readout
operations and retry waits. `maxRetries:2` allows at most three attempts per
native HTTP operation, retrying transient failures only. Multi-request native
algorithms are allowed: this is not a global three-request cap. There is no
outer evaluation retry, deadline reset or model fallback. Owner editing and
selection are outside this budget.

## Validation and limits

`tests/system-one/profile-proof.py --profile personal` and `--profile
axon-work-computer` validate isolated source mapping/rendering and targeted
dry-runs only, never apply/install. They do not prove command loading, completed
agent/manual calls, privacy, accounting or deadlines. Those require separate
scripted real-Pi/PTY/native-provider and public-consumer proofs from the
[package Pi guide](https://github.com/cartwmic/system-one-tools/tree/main/packages/pi-system-one).
Paid Jev proof is separately approved and bounded; old CLI route evidence is
not native Pi proof. Direct TypeSafe authentication, arbitrary models and
calibration are not established by these source checks.

If `/so` is unknown, configuration/loading needs verification after an approved
install/update and restart. If selection/auth is unavailable, inspect Pi provider
setup and `/so settings`; do not edit the CLI catalog to repair Pi. Failures and
cancellation must stay distinguishable from usable answers.
