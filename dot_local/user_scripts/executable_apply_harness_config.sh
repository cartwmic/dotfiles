#!/bin/sh

set -eu

SCRIPT_NAME="apply_harness_config"
CANONICAL_ROOT="${AGENT_HARNESS_CANONICAL_ROOT:-$HOME/.local/share/agent-harness/canonical}"
SKILLS_ROOT="$CANONICAL_ROOT/skills"
MCP_FILE="$CANONICAL_ROOT/mcp/servers.json"
GENERATED_ROOT="${AGENT_HARNESS_GENERATED_ROOT:-$HOME/.local/share/agent-harness/generated}"
ADAPTERS_ROOT="${AGENT_HARNESS_ADAPTERS_ROOT:-$HOME/.local/share/agent-harness/adapters}"
EXTERNAL_ROOT="${AGENT_HARNESS_EXTERNAL_ROOT:-$HOME/.local/share/agent-harness/external-skills}"

log() {
  echo "[$SCRIPT_NAME] $1"
}

log_error() {
  echo "[$SCRIPT_NAME] ERROR: $1" >&2
}

require_file() {
  if [ ! -f "$1" ]; then
    log_error "Required file not found: $1"
    exit 1
  fi
}

require_dir() {
  if [ ! -d "$1" ]; then
    log_error "Required directory not found: $1"
    exit 1
  fi
}

ensure_parent() {
  mkdir -p "$(dirname "$1")"
}

