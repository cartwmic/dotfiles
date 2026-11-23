---
name: creating-formal-verification
description: Use when a repo has a written promise about the order of steps (a race, retries, a state machine, a lifecycle) where a break costs a lot and tests reach few of the orderings, and you want a TLA+ model check run in CI. Covers choosing the target from the code, writing the model so each action maps to a file:line, proving the check can fail, a sync check that fails when the covered code changes, and keeping the model in step afterwards. Not for code-level proofs (memory safety, overflow).
---

# Creating formal verification

A test checks the orderings someone wrote. A model check tries every ordering inside stated bounds. This skill finds one promise worth that, models it, and leaves a repo with one command that checks it and a second check that says when the code has moved away from the model. Adapted from pstack's `create-formal-verification-skill` and `maintain-formal-verification-skill` (MIT, `cursor/plugins`).

The checker is TLC, driven by the `statechart` skill. Its guide is `~/.local/share/agent-harness/external-skills/pstack/statechart/SKILL.md`. It is marked so the Skill tool will not load it: read that file by path. Copy none of its commands into this skill or the repo's docs. The repo's `formal/check.sh` holds the one command.

## Choose the target from the code

Take the strongest written promise whose break costs most and that tests reach least. Start from the invariants the repo "relies on but never enforces" (`distilling-requirements` lists them). Ask the user only what the code and docs cannot tell you. Prefer a target whose covered files do not change every day, because the sync check fires on every change to them.

## Layout in the target repo

- `formal/<Name>.tla` and `.cfg`: the model and its bounds.
- `formal/README.md`: the property in one sentence, the harm in one sentence, the bounds, what is left out, and a mapping table from each model action to a `file:line`. It is also the per-repo record. Do not add a second skill to the repo. Add a short pointer in the repo's `AGENTS.md`.
- `formal/COVERS`: each covered path with its `git hash-object` value when the model was last confirmed against it.
- `formal/check-sync.py`: recomputes the hashes. `--update` rewrites `COVERS`, by hand only.
- `formal/check.sh`: runs the sync check, then the model check. Exit 0 pass, nonzero fail. CI runs only this.

## What makes the model good

- **True to the code.** One indivisible step in the code (one transaction, one lock hold) is one step in the model. Every action has a `file:line`. Names come from the repo.
- **Able to fail.** A check never seen failing proves nothing.
- **Findings stay findings.** When the current code breaks a property, report the counterexample in the code's words. Never weaken the property or the model to make it pass. Never change product code unless asked.
- **Honest scope.** State the bounds, the assumptions and what is left out. A pass covers the model, not the code.
- **One command, repeatable, short.** Pinned tools, fixed flags. If a warm run is over 2 minutes, shrink the bounds.

## Prove it before hand-off

1. Break the model's guard that mirrors a code guard (delete the check, or reorder a step). `formal/check.sh` must exit 1 with a path. Drop the break and confirm exit 0.
2. Edit a covered file (a comment is enough). The sync check must fail and name the file. Read the change, update the model if it moved, run `check-sync.py --update`, and confirm exit 0.

Say in the hand-off that the gate proves the model, and that the link to the code is the sync check, the mapping table and the repo's tests. Say what you ran and what you only read.

## When `formal/check.sh` fails later

Give the result one of four outcomes and say which:

- **in sync**: the covered change does not alter what the model describes, and the check passes.
- **updated**: the code changed shape, the model now describes it, the check passes.
- **bug**: the model describes the current code and the code breaks the property. Report the counterexample as steps in the code's words, the harm, and the commit that introduced it.
- **blocked**: it could not run or be brought in line. Say why.

Steps: read the diff of the covered files and decide for each change whether it alters a step, a guard or a range. Update the model from the code, not from the result. Rerun. For a failure, replay the counterexample against the real code: a step that cannot happen means the model is wrong (fix it); if every step can happen, it is a bug. After a pass on an updated model, break the new part once to see it fail, then drop the break. Only then run `check-sync.py --update`. A sync pass says the model was looked at, not that the code is right. Put model updates in a change of their own, apart from any product fix.

A PR that touches a covered file also touches `formal/COVERS` or says in its description why the model needs no change.
