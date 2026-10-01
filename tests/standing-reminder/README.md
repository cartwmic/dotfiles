# Standing-reminder proof

Product behavior lives in the [extension README](../../dot_pi/private_agent/extensions/standing-reminder/README.md). These drivers are source-only; `tests/` and the scoped extension `AGENTS.md` must remain ignored.

## Commands (from this worktree)

```sh
# legacy-journey: existing provenance/editor/session/unavailable-state regressions
PYTHONDONTWRITEBYTECODE=1 python3 tests/standing-reminder/isolated_pi.py -- \
  python3 tests/standing-reminder/proof.py

# selective-journey: full new matrix (final driver owns execution)
PYTHONDONTWRITEBYTECODE=1 python3 tests/standing-reminder/isolated_pi.py -- \
  python3 tests/standing-reminder/selective_proof.py

# focused acceptance path
PYTHONDONTWRITEBYTECODE=1 python3 tests/standing-reminder/isolated_pi.py -- \
  python3 tests/standing-reminder/selective_proof.py --case direct

# focused historical replay regression (no operator delivery after reload)
PYTHONDONTWRITEBYTECODE=1 python3 tests/standing-reminder/isolated_pi.py -- \
  python3 tests/standing-reminder/selective_proof.py --case historical

# source-preview: mappings, separate rendered/live reads, unforced targeted preview
PYTHONDONTWRITEBYTECODE=1 python3 tests/standing-reminder/source_proof.py
```

The supported offline pin is **Pi 0.99.2**, `@earendil-works/pi-coding-agent`.
`isolated_pi.py` locates the actual package, prints exact target SHA-256 values,
copies it privately, checks literal patch anchors, normalizes only the copied
origin bridge, and validates desktop/Termux gates, idempotence, changed-anchor
rejection and sibling-patch composition. Installed targets remain untouched and
are fingerprinted again even if the child proof fails. No relaxed provenance
checks or installed-package edits are permitted.

## Selective cases and assertion contract

`--case` selects one case; omitted runs all:

- `direct`, `cancel`, `invalid`: actual installed question tool, complete
  two-tab answer submission, cancellation and invalid arguments. Cancellation
  requires the actual 2.12.0 canonical `User declined to answer questions`
  root result and closed UI; invalid arguments require the native
  `Validation failed for tool "ask_user_question"` envelope identifying the
  empty `questions` array and its minimum-item violation (not a literal
  `cancel`/`error` keyword). Codemode requires that same validation envelope
  inside its caught `QUESTION-ERROR` output.
- `codemode`, `codemode-invalid`: explicit `builtin:codemode`, actual nested
  question tool; require native `parentToolCallId` execution evidence.
- `non-ui`: actual installed package's no-UI execution backstop, via native
  codemode. Its reconciler normally strips the tool, so a private fixture uses
  public `setActiveTools()` after reconciliation to reactivate that same
  registered real tool for this case only. No replacement/wrapper execute
  function is installed. Require the real `UI not available` result, native
  nested completion event, refresh and completed ordinary work.
- `edits`, `clear`, `coalesce`, `operator-coalesce`: A→B→C successful saves
  during a gated already-running tool, clear without a model instruction,
  question/save coalescing and queued operator/save/question coalescing.
- `rollback`: unchanged close and nonzero exit after writing a failed draft.
- `lifecycle`, `warming`: idle pending save through reload/resume/compaction;
  actual scheduled idle cache-warmer replay with a local model's declared
  lifetime/economics. Summary/warming requests must not consume pending state.
  Scripted usage here is scheduler input, **not** live-cache evidence.
- `tool-config`, `message-config`: one exact selector addition; the latter
  distinguishes a real model-visible custom message from a UI notification.
- `empty-config`, `invalid-config`, `default-exclusions`: disabling event
  triggers, invalid-selector warning with ordinary completion, and no default
  subagent/result/notification/custom-message refresh. Empty lists are valid
  and need no warning; invalid lists warn and disable event refreshes.
- `historical`: consume the saved pending value first, persist a real native
  custom message, reload, then issue only a real extension-origin request.
  Require exactly one completed request with zero projections and the custom
  history present. No intervening operator delivery can mask replay refresh.
- `independence`, `unavailable`: unrelated sessions remain empty, corrupt
  saved state warns/omits stale text then recovers through the actual editor.
  The legacy journey separately covers missing state, tree/fork/clone and
  TUI/print/JSON/RPC recovery.

Every selective work scenario records real provider counts before/after.
One initial operator request yields a root batch, one handoff request and one
ordinary tool continuation: exactly three work requests and a visible completed
response. While a questionnaire tab or gate is unresolved, no request may be
added. The handoff must contain every root result before exactly one fresh
projection, when a selected cause applies. With unchanged wording the initial
operator projection remains at its canonical position; the fresh one is after
the complete batch. Ordinary continuation carries these positions without
adding another projection. Edits retire A/B and deliver only C; clear removes
all projections without a clear instruction. Each request is inspected for exact
multiline text, not inferred from events/status. Provider completion depends on
completed expected tool results, not unconditional ACK responses.

The installed question entry is
`/Users/cartwmic/.pi/agent/npm/node_modules/@juicesharp/rpiv-ask-user-question/index.ts`.
Its version and source-tree fingerprint are printed and checked after the run.
Question acceptance uses actual PTY key input and returned answer text, not a
replacement question fixture or per-tab RPC walker. Fixture tools/custom
messages only exercise explicit non-question selectors and ordinary work.

## Source/config staging and privacy

