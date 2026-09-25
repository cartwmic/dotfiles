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

Files in this `termux/` directory are **docs, Mac-side bootstrap utilities,
and deprecated helpers**. Chezmoi ignores this directory on every profile;
no `~/termux` staging tree is deployed. The Mac utilities install apps and
open a USB-only SSH connection, but **never push dotfiles through ADB**.
Phone-side chezmoi owns configuration.

## Rebuild a phone (Mac-driven)

These scripts target an exact **USB** ADB serial and reject TCP transports
and emulators. There may be an emulator attached; never omit `--serial`.
They do not uninstall apps, bypass Play Protect,
configure Android Accessibility silently, or touch `daily-phone` (Z Fold 7).
Run them from this repo on a personal Mac with `adb`, Python 3, JDK 17,
Android SDK platforms 34/35/36 + Build Tools 35.0.0, `op` authenticated to the
`developer` vault, `~/keys/termux-fork.jks`, and the personal homelab SSH key.
For WireGuard QR preparation, also install `wg` and `qrencode` (for example,
`brew install wireguard-tools qrencode`). The signing keystore is **not** in
Git; back it up separately. Do not copy a private key from another phone.

```bash
SERIAL=ZD222TJML8 # replace after a wipe/new phone; read from `adb devices`
python3 termux/bootstrap-phone.py inspect --serial "$SERIAL"
termux/build-apks.sh build
termux/build-apks.sh check
python3 termux/bootstrap-phone.py install --serial "$SERIAL" \
  --apks-dir "$HOME/.cache/dotfiles-termux/apks" --confirm-install
```

`build-apks.sh` checks out pinned commits of `cartwmic/termux-app`,
`cartwmic/termux-api`, and upstream Termux:Boot. It signs all three with the
same certificate (`ec1ab3f5e4d261a4c6c5e2979b4af4f8d0071a951761575a2929ce59dcf1c0c1`),
checks package IDs, and uses 1Password for the keystore password at runtime.
`check --app APK --api APK --boot APK` can verify prebuilt artifacts without
building. If Android refuses an update because signatures differ, **stop**;
do not uninstall the Termux family to make installation succeed. Approve any
installation and Play Protect prompts **on-device**.

Launch Termux once and unlock the phone. Choose where **this run** retrieves
SSH keys; the choice is not saved. For Mac retrieval, the script types only
public bootstrap commands via ADB, streams two private keys from 1Password
over USB-forwarded, key-only SSH directly into Termux-private storage, then
has the phone run `chezmoi init --apply` itself:

```bash
python3 termux/bootstrap-phone.py provision --serial "$SERIAL" \
  --key-source mac --start-ui # types pkg install, then deliberately exits PENDING
# Wait for pkg to finish and confirm a shell prompt is visible on the phone.
python3 termux/bootstrap-phone.py provision --serial "$SERIAL" \
  --key-source mac --start-ui --packages-ready
```

The package pause prevents later keystrokes from going to the installer
instead of the shell. `--packages-ready` is your explicit on-device check,
not an automatic Android package-manager claim. If you installed packages and
started key-only sshd manually, rerun without `--start-ui`. After a wipe,
SSH may reject the changed Termux **host** key saved as
`termux-usb-SERIAL` in `~/.cache/dotfiles-termux/known_hosts`. Verify the new
host-key fingerprint on the phone, then remove only that stale cache entry
with `ssh-keygen -R termux-usb-SERIAL -f ~/.cache/dotfiles-termux/known_hosts`.
Do not disable host-key checking globally. For phone-side retrieval instead,
first run the package stage with `--key-source phone --start-ui` (no token
needed). **After** pkg finishes and the shell prompt returns, copy the
service-account token in the 1Password Android app (see SSH key provision
below) and immediately rerun with
`--key-source phone --ready-phone-token --start-ui --packages-ready`.
That path installs proot/op and **retains the token on the phone**. Mac-side
provisioning does not need a phone token. A wrong existing key fingerprint
stops rather than overwriting it.

Install WireGuard, ntfy, and Whisperian from the Play Store; complete any
Google login/biometric/install approvals on-device. Package IDs:
`com.wireguard.android`, `io.heckel.ntfy`, `app.whisperian.client`.

### Router and VPN (preview, stage, cut over)

`router-phone.py inspect` reads only public peer identifiers and DHCP metadata
from `root@10.19.1.1`, using its password from
`op://developer/opnsense/password`. It never prints router private keys or
config.xml. SSH host-key verification must already be established. The current
peer, LAN IP, and MAC are in its output; **do not assume** `.7`/`.88` remain
correct after a previous replacement.

**Wiped same phone:** Reuse its existing `ssh-phone WireGuard` key from
1Password, not a different phone's key. Obtain the server public key and the
current address from `router-phone.py inspect`:

