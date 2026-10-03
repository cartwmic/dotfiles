---
name: minimizing-prompt-compat-edits
description: Find and validate the smallest reviewed edits that restore prompt compatibility with an authenticated model provider. Use when a full prompt is reproducibly rejected but a controlled prompt succeeds, especially for Pi Claude Compat. Preserve owner instructions, real paths, tools, and billing policy.
---

# Minimize prompt compatibility edits

Produce a digest-bound patch, a qualified minimality result, and completed
functional checks. Do not replace the owner's full prompt with a short prompt.

## 1. Establish the failure

1. Get owner approval for source writes, delegated models, the live inference
   budget, and any later rollout. Name one cheap discovery model and **every
   intended adoption model** by exact provider/model ID, plus thinking/tool scope.
   Check the candidate catalog before inference; never silently substitute a model.
   Missing models block stock adoption. An owner-approved, isolated metadata
   override may test an exact model, but must be labelled experimental and cannot
   erase the catalog blocker. Reserve higher-tier checks and functional proof
   before spending on discovery.
2. Freeze the actual input prompt privately. Capture the assembled prompt from
   the active session, then verify its complete serialized system envelope on wire.
   Record provider/model, host/extension versions, tools, thinking, headers/profile,
   credential source, and permitted adapter additions. Do not include chat history.
3. Reproduce rejection of the unchanged full prompt and acceptance of a positive
   control under the same context. Require a completed correct answer, not exit zero,
   prompt acceptance, footer state, or partial output.
4. Classify the exact calibrated rejection. An auth failure, timeout, HTTP429,
   network error, wrong answer, or changed wire context is **inconclusive**.
   An “extra usage” error counts as this gate only while same-account controls
   reproducibly distinguish the two prompts. Never enable paid fallback or buy usage.
5. If the unchanged prompt now succeeds, report no compatibility edit needed.
   If no positive control works, stop; do not minimize an account/transport failure.

Refresh ownership is credential-specific. Do not rotate Claude Code-owned tokens.
An independently logged-in Pi credential uses Pi's own refresh path with owner
approval. Use isolated probe auth; do not copy refresh tokens into test stores.
Do not launch Claude with an OAuth-token environment override to obtain a reference:
it can affect macOS Keychain credentials.

## 2. Find a semantics-preserving passing seed

Use coarse section/line experiments only for diagnosis. Do not ship deleted
instructions, renamed real paths, missing tools, or broad brand replacement.
Prefer readable case, formatting, or wording alternatives that keep the original
target and requirement. Review semantics separately from server acceptance.

Make a small, fixed palette of original-byte-offset edits. Keep the full prompt;
apply edits against its immutable original, never against previously edited text.
Protect actual paths, commands, identifiers, owner policy, tool schemas, and auth
envelope. Changes outside the approved region need a new decision and run.

Read the scripts before using them:
- [Reducer](scripts/reduce.py): exhaustive subset search and fresh evidence.
- [Pi oracle](scripts/pi_probe.py): isolated real CLI, one guarded inference.
- [Wire guard](scripts/wire_guard.mjs): exact three-block Compat envelope and
  explicitly permitted Pi cwd suffix. The normalized complete URL/payload/header
  digest also freezes messages, account/device metadata, and all other fields.
  Only request/session IDs, attestation checksum, and verified derived content
  length are excluded. The actual Authorization header is hashed and checked
  against the configured credential before transport; no credential value is
  logged. Stop and adapt/review this contract if the host/adapter changes;
  do not relax it to substring matching.

## 3. Minimize

Run discovery and refinement on the cheapest suitable model. It must support
this prompt and tool protocol and have calibrated passing/failing controls;
“cheap” alone is not sufficient. Stop discovery after obtaining a confirmed
minimal patch. Do not spend the adoption-model reservation on a larger search.

The reducer takes original UTF-8 bytes, a private JSON manifest, and a private
oracle config. Manifest fields:

- `sourceSha256`, `editableRange: [start,end]`, `protectedRanges`.
- `edits: [{id,start,old,new}]`; offsets refer to original UTF-8 bytes.
- `context`: model, versions, scope, objective, budget/ownership assumptions,
  and owner-approved per-run `budgetCeiling`. Subtract earlier runs and reserve
  final proof before setting it; the script rejects a larger CLI budget.
- `contextFiles`: every driver, oracle, guard, config, and relevant adapter source
  whose change would invalidate evidence. No credentials in this manifest.

Pi oracle config fields: `mode` (`live` or `fixture`), `pi`,
`expectedPiVersion`, `extension`, `model`, `cwd`, `authPath`,
`authProvider`, fixed `installId`, and private `wireContext` path.
Fixture mode additionally requires `transportExtension`; live mode forbids it.
An explicitly approved isolated catalog addition uses `modelConfigFile` plus
`modelConfigApproved: true`; freeze that file and its authoritative metadata
provenance, keep the Compat endpoint/auth/dispatch unchanged, and report that
model separately from stock-catalog support.
Capture configuration hashes, not secret values. Inference sends are guarded;
bootstrap reads are recorded separately and are not inference-budget units.

