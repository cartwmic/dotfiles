#!/bin/sh
#
# Builds each loop-engine workflow provider under
# ~/.local/share/loop-engine-providers/ and registers it with loop-engine.
#
# Providers are ordinary executables: the engine spawns one fresh process per
# invocation and speaks provider protocol v1 over stdio. Registration is
# machine-local and stores an absolute executable path, so the binary is
# installed to a stable location rather than left in a cargo target directory.

set -eu

LOG_PREFIX="[build_loop_engine_providers]"
PROVIDER_ROOT="$HOME/.local/share/loop-engine-providers"
BIN_DIR="$PROVIDER_ROOT/bin"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/loop-engine-providers"

log() { echo "$LOG_PREFIX $1: $2"; }

if [ ! -d "$PROVIDER_ROOT" ]; then
  log INFO "no provider root at $PROVIDER_ROOT, skipping"
  exit 0
fi

if ! command -v cargo >/dev/null 2>&1; then
  log WARN "cargo not found; skipping provider build"
  exit 0
fi

mkdir -p "$BIN_DIR" "$CACHE_DIR"

built_any=0

for manifest in "$PROVIDER_ROOT"/*/Cargo.toml; do
  [ -e "$manifest" ] || continue
  source_dir=$(dirname "$manifest")
  name=$(basename "$source_dir")

  log INFO "building $name"
  # Build output goes to the cache, never into the chezmoi-managed source tree.
  if ! CARGO_TARGET_DIR="$CACHE_DIR/$name" cargo build \
      --release --manifest-path "$manifest" >/dev/null 2>"$CACHE_DIR/$name.build.log"; then
    log ERROR "build failed for $name; see $CACHE_DIR/$name.build.log"
    continue
  fi

  artifact="$CACHE_DIR/$name/release/$name"
  if [ ! -x "$artifact" ]; then
    log ERROR "expected binary $artifact was not produced"
    continue
  fi

  install -m 0755 "$artifact" "$BIN_DIR/$name"
  log INFO "installed $BIN_DIR/$name"
  built_any=1

  if ! command -v loop-engine >/dev/null 2>&1; then
    log WARN "loop-engine not on PATH; skipping registration of $name"
    continue
  fi

  # The registration timeout bounds ONE provider invocation, and a gate that
  # calls LLM judges spends most of that budget waiting on models rather than
  # computing. The default of 60s kills such a gate mid-judgment and reports it
  # as a provider failure, so registration is made generous here; providers that
  # need less simply finish sooner.
  timeout_seconds=900

  # `provider add` is create-only and rejects an existing handle, so fall back to
  # `provider update` to re-point the registration at the freshly built binary.
  # Registration carries an absolute path; without this a rebuild would leave the
  # catalog pointing at the previous executable.
  if loop-engine --format json provider add "$name" \
      --exec "$BIN_DIR/$name" --working-directory "$BIN_DIR" \
      --timeout "$timeout_seconds" >/dev/null 2>&1; then
    log INFO "registered $name"
  elif loop-engine --format json provider update "$name" \
      --exec "$BIN_DIR/$name" --working-directory "$BIN_DIR" \
      --timeout "$timeout_seconds" >/dev/null 2>&1; then
    log INFO "updated registration $name"
  else
    log WARN "could not register $name; run 'loop-engine provider check $name' to diagnose"
    continue
  fi

  # A registration that cannot describe itself is worse than none: fail loudly
  # here rather than at the first `run create`.
  if ! loop-engine --format json provider check "$name" >/dev/null 2>&1; then
    log WARN "provider check failed for $name; the graph or executable is not usable"
  fi
done

if [ "$built_any" -eq 0 ]; then
  log INFO "no providers built"
fi
