# Termux

First-class chezmoi profile: **`termux`**.

Phone config is no longer ADB/`scp`-pushed from this staging directory. On the
phone, set `profile: "termux"` and `chezmoi apply` owns:

| Destination | Source |
|---|---|
| `~/.termux/termux.properties` | `dot_termux/termux.properties` |
| `~/.termux/font.ttf` | `dot_termux/font.ttf` |
| `~/bin/zellij-jump` | `bin/executable_zellij-jump` |
| `~/bin/herdr-jump` | `bin/executable_herdr-jump` |
| `~/.ssh/config` (managed block) | `private_dot_ssh/modify_config.tmpl` |
| `~/.ssh/homelab`, `~/.ssh/whonix-homelab` | `run_after_05_provision_termux_ssh_keys.sh.tmpl` |

Files in this `termux/` directory are **docs + deprecated helpers only** —
chezmoi ignores them on every profile (no more `~/termux` staging deploy).

## Bootstrap on the phone

Phone-only. No Mac/ADB sync.

Prerequisites:

1. Install the **Termux:API** Android app (F-Droid / GitHub release matching your
   Termux build).
2. Packages:

```bash
pkg install -y chezmoi git openssh coreutils termux-api
```

3. Create a **read-only fine-grained GitHub PAT** scoped to `cartwmic/dotfiles`
   contents:read, store it in 1Password (e.g. item `dotfiles-readonly-pat`).
   Fresh Termux has no GitHub SSH key yet, and the homelab key is provisioned
   *by* this apply — do not use `git@github.com:...` for first bootstrap.

```bash
mkdir -p ~/.config/chezmoi
cat > ~/.config/chezmoi/chezmoi.yaml <<'EOF'
data:
  profile: "termux"
EOF

# Copy the PAT from the 1Password Android app, then:
chezmoi init --apply https://github.com/cartwmic/dotfiles.git
# git will prompt for credentials: username = anything, password = PAT
# Optional persistence:
#   git config --global credential.helper store
```

After apply (and SSH key provision below):

- `ssh cartwmic-server` / `ssh remote` → `cartwmic@10.19.1.221` via `~/.ssh/homelab`
- `ssh macbook` → `cartwmic@10.19.1.200` via `~/.ssh/homelab`
- `ssh whonix-gw` / `ssh whonix-ws` → Whonix via `~/.ssh/whonix-homelab`
- Jump handlers live in `~/bin/{zellij,herdr}-jump` (ControlMaster over `remote`)

## SSH key provision

`05_provision_termux_ssh_keys` runs on **every** `chezmoi apply`. It fast-exits
when both keys already match the expected fingerprints; otherwise it always
fetches from 1Password (via `proot-distro` + `op`; there is no native Termux
`op` build). It does not migrate or reuse existing key files.

Prerequisite — service-account token at
`~/.config/agent-harness/op-service-token`:

1. In the 1Password Android app, open
   `Service Account Auth Token: developer-sa` → copy the `credential` (`ops_...`).
2. Switch back to Termux and run `chezmoi apply` immediately.
3. The script reads the clipboard via `termux-clipboard-get` (5s timeout),
   writes the token file (mode 600), clears the clipboard, then fetches the
   SSH keys. If the clipboard is empty and you are on a TTY, it prompts.

Missing token → apply warns and continues (re-run after copying). Token present
but proot/op/fetch failure → apply exits non-zero so the next apply retries.

Re-copy from 1Password only when rotating the SA token.

References:

- Homelab: `op://developer/cartwmic-homelab ssh key/private key?ssh-format=openssh`
  (fingerprint `SHA256:s1NF+DDqZKlvvy/wDQXBACMs3jb/cjkvy/UpOYbypOQ`)
- Whonix: `op://developer/whonix-homelab/private key?ssh-format=openssh`
  (fingerprint `SHA256:oNPHkrMebH0d0dq6B+gexDeimXdUbDHh38dHf3EGpEE`)

## Migrating from the old tar/ADB sync

If the phone still has a non-git tree left by an earlier Mac-side tar/scp push,
wipe source **and** chezmoi script state before re-bootstrapping:

```bash
rm -rf ~/.local/share/chezmoi
chezmoi state delete-bucket --bucket=scriptState
# then follow Bootstrap above
```

`rm -rf` alone is not enough — stale `scriptState` entries can skip provision
scripts from the old `run_once_` era.

## Deprecated: `sync.sh` / ADB push

`./termux/sync.sh` now refuses to push and prints the chezmoi bootstrap
reminder. Do not use ADB to overwrite phone config — edit sources under
`dot_termux/`, `bin/`, `private_dot_ssh/` and apply on the phone.

## Pulling live phone drift back into the repo

From a machine with the `personal` profile (needs `Host phone` in SSH config):

```bash
scp phone:.termux/termux.properties dot_termux/termux.properties
scp phone:bin/zellij-jump bin/executable_zellij-jump
scp phone:bin/herdr-jump bin/executable_herdr-jump
```