Both journeys copy the real source extension and its inspect-prompt editor
helper dependency into temporary directories. `config.json` is placed **beside
the source-loaded index.ts**, where production `import.meta.url` resolves it.
The legacy journey uses `create_config.json`; selective cases supply explicit
private configs. No production test-only config hook or measured-tree config is
created. All agent/project/editor/session/provider files are temporary. The
saved-session inspector rejects reminder messages and origin markers, checks
unchanged original user text, and reads private current-value sidecars. Failure
diagnostics contain only fixture text. Use `PYTHONDONTWRITEBYTECODE=1` to keep
imports from leaving bytecode in the measured tree.

`source_proof.py` inspects the effective config before source-state reads. It
allows only the inspected password-manager pre-hook with `op` already present;
unknown hooks or missing `op` block rather than install software. It checks all
three profile mappings, independently reads rendered and live touched files,
prints hashes rather than content, and runs the exact source-scoped targeted
`apply --dry-run --verbose` **without force or apply**. Unexplained TTY/merge
failure stays blocked; it is not permission to force. Preview includes the
extension's runtime/README/config and origin-patch README, not global onchange
execution. Destination-only `create_` config drift is preserved, not reset.

## Separate live-cache duty

This offline proof does not establish genuine provider cache reads or spend.
`cache_proof.py` targets exact Pi **0.99.2** and
`openai-codex/gpt-6.1-sol` (thinking low). The final driver, not the worker,
owns billable execution on the stable tree:

```sh
# cache-self: no requests or credentials required
PYTHONDONTWRITEBYTECODE=1 python3 tests/standing-reminder/cache_proof.py --self-test

# Offline real-Pi loadout regression: private auth, forced exit before HTTP
PYTHONDONTWRITEBYTECODE=1 python3 tests/standing-reminder/isolated_pi.py -- \
  python3 tests/standing-reminder/cache_proof.py --loadout-test

# cache-live: explicitly approved driver cap; capture stdout outside source
PYTHONDONTWRITEBYTECODE=1 python3 tests/standing-reminder/isolated_pi.py -- \
  python3 tests/standing-reminder/cache_proof.py --cap-usd 250
```

The backend rejects `max_output_tokens`; an artificial `maxTokens: 256`
override is not an enforced limit. No model override or request-field injection
is used. Instead preflight requires the isolated registry's native metadata:
272,000 context and 128,000 output tokens. The owner's 872,000-context
`models.json` override is not copied into the private fixture. Reservation relies on declared provider/model capacity,
not short-output instructions or a universal cloud guarantee. Missing or changed
native metadata blocks. Offline self-tests do not establish a measured live
outcome; retain the actual captured comparison before claiming cache evidence.

Both arms share the same **300-row cold seed** (reduced from 400 after the
measured gate continuation exceeded the unchanged 40,904-byte guard). This
changes fixture size only, not acceptance or capacity reservation.
The matched off/on arms each have six stages: cold, ordinary warm, unchanged
ordinary, deterministic question completion, gated private saved-value change,
and edited ordinary continuation. Each stage requires one fixture tool and one
completed ACK: **24 provider calls maximum**. The on arm starts cold without a
reminder, creates its first sidecar, then restores the active value. Ordinary
continuations preserve the projection; question completion adds exactly one.
The finite gate writes only current value/pending state; the next invocation
restores the changed value. This live fixture does **not** prove editor/UI
mid-turn saving: the selective journey separately drives actual UI semantics.
No saved reminder
messages are replayed to improve counters.

Each call reserves 272,000 context tokens and 128,000 output tokens at the
maximum reported input/cache/output rates across all tiers. At $5/M input and
$15/M output the 24-call reserve is **$78.72** ($3.28 per call); actual native
rates determine preflight's reservation, which must fit the finite explicit cap.
The driver cap is **$250**, not a universal maximum. Before every stage, actual
spend plus all remaining calls' worst-case reservation must fit that cap.
The CLI uses `--tools cache_ordinary,ask_user_question,cache_gate`, not
`--no-tools` (which disables extension tools too). A pre-provider hook refuses
anything other than exactly those three function declarations. The offline
real-Pi loadout regression proves both the allowlist and the old disabled-tool
refusal, exiting before HTTP; it uses privately copied auth to construct the
Codex payload without printing credentials. Retry, idle warming and compaction are disabled. Child guards exit before excess
requests or tool deviations (ordinary handler exceptions would not suffice),
check each response's identity, native token ceilings and spend before continuation,
and enforce a 40,904-byte transcript ceiling with framing/tool headroom. These
checks reserve native capacity; they do not claim wire-enforced short output.

Credentials are read only from the selected provider entry of the owner's Pi
`auth.json`, copied into a 0700 temporary agent directory with a 0600 auth file,
and never printed. HOME, settings, adjacent active reminder config,
source extension/editor dependency and sessions are private temporary copies.
Refresh cannot modify the owner's credentials. `isolated_pi.py` privately
patches the same installed package and verifies installed fingerprints unchanged.

Output retains exact runtime/model/workload/reserve, per-call input/cacheRead,
output/cacheWrite/cost, late full request snapshots and genuine zero-cache misses.
Usable finite nonnegative integer token counters and finite nonnegative spend
are mandatory; each arm must have some nonzero cacheRead during ordinary warm
stages. Missing counters or an unwarmed arm block: no prefix-only substitute,
universal hit ratio, or reliable-cache claim. Keep captures outside Git/source.
Do not infer cache acceptance from scripted counters or prefix snapshots.
No live chezmoi apply, installed changes, Git staging/commit/push or persistent
user-state deletion is part of this proof. Focused self-tests do not replace
the full matrix or live-provider proof.
