# The PATH mise builds, for a person's terminal and for an agent harness

Two kinds of zsh get two kinds of mise PATH. `private_dot_zshrc.tmpl` tells them apart by `$ZSH_EXECUTION_STRING`, which zsh sets only when a command string was given (`zsh -c`, `-lc`, `-ic`, `-ilc`).

| Shell | `$ZSH_EXECUTION_STRING` | mise | PATH holds | Why |
|---|---|---|---|---|
| A person's terminal (`zsh -i`, a login shell with no command) | empty | `mise activate zsh` (full) | each tool's versioned install folder, refreshed at every prompt | per-directory tool versions and `[env]` follow `cd`; a new pin shows at the next prompt |
| A command run through zsh (`zsh -ic CMD`) | set | `mise activate zsh --shims` | the shims folder only | nothing refreshes the PATH of such a shell, and a program may keep it |

## Why the second form exists

The agent harness (T3 Code) reads PATH once, at start, by running the login shell as `zsh -ilc <print PATH and __MISE_DIFF>` with no terminal, and gives that PATH to every session and child it opens. Under full activation that PATH names `installs/<tool>/<version>`. After a pin bump the kept PATH still names the old version, so agents ran the old `loop-engine`, `lean-change`, `policy-document` and `bookends-check` until the harness restarted. A shim finds the pinned version when it runs, so a PATH that holds the shims folder stays right across pin bumps.

Full activation also put every tool's real folder ahead of `~/.zshenv`'s `op` shim, so the guard shim never ran in those sessions. In the command form `private_dot_zshrc.tmpl` puts the op shim and the gh wrapper first again, as `~/.zshenv` and `~/.zprofile` do. In a person's terminal `dot_config/mise/conf.d/op-shim.toml` does it (`_.path`, as `~/.config/mise/conf.d/gh-wrapper.toml` does for the wrapper), so an agent started from a terminal inherits the guard first too.

## What it costs and what it changes

- A call through a shim starts `mise` first. Measured on the agent host (30 calls each): `bookends-check --version` took 3.3 ms from its install folder and 52.9 ms through its shim; `node -e 0` 70 ms and 118 ms. About 50 ms more per call.
- `command -v tool` names the shim, not the install file. `mise which tool` still names the install file.
- A shim applies the `[env]` of the config for the tool it runs, so tool-specific variables still arrive.
- A new global install of an npm, pip or cargo program is not shimmed until `mise reshim`.
- A change to the pin reaches a kept PATH at the next call. A change to the harness's own PATH (the harness reads it once) needs the harness restarted once, after this file's change first applies.

## Way back

Delete the `if [[ -n $ZSH_EXECUTION_STRING ]]` branch in `private_dot_zshrc.tmpl` (keep the `else` line), apply, restart the harness.

## Test

`tests/mise/test_agent_shell_path.py`: fresh `zsh -ilc` and `zsh -i` processes with the repository's own zsh files and real mise, with fake installed tools. It fails without the change in three places: the snapshot names an install folder, the op shim is not first, and a snapshot taken before a pin bump runs the old version after it.
