# passage-review Pi adapter — agent instructions

## Scope and authority

This file covers `dot_pi/private_agent/extensions/passage-review/`. Repo-root
`AGENTS.md` controls source and apply. Read
`dot_pi/private_agent/extensions/README.md` for shared Pi extension lifecycle
and per-call `ctx` rules. The local `README.md` owns the human `/review` path.
`dot_local/share/passage-review/AGENTS.md` owns the standalone library's
snapshot, note, and export invariants.

## Workflow

- Keep `/review` as a thin Pi command in `index.ts`. Its `helpers.ts` gets the
  latest text-bearing assistant message on the active branch, only when Pi is
  idle in an interactive TUI. A non-interactive mode or missing reply should
  report why it cannot open a review. Never retain an `ExtensionContext`
  across callbacks or reuse a stale branch.
- Pass the exact reply on stdin to the standalone
  `passage-review new --title ...` command. `PASSAGE_REVIEW_BIN` selects a
  non-default executable. Pause and resume Pi's TUI around that foreground
  terminal reviewer; do not build a second note store or editor in Pi.
- Export is a separate user-chosen CLI step. This adapter must not alter
  notes, paste exported feedback into Pi, edit an assistant reply, or use
  Herdr as a prerequisite. `helpers.ts` enforces the idle TUI and branch
  guards; `index.test.ts` checks that `/review` spawns no export/archive
  action. Markdown is advisory and cannot block a future violating change;
  keep the source guards and regression tests. Termux installs the standalone
  CLI and skips this `.pi` extension.
- Use `index.test.ts` with a scripted CLI for changes to input selection,
  error display, or the TUI handoff. If a change affects the actual Pi screen,
  also use the `pi-tui-scenario-tests` skill for an outside-in journey.

## Validation

From the chezmoi source root:

```sh
node --test dot_pi/private_agent/extensions/passage-review/index.test.ts
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s dot_local/share/passage-review -p 'test_*.py' -v
chezmoi apply --dry-run --verbose ~/.pi/agent/extensions/passage-review
```

The Node test uses a fake Pi context and scripted reviewer CLI; it cannot
prove the live TUI, and no feedback is automatically delivered to an agent. Ask before applying the
extension, restarting an owner's Pi session, or touching an existing review
library.

## Completion and handoff

List changed source paths, the mode/branch and process-handoff cases covered,
the checks actually run, and any untested live TUI path. State whether live
apply or Pi restart remains for the owner; no note export implies delivery.