```bash
python3 termux/router-phone.py inspect
python3 termux/wireguard-phone.py prepare --mode restore --serial "$SERIAL" \
  --address CURRENT_WG_IP/32 --server-key SERVER_PUBLIC_KEY
python3 termux/router-phone.py plan --mode restore --mac CURRENT_WIFI_MAC \
  --lan CURRENT_RESERVED_LAN_IP --address CURRENT_WG_IP/32 \
  --public-key CURRENT_PHONE_PUBLIC_KEY
# Review PLAN_PATH, then separately:
python3 termux/router-phone.py apply --plan PLAN_PATH --confirm RESTORE-SSH-PHONE
```

A wipe may change the per-network randomized Wi-Fi MAC and Termux's Android
UID. Read the actual Wi-Fi MAC from Android's connected-network settings.
The restore plan only updates the old reservation's MAC; it refuses a different
WireGuard public key or address. Reconnect Wi-Fi after a DHCP change.

**New hardware replacing `ssh-phone`:** Pick an *unused* candidate WireGuard
`/32` and a home-LAN IP not used by another reservation/lease. The candidate
uses a **new** Mac-generated WireGuard private key. `wireguard-phone.py`
creates a separate `ssh-phone Candidate WireGuard SERIAL` item in 1Password,
then a mode-0600 QR PNG in `~/.cache/dotfiles-termux/wg-import/`; it never
prints the key or writes it into Android shared storage. Repeated preparation
reuses that candidate item instead of silently rotating it.

```bash
python3 termux/wireguard-phone.py prepare --mode replace --serial "$SERIAL" \
  --address NEW_WG_IP/32 --server-key SERVER_PUBLIC_KEY
# Open the QR PNG on the Mac; on the phone WireGuard > + > Scan from QR code.
python3 termux/wireguard-phone.py cleanup --serial "$SERIAL" # after import
python3 termux/router-phone.py plan --mode stage --mac NEW_WIFI_MAC \
  --lan NEW_LAN_IP --address NEW_WG_IP/32 --public-key NEW_PUBLIC_KEY
# Review the exact old and proposed identifiers and saved PLAN_PATH first.
python3 termux/router-phone.py apply --plan PLAN_PATH --confirm STAGE-SSH-PHONE
```

Staging leaves the old peer, reservation, `ssh-phone` alias, and `daily-phone`
untouched. `apply` creates a mode-0600 **router-local** backup, reloads the
WireGuard template **before** configure, restarts DHCP, and checks the new
runtime wg1 peer. A failed service/runtime check reports an incomplete apply;
inspect the router backup rather than blindly retrying a different plan.
Both the old and candidate clients can coexist during testing.

Enable the new tunnel on Android as a split tunnel (`10.19.1.0/24` and
`10.21.1.0/24`, DNS `10.19.1.1`, endpoint `cartwmic.com:61583`). Enable
always-on VPN **without lockdown** on-device. Prove direct candidate SSH and
`ssh macbook` -> visible Herdr (not just installed binaries), then test an
external network when available. To switch the Mac alias after that proof:

```bash
python3 termux/update-phone-alias.py plan --wg NEW_WG_IP --lan NEW_LAN_IP --user NEW_TERMUX_USER
python3 termux/update-phone-alias.py apply --wg NEW_WG_IP --lan NEW_LAN_IP \
  --user NEW_TERMUX_USER --attest-candidate --confirm-alias
ssh -G ssh-phone | grep -E '^(hostname|user) '
python3 termux/router-phone.py plan --mode retire --mac NEW_WIFI_MAC \
  --lan NEW_LAN_IP --address NEW_WG_IP/32 --public-key NEW_PUBLIC_KEY
python3 termux/router-phone.py apply --plan PLAN_PATH --confirm RETIRE-OLD-SSH-PHONE \
  --new-user NEW_TERMUX_USER --attest-candidate --attest-off-lan
python3 termux/router-phone.py inspect # current peer must be the new public key; candidate gone
python3 termux/wireguard-phone.py promote --serial "$SERIAL" \
  --expected-public-key NEW_PUBLIC_KEY --confirm-promote
```

Promotion renames the old 1Password item (kept for rollback), then renames
the candidate item to `ssh-phone WireGuard`. It refuses promotion unless live
router inspection shows the candidate is now the only `ssh-phone` peer; a
future wipe will therefore restore the **current** private key. If a router
apply saved config but service reload failed, inspect its reported backup,
then explicitly run `router-phone.py reconcile --confirm RELOAD-ROUTER-SERVICES`
to reload template/configure/DHCP and check wg1 without rewriting config.xml.

