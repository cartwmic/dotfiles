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

`cartwmic/dotfiles` is **public**, so first bootstrap needs no GitHub auth.
(Optional later: `pkg install gh && gh auth login` if you want `gh` / push from
the phone.)

```bash
mkdir -p ~/.config/chezmoi
cat > ~/.config/chezmoi/chezmoi.yaml <<'EOF'
data:
  profile: "termux"
EOF

chezmoi init --apply https://github.com/cartwmic/dotfiles.git
```

After apply (and SSH key provision below):

- `ssh cartwmic-server` / `ssh remote` → `cartwmic@10.19.1.221` via `~/.ssh/homelab` (ControlMaster)
- `ssh macbook` → `cartwmic@10.19.1.200` via `~/.ssh/homelab` (ControlMaster)
- `ssh laptop` → `michael@10.19.1.112` via `~/.ssh/homelab` (ControlMaster)
- `ssh whonix-gw` / `ssh whonix-ws` → Whonix via `~/.ssh/whonix-homelab`
- Jump handlers live in `~/bin/{zellij,herdr}-jump`. Usage: `<id> [host]`.
  Unset identity (missing host) defaults to `remote`. A present host must be a
  grammar-valid Termux SSH alias in `{remote, cartwmic-server, macbook, laptop}`
  or the script exits without ssh.
- ntfy Click URLs carry a host query (`?host=<alias>`) when the producer stamps
  that alias. Termux session name equals alias: the visible session must be named
  exactly the stamped SSH alias for focus. A miss still foregrounds Termux and
  still jumps over SSH.

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
