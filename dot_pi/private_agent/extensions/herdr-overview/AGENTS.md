# Herdr overview Pi adapter — agent instructions

## Scope and authority

This file covers `dot_pi/private_agent/extensions/herdr-overview/`. The
repo-root `AGENTS.md` controls chezmoi source and apply. Read
`dot_pi/private_agent/extensions/README.md` for shared Pi extension rules when
editing this adapter, especially per-call `ctx` lifetime. The local
`README.md` owns human setup. `session-recap` owns prompts, recap records, and
backend configuration; the Herdr plugin owns the native overview and grouping.

## Workflow

- Work in `index.ts` and `helpers.ts`. Hold only serializable pending state
  across events. Use the `ctx` passed to each callback; a saved
  `ExtensionContext` becomes stale after session replacement or reload.
- Accept only real interactive TUI or RPC user input for current prompts.
  Extension-generated continuations must not replace them. At
  `agent_settled`, require idle state and take the latest assistant reply from
  the public branch API. Consume a prompt once, before awaiting the backend;
  skip blank, aborted, and errored responses.
- For a Pi pane, call Herdr's caller-aware `pane.current` using the inherited
  `HERDR_PANE_ID`. Resolve it before prompt storage, after a possible pane
  rekey, and again at publication for workspace membership. Missing socket,
  pane, or workspace keeps the record session-only. Never substitute UI focus
  or change Pi session identity or `herdr-agent-state.ts`.
- `session-recap prompt set/settle/rekey` keeps the working prompt separate
  from `prepare/publish`. After settling the prompt, check
  `session-recap config auto-publish`. The managed default is `disabled` and
  must skip preparation and wake-up without warning; an invalid policy fails
  closed. When opted in, confirm the prepared ID and publication before
  invoking the public `overview.reconcile` action. A failed Herdr wake-up
  leaves the durable publication for later startup reconciliation. The plugin
  does not generate a recap when its pane renders.
- Keep private current session identity/name publication independent of recap
  opt-in. Join by socket and unique live terminal, refresh on session lifecycle
  replacement/reload and `session_info_changed`, using actual public UUID/name
  from per-call `ctx` before awaits. Name-only refresh invokes passive
  `overview.refresh_names`, not recap-enabled reconcile. Only TUI/RPC publish;
  print/JSON children must neither claim nor retire interactive records.
  Keep generation/revision guards and compare-owned retirement. Reader joins
  require live publisher, unique native terminal, correct socket and no
  duplicate/conflicting session record. Do not infer session identity
  from recap/digest text or focused panes. The popup reads UUID-keyed dated
  digests separately; rendering must not generate them.
- This adapter is desktop-only. The `termux` profile skips `.pi`; phone
  access reaches the desktop through SSH.

## Validation

From the chezmoi source root, run the adapter suite after changing hooks,
caller membership, or publication. The test drives temporary Pi RPC with a
scripted response server, the real CLI with a fake recap backend, and a fake
protocol-22 Herdr socket. It needs no owner server or live model.

```sh
node --test dot_pi/private_agent/extensions/herdr-overview/index.test.ts
python3 tests/herdr-overview/proof.py recap
chezmoi apply --dry-run --verbose ~/.pi/agent/extensions/herdr-overview
```

For a user-facing Pi TUI change, load the `pi-tui-scenario-tests` skill and
use an outside-in disposable path; `index.test.ts` alone cannot prove what a
user sees after move/reload. Ask before applying, restarting Pi or Herdr, or
running an attended phone check.

## Completion and handoff

Name changed source paths, which input and publication cases were checked,
the exact tests and dry-run result, and any untested live TUI or phone path.
Leave live apply and owner-process restarts explicitly to the owner unless
authorized.
