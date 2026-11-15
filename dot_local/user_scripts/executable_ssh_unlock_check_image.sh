#!/bin/sh
# Pre-reboot check of an initramfs image or UKI built with the sd-ssh-unlock hook (see dot_local/share/initramfs-ssh-unlock).
# Usage: ssh_unlock_check_image.sh <image-or-uki>     (run after any kernel update by hand too: it reads the file Limine boots)
# Exits 0 when every piece is in the image; otherwise exits 1 and names the first one missing. Reads the image with lsinitcpio, never boots it.
# Test hooks: SSH_UNLOCK_DIR (the stored key files; default /etc/initcpio/ssh-unlock).
set -eu
log() { printf '[ssh_unlock_check_image] %s: %s\n' "$1" "$2"; }
fail() { log ERROR "missing from the image: $1"; exit 1; }

[ $# -eq 1 ] || { log ERROR "usage: ssh_unlock_check_image.sh <image-or-uki>"; exit 2; }
image=$1
dir=${SSH_UNLOCK_DIR:-/etc/initcpio/ssh-unlock}
as_root=""
[ "$(id -u)" = 0 ] || as_root="sudo -n"

work=$(mktemp -d "${TMPDIR:-/tmp}/ssh-unlock-check.XXXXXX")
trap '$as_root rm -rf "$work"' EXIT
$as_root lsinitcpio -l "$image" > "$work/list" 2>/dev/null || { log ERROR "cannot list $image"; exit 1; }
(cd "$work" && mkdir root && cd root && $as_root lsinitcpio -x "$image" >/dev/null 2>&1) || { log ERROR "cannot extract $image"; exit 1; }
$as_root chown -R "$(id -u):$(id -g)" "$work"
root=$work/root

has() { grep -qx "$1" "$work/list" || fail "$1"; }
same() { $as_root cmp -s "$1" "$2"; }
has_glob() { grep -q "$1" "$work/list" || fail "$2"; }

# The SSH unlock: network unit and config, server, host key, authorized key, USB controller and network drivers.
has usr/lib/systemd/system/systemd-networkd.service
has usr/lib/systemd/system/ssh-unlock.service
has usr/lib/systemd/system/initrd.target.wants/ssh-unlock.service
has etc/systemd/network/10-ssh-unlock.network
grep -qx 'KeepConfiguration=no' "$root/etc/systemd/network/10-ssh-unlock.network" || fail "KeepConfiguration=no in 10-ssh-unlock.network"
grep -q '^Driver=' "$root/etc/systemd/network/10-ssh-unlock.network" || fail "Driver= match in 10-ssh-unlock.network"
has usr/bin/dropbear
has etc/ssh-unlock/dropbear_ed25519_host_key
same "$root/etc/ssh-unlock/dropbear_ed25519_host_key" "$dir/dropbear_ed25519_host_key" \
  || fail "the stored host key (the image's key differs from $dir/dropbear_ed25519_host_key)"
has root/.ssh/authorized_keys
grep -q '^command="[^"]*systemd-tty-ask-password-agent' "$root/root/.ssh/authorized_keys" || fail "forced command in root/.ssh/authorized_keys"
same "$root/root/.ssh/authorized_keys" "$dir/authorized_keys" \
  || fail "the stored authorized key (the image's differs from $dir/authorized_keys)"
for f in passwd shadow group; do
  grep -q '^systemd-network:' "$root/etc/$f" || fail "systemd-network line in etc/$f"
done
# dwc3-apple binds the Type-C USB controllers; without it the cable has no USB bus in early boot.
has_glob 'usr/lib/modules/.*/dwc3-apple\.ko' "kernel module dwc3-apple"
for m in r8152 r8153_ecm cdc_ether usbnet mii; do
  has_glob "usr/lib/modules/.*/$m\.ko" "kernel module $m"
done

# The pieces that were there before still are: a drop-in or update that dropped one would strand the passphrase prompt.
has usr/bin/systemd-tty-ask-password-agent
has usr/lib/systemd/system/systemd-ask-password-plymouth.service
has usr/lib/systemd/system/omarchy-mac-encrypt.service
has usr/bin/systemd-cryptsetup
has usr/bin/plymouth

# No ordering cycle and no missing user in the new units.
if command -v systemd-analyze >/dev/null 2>&1; then
  systemd-analyze verify --root="$root" ssh-unlock.service systemd-networkd.service >"$work/verify.log" 2>&1 \
    || { cat "$work/verify.log"; log ERROR "systemd-analyze verify failed on ssh-unlock.service or systemd-networkd.service"; exit 1; }
fi
log INFO "ok: $image has the SSH unlock pieces and the original unlock pieces"
