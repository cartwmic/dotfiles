#!/bin/bash
# omarchy-remote-unlock.sh: type the Omarchy disk passphrase into its early-boot SSH prompt from another machine.
#
# An operations script, not applied by chezmoi (scripts/ is in .chezmoiignore). It runs on mac-mini (macOS
# /bin/bash 3.2), because the agents run on Omarchy and Omarchy is down while it waits for the passphrase.
# The early-boot SSH server (dot_local/share/initramfs-ssh-unlock/) accepts only the homelab key and runs
# only `systemd-tty-ask-password-agent --watch`, so one line typed into the session answers the prompt.
#
# Waiter (default mode):
#   op read ... | ssh mac-mini '~/bin/omarchy-remote-unlock.sh [--host H] [--timeout S]'
# reads ONE line from stdin (never from arguments, environment or a file), detaches (stdin, stdout and stderr
# closed or sent to the log, own process group, SIGHUP ignored) so the ssh that started it returns at once,
# and keeps the passphrase in memory only. It retries `ssh` to --host every --interval seconds until --timeout.
# The first connection that gets in (key checked against the one pinned for --alias) gets the line, once.
# After that write it never sends again, even if the connection drops. It then exits.
#
# Pin mode (no stdin): --pin-hostkey <file-or-line> writes the early-boot host key into known_hosts under
# --alias. Run it after the dotfiles apply on Omarchy and before the reboot. The normal Omarchy sshd has a
# different key, so it fails the key check and gets nothing.
#
# The log holds timestamps and outcomes only, never the passphrase.
set -eu

NAME=omarchy-remote-unlock
HOST=10.19.1.75
ALIAS=omarchy-unlock
TIMEOUT=1200
LOG="$HOME/Library/Logs/omarchy-remote-unlock.log"
SSH_USER=root
PORT=22
IDENTITY="$HOME/.ssh/homelab"
KNOWN_HOSTS="$HOME/.ssh/known_hosts"
INTERVAL=5
PROMPT_DELAY=3
LINGER=10
PIN=""
RUN=$$

usage() {
  cat >&2 <<EOF
usage: omarchy-remote-unlock.sh [options] < passphrase-line
       omarchy-remote-unlock.sh --pin-hostkey <pubkey-file-or-line> [--alias A] [--known-hosts F]

  --host H           early-boot address (default $HOST)
  --alias A          known_hosts name for the early-boot key (default $ALIAS)
  --timeout S        give up waiting after S seconds (default $TIMEOUT)
  --log F            log file (default $LOG)
  --user U           ssh user (default $SSH_USER)
  --port P           ssh port (default $PORT)
  --identity F       ssh key (default $IDENTITY)
  --known-hosts F    known_hosts file (default $KNOWN_HOSTS)
  --interval S       seconds between connection tries (default $INTERVAL)
  --prompt-delay S   seconds between the login and the passphrase, so the prompt is up first (default $PROMPT_DELAY)
  --linger S         seconds to keep the session open after the passphrase (default $LINGER)
  --pin-hostkey K    pin the early-boot host key (a file, or the key line) and exit; reads no stdin
EOF
}

die() {
  echo "[$NAME] ERROR: $*" >&2
  exit 2
}

# One log line: UTC time, level, run id (the pid of the command that started it), message. stdout is the log.
log() {
  printf '%s [%s] %s: run=%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$NAME" "$1" "$RUN" "$2"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --host|--alias|--timeout|--log|--user|--port|--identity|--known-hosts|--interval|--prompt-delay|--linger|--pin-hostkey)
      [ $# -ge 2 ] || die "$1 needs a value"
      case "$1" in
        --host) HOST=$2 ;;
        --alias) ALIAS=$2 ;;
        --timeout) TIMEOUT=$2 ;;
        --log) LOG=$2 ;;
        --user) SSH_USER=$2 ;;
        --port) PORT=$2 ;;
        --identity) IDENTITY=$2 ;;
        --known-hosts) KNOWN_HOSTS=$2 ;;
        --interval) INTERVAL=$2 ;;
        --prompt-delay) PROMPT_DELAY=$2 ;;
        --linger) LINGER=$2 ;;
        --pin-hostkey) PIN=$2 ;;
      esac
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) usage; die "unknown argument: $1" ;;
  esac
done

case "$TIMEOUT" in ''|*[!0-9]*) die "--timeout must be whole seconds" ;; esac

# Write the early-boot host key into known_hosts as `<alias> <type> <key>`, replacing any older line for the alias.
pin_hostkey() {
  local source=$1 text key dir tmp
  if [ -f "$source" ]; then text=$(cat "$source"); else text=$source; fi
  # The first line that looks like a public key; this also accepts the output of `dropbearkey -y`.
  key=$(printf '%s\n' "$text" | sed -n -E 's#^((ssh-[a-z0-9]+|ecdsa-sha2-[a-z0-9]+) [A-Za-z0-9+/=]+).*$#\1#p' | head -n 1)
  [ -n "$key" ] || die "no public key line (like 'ssh-ed25519 AAAA...') in: $source"
  dir=$(dirname "$KNOWN_HOSTS")
  mkdir -p "$dir"
  tmp=$(mktemp "$dir/.known_hosts.XXXXXX")
  {
    if [ -f "$KNOWN_HOSTS" ]; then awk -v alias="$ALIAS" '$1 != alias' "$KNOWN_HOSTS"; fi
    printf '%s %s\n' "$ALIAS" "$key"
  } > "$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$KNOWN_HOSTS"
  echo "[$NAME] INFO: pinned a ${key%% *} host key for $ALIAS in $KNOWN_HOSTS"
}

