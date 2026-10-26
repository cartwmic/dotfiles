# Instances (LaunchAgent units, opt-in flags, reconcile script)

Source-only tests (`./tests/` is in .chezmoiignore).

    python3 -m unittest discover -s tests/instances -v
    python3 tests/instances/mutate.py [name substring]

- `golden/*.plist`: the units as the repos ship them (the coordinator unit is also byte-identical to the one deployed on the personal Mac), rendered for `HOME=/Users/test`. Default renders must stay byte-identical.
- MatrixTests run `dot_local/user_scripts/executable_instances_reconcile.sh` directly in a scratch HOME. The stub `launchctl` keeps loaded state, exits 113 from `print` for a service that is not loaded (as the real one does), can be told to fail `bootstrap` or `bootout`, and records every call. Cases assert the exact call list.
- ApplyTests (macOS) run `chezmoi apply` into a scratch HOME with the same stub, to prove the flags in chezmoi.yaml reach the script.
- `mutate.py` breaks the script 13 ways (restart on a changed unit, opt-out of something never started, adopt by bootstrapping, delete state, ...). Each must fail the suite. `INSTANCES_SCRIPT_UNDER_TEST` points the suite at the mutated copy.
- Nothing here reads or writes the real home, the real chezmoi state, launchd or Herdr.
