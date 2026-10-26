# Instances (LaunchAgent units, opt-in flags, reconcile script)

Source-only tests (`./tests/` is in .chezmoiignore).

    python3 -m unittest discover -s tests/instances -v
    python3 tests/instances/mutate.py [name substring]

- `golden/*.plist`: the units as the repos ship them (the coordinator unit is also byte-identical to the one deployed on the personal Mac), rendered for `HOME=/Users/test`. Default renders must stay byte-identical. `golden/coordinator-repo.local.coordinatord.work.plist` is a copy of the coordinator repo's `docs/launchd/local.coordinatord.work.plist` (last changed in coordinator ef403d3): RenderTests apply the setup script's `sed` to it and require the rendered work unit to be byte-identical, so adopting the hand-installed unit sees no difference. `COORDINATOR_CHECKOUT=/path python3 -m unittest discover -s tests/instances` also compares with a live checkout's template.
- MatrixTests run `dot_local/user_scripts/executable_instances_reconcile.sh` directly in a scratch HOME. The stub `launchctl` keeps loaded state, exits 113 from `print` for a service that is not loaded (as the real one does), can be told to fail `bootstrap` or `bootout`, and records every call. Cases assert the exact call list.
- ApplyTests (macOS) run `chezmoi apply` into a scratch HOME with the same stub, to prove the flags in chezmoi.yaml reach the script.
- WorkMatrixTests are the same matrix for the work coordinator (label `local.coordinatord.work`, `coordinator-work` markers), adoption of the hand-made service included; its setup script is a stub that records its arguments and PATH.
- `mutate.py` breaks the reconcile script (restart on a changed unit, opt-out of something never started, adopt by bootstrapping, delete state, the work variant's label, state, PATH, setup arguments, ...) and the files that feed it (`.chezmoiignore`, the wrapper, the work unit template). Each must fail the suite. `INSTANCES_SCRIPT_UNDER_TEST` points the suite at the mutated copy of the script; other files are edited in place for the run and restored.
- Nothing here reads or writes the real home, the real chezmoi state, launchd or Herdr.
- R11 (marker writes must not use a POSIX special builtin like ':'; dash aborts on a redirect error) is checked by the marker tests under CI's /bin/sh (dash); macOS sh does not abort, so mutate.py has no mutation for it.
