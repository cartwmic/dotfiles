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
secrets_arg = sys.argv[2]
out_file = pathlib.Path(sys.argv[3])

canonical = json.loads(mcp_file.read_text())
resolved = canonical

if secrets_arg:
    secrets = json.loads(pathlib.Path(secrets_arg).read_text())
    for server_name, secret_cfg in secrets.get("mcpServers", {}).items():
        target = resolved.get("mcpServers", {}).get(server_name)
        if not target:
            continue

        for section_name in ("headers", "env"):
            section = secret_cfg.get(section_name, {})
            if not section:
                continue
            target.setdefault(section_name, {})
            for key, cfg in section.items():
                env_name = cfg.get("env") if isinstance(cfg, dict) else None
                if env_name:
                    target[section_name][key] = "${" + env_name + "}"

out_file.write_text(json.dumps(resolved, indent=2) + "\n")
PY

  if [ -n "$secrets_file" ]; then
    python3 - "$secrets_file" <<'PY' | while IFS='	' read -r env_name secret_ref; do
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text())
for _, cfg in data.get("mcpServers", {}).items():
    for section_name in ("headers", "env"):
        for _, mapping in cfg.get(section_name, {}).items():
            if isinstance(mapping, dict) and mapping.get("env") and mapping.get("op"):
                print(f"{mapping['env']}\t{mapping['op']}")
PY
      if value=$(resolve_secret "$secret_ref"); then
        export "$env_name=$value"
      else
        log "1Password secret unavailable for $env_name from $secret_ref"
      fi
    done
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
import sys

mcp_file = pathlib.Path(sys.argv[1])
out_file = pathlib.Path(sys.argv[2])
data = json.loads(mcp_file.read_text())
servers = data.get("mcpServers", {})

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
        env_parts = []
        for key, value in cfg.get("env", {}).items():
            env_parts.append(f"{key}={json.dumps(value)}")
        prefix = ""
        if env_parts:
            prefix = "env " + " ".join(env_parts) + " "
        lines.append(
            f"{prefix}\"${{CLAUDE_BIN:-claude}}\" mcp add -s user {json.dumps(name)} -- {cmd}"
            + (f" {args}" if args else "")
            + " || true"
        )
    elif cfg.get("type") == "http" or "url" in cfg:
        parts = [f"\"${{CLAUDE_BIN:-claude}}\" mcp add --transport http {json.dumps(name)} {json.dumps(cfg['url'])}"]
        required_env_names = []
        for header_name, header_value in cfg.get("headers", {}).items():
            env_name = None
            if isinstance(header_value, str) and header_value.startswith("${") and header_value.endswith("}"):
                env_name = header_value[2:-1]
            if env_name:
                required_env_names.append(env_name)
                rendered = f"{header_name}: ${env_name}"
                parts.append(f"--header {json.dumps(rendered)}")
            else:
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

merge_pi_mcp() {
  harness_json="$1"
  target_json="$2"

  python3 - "$harness_json" "$target_json" <<'PY'
import json
import pathlib
import sys

harness_path = pathlib.Path(sys.argv[1])
target_path = pathlib.Path(sys.argv[2])

harness = json.loads(harness_path.read_text())
harness_servers = harness.get("mcpServers", {})

if target_path.exists():
    existing = json.loads(target_path.read_text())
else:
    existing = {"mcpServers": {}}

existing_servers = existing.get("mcpServers", {})

# Harness-managed servers overwrite their keys; manual additions are preserved
merged_servers = {**existing_servers, **harness_servers}
result = {**existing, "mcpServers": merged_servers}

target_path.write_text(json.dumps(result, indent=2) + "\n")
PY
}

apply_pi() {
  log "Applying Pi adapters"
  link_skill_dirs "$HOME/.pi/agent/skills"

  resolved_mcp="$GENERATED_ROOT/pi/mcp-resolved.json"
  pi_mcp_json="$HOME/.pi/agent/mcp.json"
  render_harness_mcp_json "pi" "$resolved_mcp"
  ensure_parent "$pi_mcp_json"
  merge_pi_mcp "$resolved_mcp" "$pi_mcp_json"
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
