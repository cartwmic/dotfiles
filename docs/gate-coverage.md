# Agent guard rails: which profile gets each one

The agent guard rails (the PR gates, the review log and the Bash rules) land on both desktop profiles, `personal` and `axon-work-computer`, unless a row below says no and why. A lead on the work profile has the same refusals before a PR body is set or a PR is merged as a lead on personal does. `tests/profiles/test_gate_coverage.py` checks this table (see "What the test checks"). [docs/profiles.md](./profiles.md) lists every path that lands on one profile only.

| Gate | Personal | Work | Where it lands | Test that proves it |
|---|---|---|---|---|
| PR body check: `pr-body-check` | yes | yes | `.local/bin/pr-body-check` | `tests/pr-body-check/test_pr_body_check.py`, `tests/profiles/test_gate_coverage.py` |
| Agent record path and import: `pr-record` | yes | yes | `.local/bin/pr-record` | `tests/pr-record/test_pr_record.py`, `tests/profiles/test_gate_coverage.py` |
| Open or edit a PR through the body check: `pr-open` | yes | yes | `.local/bin/pr-open` | `tests/pr-open/test_pr_open.py`, `tests/profiles/test_gate_coverage.py` |
| Review-record merge rule: `intent-review-check` | yes | yes | `.local/bin/intent-review-check` | `tests/intent-review-check/test_intent_review_check.py`, `tests/profiles/test_gate_coverage.py` |
| Merge gate: `ci-main-status --merge-gate` | yes | yes | `.local/bin/ci-main-status` | `tests/ci-main-status/test_ci_main_status.py`, `tests/profiles/test_gate_coverage.py` |
| Bash rule: `gh pr merge` only after both gates | yes | yes | `.local/share/agent-harness/hooks/bash_rules.py`, `.local/share/agent-harness/hooks/refuse_pattern_kill.py` | `tests/agent-kill-guard/test_bash_rules.py`, `tests/profiles/test_gate_coverage.py` |
| Bash rule: PR body only from a checked body file | yes | yes | `.local/share/agent-harness/hooks/bash_rules.py` | `tests/agent-kill-guard/test_bash_rules.py`, `tests/profiles/test_gate_coverage.py` |
| Bash rule: poll loops (`sleep` in a `while` or `until`) | yes | yes | `.local/share/agent-harness/hooks/bash_rules.py` | `tests/agent-kill-guard/test_bash_rules.py`, `tests/profiles/test_gate_coverage.py` |
| Bash rule: unquoted heredoc with a backtick | yes | yes | `.local/share/agent-harness/hooks/bash_rules.py` | `tests/agent-kill-guard/test_bash_rules.py`, `tests/profiles/test_gate_coverage.py` |
| Bash rule: credential config read raw | yes | yes | `.local/share/agent-harness/hooks/bash_rules.py`, `.local/share/agent-harness/bin/config-show` | `tests/agent-kill-guard/test_bash_rules.py`, `tests/profiles/test_gate_coverage.py` |
| Bash rule: git that changes the live coordinator checkout | yes | yes | `.local/share/agent-harness/hooks/bash_rules.py`, `.local/share/agent-harness/coordinator-instance` | `tests/agent-kill-guard/test_bash_rules.py`, `tests/profiles/test_gate_coverage.py` |
| Bash rule: heavy jobs in the agent host pod | yes (pod only) | no: a pod-only rule (the personal Mac gets it too, inert); the work Mac is no pod and has no kgate host, so a work lead runs a suite where its repo runs it | `.local/share/agent-harness/hooks/bash_rules.py` | `tests/agent-kill-guard/test_bash_rules.py`, `tests/profiles/test_gate_coverage.py` |
| Bash rule: kubectl on a context other than the homelab's | yes | no: it keeps agents on the personal homelab cluster, which the standing grant for that cluster covers and the work clusters it does not | `.local/share/agent-harness/hooks/bash_rules.py` | `tests/agent-kill-guard/test_bash_rules.py`, `tests/profiles/test_gate_coverage.py` |
| Bash rule: local `docker run`, `build`, `compose up` | yes (Linux) | no: it guards the Linux personal workstation, where the refusal sends the job to kgate and a throwaway namespace on the homelab cluster; the work profile has no Linux machine | `.local/share/agent-harness/hooks/bash_rules.py` | `tests/agent-kill-guard/test_bash_rules.py`, `tests/profiles/test_gate_coverage.py` |
| Bash hook wired into Claude Code, Codex, Cursor and Pi | yes | yes | `.local/share/agent-harness/hooks/refuse_pattern_kill.py`, `.cursor/hooks/shell_guard.py`, `.pi/agent/extensions/refuse-pattern-kill/index.ts` | `tests/agent-kill-guard/test_claude_settings.py`, `tests/agent-kill-guard/test_codex_hook.py`, `tests/cursor/test_shell_guard.py`, `tests/profiles/test_gate_coverage.py` |
| Review log CLI: `agent-traces` | yes | yes, when the work coordinator's checkout holds the kit (else exit 3) | `.local/bin/agent-traces` | `tests/agent-kit/test_wrapper.py`, `tests/profiles/test_gate_coverage.py` |

