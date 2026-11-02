#!/bin/sh
# Keep Claude Code transcripts for a year: set cleanupPeriodDays in ~/.claude/settings.json (default 30).
# qmd-export prunes a session's copy once its source is gone, so this is what lets the claude-sessions QMD collection cover
# the same 365 days as the Pi sessions (docs/qmd.md). personal and axon-work-computer only (.chezmoiignore).
#
# ~/.claude/settings.json is not managed by chezmoi (Claude and the helper scripts edit it in place), so only this one key is
# set; every other key is kept. Runs again when this script changes; a later hand edit of the key is left alone until then.
set -eu
log() { printf '[claude_transcript_retention] %s: %s\n' "$1" "$2"; }

days=365
dir="$HOME/.claude"
settings="$dir/settings.json"
if [ ! -d "$dir" ]; then
  log INFO "$dir does not exist (Claude Code not used here): nothing to set"
  exit 0
fi
command -v python3 >/dev/null 2>&1 || { log ERROR "python3 is needed to edit $settings"; exit 1; }

python3 -I - "$settings" "$days" <<'EOF'
import json, os, sys, tempfile
path, days = sys.argv[1], int(sys.argv[2])
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
if not isinstance(data, dict):
    sys.exit("[claude_transcript_retention] ERROR: %s is not a JSON object; not touching it" % path)
if data.get("cleanupPeriodDays") == days:
    print("[claude_transcript_retention] INFO: cleanupPeriodDays is already %d" % days)
    sys.exit(0)
old = data.get("cleanupPeriodDays", "unset (30)")
data["cleanupPeriodDays"] = days
mode = os.stat(path).st_mode & 0o777 if os.path.exists(path) else 0o600
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".settings.json.")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.chmod(tmp, mode)
    os.replace(tmp, path)
except BaseException:
    os.unlink(tmp)
    raise
print("[claude_transcript_retention] INFO: cleanupPeriodDays %s -> %d in %s" % (old, days, path))
EOF
