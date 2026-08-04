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
| `~/.ssh/homelab`, `~/.ssh/whonix-homelab` | `run_once_after_05_provision_termux_ssh_keys.sh.tmpl` |

Files in this `termux/` directory are **docs + deprecated helpers only** —
chezmoi ignores them on every profile (no more `~/termux` staging deploy).

## Bootstrap on the phone

```bash
pkg install -y chezmoi git openssh coreutils

mkdir -p ~/.config/chezmoi
cat > ~/.config/chezmoi/chezmoi.yaml <<'EOF'
data:
  profile: "termux"
EOF

# Private repo: use the already-authorized homelab key (or HTTPS + token).
chezmoi init --apply git@github.com:cartwmic/dotfiles.git
# If the source is already cloned elsewhere:
#   chezmoi init --source ~/path/to/dotfiles --apply
```

After apply:

- `ssh cartwmic-server` / `ssh remote` → `cartwmic@10.19.1.221` via `~/.ssh/homelab`
- `ssh macbook` → `cartwmic@10.19.1.200` via `~/.ssh/homelab`
- `ssh whonix-gw` / `ssh whonix-ws` → Whonix via `~/.ssh/whonix-homelab`
- Jump handlers live in `~/bin/{zellij,herdr}-jump` (ControlMaster over `remote`)

## SSH key provision

`05_provision_termux_ssh_keys` is non-fatal:

1. Keeps keys that already match the expected fingerprints
2. Migrates `~/.ssh/id_ed25519` → `~/.ssh/homelab` when fingerprints match
3. Otherwise fetches from 1Password inside `proot-distro` using
   `~/.config/agent-harness/op-service-token` (same pattern as the old
   `setup-ssh-key.sh`)

References:

- Homelab: `op://developer/cartwmic-homelab ssh key/private key?ssh-format=openssh`
  (fingerprint `SHA256:s1NF+DDqZKlvvy/wDQXBACMs3jb/cjkvy/UpOYbypOQ`)
- Whonix: `op://developer/whonix-homelab/private key?ssh-format=openssh`
  (fingerprint `SHA256:oNPHkrMebH0d0dq6B+gexDeimXdUbDHh38dHf3EGpEE`)

## Deprecated: `sync.sh` / ADB push

`./termux/sync.sh` now refuses to push and prints the chezmoi bootstrap
reminder. Do not use ADB to overwrite phone config — edit sources under
`dot_termux/`, `bin/`, `private_dot_ssh/` and apply on the phone.

## Pulling live phone drift back into the repo

```bash
scp phone:.termux/termux.properties dot_termux/termux.properties
scp phone:bin/zellij-jump bin/executable_zellij-jump
scp phone:bin/herdr-jump bin/executable_herdr-jump
```