## Why three rules stay off on work

The three Bash rules that read "no" on work cannot fire there: one guards the agent host pod, one the personal homelab cluster, and one the Linux personal workstation. A rule that guarded the work clusters would be a new hook on the work Mac, which is the owner's call, not part of this table. The reason is in each Work cell. Everything else, including every PR gate, the poll, heredoc, credential and live-checkout rules, and the review log, is "yes" on work.

## How the work profile finds the coordinator

The gate wrappers run scripts in the coordinator checkout. Chezmoi renders `~/.local/share/agent-harness/coordinator-instance` per profile: line 1 is the checkout (personal `~/git/coordinator`; work `instances.coordinator.repo` in local data, else `~/coordinator-work`), and on work line 2 is the work coordinator's state directory (`~/.local/share/coordinator-work`). The wrappers use line 1, and set `COORDINATOR_STATE_DIR` from line 2 only when it is unset and that directory holds `pane-bin/ledger`. `COORDINATOR_REPO` overrides line 1. The live-checkout git rule protects line 1 as well as `~/git/coordinator`.

## What `pr-body-check REPO PR` also runs

After the body check passes, `pr-body-check REPO PR` runs `ci-main-status --threads REPO PR`: no unresolved review thread may be left (playbook 580f3e02 step 3). Every merge chain that runs the body check therefore runs the thread check, and an unresolved thread is exit 1, like a broken body rule. An unreadable thread state is also exit 1, never a silent pass. The thread check is not run for a body-only check (`--body-file`), a check made before a review round (`--skip-intent-review`), or the `--pr`/`--repo`/`--base` forms, which have no `REPO PR` pair. `ci-main-status --threads` itself ships on both profiles, in `ci-main-status`.

The merge form of `pr-body-check` also refuses a PR whose agent record has no `Promises:` line (the coordinator's `pr-body-check.ts`; both profiles run the same checkout script).

## `agent-traces` on work

`intent-review-check` and the merge form of `pr-body-check` call `agent-traces review verify` for the five repos the review rule covers (the cartwmic repos: coordinator, dotfiles, cartwmic-homelab-v2, agent-kit, loop-engine). For any other repo, the check says "out of scope" and does not call it, so a work repo's merge needs no `agent-traces`. The review log itself (`agent-traces review add`, `label`, `record`, `report`) does.

The pinned install (`65_agent_kit_install.sh`) stays off on work: `npm ci` of the private package needs a token the work Mac's gh accounts may not hold, and a failed run stops the apply before the later scripts. The work wrapper therefore falls back to the CLI that the work coordinator's checkout already holds (`node_modules/@cartwmic/agent-kit`, at the coordinator's pin, not this repo's). Every run on work appends one JSON line to `${XDG_STATE_HOME:-~/.local/state}/agent-traces/wrapper.jsonl` (`utc`, `outcome` of `pinned`, `fallback` or `none`, the `kit` path and `version`, and the paths `looked` at), the exit-3 run included, so a review record can be traced to the kit that wrote it by matching its time against that log, and fallbacks can be counted. A log that cannot be written never changes the run. A fallback run also prints one line on stderr with the kit path and version. Where the checkout has no kit either, the wrapper exits 3, prints where it looked (the pinned path and the checkout's path) and the log is kept by hand (playbook 58fdb05d). Node problems found after the kit is chosen (no node, too old) are not written to this log. Turning the install on for work (`agentKit: {enabled: true}` in local data) needs a gh account on that Mac that can read the package, which is the owner's call.

## What the test checks

`tests/profiles/test_gate_coverage.py`:

- Every path in the "Where it lands" column of a `yes` row is in `chezmoi managed` for each profile the row says yes for. Every test file in the last column exists. (A rule that is `no` on work still has its file there: the hook is shared, and the sample command proves the rule stays silent.)
- Renders the work profile's `profile` and `coordinator-instance` files and runs the real hook script with them: each Bash rule above that says yes for work refuses its sample command, the `no` rows let theirs through, and a clean command passes.
- Runs each gate wrapper from a work-shaped home: it finds the work coordinator's checkout and state directory, and on personal it still finds `~/git/coordinator`.
- Runs the work `agent-traces` wrapper: the coordinator checkout's kit is used when the pinned install is absent, and not on personal; each outcome (pinned, fallback, none) writes one line to the wrapper log, an unwritable log changes nothing, personal writes none, and the fallback and exit-3 stderr lines stay.
- Checks that Termux gets none of the gate paths.
- Renders the Claude Code, Codex and Cursor hook installers for work and checks each wires the shared hook; checks the Pi extension and the Cursor guard are managed on work.