Retirement requires the managed SSH **source and applied live alias** to
point at the candidate; it then removes only the old `cartwmic-ssh-phone`
peer and `ssh-phone` DHCP mapping. If an off-home-network test is impossible,
`--defer-off-lan` is an explicit override in place of `--attest-off-lan`:
report the remote test as **pending**, not passed. Do not retire a lost phone
and assume its shared homelab SSH key is revoked; wipe it or rotate that key
separately. The router-local backup includes secrets; do not copy it into Git.
No script commits or pushes the new public alias values; review and publish
the chezmoi source separately.

### Android completion and checks

1. Launch Termux:Boot once, grant its requested permissions, disable battery
   optimization for Termux/Boot and ntfy as appropriate. Only a **future
   explicit reboot** can prove SSH auto-start; installation alone cannot.
2. In ntfy subscribe to `https://ntfy.internal.cartwmic.com/pi`, grant
   notifications, and send one harmless test. Check Android HTTPS trust and
   DNS both on Wi-Fi and over the WireGuard path. Tap an actual pi notification;
   a Termux session must be named **`macbook`** to focus that SSH/Herdr path.
3. Restore/configure Whisperian's provider/profile/history through supported
   Android/app UI, grant microphone and its keyboard/Accessibility controls.
   App-private data has no proven export/import path on this unrooted phone;
   installing the APK does **not** prove its settings were restored.
4. In the phone's visible Termux terminal run `ssh macbook`, then `herdr`, and
   select the intended workspace/tab/pane. Verify a notification tap returns
   to that pane. Work-laptop access is **interactive `ssh mac-kvm`**, never
   `ssh laptop` as a replacement.

```bash
python3 termux/bootstrap-phone.py verify --serial "$SERIAL"
# Only AFTER on-device checks succeed:
python3 termux/bootstrap-phone.py verify --serial "$SERIAL" --attest-android
python3 -m unittest discover -s termux/tests -v # scripted CLI, no live mutations
```

`verify` checks APK signers, key fingerprints, USB key-only SSH, managed
phone files, and phone-to-Mac Herdr availability; without the attended flag
it deliberately exits nonzero. The flag records an **operator attestation**,
not an automated observation of the Android screen. A live reboot and remote
network test remain separate, deferred checks. The existing Motorola was
previously observed showing this Pi conversation inside Herdr; none of these
scripts wipe or re-run that destructive setup as part of tests.

## Phone-owned profile (manual fallback)

No Mac/ADB config sync. Prerequisites:

1. Install the matching-signed **Termux:API** and **Termux:Boot** Android apps.
   Stock F-Droid plugins cannot share the fork's signing identity.
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
- `ssh mac-kvm` → normal-user macOS shell over NanoKVM USB. SSH terminates as
  `macbridge@10.19.1.223`, using `~/.ssh/homelab`. The address is reserved in
  OPNsense for NanoKVM Ethernet MAC `48:da:35:6f:61:ad`. A PTY is forced and
  multiplexing disabled: one interactive shell, no remote commands, SFTP or
  forwarding. The Mac user bridge must be running (configured to start at login).
- `ssh whonix-gw` / `ssh whonix-ws` → Whonix via `~/.ssh/whonix-homelab`
- Jump handlers live in `~/bin/{zellij,herdr}-jump`. Usage: `<id> [host]`.
  Unset identity (missing host) defaults to `remote`. A present host must be a
  grammar-valid Termux SSH alias in `{remote, cartwmic-server, macbook, laptop}`
  or the script exits without ssh.
- ntfy Click URLs carry a host query (`?host=<alias>`) when the producer stamps
  that alias. Termux session name equals alias: the visible session must be named
  exactly the stamped SSH alias for focus. A miss still foregrounds Termux and
  still jumps over SSH.

Phone `chezmoi apply` owns the jump scripts and the SSH ControlMaster block. It
does not:

- build, sign, or sideload the Termux APK (fork in `termux-app`; session focus on
  `?host=` requires that build)
- set Termux session names — name each visible session exactly the SSH alias
  (`macbook`, `remote`, …)
- set producer identity — each pi machine needs `data.jumpSshHost` in *its*
  `~/.config/chezmoi/chezmoi.yaml`, then apply *there*

Do not scp jump scripts from a Mac as a substitute for phone apply.

## SSH key provision

`05_provision_termux_ssh_keys` runs on **every** `chezmoi apply`. It fast-exits
when both keys already match the expected fingerprints (including Mac-side
USB provision above). With missing keys, the phone-side alternative fetches
from 1Password through `proot-distro` + `op` (no native Termux `op` build).
It refuses mismatched existing keys instead of overwriting them.

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

From a machine with the `personal` profile (needs `Host ssh-phone` in SSH config;
`daily-phone` is the older Z Fold 7):

```bash
scp ssh-phone:.termux/termux.properties dot_termux/termux.properties
scp ssh-phone:bin/zellij-jump bin/executable_zellij-jump
scp ssh-phone:bin/herdr-jump bin/executable_herdr-jump
```
