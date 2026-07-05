<!-- authored: in-session -->

# Execution Plan

Execution Mode = standard (no TDD); shell artifacts verified by `bash -n` +
idempotence reasoning rather than a unit harness. Each step is a simple ordered
list.

## Plan step 1: Remote notify wrapper

- **Covers:** T1.1
- **Pre-conditions:**
  - Harpoon `slot_for_pane` / `jump_pane` pipes shipped (sibling slice, done).
  - `dot_local/bin/` is the cross-machine executable source path (deploys to the
    homelab remote's `~/.local/bin/` on `chezmoi apply` there — Constitution I).
- **Action:**
  1. Create `dot_local/bin/executable_ntfy-zellij-notify.sh` with `set -euo pipefail`.
  2. Read config from env: `NTFY_SERVER`, `NTFY_TOPIC`, optional `NTFY_TOKEN`
     (referenced by storage location; never literal — Constitution III); fail
     non-zero naming any missing required value.
  3. Read `$ZELLIJ_PANE_ID` + `$ZELLIJ_SESSION_NAME`; when the pane id is present
     embed it as the jump key header/field; when absent, deliver keyless.
  4. Best-effort `zellij pipe --name slot_for_pane` for a display hint; never let
     its failure abort delivery.
  5. `curl` the ntfy publish with the assembled headers/body.
- **Verification:**
  - `bash -n dot_local/bin/executable_ntfy-zellij-notify.sh`
  - Manual read-through against the two ntfy-jump-wiring requirements it covers.
- **Rollback:** delete the new file (net-new, no existing behavior touched).

## Plan step 2: Phone ControlMaster snippet

- **Covers:** T2.1
- **Pre-conditions:** shared ed25519 key already on the phone; `termux/` staging
  is the delivery surface (Constitution VII — never `dot_termux/`).
- **Action:**
  1. Create `termux/ssh-controlmaster.config` with a `Host` block for the remote:
     `ControlMaster auto`, `ControlPath ~/.ssh/cm-%r@%h:%p`, `ControlPersist`.
  2. Reference host/user by storage location only; no secrets.
- **Verification:** read-through against "enables connection reuse" +
  "staged, not chezmoi-deployed".
- **Rollback:** delete the snippet file.

## Plan step 3: Idempotent sync + docs

- **Covers:** T2.2, T2.3
- **Pre-conditions:** step 2 snippet exists; `termux/sync.sh` present.
- **Action:**
  1. Extend `sync.sh`: ensure the phone `ControlPath` parent dir exists;
     marker-guard the append of the snippet into the phone `~/.ssh/config` (grep
     for a sentinel comment; skip when already present) so a re-run is a no-op.
  2. Update `termux/README.md` with the snippet + push step.
- **Verification:**
  - `bash -n termux/sync.sh`
  - Reason through the marker-guard: second run finds the sentinel → no append.
- **Rollback:** `git checkout -- termux/sync.sh termux/README.md`.

## Plan step 4: Verify

- **Covers:** T3.1
- **Pre-conditions:** steps 1-3 complete.
- **Action:** run `bash -n` on both scripts; confirm the marker-guard no-op
  reasoning; seal verify.md.
- **Verification:** both `bash -n` exit 0; verify.md check table green.
- **Rollback:** n/a (verification only).

## Completion Verification

- `bash -n dot_local/bin/executable_ntfy-zellij-notify.sh && bash -n termux/sync.sh`
  → both exit 0.
- `openspec validate ntfy-harpoon-jump --strict` → passes.
- All ntfy-jump-wiring requirements have a covering task + plan step.

## Manual Adjustments

- Standard (non-TDD) execution: the deliverables are shell scripts + an ssh
  config snippet whose correctness is `bash -n` + idempotence reasoning, not an
  automated test suite. Recorded so the doneness/code-review judges do not expect
  a unit harness.
