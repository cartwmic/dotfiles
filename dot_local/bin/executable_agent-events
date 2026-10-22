#!/bin/sh
# Run agent-events: build | sessions | session REF | tools | events | projects | show REF | sql | export | status | run (the LaunchAgent tick)
set -eu

case "$0" in
  /*) script_path=$0 ;;
  */*) script_path="$(pwd)/$0" ;;
  *) script_path=$(command -v "$0") ;;
esac
script_dir=$(dirname "$script_path")
implementation=${AGENT_EVENTS_IMPLEMENTATION:-}
if [ -z "$implementation" ]; then
  implementation="$script_dir/../share/agent-events/agent_events.py"
  if [ ! -f "$implementation" ]; then
    implementation="${HOME:?HOME is not set}/.local/share/agent-events/agent_events.py"
  fi
fi
if [ ! -f "$implementation" ]; then
  printf '%s\n' 'agent-events: implementation not found under ~/.local/share/agent-events' >&2
  exit 1
fi

python_binary=${AGENT_EVENTS_PYTHON:-}
if [ -z "$python_binary" ] && python3 -c 'import tomllib' >/dev/null 2>&1; then
  python_binary=python3
fi
mise_python="${HOME:-}/.local/share/mise/shims/python3"
if [ -z "$python_binary" ] && [ -x "$mise_python" ] && "$mise_python" -c 'import tomllib' >/dev/null 2>&1; then
  python_binary=$mise_python
fi
if [ -z "$python_binary" ]; then
  printf '%s\n' 'agent-events: Python 3.11+ is required (set AGENT_EVENTS_PYTHON if it is not on PATH)' >&2
  exit 1
fi

exec "$python_binary" "$implementation" "$@"
