# Response visibility owner adapter

Thin delegation only; the `pi-response-visibility` package owns the canonical
payload, version checks and sibling-safe rollback. No telemetry payload lives here.
Only `personal` and `axon-work-computer` run the helper; Termux, unknown and unset
profiles skip without touching Pi.

Prerequisites: Node >=22.19, Pi 0.99.2, and the canonical package installed by Pi
from `https://github.com/cartwmic/pi-response-visibility`. Desktop Pi settings
declare that package. The wrapper finds its helper in Pi's installed Git checkout;
an explicit `PI_RESPONSE_VISIBILITY_HELPER` or a package bin on PATH takes precedence.
A missing helper fails on desktop profiles; it is not silently downloaded.
This source change does not install or publish the package or configure a remote.
For developer/private tests, explicitly set `PI_RESPONSE_VISIBILITY_HELPER` to an
absolute package `bin/core.mjs` and `PI_ROOT` to an absolute private Pi package root.
Without `PI_ROOT`, the wrapper passes the global npm Pi package root to the canonical
helper, which enforces its exact supported version and checked anchors.

Direct invocation from this checkout (default action is apply):

```sh
PI_CHEZMOI_PROFILE=personal \
PI_RESPONSE_VISIBILITY_HELPER=/absolute/pi-response-visibility/bin/core.mjs \
PI_ROOT=/absolute/private/pi-copy \
node dot_local/share/pi-patches/response-visibility/patch.mjs --check
# Same environment, no argument: apply; --rollback: rollback.
```

Chezmoi path: `run_onchange_after_30_apply_pi_patches.sh.tmpl` hashes this wrapper,
exports the active profile and invokes `~/.local/user_scripts/apply_pi_patches.sh`.
For an approved worktree deployment, use `chezmoi --source "$REPO" apply` only
after the parent patch guide's hook/config preflight and targeted preview.
Manual source-loop invocation uses `PI_PATCHES_ROOT="$REPO/dot_local/share/pi-patches"`
and the actual `PI_CHEZMOI_PROFILE`; it runs all sibling patches too.
Helper payload upgrades alone do not change this wrapper hash: explicitly rerun
when upgrading the helper or reinstalling the same Pi version.

Ordinary Pi package installation never patches the runtime. This owner-specific
chezmoi patch loop is the separate explicit opt-in deployment path; preview and
obtain owner approval before applying it. Reinstall/update the Git package before
rerunning this helper after a package upgrade. No npm publication is required.
