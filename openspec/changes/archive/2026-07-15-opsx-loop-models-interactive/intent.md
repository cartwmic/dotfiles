# Intent — opsx-loop-models-interactive

**Status:** FROZEN (explore concluded 2026-07-14; amended 2026-07-14 with
explicit human authorization — per-model review thinking + CLI scope widen)
**Recommended Scale:** M, `full_rigor: false`

Schema: opsx-superpowers. This intent.md is the frozen baseline; do not edit
without explicit human authorization.

## Intent

Give `/opsx-loop models set` the same interactive UX humans got from shell
`opsx models set`, without reimplementing YAML writes inside the extension —
and fix interactive **review** so each selected model gets its own thinking
suffix (today CLI applies one shared level to the whole list).

Spikes proved pi extensions cannot hand a real TTY to a child (`pi.exec` uses
`stdio: ["ignore","pipe","pipe"]`; `ExtensionUIContext` has no `ui.stop` /
terminal-release hook). Path B is the workable solution for the slash UX:

```
/opsx-loop models set  (bare or role-only, hasUI)
        │
        ▼
  pi TUI: role → filtered model catalog
        → (review: for each pick: model → thinking for that model → next; Done)
        → (author/impl: one model → one thinking)
        → author-in-session boolean when needed
        │
        ▼
  opsx models set <role> <id[:suffix]…>   ← non-interactive write (CLI owns YAML)
```

Shell interactive `opsx models set` MUST use the same per-model review thinking
contract (amend `executable_opsx` interactive path; non-interactive
`set review a:high b:xhigh` already supports per-entry suffixes).

Value-bearing `/opsx-loop models set <role> <value…>` stays a thin passthrough
to the CLI (unchanged). Bare `/opsx-loop models` still lists.

## Constraints

- **Write owner:** extension NEVER writes `~/.config/opsx/models.yaml` (or any
  models file). Final write is always `opsx models set …` with explicit args.
- **UX home:** interactive path on bare `/opsx-loop models set` and role-only
  `/opsx-loop models set <role>` when `ctx.hasUI`. Without UI, fall back to
  current thin-wrapper behavior (passthrough / actionable error — do not hang).
- **Catalog source:** extension runs `pi --list-models` and parses the same
  columnar layout the CLI already assumes (`provider` + `model` → `provider/id`).
  Missing/empty catalog → actionable error; no hard-coded catalog.
- **Picker:** custom filtered SelectList via `ctx.ui.custom` (stock
  `SelectList.setFilter` is startsWith-on-value — insufficient for 547
  `provider/id` strings). Filter MUST match substring / contains on the id
  (e.g. typing `claude` finds `anthropic/claude-sonnet-5`).
- **Review multi:** sequential single picks + Done/Esc end; selection order
  becomes the list passed to `opsx models set review …` (same contract as
  CLI sequential fzf).
- **Thinking — per model for review:** after each review model pick, prompt
  thinking for **that** model only; append `:<level>` (or none on
  skip/off/none) to that id before accumulating. Vocabulary:
  `off|minimal|low|medium|high|xhigh|max|skip`. Do **not** apply one shared
  level across the whole review list.
- **Thinking — scalar roles:** `author` / `impl` keep a single pick → one
  thinking prompt (unchanged shape).
- **Roles:** `author`, `review`, `impl`, `author-in-session` (boolean via
  `ui.select` / confirm).
- **CLI parity:** interactive `opsx models set` / `set review` in
  `dot_local/bin/executable_opsx` MUST prompt thinking after each review
  pick (same per-model contract); hermetic tests cover mixed suffixes in the
  interactive review path. Non-interactive multi-arg/comma set already
  preserves per-entry suffixes — keep that.
- **Timeouts:** interactive catalog fetch may exceed today's `runModels` 10s
  cap; raise or bypass timeout for `pi --list-models` / interactive path only.
- **Code home:** `dot_pi/agent/extensions/opsx-loop/` **and**
  `dot_local/bin/executable_opsx` interactive review thinking loop (+
  `openspec/specs/opsx-loop` and, if needed, `opsx-cli` /
  `opsx-model-config` delta for the CLI AC); tests in extension suite /
  `tests/opsx-models` as needed.
- **Spec impact:** MODIFY `opsx-loop` "Model config subcommand" for interactive
  bare/role-only set when UI available; MODIFY CLI interactive ACs so review
  thinking is per selected model (not one level for the whole list).

## Invariants honored

- Constitution I — chezmoi-deployed pi extension at `dot_pi/agent/extensions/opsx-loop/`
  and CLI at `dot_local/bin/executable_opsx`.
- Constitution III — no secrets; model ids are not credentials.
- Constitution VIII — `openspec/` not chezmoi-deployed.
- Existing opsx-loop invariant: CLI owns model-config writes; extension is UX +
  spawn wrapper.
- Resolver / YAML / atomic-write contracts remain owned by `opsx models` (no
  second writer).
- Stored review lists may already carry per-entry `:thinking` suffixes
  (non-interactive path); interactive must produce the same shape.

## Non-goals

- Path A TTY handoff / `ui.stop` / upstream `withReleasedTerminal` API.
- Zellij/kitty floating-pane launch of CLI interactive.
- New `opsx models catalog --json` verb (deferred; extension parses
  `pi --list-models` directly for v1).
- Reimplementing fzf inside the extension.
- Auto-pinning change `review.md` front-matter from the picker.
- Changing gate / loop dispatch beyond consuming suffix-bearing ids the CLI
  already stores.
- "Same as previous" thinking shortcut (deferred; may follow-up).
- Changing non-interactive `opsx models set review a,b` to invent suffixes —
  callers already pass per-id `:level` when wanted.
