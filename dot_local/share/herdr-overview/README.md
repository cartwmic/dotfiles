# Herdr Overview plugin runtime

This source-managed Herdr plugin (`dot_local/share/herdr-overview/`) targets Herdr **0.9.1 / protocol 22**. The desktop mise task `install-herdr-overview` installs Herdr 0.9.1 and links/enables this manifest; it is deployed on `personal` and `axon-work-computer`. Termux skips `.config` and `.pi` and remains an SSH client, not a plugin host. The thin Pi adapter lives at `dot_pi/private_agent/extensions/herdr-overview/`. Linking does not run the startup hook or restart a Herdr server. The plugin `[[startup]]` hook runs after a compatible server starts, opens one overview tab, and initializes the shared model. It detects a saved overview pane whose plugin process did not survive a server restart, and closes that stale plugin-owned shell pane only when its dedicated tab is still intact. The `overview.reconcile` action calls the same idempotent initializer for an already-loaded server. No apply or bootstrap step restarts the owner's main server.

The adapter uses only public protocol methods: `session.snapshot`, `pane.read`, `pane.process_info`, `pane.focus`, `pane.rename`, `tab.rename`, `events.subscribe`, `plugin.pane.open`, and `plugin.action.invoke`. Manifest event hooks refresh structural, focus, and agent changes; the overview pane subscribes to the public `pane.output_matched` stream for output previews (Herdr 0.9.1 intentionally excludes high-volume output events from plugin hooks). Model keys are native Herdr IDs. The reader joins T1's `session-recap` v1 prompt and published recap files to native panes by their optional `pane_id` fields or an explicit manual source ID matching a pane ID, with the live Herdr Pi session ID as a fallback. At reconciliation, it persists each published Pi source's Herdr `terminal_id` while its pane ID still resolves. This stable association preserves pane detail and maps a prompt carrying its pre-move pane ID to the current pane after `pane.move` rekeys the ID, even when v0.9.1 reports `agent_session = null`. Prompt, recap, and live agent state stay separate.

## Presenters and navigation

The pane selects the narrow Board when its width is at or below `[ui].mobile_width_threshold` in Herdr `config.toml` (the managed value is 64); wider terminals get the independent Mosaic. There is no runtime layout switch. Each presenter owns its all-workspaces, workspace, and pane-detail rendering over the same ID-keyed model.

- Board: summary-first workspaces, then scrollable tab-grouped pane tiles and recent-output-first detail.
- Mosaic: all-workspace/all-pane simultaneous preview, then a tab-grouped preview grid and pane detail.
- `j`/`k` moves through workspaces or panes; `[`/`]` selects tabs; `Enter` opens the next level; `Esc` returns; `f` focuses the selected native pane; `q` closes; `r` rereads saved overview state. In pane detail, `j`/`k`, Space, and `b` scroll.

The display is passive: it shows only supplied prompt fields and published recap records, with age and missing/failure status. Opening, selection, preview refresh, scrolling, and focus never run `session-recap` or synthesize recap text. `overview.reconcile` remains a separate plugin action for publication coordination. To show a manually generated single recap in a pane's detail, use that native pane ID as the source ID, for example `printf '%s\n' 'Recent work and current state.' | session-recap create --kind single --source-id PANE_ID`. Its published or failed status is displayed, but manual results are not Pi auto-naming inputs.

The existing `overview.reconcile` action and server-start hook also drain successful Pi-session publications. The coordinator deduplicates published record IDs and stores them with absolute per-workspace deadlines in user-local `herdr-overview/overview.json` state. A publication's recorded `workspace_id` is authoritative for its deadline attribution; later pane moves do not reassign that deadline. Each in-workspace success starts or resets a 30-second quiet period. A detached one-shot deadline wake-up invokes the same existing action; startup resumes pending deadlines. At expiry, a fresh native snapshot selects each current pane's latest indexed published recap, including Pi-session records matched through the current session or persisted terminal-ID association after pane moves, and manual pane-source recaps for non-Pi panes; closed panes are excluded. Those member recaps are supplied to `session-recap create --kind group`. Only a successful workspace publication is followed by an `active` Herdr-session group from latest indexed workspace recaps whose native workspace IDs are still live. Failed workspace grouping leaves its deadline due for the next startup/reconcile wake-up; it does not trigger a session recap or a retry poll. Raw non-Pi output is not included. The overview itself remains a passive reader; it does not poll or generate recaps on display events.

Display-name ownership is persisted per pane/tab ID in overview state. Unlabelled panes and Herdr v0.9.1's positional numeric tab defaults (`1`, `2`, etc.; `workspace.rs::tab_display_name`) can be named from native titles, agent/process metadata, cwd, and eligible published Pi recaps. Unknown initial labels and later owner edits become manual and are preserved. The `overview.auto_name_pane` and `overview.auto_name_tab` actions are scoped to Herdr's pane/tab action contexts and explicitly return only that live ID to automatic ownership. Pi names use only a successful recap published for that pane in its Herdr workspace; the live prompt, workspace labels, and Pi session identity are never naming inputs or mutation targets. A tab name combines the available pane task labels from its panes.

`src/palette-v0.9.1.json` is attributed to `herdrdev/herdr` tag `v0.9.1` (commit `8544776216a8d28088db59a5344ea21ee2d05d2b`), `src/app/state.rs`, `Palette` constructors and `Palette::from_name`. RGB values are copied from the pinned source literals; Reset and ANSI variants remain typed. The theme adapter reads the managed `config.toml` on pane open and watches the file for changes. With `auto_switch = false`, `[theme].name` and `[theme.custom]` resolve directly. If `auto_switch = true`, the adapter does not claim host appearance detection without an explicit appearance input.

Run package tests with:

```sh
npm test
```

The source-only outside-in driver is `tests/herdr-overview/proof.py`; it is
excluded from chezmoi deployment. Run its named scenarios from the repo root:

```sh
python3 tests/herdr-overview/proof.py recap
python3 tests/herdr-overview/proof.py review
python3 tests/herdr-overview/proof.py herdr-prepare # copy run_id from its JSON result
python3 tests/herdr-overview/proof.py herdr-wide --run-id RUN_ID
python3 tests/herdr-overview/proof.py pi-grouped --run-id RUN_ID
# On the attended Termux phone: ~/bin/herdr-overview-proof RUN_ID macbook
python3 tests/herdr-overview/proof.py termux-ssh --run-id RUN_ID
# After the attended phone route: real pane.move, post-move Pi input, and live-group regressions.
python3 tests/herdr-overview/proof.py herdr-native-move --run-id RUN_ID
python3 tests/herdr-overview/proof.py herdr-cleanup --run-id RUN_ID
python3 tests/herdr-overview/proof.py chezmoi-dry-run
```

The supplemental `herdr-native-move` journey requires the returned phone receipt
and runs after the phone stage. It moves the live Pi pane with native
`pane.move`, submits a new prompt through the process's inherited caller ID,
checks the current prompt in the rekeyed pane detail, groups a current manual
non-Pi pane recap, and closes a workspace before the next Herdr-session group.
Its scripted loopback Pi provider is recorded under the same isolated run and
stopped by `herdr-cleanup`. Each JSON line carries its `command_id`. Cleanup
stops only that run's recorded provider/server and removes only its marked
temporary directory.
A `termux-ssh` PASS requires an attended phone or ADB-controlled Termux
emulator to run the phone-owned helper and return its receipt over
phone-to-desktop SSH; a narrow local PTY is never phone proof. The stable-tree
driver runs the sole full matrix and retains each JSON outcome under its
`command_id`.
