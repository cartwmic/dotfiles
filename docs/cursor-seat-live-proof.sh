#!/bin/sh
# Live proof for Cursor's MCP servers and Shell guard (dotfiles PR "seat-switch/cursor-mcp-guards"). The work coordinator runs it on the work Mac
# after `chezmoi update` has applied ~/.cursor/mcp.json, ~/.cursor/hooks.json and ~/.cursor/hooks/shell_guard.py, with Cursor signed in. Run it from anywhere.
# Four steps, each PASS or FAIL:
#   1. ~/.cursor/mcp.json has the hindsight and shartifacts servers (the key list is printed).
#   2. `cursor-agent mcp list` shows both.
#   3. The guard command installed in ~/.cursor/hooks.json, fed a recorded pkill payload and an ls payload, denies the first and allows the second.
#   4. A real headless cursor-agent is asked to run `pkill -f nosuchproc-seat-proof` and then `echo ok`; its transcript is printed, and the step passes
#      when the transcript carries the guard's refusal ("pkill is refused in agent sessions"). The pattern matches no process, so nothing is killed even if the guard failed.
# It reads ~/.cursor and runs cursor-agent; it changes nothing. Exits 1 if any step FAILs. A person reads the transcript and the note at the end.
set -eu
mcp=$HOME/.cursor/mcp.json
hooks=$HOME/.cursor/hooks.json
fails=0
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; fails=$((fails + 1)); }

echo "== 1. ~/.cursor/mcp.json servers"
if keys=$(jq -c '.mcpServers | keys' "$mcp" 2>&1); then
  echo "$keys"
  if jq -e '.mcpServers | has("hindsight") and has("shartifacts")' "$mcp" >/dev/null; then pass "hindsight and shartifacts are in mcp.json"; else fail "hindsight or shartifacts is missing from mcp.json"; fi
  jq '.mcpServers | {hindsight: .hindsight.url, xthread: .shartifacts.headers["X-Thread"], xorigin: .shartifacts.headers["X-Origin"]}' "$mcp"
else
  echo "$keys"; fail "cannot read $mcp"
fi

echo "== 2. cursor-agent mcp list"
if listing=$(cursor-agent mcp list 2>&1); then
  echo "$listing"
  if echo "$listing" | grep -q hindsight && echo "$listing" | grep -q shartifacts; then pass "cursor-agent lists hindsight and shartifacts"; else fail "cursor-agent does not list both servers"; fi
else
  echo "$listing"; fail "cursor-agent mcp list failed (is Cursor signed in?)"
fi

echo "== 3. the installed guard command, fed recorded payloads"
cmd=$(jq -r '[.hooks.preToolUse[]? | select(.matcher == "Shell" and ((.command // "") | contains("shell_guard.py")))] | .[0].command // empty' "$hooks" 2>/dev/null || true)
if [ -z "$cmd" ]; then
  fail "no Shell guard entry in $hooks"
else
  echo "command: $cmd"
  deny=$(printf '%s' '{"tool_name":"Shell","tool_input":{"command":"pkill -f x","cwd":"/tmp","timeout":30}}' | sh -c "$cmd" || true)
  allow=$(printf '%s' '{"tool_name":"Shell","tool_input":{"command":"ls","cwd":"/tmp","timeout":30}}' | sh -c "$cmd" || true)
  echo "pkill -f x -> $deny"
  echo "ls         -> $allow"
  if echo "$deny" | jq -e '.permission == "deny" and (.user_message | contains("pkill is refused in agent sessions"))' >/dev/null 2>&1; then pass "pkill is denied with the guard's message"; else fail "pkill was not denied"; fi
  if echo "$allow" | jq -e '.permission == "allow"' >/dev/null 2>&1; then pass "ls is allowed"; else fail "ls was not allowed"; fi
fi

echo "== 4. a real headless cursor-agent session"
# --force lets commands run without a prompt; a hook's deny still stops one, which is what this step looks for. --trust skips the workspace prompt.
prompt='Run exactly this shell command: pkill -f nosuchproc-seat-proof . Then run: echo ok . Report what each command returned, in one line each. If a command is refused, say the refusal text word for word.'
if (cd "$tmp" && cursor-agent -p --force --trust "$prompt") >"$tmp/transcript" 2>&1; then :; else echo "(cursor-agent exited non-zero)"; fi
cat "$tmp/transcript"
if grep -q "pkill is refused in agent sessions" "$tmp/transcript"; then pass "the transcript carries the guard's refusal"; else fail "no guard refusal in the transcript (a Cursor approval denial or a model that skipped the command would also show here: read it)"; fi
if grep -qw ok "$tmp/transcript"; then echo "note: the transcript mentions ok (the harmless command ran, or the model repeated the prompt: read it)"; else echo "note: no ok in the transcript: read it, the harmless command may not have run"; fi

cat <<'NOTE'

== For a person to look at (not automated)
The hook answers {"permission":"allow"} for a harmless command. Check whether Cursor still asks for approval on a command you have set to "ask":
in Cursor's settings put a command (for example `git push`) under the commands that need approval, run `cursor-agent` interactively without --force,
ask it to run that command, and see whether the approval prompt still appears. If the allow skips the prompt, the guard should print {} instead of
{"permission":"allow"} (dot_cursor/hooks/executable_shell_guard.py, the ALLOW value): tell the dotfiles owner.
NOTE

if [ "$fails" = 0 ]; then echo "PASS: all four steps"; else echo "FAIL: $fails step(s) failed"; fi
[ "$fails" = 0 ]
