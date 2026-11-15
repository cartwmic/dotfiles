# Container mode

A setting that makes a personal Linux home fit the agent host pod (homelab repo, `k8s/agent-host`): no desktop, no systemd, no launchd, only the tools the pod uses, and Claude Code through the in-cluster cliproxy. Personal profile on Linux only; the work coordinator runs on the work Mac (see the Feature row in [profiles.md](./profiles.md)).

## Turn it on

In the pod's `~/.config/chezmoi/chezmoi.yaml` (no `read-source-state` hook in it):

```yaml
data:
  profile: personal
  container:
    enabled: true
    # cliproxyUrl: http://cliproxyapi.cliproxyapi.svc.cluster.local   # default, plain http, no /v1
    # cliproxyKeyFile: /run/secrets/cliproxy/api-key                  # default; the file holds the key
  sshHosts:                # top-level, beside container; the pod's configmap sets it (k8s/agent-host/base/configmap.yaml)
    kgate: {address: 10.19.1.196, user: cartwmic}
    # kgateFallback:         # optional: more control planes, tried in order
```

Then `chezmoi init --apply cartwmic`, `npm ci` in the coordinator checkout (`~/git/coordinator`), and `chezmoi apply` once more ("Two applies"). Any other profile or OS, an unknown key under `container`, or a bad value fails the render, so nothing is applied.

## What it does

| Part | In container mode |
|---|---|
| Claude Code (`~/.claude/settings.json`) | `env.ANTHROPIC_BASE_URL` is `cliproxyUrl`; `apiKeyHelper` is `cat` of `cliproxyKeyFile`, which Claude reads when it calls the model. No `op`, no token variable, and nothing writes `~/.claude/.credentials.json`. |
| Mise | `~/.config/mise/config.toml` is left out. `~/.config/mise/conf.d/container.toml` is rendered from it instead (`container.toml.tmpl`): `node`, `python`, `gh`, `jq`, `chezmoi`, `loop-engine`, `lean-change` at the pins in `config.toml`, the `install-claude` task, and `op` pinned in the template. So `mise ls --missing` lists only these until they are installed, then nothing. |
| Run scripts | Only `05_container_tools.sh` (mise install, the Claude install, T3 through `install_t3.sh`), `20_apply_harness_config.sh`, `65_agent_kit_install.sh` (gives `agent-traces`), `76_git_credential_linux.sh` (git uses `gh auth git-credential`) and `77_git_identity_linux.sh` (git author) run. The rest are left out, computed from the files in the source root, so a new script is out until it is listed in `.chezmoiignore`. None of the five runs on every apply, so plain `chezmoi verify` exits 0 after the first successful apply. |
| Left out | Everything under `.config/systemd`, `.config/hypr`, `.config/kitty`, `.config/zellij`, `.local/share/instances`, `.ssh`, the desktop helpers, the timer-backed tools, and the config of tools the pod does not install (nvim, lazygit, starship, qmd, agentsview). The list is in `.chezmoiignore`; `tests/container-mode` pins the checks. |
| Coordinator hook | Installed by the same template as everywhere: only while `$HOME/git/coordinator/src/t3-hook/hook.ts` exists at apply time, state in `$HOME/.local/share/coordinator`. |
| GitHub | `gh` is in the lean set. Set `GH_TOKEN` in the pod's environment and `gh auth status` passes with no login step; git pushes use `gh auth git-credential` (script 76), so they use the same token. |
| T3 instances (`~/.t3/userdata/settings.json`) | Kept. The four `seat-*` instances are written even before T3 has created the file: in container mode an empty file counts as `{}`. Each seat's `--settings` file is `~/.claude/fleet/seat-<seat>.json`, also kept. `pi` and `pi-lead` are not written: Pi is not in the pod's tool set. The T3 hub switch (`hub.enabled`, default on) stays on, as on any personal host: on the second apply it reads the hub management key with `op` (the pod's `OP_SERVICE_ACCOUNT_TOKEN`) for T3's usage panel. If that read fails, the apply warns and goes on. Not shown here: that T3 accepts the seeded file at its first start (the pod shows it). |
| kgate | `~/.config/kgate/host` is written from `sshHosts.kgate` (and `sshHosts.kgateFallback`), which the pod's configmap sets; without `sshHosts.kgate` it is left out. The homelab repo's `scripts/agent-host/kubectl.sh` also takes `KGATE_SSH` from the environment, which wins over the file. |
| Codex | Left out (config and pins). There is no OpenAI model in the pod, so Codex is out of scope. |

## Two applies

`modify_settings.json.tmpl` asks the coordinator's hook for its settings entries by running `node` while it renders. On a fresh pod the first apply renders `settings.json` before `05_container_tools.sh` has installed node, so it prints a `WARN ... did not print its settings entries` and leaves the hook entries out. The hook script imports from the coordinator checkout's `node_modules`, so run `npm ci` there between the applies (the image's start script does). Run `chezmoi apply` a second time and they are added. Without `node_modules` the hook does not print its entries and the hook stays off. `tests/container-mode` runs this exact sequence.

The shell that runs `claude`, `kgate` and the other tools needs `$HOME/.local/bin` and `$HOME/.local/share/mise/shims` on `PATH` (the `ENV` of the image), not only in `.zshrc`.

## Proof

`python3 -m unittest discover -s tests/container-mode -v` renders the source with the real chezmoi into a throwaway HOME (files only, no run script, no network) and checks the Claude settings, the exact script set, the left-out paths, `chezmoi verify`, the lean mise set and the two-apply hook sequence. It cannot show the installed tools or a model call; those need the pod (`chezmoi verify`, `mise ls --missing` and `claude -p` inside it).
