<!-- authored: in-session -->
# Intent (frozen baseline)

**Frozen:** 2026-06-25. Immutable for the life of branch `opsx/consolidate-opsx-cli`.

## Problem

Three sibling bash CLIs (`opsx-gate`, `opsx-models`, `opsx-loop`) are one tool family
pretending to be three — duplicated conventions, no shared home, and no place to add the
needed model-config write surface. The opsx-loop pi extension also carries three latent
bugs (arg truncation, worktree-path staleness, no stall detection).

## Goal (what "done" means)

1. A single `opsx` executable dispatches `gate` / `models` / `loop` subcommands; the three
   standalone executables are removed (hard cutover, no shims); every in-repo caller uses the
   subcommand form.
2. `opsx models set/get/list` provides a harness-neutral write surface (user-layer default,
   `--layer`, atomic, comment-preserving) so any harness can write config, not just read it.
3. pi `/opsx-loop models` is a thin wrapper over `opsx models`.
4. The opsx-loop extension: argument parsing never silently truncates input; the worktree is
   re-resolved each turn; the loop stops on a genuine stall.
5. Behavior of the gate/resolver/driver is otherwise UNCHANGED; the spec-of-record names only
   commands that exist.

## Non-negotiables

- Hard cutover (owner choice) — no compatibility shims.
- CLI is the owner of model config; the pi extension stays a consumer. YAML files remain the
  sole source of truth.
- Constitution I (chezmoi source of truth, incl. removals) and IX (skill edits → adversarial
  review) hold.

## Out of scope

- Auto-archive from the loop (it still stops at gate-green).
- List-mutation grammar for `set review` (replace-only; lists stay manual YAML).
- Rewriting historical ADRs 0005-0010.
