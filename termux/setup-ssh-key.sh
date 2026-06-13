#!/data/data/com.termux/files/usr/bin/bash
#
# setup-ssh-key.sh — fetch a shared SSH private key from 1Password into
# Termux's ~/.ssh so you can ssh out from the phone with native openssh.
#
# Design (matches the Mac/agent-harness setup):
#   - `op` does not run natively on Termux (glibc vs Android bionic), so we
#     run it inside a proot-distro Debian guest *only to fetch the key*.
#   - Headless 1Password auth uses a service-account token (ops_...), read
#     from the same file the rest of the harness uses:
#       ~/.config/agent-harness/op-service-token
#   - The key is written straight into Termux ~/.ssh via a proot bind mount,
#     then you ssh from bare Termux. proot stays a thin fetch tool.
#
# Idempotent: re-running re-installs nothing already present and re-pulls
# the key.
#
# Override anything via env:
#   OP_SSH_KEY_REF   op:// reference to the PRIVATE key field
#   OP_TOKEN_FILE    path to the ops_... service-account token file
#   KEY_PATH         destination private key path in Termux
#   DISTRO           proot-distro alias (default: debian)
#   OP_VERSION       1Password CLI version to install in the guest
#   OP_ARCH          op build arch (default: arm64)

set -euo pipefail

# SSH_KEY item in 1Password: append ?ssh-format=openssh so op returns native
# OpenSSH format (the default PKCS#8 'BEGIN PRIVATE KEY' is flaky for ed25519).
OP_SSH_KEY_REF="${OP_SSH_KEY_REF:-op://developer/cartwmic-homelab ssh key/private key?ssh-format=openssh}"
OP_TOKEN_FILE="${OP_TOKEN_FILE:-$HOME/.config/agent-harness/op-service-token}"
KEY_PATH="${KEY_PATH:-$HOME/.ssh/id_ed25519}"
DISTRO="${DISTRO:-debian}"
OP_VERSION="${OP_VERSION:-2.31.1}"   # bump as needed; https://app-updates.agilebits.com/product_history/CLI2
OP_ARCH="${OP_ARCH:-arm64}"

log()  { printf '[setup-ssh-key] %s\n' "$1"; }
die()  { printf '[setup-ssh-key] ERROR: %s\n' "$1" >&2; exit 1; }

# --- preconditions ---------------------------------------------------------

[ -r "$OP_TOKEN_FILE" ] || die "service-account token file not found/readable: $OP_TOKEN_FILE
  Create it from the value of your 'ops_...' token, e.g.:
    mkdir -p \"\$(dirname \"$OP_TOKEN_FILE\")\" && chmod 700 \"\$(dirname \"$OP_TOKEN_FILE\")\"
    printf '%s' 'ops_...' > \"$OP_TOKEN_FILE\" && chmod 600 \"$OP_TOKEN_FILE\""

case "$(cat "$OP_TOKEN_FILE")" in
  ops_*) ;;
  *) die "token file does not contain an 'ops_...' service-account token: $OP_TOKEN_FILE" ;;
esac

# --- ensure Termux deps (native openssh + proot-distro) --------------------

need_pkg() { command -v "$1" >/dev/null 2>&1; }

if ! need_pkg ssh || ! need_pkg ssh-keygen; then
  log "installing openssh"
  pkg install -y openssh
fi
if ! need_pkg proot-distro; then
  log "installing proot-distro"
  pkg install -y proot-distro
fi

# --- ensure the Debian guest exists ----------------------------------------

if ! proot-distro list --installed 2>/dev/null | grep -qw "$DISTRO"; then
  log "installing proot-distro guest: $DISTRO"
  proot-distro install "$DISTRO"
fi

# --- ensure `op` is installed inside the guest -----------------------------

GUEST_OP="/usr/local/bin/op"
if ! proot-distro login "$DISTRO" -- bash -lc 'command -v op >/dev/null 2>&1'; then
  log "installing 1Password CLI v$OP_VERSION ($OP_ARCH) inside $DISTRO"
  proot-distro login "$DISTRO" -- env OP_VERSION="$OP_VERSION" OP_ARCH="$OP_ARCH" bash -lc '
    set -eu
    apt-get update -qq
    apt-get install -y -qq curl unzip >/dev/null
    url="https://cache.agilebits.com/dist/1P/op2/pkg/v${OP_VERSION}/op_linux_${OP_ARCH}_v${OP_VERSION}.zip"
    tmp=$(mktemp -d)
    curl -fsSL "$url" -o "$tmp/op.zip"
    unzip -oq "$tmp/op.zip" op -d /usr/local/bin
    chmod 0755 /usr/local/bin/op
    rm -rf "$tmp"
    op --version
  '
fi

# --- fetch the key ----------------------------------------------------------

mkdir -p "$(dirname "$KEY_PATH")"
chmod 700 "$(dirname "$KEY_PATH")"

log "fetching private key from 1Password: $OP_SSH_KEY_REF"

# Bind Termux ~/.ssh and the token file into the guest. The token is passed
# via a read-only bind (not argv) so it never appears in `ps`. The op://
# reference (not secret) is passed via env.
SSH_DIR="$(cd "$(dirname "$KEY_PATH")" && pwd)"
KEY_BASE="$(basename "$KEY_PATH")"

proot-distro login "$DISTRO" \
  --bind "$SSH_DIR:/mnt/ssh" \
  --bind "$OP_TOKEN_FILE:/mnt/op-token:ro" \
  -- env OP_REF="$OP_SSH_KEY_REF" KEY_BASE="$KEY_BASE" bash -lc '
    set -eu
    export OP_SERVICE_ACCOUNT_TOKEN="$(cat /mnt/op-token)"
    umask 077
    op read "$OP_REF" > "/mnt/ssh/${KEY_BASE}.tmp"
    [ -s "/mnt/ssh/${KEY_BASE}.tmp" ] || { echo "op read returned empty" >&2; exit 1; }
  '

# --- finalize on the Termux side -------------------------------------------

mv "$KEY_PATH.tmp" "$KEY_PATH"
chmod 600 "$KEY_PATH"

# Derive the public key from the private key (sanity-checks the key too).
if ssh-keygen -y -f "$KEY_PATH" > "$KEY_PATH.pub.tmp" 2>/dev/null; then
  mv "$KEY_PATH.pub.tmp" "$KEY_PATH.pub"
  chmod 644 "$KEY_PATH.pub"
  log "wrote $KEY_PATH (0600) and $KEY_PATH.pub (0644)"
  log "fingerprint: $(ssh-keygen -lf "$KEY_PATH.pub" | awk '{print $2, $4}')"
else
  rm -f "$KEY_PATH.pub.tmp"
  die "fetched key is not a valid OpenSSH private key (passphrase-protected keys: that's expected, ssh will prompt). Verify the op:// reference."
fi

log "done. test with: ssh -T user@host"
