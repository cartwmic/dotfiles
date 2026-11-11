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

- `images/dashboard-hub/publish.sh` (coordinator repo; pushes to the homelab Gitea registry). It builds its own throwaway config when `DOCKER_CONFIG` is unset or empty, and uses a set one as it is. From an agent shell run `DOCKER_CONFIG= sh images/dashboard-hub/publish.sh`.
- kgate's `ghcr.io` pull credential is read from 1Password and sent to the cluster as a Secret. It never goes through a local docker.

For a one-off private pull, build a throwaway config as `docker-config.sh` does and point `DOCKER_CONFIG` at it for that command. Do not `docker login` into the agent config: the CLI may pick the keychain helper to store it, and the keychain prompt is back.

## Changing it

- `currentContext` is fixed at `desktop-linux`. If Docker Desktop's context is renamed, edit `dot_config/agent-docker/config.json`; `tests/agent-docker` checks it names a context in `~/.docker/contexts` only on a Mac that has one.
- Another harness's marker: add it to the list in `dot_zshenv` and in the op shim together.

## Not proven here

No docker process ran when this was built (the Mac was in use). The tests read files and run `zsh`, `chezmoi` and `jq`. The live proof is the commands below, run on a quiet machine after apply:

```sh
env -i HOME="$HOME" PATH="$PATH" CLAUDECODE=1 zsh -c 'echo "$DOCKER_CONFIG"; docker context show; docker pull hello-world; docker buildx imagetools inspect hello-world:latest' &
sleep 5; ps -axo pid,etime,command | grep '[d]ocker-credential'   # expect nothing
wait
```