Set the search budget only after reserving adoption checks. For a patch with
`k` edits, reserve at least `7 + 2*k` sends per adoption model: two original,
two exact-winner, two per single-edit reversion, and three functional sends.
Keep separate contingency for neutral controls or renewed model-specific search.
For example, **if** the owner has reserved 92 sends for discovery:

```sh
python3 scripts/reduce.py /private/run/original.txt /private/run/edits.json \
  /private/run/search --budget 92 --controls-every 16 \
  --oracle python3 scripts/pi_probe.py /private/run/oracle.json
```

Run from this skill directory, or use absolute script paths. Use a new 0700
output directory per run; the reducer refuses an existing one. Keep source
prompt, private trials, credentials, and response bodies out of public repositories.

Search order is edit count, removed bytes, added bytes, then source order. No
monotonicity assumption: test lower-ranked subsets rather than pruning them.
Controls repeat periodically. Any inconclusive cheaper candidate, exhausted
budget, contradictory result, or context drift blocks a minimum claim.

Confirm the winner twice and freshly reject each single-edit reversion twice.
Keep result.json/trials.jsonl and inspect the exact diff. The resulting claim is
**minimum within this fixed palette under the observed stable oracle**, not the
global smallest rewrite. A greedy removal pass proves only 1-minimality.

For refinement, author a new, reviewed palette of smaller/case-only wording
alternatives and run it against the same immutable original if the remaining
budget permits. Do not silently broaden the minimality claim or reuse stale evidence.

## 4. Validate the higher-tier ladder

Cheap-model success is not adoption acceptance. Freeze the exact winning bytes
and run the following on **every owner-named adoption model**, including higher
tiers, with a separate model-labelled config, context binding, cache, and receipt:

1. Repeat the unchanged full-prompt control twice and the exact cheap-model patch
   twice. Do not shorten or reword the winner for an expensive model.
2. Test each single-edit reversion twice. If the original already passes, record
   zero-edit compatibility; do not demand a rejection. If a reversion passes,
   cheap-model minimality does not transfer. For more than two edits these checks
   prove only 1-minimality on this model, not its palette minimum; exhaustive
   cheap-tier evidence cannot substitute for this model’s missing subsets.
3. Require real tool/result and fresh-process history proof with the exact winner
   for a shared-patch adoption path. If choosing a zero-edit/per-model adoption
   path, verify that actual sent prompt instead. Shared-patch functional success
   does not establish unchanged-original functional acceptance, or vice versa.
4. Report every necessity/minimality disagreement explicitly. A passing reversion
   does not invalidate a compatible winner, but it requires model-specific
   minimization, a justified shared-patch strategy, or pending per-model minimum
   claims. If the winner is rejected or a result is inconclusive, do not claim
   cross-model compatibility. Use a calibrated neutral control to distinguish a prompt gate
   from account/model/protocol failure, within budget. Re-minimize under the
   affected model or find a shared patch only with remaining approved budget;
   otherwise mark adoption blocked/pending. Repeat the ladder after any patch change.

Track separately: discovery minimum, each model’s compatibility/functional result,
per-model necessity/minimality, stock vs override support, and remaining adoption
scope. Call a patch shared only if every intended model passed. Do not infer an
Opus/Sonnet pass from Haiku, a family name, or an API catalogue entry.

## 5. Functional proof and handoff

On each intended model, use the complete unchanged winning prompt to drive:
- real tool execution, tool result, and correctly derived final answer;
- a fresh-process resume/coherence probe that recalls those results without
  repeating the tool call;
- the intended thinking/tool loadout, auxiliary calls, compaction, and TUI flows
  where relevant. Mark any unrun scope pending even if the model ladder passed.

For Pi, use the bundled [functional verifier](scripts/verify_pi.py). It guards
at most two sends for the read/result phase and one for fresh-process resume:

```sh
python3 scripts/verify_pi.py /private/run/oracle.json \
  /private/run/search/minimal-prompt.txt /private/run/functional \
  --sha256 RESULT_SHA256 --remaining-inferences REMAINING_BUDGET
```

Run fixture tests with `python3 -m unittest discover -s tests -v`; set
`PROMPT_COMPAT_TEST_EXTENSION` to the candidate extension for the real CLI
scripted-transport check. Fixture checks use no real credits.

Count every inference send, including retries and tool continuations, against
the owner-approved total. Stop before overspending. A search result is not
functional acceptance; its `functionalValidation` remains pending until this proof.

Report original/result hashes, exact edits and preserved regions, tried palette,
objective/limitations, controls, call count, functional evidence, and remaining
integration work. Revalidate after prompt, model, adapter, or server behavior changes.
Do not auto-apply compatibility rewrites or make them global across providers.
Obtain owner approval before deployment, and retain a tested rollback.
