# Agent docker config

Personal macOS only (`docs/profiles.md`). `~/.docker/config.json` has `credsStore: desktop`, so every `docker` command runs `docker-credential-desktop`. Run from an agent's shell, that helper makes macOS ask "access data from other apps" for the agent app, again after every Allow. On 2026-11-10 eight of them hung and kept asking for two hours.

## What is deployed

| Path | Content |
|---|---|
| `~/.config/agent-docker/config.json` | `currentContext: desktop-linux`, no `credsStore`, no `credHelpers`, and one placeholder `auths` entry (`agent-config.invalid`, empty) |
| `~/.config/agent-docker/contexts`, `cli-plugins`, `buildx` | symlinks to `~/.docker/contexts`, `cli-plugins` and `buildx`, so the Docker Desktop context, `docker buildx` and `docker compose` work as before |

The `auths` entry is not decoration. The docker CLI picks a default credential helper (`docker-credential-osxkeychain` here) for a config that holds no auth at all, and a keychain helper can prompt too. Any `auths` entry stops that, and a registry that has no entry is pulled anonymously.

`dot_zshenv` exports `DOCKER_CONFIG` to that directory when none is set, the directory exists, and one of `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `T3CODE_THREAD_ID`, `HERDR_ENV`, `CODEX_SANDBOX` is set (the op shim's list). Every harness reaches it through its shell: Claude Code and T3 run zsh (which reads `~/.zshenv`); Pi starts inside a herdr pane's zsh and its bash tool inherits the environment (`getShellEnv` spreads `process.env`); Codex runs the login shell, zsh here. Michael's own terminals set none of those markers, so they keep `~/.docker`. A terminal started inside one of those apps, or a herdr pane he opens himself, inherits the marker and gets the agent config; `DOCKER_CONFIG= docker ...` or `unset DOCKER_CONFIG` gives it back the normal one.

## Private registries

The agent config holds no login, so a pull or push that needs one fails with an authorization error instead of prompting. Flows that need one:

- `images/dashboard-hub/publish.sh` (coordinator repo; pushes to the homelab Gitea registry). The coordinator repo's `publish.sh` and `docs/deploy.md` handle the agent config themselves: `publish.sh` treats `~/.config/agent-docker` like an unset `DOCKER_CONFIG` and builds its own throwaway login. Order: the coordinator PR that does this is merged before this dotfiles change is applied; applied first, an agent-run publish fails its push with an authorization error.
- kgate's `ghcr.io` pull credential is read from 1Password and sent to the cluster as a Secret. It never goes through a local docker.

For a one-off private pull, build a throwaway config as `docker-config.sh` does and point `DOCKER_CONFIG` at it for that command. Do not `docker login` into the agent config: with no credential store the login is written as a plaintext credential into `config.json`, which chezmoi manages.

## Limits

- Docker Hub pulls from agent shells are anonymous and count against Docker Hub's anonymous rate limit.
- A Codex session with its sandbox off and not under T3 sets no agent marker and still uses the desktop helper (the same gap as the 1Password shim).

## Applying

Personal Mac only, and only after the coordinator `publish.sh` change above is merged. Before the apply, check chezmoi's `hooks.read-source-state.pre` in the effective config (dotfiles `AGENTS.md`, "Workflow"), and check that the live `~/.zshenv` matches `main`'s `dot_zshenv` (`chezmoi --source <merged checkout> diff ~/.zshenv` shows only this block), so no drift is overwritten. Then:

```sh
chezmoi --source <merged checkout> apply --dry-run --verbose ~/.config/agent-docker ~/.zshenv
chezmoi --source <merged checkout> apply ~/.config/agent-docker ~/.zshenv
```

New agent sessions get `DOCKER_CONFIG`; running shells keep their old environment.

## Changing it

- `currentContext` is fixed at `desktop-linux`. If Docker Desktop's context is renamed, edit `dot_config/agent-docker/config.json`. `docker context use` from an agent shell rewrites that managed file; the next apply resets it.
- Another harness's marker: add it to the list in `dot_zshenv` and in the op shim together.

## Not proven here

No docker process ran when this was built (the Mac was in use). The tests read files and run `zsh`, `chezmoi` and `jq`. The live proof is the commands below, run on a quiet machine after apply:

```sh
env -i HOME="$HOME" PATH="$PATH" CLAUDECODE=1 zsh -c 'echo "$DOCKER_CONFIG"; docker context show; docker pull hello-world; docker buildx imagetools inspect hello-world:latest' &
sleep 5; ps -axo pid,etime,command | grep '[d]ocker-credential'   # expect nothing
wait
```