resolve_secret() {
  secret_ref="$1"

  if ! command -v op >/dev/null 2>&1; then
    return 1
  fi

  # Prefer a 1Password service-account token so `op` runs fully
  # non-interactive (no biometric / desktop-app prompt). Token is loaded
  # from $OP_SERVICE_ACCOUNT_TOKEN if already exported, otherwise from a
  # local file (default: ~/.config/agent-harness/op-service-token).
  # Override the path with $AGENT_HARNESS_OP_TOKEN_FILE.
  if [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
    token_file="${AGENT_HARNESS_OP_TOKEN_FILE:-$HOME/.config/agent-harness/op-service-token}"
    if [ -r "$token_file" ]; then
      OP_SERVICE_ACCOUNT_TOKEN=$(cat "$token_file")
      export OP_SERVICE_ACCOUNT_TOKEN
    fi
  fi

  op read "$secret_ref" --no-newline 2>/dev/null
}

render_harness_mcp_json() {
  harness="$1"
  out_file="$2"
  secrets_file="$ADAPTERS_ROOT/$harness/mcp-secrets.json"

  require_file "$MCP_FILE"
  ensure_parent "$out_file"

  if [ ! -f "$secrets_file" ]; then
    secrets_file=""
  fi

  python3 - "$MCP_FILE" "$secrets_file" "$out_file" <<'PY'
import json
import pathlib
import sys

mcp_file = pathlib.Path(sys.argv[1])
out_file = pathlib.Path(sys.argv[3])

canonical = json.loads(mcp_file.read_text())
out_file.write_text(json.dumps(canonical, indent=2) + "\n")
PY

  if [ -n "$secrets_file" ]; then
    # Extract (placeholder, op_ref) pairs into a variable so the while loop
    # below runs in the *current* shell (a `py | while` pipeline runs the
    # loop in a subshell, which would discard `export` calls before our
    # substitution pass below could see them).
    secrets_pairs=$(python3 - "$secrets_file" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text())
for placeholder, mapping in data.get("substitutions", {}).items():
    if isinstance(mapping, dict) and mapping.get("op"):
        print(f"{placeholder}\t{mapping['op']}")
PY
)
    while IFS='	' read -r placeholder secret_ref; do
      [ -z "$placeholder" ] && continue
      if value=$(resolve_secret "$secret_ref"); then
        export "$placeholder=$value"
      else
        log "1Password secret unavailable for $placeholder from $secret_ref"
      fi
    done <<HEREDOC_END
$secrets_pairs
HEREDOC_END
  fi

  # Inline pass: substitute ${VAR} references anywhere in the resolved JSON
  # with values that op resolution just exported. Harnesses therefore do not
  # depend on env vars being set at session start. If a managed substitution
  # remains unresolved, omit only the affected server.
  if [ "${AGENT_HARNESS_INLINE_SECRETS:-1}" = "1" ]; then
    python3 - "$out_file" "$secrets_file" <<'PY'
import json
import os
import pathlib
import re
import sys

out = pathlib.Path(sys.argv[1])
data = json.loads(out.read_text())
secrets_arg = sys.argv[2]
managed = set()
if secrets_arg:
    secrets = json.loads(pathlib.Path(secrets_arg).read_text())
    managed = set(secrets.get("substitutions", {}))
env_re = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

def substitute(obj):
    if isinstance(obj, str):
        def replace(m):
            val = os.environ.get(m.group(1))
            return val if val is not None else m.group(0)
        return env_re.sub(replace, obj)
    if isinstance(obj, dict):
        return {k: substitute(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute(v) for v in obj]
    return obj

def has_unresolved_managed_placeholder(obj):
    if isinstance(obj, str):
        return any(match.group(1) in managed for match in env_re.finditer(obj))
    if isinstance(obj, dict):
        return any(has_unresolved_managed_placeholder(v) for v in obj.values())
    if isinstance(obj, list):
        return any(has_unresolved_managed_placeholder(v) for v in obj)
    return False

resolved = substitute(data)
servers = resolved.get("mcpServers", {})
for name in list(servers):
    if has_unresolved_managed_placeholder(servers[name]):
        print(f"[apply_harness_config] Skipping {name}: required substitution unavailable")
        del servers[name]

out.write_text(json.dumps(resolved, indent=2) + "\n")
PY
  fi
}

# Link skills from a single source directory into dest_root.
# Only replaces existing symlinks if they point into the same source tree,
# so canonical skills (linked first) win over external ones on name collisions.
_link_skills_from() {
  source_root="$1"
  dest_root="$2"

  [ -d "$source_root" ] || return 0

  find "$source_root" -mindepth 1 -maxdepth 1 -type d | while IFS= read -r skill_dir; do
    if [ ! -f "$skill_dir/SKILL.md" ]; then
      continue
    fi

    skill_name=$(basename "$skill_dir")
    dest_path="$dest_root/$skill_name"

    if [ -L "$dest_path" ]; then
      current_target=$(readlink "$dest_path")
      if [ "$current_target" = "$skill_dir" ]; then
        log "Skill already linked: $dest_path"
        continue
      fi
      # Only replace if existing link points into the same source tree
      case "$current_target" in
        "$source_root"/*)
          rm -f "$dest_path"
          ;;
        *)
          log "Skill $skill_name already linked from another source, skipping"
          continue
          ;;
      esac
    elif [ -e "$dest_path" ]; then
      log "Skipping existing non-symlink skill path: $dest_path"
      continue
    fi

    ln -s "$skill_dir" "$dest_path"
    log "Linked skill: $dest_path -> $skill_dir"
  done
}

link_skill_dirs() {
  dest_root="$1"

  require_dir "$SKILLS_ROOT"
  mkdir -p "$dest_root"

  # Clean stale symlinks pointing into canonical or external skill roots
  find "$dest_root" -mindepth 1 -maxdepth 1 -type l | while IFS= read -r existing_link; do
    link_target=$(readlink "$existing_link")
    case "$link_target" in
      "$SKILLS_ROOT"/*|"$EXTERNAL_ROOT"/*)
        if [ ! -d "$link_target" ]; then
          rm -f "$existing_link"
          log "Removed stale skill link: $existing_link"
        fi
        ;;
    esac
  done

  # Link canonical skills first (they take precedence)
  _link_skills_from "$SKILLS_ROOT" "$dest_root"

  # Link external skills from each cloned repo
  if [ -d "$EXTERNAL_ROOT" ]; then
    find "$EXTERNAL_ROOT" -mindepth 1 -maxdepth 1 -type d | while IFS= read -r repo_dir; do
      _link_skills_from "$repo_dir" "$dest_root"
    done
  fi
}

render_claude_mcp_commands() {
  mcp_json="$1"
  out_file="$2"

  require_file "$mcp_json"
  ensure_parent "$out_file"

  python3 - "$mcp_json" "$out_file" <<'PY'
import json
import pathlib
import re
import sys

mcp_file = pathlib.Path(sys.argv[1])
out_file = pathlib.Path(sys.argv[2])
data = json.loads(mcp_file.read_text())
servers = data.get("mcpServers", {})

env_ref_re = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

lines = [
    "#!/bin/sh",
    "set -eu",
    "",
    "log() {",
    "  echo \"[apply_harness_config:claude:mcp] $1\"",
    "}",
    "",
    "if ! command -v \"${CLAUDE_BIN:-claude}\" >/dev/null 2>&1; then",
    "  log \"claude CLI not found; generated commands only\"",
    "  exit 0",
    "fi",
    "",
]

for name, cfg in servers.items():
    if "command" in cfg:
        args = " ".join([json.dumps(a) for a in cfg.get("args", [])])
        cmd = json.dumps(cfg["command"])
        # The server's own environment is stored with -e after the name (a prefix `env K=V claude ...` would only
        # reach the registering process).
        env_opts = "".join(f" -e {json.dumps(key + '=' + str(value))}" for key, value in cfg.get("env", {}).items())
        lines.append(
            f"\"${{CLAUDE_BIN:-claude}}\" mcp add -s user {json.dumps(name)}{env_opts} -- {cmd}"
            + (f" {args}" if args else "")
            + " || true"
        )
    elif cfg.get("type") == "http" or "url" in cfg:
        parts = [f"\"${{CLAUDE_BIN:-claude}}\" mcp add -s user --transport http {json.dumps(name)} {json.dumps(cfg['url'])}"]
        required_env_names = []
        for header_name, header_value in cfg.get("headers", {}).items():
            if isinstance(header_value, str):
                # Track every ${VAR} reference inside the header value so the
                # generated script can guard the registration on those vars
                # being set (e.g. "Bearer ${MCP_MEMORY_API_KEY}" depends on
                # MCP_MEMORY_API_KEY being exported by the apply step).
                refs = env_ref_re.findall(header_value)
                if refs:
                    required_env_names.extend(refs)
            parts.append(f"--header {json.dumps(f'{header_name}: {header_value}')}")
        command = " ".join(parts) + " || true"
        if required_env_names:
            condition = " || ".join([f"[ -z \"${{{env_name}:-}}\" ]" for env_name in required_env_names])
            missing_names = ", ".join(required_env_names)
            lines.append(
                f"if {condition}; then log {json.dumps(f'Skipping {name}: missing required env one of [{missing_names}]')}; "
                f"else {command}; fi"
            )
        else:
            lines.append(command)
    else:
        lines.append(f"log {json.dumps(f'Skipping unsupported MCP server shape for {name}')}")

out_file.write_text("\n".join(lines) + "\n")
out_file.chmod(0o755)
PY
}

apply_claude() {
  log "Applying Claude adapters"
  link_skill_dirs "$HOME/.claude/skills"

  resolved_mcp="$GENERATED_ROOT/claude/mcp-resolved.json"
  claude_script="$GENERATED_ROOT/claude/setup-mcp.sh"
  render_harness_mcp_json "claude" "$resolved_mcp"
  render_claude_mcp_commands "$resolved_mcp" "$claude_script"
  log "Generated Claude MCP script: $claude_script"

  if [ "${AGENT_HARNESS_APPLY_CLAUDE_MCP:-1}" = "1" ]; then
    "$claude_script"
  fi
}

render_codex_mcp_block() {
  mcp_json="$1"
  out_file="$2"

  require_file "$mcp_json"
  ensure_parent "$out_file"

  python3 - "$mcp_json" "$out_file" <<'PY'
import json
import pathlib
import sys

mcp_file = pathlib.Path(sys.argv[1])
out_file = pathlib.Path(sys.argv[2])
data = json.loads(mcp_file.read_text())
servers = data.get("mcpServers", {})

lines = ["# BEGIN CHEZMOI AGENT HARNESS MCP"]
for name, cfg in servers.items():
    if "command" in cfg:
        lines.append(f"[mcp_servers.{name}]")
        lines.append(f"command = {json.dumps(cfg['command'])}")
        if cfg.get("args"):
            args = ", ".join(json.dumps(arg) for arg in cfg["args"])
            lines.append(f"args = [{args}]")
        if cfg.get("env"):
            lines.append("env = { " + ", ".join(f"{k} = {json.dumps(v)}" for k, v in cfg["env"].items()) + " }")
        lines.append("")
    elif cfg.get("type") == "http" or "url" in cfg:
        lines.append(f"[mcp_servers.{name}]")
        lines.append(f"url = {json.dumps(cfg['url'])}")
        if cfg.get("headers"):
            lines.append(
                "http_headers = { "
                + ", ".join(f"{json.dumps(k)} = {json.dumps(v)}" for k, v in cfg["headers"].items())
                + " }"
            )
        lines.append("")
    else:
        lines.append(f"# Skipped {name}: unsupported MCP shape")
        lines.append("")

lines.append("# END CHEZMOI AGENT HARNESS MCP")
out_file.write_text("\n".join(lines) + "\n")
PY
}

merge_codex_config() {
  block_file="$1"
  config_file="$HOME/.codex/config.toml"

  mkdir -p "$HOME/.codex"

  python3 - "$block_file" "$config_file" <<'PY'
import pathlib
import sys

block = pathlib.Path(sys.argv[1]).read_text().rstrip() + "\n"
config_path = pathlib.Path(sys.argv[2])
begin = "# BEGIN CHEZMOI AGENT HARNESS MCP"
end = "# END CHEZMOI AGENT HARNESS MCP"

if config_path.exists():
    content = config_path.read_text()
else:
    content = ""

if begin in content and end in content:
    start = content.index(begin)
    finish = content.index(end, start) + len(end)
    new_content = content[:start].rstrip()
    if new_content:
        new_content += "\n\n"
    new_content += block
    suffix = content[finish:].lstrip("\n")
    if suffix:
        new_content += "\n" + suffix
else:
    new_content = content.rstrip()
    if new_content:
        new_content += "\n\n"
    new_content += block

config_path.write_text(new_content.rstrip() + "\n")
PY
}

apply_codex() {
  log "Applying Codex adapters"
  link_skill_dirs "$HOME/.codex/skills"

  resolved_mcp="$GENERATED_ROOT/codex/mcp-resolved.json"
  codex_block="$GENERATED_ROOT/codex/mcp.toml"
  render_harness_mcp_json "codex" "$resolved_mcp"
  render_codex_mcp_block "$resolved_mcp" "$codex_block"
  merge_codex_config "$codex_block"
  log "Updated Codex config: $HOME/.codex/config.toml"
}

# Pi only: wrap the local MCP servers named in servers.list in the lazy stand-in, so a
# session does not start them until a call needs them. Each server is refreshed once here
# (the stand-in's --refresh mode saves its handshake and tool list). A failed refresh is
# logged. The entry is still wrapped when a saved list with tools exists (an earlier state
# copy or the shipped seed); with none, it is left as rendered so Pi starts the server at
# session start instead of showing no tools. Claude and Codex rendering do not call this.
# Roll back by removing the name from servers.list.
wrap_pi_lazy_servers() {
  resolved_json="$1"
  lazy_list="${PI_MCP_LAZY_LIST:-$HOME/.local/share/pi-mcp-lazy/servers.list}"
  lazy_bin="${PI_MCP_LAZY_BIN:-$HOME/.local/bin/pi-mcp-lazy}"
  lazy_idle="${PI_MCP_LAZY_IDLE:-600}"

  if [ ! -f "$lazy_list" ]; then
    log "pi-mcp-lazy: no server list at $lazy_list; Pi MCP entries stay as rendered"
    return 0
  fi
  if [ ! -x "$lazy_bin" ]; then
    log_error "pi-mcp-lazy: stand-in not executable at $lazy_bin; Pi MCP entries stay as rendered"
    return 0
  fi

  python3 - "$resolved_json" "$lazy_list" "$lazy_bin" "$lazy_idle" <<'PY'
import json
import os
import pathlib
import subprocess
import sys

path, list_file, binp, idle = sys.argv[1:5]

def run_bounded(argv, env, cwd, limit):
    """Run argv; on timeout ask it to stop (SIGTERM, so the stand-in stops the server it started) before killing it."""
    p = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env=env, cwd=cwd)
    try:
        _, err = p.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        p.terminate()
        try:
            _, err = p.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
            _, err = p.communicate()
        return False, "timed out after %ss" % limit
    return p.returncode == 0, (err or "").strip()[-600:]
data = json.loads(pathlib.Path(path).read_text())
servers = data.get("mcpServers", {})
names = [l.strip() for l in pathlib.Path(list_file).read_text().splitlines()
         if l.strip() and not l.strip().startswith("#")]

def say(msg):
    print(f"[apply_harness_config] pi-mcp-lazy: {msg}")

for name in names:
    cfg = servers.get(name)
    if not isinstance(cfg, dict) or "command" not in cfg:
        say(f"{name} is not a local (command) server in this profile; skipped")
        continue
    args = [str(a) for a in cfg.get("args", [])]
    env = dict(os.environ)
    env.update({str(k): str(v) for k, v in (cfg.get("env") or {}).items()})
    cwd = cfg.get("cwd") or None
    # Arguments and env values can carry a resolved secret (a server URL); keep them out of the log.
    hidden = [a for a in args if a.startswith(("http://", "https://"))]
    hidden += [str(v) for v in (cfg.get("env") or {}).values() if len(str(v)) > 3]
    try:
        ok, tail = run_bounded([binp, "--refresh", name, "--", cfg["command"], *args], env, cwd, 240)
    except Exception as e:  # never abort the apply for the other entries
        ok, tail = False, str(e)
    for s in hidden:
        tail = tail.replace(s, "<hidden>")
    if ok:
        say(f"refreshed {name}")
    else:
        say(f"refresh of {name} failed: {tail}")
    try:
        usable, _ = run_bounded([binp, "--check", name, "--", cfg["command"], *args], env, cwd, 30)
    except Exception:
        usable = False
    if not usable:
        say(f"{name} has no saved tool list; left as rendered, so Pi starts it at session start")
        continue
    wrapped = {"command": binp, "args": [name, idle, "--", cfg["command"], *args]}
    wrapped.update({k: v for k, v in cfg.items() if k not in ("command", "args")})
    servers[name] = wrapped

pathlib.Path(path).write_text(json.dumps(data, indent=2) + "\n")
PY
}

# Merge the rendered servers into Pi's mcp.json. Names this script wrote on an earlier apply
# (recorded in $3, plus the retired names below that predate that record) and that are no longer
# rendered are pruned; entries it never wrote are kept.
merge_pi_mcp() {
  harness_json="$1"
  target_json="$2"
  managed_json="$3"

  python3 - "$harness_json" "$target_json" "$managed_json" <<'PY'
import json
import pathlib
import sys

harness_path = pathlib.Path(sys.argv[1])
target_path = pathlib.Path(sys.argv[2])
managed_path = pathlib.Path(sys.argv[3])

# Harness-managed before the managed-names record existed, since removed from canonical.
RETIRED = {"furi", "automation-mcp"}

harness = json.loads(harness_path.read_text())
harness_servers = harness.get("mcpServers", {})

if target_path.exists():
    existing = json.loads(target_path.read_text())
else:
    existing = {"mcpServers": {}}

existing_servers = existing.get("mcpServers", {})

previous = set(RETIRED)
if managed_path.exists():
    try:
        previous |= set(json.loads(managed_path.read_text()))
    except (ValueError, TypeError):
        pass  # unreadable record: prune only the retired names

stale = sorted(n for n in previous if n in existing_servers and n not in harness_servers)
kept = {n: c for n, c in existing_servers.items() if n not in stale}

# Harness-managed servers overwrite their keys; manual additions are preserved
merged_servers = {**kept, **harness_servers}
result = {**existing, "mcpServers": merged_servers}

target_path.write_text(json.dumps(result, indent=2) + "\n")
managed_path.parent.mkdir(parents=True, exist_ok=True)
managed_path.write_text(json.dumps(sorted(harness_servers)) + "\n")
for name in stale:
    print(f"[apply_harness_config] Pruned Pi MCP server no longer in canonical: {name}")
PY
}

apply_pi() {
  log "Applying Pi adapters"
  link_skill_dirs "$HOME/.pi/agent/skills"

  resolved_mcp="$GENERATED_ROOT/pi/mcp-resolved.json"
  pi_mcp_json="$HOME/.pi/agent/mcp.json"
  render_harness_mcp_json "pi" "$resolved_mcp"
  wrap_pi_lazy_servers "$resolved_mcp"
  ensure_parent "$pi_mcp_json"
  merge_pi_mcp "$resolved_mcp" "$pi_mcp_json" "$GENERATED_ROOT/pi/mcp-managed.json"
  log "Updated Pi MCP config: $pi_mcp_json"
}

apply_agents_shared() {
  log "Applying shared ~/.agents/skills"
  link_skill_dirs "$HOME/.agents/skills"
}

apply_all() {
  apply_agents_shared
  apply_claude
  apply_codex
  apply_pi
}

main() {
  if [ "$#" -eq 0 ]; then
    set -- all
  fi

  case "$1" in
    all)
      apply_all
      ;;
    *)
      for harness in "$@"; do
        case "$harness" in
          claude)
            apply_claude
            ;;
          codex)
            apply_codex
            ;;
          pi)
            apply_pi
            ;;
          *)
            log_error "Unsupported harness: $harness"
            exit 1
            ;;
        esac
      done
      ;;
  esac
}

main "$@"
