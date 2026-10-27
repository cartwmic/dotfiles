# work-mac-instances.sh

A one-time helper for the work Mac (`axon-work-computer`): it does the "Apply on the work Mac" steps of dotfiles PR #80 safely, one step at a time. It is not deployed by chezmoi (`docs/` is ignored); copy it or run it from the checkout.

Run it as yourself, no sudo:

1. `sh work-mac-instances.sh --dry-run` shows what it would do. It writes and fetches nothing.
2. `sh work-mac-instances.sh` runs steps 1 to 4. It does not change `instances.coordinator.enabled`.
3. `sh work-mac-instances.sh --enable` also runs step 5, when you decide: it turns the flag on and applies. The running service is adopted, not restarted. It prints READY or NOT READY.

Options: `--coordinator DIR` (or env `COORDINATOR_DIR`), `--allow-hooks` (accept chezmoi hooks other than the 1Password installer, after you have read them).

Exit codes: 0 done, 1 a step failed, 2 bad usage, 4 you must do one thing by hand (it says what), 5 `--enable` applied but the instance is NOT READY.

## Steps

1. Preflight: tools, chezmoi hooks (listed without being run), the dotfiles source (`git pull --ff-only`; stops if tracked files are dirty or it cannot fast-forward), the coordinator checkout.
2. Local chezmoi data: `profile: axon-work-computer` and `instances.coordinator.repo`. A verified backup (`chezmoi.yaml.bak.<timestamp>`) first; it only adds what is missing and never overwrites a value.
3. `chezmoi apply` limited to the inert unit and the reconcile script.
4. Compare the rendered unit with `~/Library/LaunchAgents/local.coordinatord.work.plist` (read-only).
5. (`--enable` only) set the flag, apply the reconcile step, report.

## Values it reads from the live unit

- **Checkout.** With no `--coordinator`, no `COORDINATOR_DIR` and no `instances.coordinator.repo`, it uses the `WorkingDirectory` of the installed live unit, if that is a usable coordinator checkout; otherwise `~/git/coordinator`. If neither works it stops and says why. An argument or an existing value always wins.
- **`extraPath`.** If the live unit differs from the rendered one only by a PATH prefix (for example the mise node and herdr directories) and `extraPath` is unset, it adds that prefix to your config (backup first, read back through chezmoi, unit applied again, compared again). An `extraPath` that is already set is never overwritten: it prints the live value and stops (exit 4). A prefix that is not absolute directories of plain characters is printed, not written.
- **`--dry-run`** renders the unit against a copy of your config with the lines it would add (`chezmoi --config`), so it works with a chezmoi that has no `--override-data`.

## What it does not touch

The live unit, the coordinator's setup script, secrets, sudo. `launchctl` is used read-only (`print`); the reconcile step under `--enable` is the dotfiles script.

## Tests

`python3 -m unittest discover -s tests/work-mac-instances -v` (macOS, chezmoi and git; a scratch HOME, real chezmoi and git against a local bare remote, a stub `launchctl`). `python3 tests/work-mac-instances/mutate.py` checks the suite catches deliberate breaks of each safety property. `shellcheck -s sh docs/work-mac/work-mac-instances.sh` is clean.
