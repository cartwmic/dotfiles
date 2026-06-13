# Termux

Canonical source for Termux configuration on the Android phone.

Chezmoi cannot deploy these files directly (the destination lives on the phone,
not this machine), so the workflow is **edit-here, push-via-adb**.

## Files

- `termux.properties` — extra-keys home row (long-press popups bound to zellij
  shortcuts: `CTRL T` → room, `CTRL Y` → harpoon, etc.).
- `font.ttf` — terminal font. Currently **FiraCode Nerd Font Regular v3.4.0**
  (provides Nerd Font glyphs for the extra-keys row and the prompt). Replace
  this file with another `.ttf` to switch fonts, then re-run `sync.sh`.

## SSH private key (pull from 1Password)

`setup-ssh-key.sh` runs **on the phone** (not pushed via ADB) to fetch a shared
SSH private key from 1Password into Termux `~/.ssh`, so you can ssh out with
native openssh.

Why a helper: `op` has no native Termux build (glibc vs Android bionic), so the
script runs `op` inside a `proot-distro` Debian guest *only to fetch the key*,
authenticated headlessly by the same service-account token file the harness
uses (`~/.config/agent-harness/op-service-token`). The key is bind-mounted
straight into Termux `~/.ssh`; you ssh from bare Termux.

We accept a single shared key across machines (low stakes) rather than a
per-device key.

One-time, on the phone:

```bash
# 1. ensure the ops_... service-account token file exists
mkdir -p ~/.config/agent-harness && chmod 700 ~/.config/agent-harness
printf '%s' 'ops_...' > ~/.config/agent-harness/op-service-token
chmod 600 ~/.config/agent-harness/op-service-token

# 2. run the bootstrap (override the op:// ref if needed)
OP_SSH_KEY_REF='op://personal/ssh-termux/private key' bash setup-ssh-key.sh
```

The private key must already exist in 1Password (e.g. item `ssh-termux`, field
`private key`). Bump `OP_VERSION` in the script as the 1Password CLI releases.

## Sync to device

Phone must be reachable over ADB (`adb devices` shows it).

```bash
./termux/sync.sh
```

Or manually:

```bash
adb push termux/termux.properties /data/local/tmp/termux.properties.new
adb shell 'run-as com.termux cp /data/local/tmp/termux.properties.new \
    files/home/.termux/termux.properties && \
    rm /data/local/tmp/termux.properties.new'
adb shell 'am broadcast --user 0 -a com.termux.app.reload_style com.termux'
```

## Pull from device (when editing on phone)

```bash
adb shell 'run-as com.termux cat files/home/.termux/termux.properties' \
    > termux/termux.properties
adb shell 'run-as com.termux cat files/home/.termux/font.ttf' \
    > termux/font.ttf
```