if [ -n "$PIN" ]; then
  pin_hostkey "$PIN"
  exit 0
fi

# ---- waiter ----

[ ! -t 0 ] || die "pipe the passphrase in on stdin (one line); it is never taken from arguments, the environment or a file"
IFS= read -r PASS || [ -n "$PASS" ] || die "no passphrase on stdin"
[ -n "$PASS" ] || die "the passphrase line is empty"
exec 0</dev/null

command -v ssh >/dev/null 2>&1 || die "ssh is not on PATH"
[ -r "$IDENTITY" ] || die "ssh key not readable: $IDENTITY"
ssh-keygen -F "$ALIAS" -f "$KNOWN_HOSTS" >/dev/null 2>&1 || die "no host key pinned for '$ALIAS' in $KNOWN_HOSTS; run --pin-hostkey first"
mkdir -p "$(dirname "$LOG")"

# Runs only in the detached waiter, which owns $tmp and $pid (it is the EXIT trap of wait_and_send).
# shellcheck disable=SC2329
cleanup() {
  [ -z "${pid:-}" ] || kill "$pid" 2>/dev/null || true
  [ -z "${tmp:-}" ] || rm -rf "$tmp"
}

wait_and_send() {
  local marker rc="" reason last_reason="" fifo tick
  tmp=$(mktemp -d "${TMPDIR:-/tmp}/$NAME.XXXXXX")
  marker=$tmp/up
  fifo=$tmp/in
  mkfifo "$fifo"
  pid=""
  trap cleanup EXIT
  trap 'log WARN "stopped by signal"; exit 143' TERM INT

  log INFO "waiting for $SSH_USER@$HOST:$PORT (key alias $ALIAS, timeout ${TIMEOUT}s)"
  SECONDS=0
  while :; do
    if [ "$SECONDS" -ge "$TIMEOUT" ]; then
      log ERROR "timeout after ${SECONDS}s, passphrase not sent"
      exit 1
    fi
    rm -f "$marker"
    exec 3<>"$fifo"
    # LocalCommand runs once the login has succeeded (the host key matched and the key was accepted): it drops the marker.
    # The passphrase goes in only after the marker, so a refused key or a wrong host key never receives it.
    ssh -tt -F /dev/null -i "$IDENTITY" -p "$PORT" \
      -o IdentitiesOnly=yes -o HostKeyAlias="$ALIAS" -o StrictHostKeyChecking=yes \
      -o UserKnownHostsFile="$KNOWN_HOSTS" -o GlobalKnownHostsFile=/dev/null \
      -o BatchMode=yes -o ConnectTimeout=5 -o LogLevel=ERROR \
      -o PermitLocalCommand=yes -o "LocalCommand=touch '$marker'" \
      "$SSH_USER@$HOST" <"$fifo" >/dev/null 2>"$tmp/err" &
    pid=$!
    while kill -0 "$pid" 2>/dev/null && [ ! -e "$marker" ]; do sleep 0.1; done

    if [ -e "$marker" ]; then
      log INFO "connected"
      sleep "$PROMPT_DELAY"
      if kill -0 "$pid" 2>/dev/null; then
        printf '%s\n' "$PASS" >&3
        log INFO "passphrase written to the connection (one attempt, not repeated)"
        tick=0
        while kill -0 "$pid" 2>/dev/null && [ "$tick" -lt $((LINGER * 5)) ]; do sleep 0.2; tick=$((tick + 1)); done
        if kill -0 "$pid" 2>/dev/null; then
          kill "$pid" 2>/dev/null || true
          wait "$pid" 2>/dev/null || true
          log INFO "closed the connection after $((tick / 5))s"
        else
          wait "$pid" 2>/dev/null && rc=0 || rc=$?
          log INFO "connection closed by the server after $((tick / 5))s (ssh exit $rc)"
        fi
        pid=""
        exec 3>&-
        return 0
      fi
      wait "$pid" 2>/dev/null || true
      pid=""
      exec 3>&-
      log WARN "connection closed before the passphrase was written; still waiting"
    else
      wait "$pid" 2>/dev/null && rc=0 || rc=$?
      pid=""
      exec 3>&-
      reason=$(tail -n 1 "$tmp/err" 2>/dev/null | cut -c1-200)
      [ -n "$reason" ] || reason="ssh exit $rc"
      if [ "$reason" != "$last_reason" ]; then
        log INFO "not yet: $reason"
        last_reason=$reason
      fi
    fi
    sleep "$INTERVAL"
  done
}

# Detach: own process group, SIGHUP ignored, stdin/stdout/stderr off the caller's session, so the ssh that ran this returns now.
set -m
(
  trap '' HUP
  exec 0</dev/null >>"$LOG" 2>&1
  wait_and_send
) &
echo "[$NAME] INFO: waiting in the background for $HOST (log: $LOG)"
exit 0
