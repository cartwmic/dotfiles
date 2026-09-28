#!/usr/bin/env python3
"""Render the work-profile Learnings extension in a disposable chezmoi HOME."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILE = "axon-work-computer"
EXTENSION_SOURCE = ROOT / "dot_pi/private_agent/extensions/learnings-monitor"
HINDSIGHT_SOURCE = ROOT / "dot_pi/private_agent/extensions/hindsight/config.json.tmpl"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def invoke(command: list[str], env: dict[str, str]) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()[-30:]
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            + "\n".join(detail)
        )
    return result.stdout


def main() -> int:
    chezmoi = shutil.which("chezmoi")
    require(chezmoi is not None, "chezmoi is required for the isolated profile proof")
    require((EXTENSION_SOURCE / "index.ts").is_file(), "worktree Learnings extension entry point is missing")
    require(HINDSIGHT_SOURCE.is_file(), "worktree Hindsight profile template is missing")

    with tempfile.TemporaryDirectory(prefix="learnings-monitor-work-profile-") as temporary:
        root = Path(temporary).resolve()
        home = root / "home"
        config_home = root / "config"
        cache = root / "cache"
        destination_extension = home / ".pi/agent/extensions/learnings-monitor"
        destination_hindsight = home / ".pi/agent/extensions/hindsight/config.json"
        for directory in (
            home,
            config_home,
            cache,
            destination_extension,
            destination_hindsight.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)

        real_home = Path.home().resolve()
        require(
            not home.is_relative_to(real_home) and not real_home.is_relative_to(home),
            "temporary destination unexpectedly overlaps the real HOME",
        )

        config_file = config_home / "chezmoi.yaml"
        config_file.write_text(f"data:\n  profile: {PROFILE}\n", encoding="utf-8")
        config_file.chmod(0o600)
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(config_home),
            "XDG_CACHE_HOME": str(cache),
            "NO_COLOR": "1",
        }
        base = [
            chezmoi,
            "--source", str(ROOT),
            "--destination", str(home),
            "--config", str(config_file),
            "--cache", str(cache),
            "--persistent-state", str(root / "state.json"),
            "--no-tty",
            "--color=false",
            "--refresh-externals=never",
        ]

        # Limit materialization to the extension and its existing profile-rendered
        # Hindsight config. No bootstrap or other machine setup scripts can run.
        invoke(base + [
            "apply",
            "--verbose",
            str(destination_extension),
            str(destination_hindsight),
        ], env)

        managed_output = invoke(base + [
            "managed",
            "--include=files",
            "--path-style=absolute",
            str(destination_extension),
        ], env)
        managed_files = {
            Path(line.strip()).resolve()
            for line in managed_output.splitlines()
            if line.strip()
        }
        rendered_entry = (destination_extension / "index.ts").resolve()
        require(rendered_entry in managed_files,
                "the work-profile destination does not manage learnings-monitor/index.ts")
        required_files = {
            destination_extension / "README.md",
            destination_extension / "core/index.mjs",
            destination_extension / "runtime.mjs",
        }
        require(required_files <= managed_files,
                f"the work-profile extension is missing managed files: {sorted(map(str, required_files - managed_files))}")
        for target in managed_files:
            source = EXTENSION_SOURCE / target.relative_to(destination_extension.resolve())
            require(source.is_file(), f"managed extension file has no source in this worktree: {source}")
            require(target.is_file(), f"managed extension file was not rendered: {target}")
            require(target.read_bytes() == source.read_bytes(),
                    f"rendered extension content differs from this worktree source: {target.name}")

        mapped_source = invoke(base + ["source-path", str(rendered_entry)], env).strip()
        require(Path(mapped_source).resolve() == (EXTENSION_SOURCE / "index.ts").resolve(),
                f"unexpected chezmoi source mapping for {rendered_entry}: {mapped_source}")

        config = json.loads(destination_hindsight.read_text(encoding="utf-8"))
        require(config.get("bankId") == "work",
                f"work profile selected {config.get('bankId')!r}, expected 'work'")
        require(config.get("bankId") != "cartwmic",
                "work profile must not select the personal Hindsight bank")
        hindsight_source_path = invoke(base + ["source-path", str(destination_hindsight)], env).strip()
        require(Path(hindsight_source_path).resolve() == HINDSIGHT_SOURCE.resolve(),
                f"unexpected Hindsight config source mapping: {hindsight_source_path}")

        print(json.dumps({
            "status": "PASS",
            "profile": PROFILE,
            "destination": "isolated temporary HOME (removed at exit)",
            "extensionTarget": "~/.pi/agent/extensions/learnings-monitor",
            "managedExtensionFiles": len(managed_files),
            "hindsightConfigTarget": "~/.pi/agent/extensions/hindsight/config.json",
            "hindsightBank": config["bankId"],
            "personalBankSelected": False,
            "liveApply": False,
        }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"status": "FAIL", "failure": f"{type(error).__name__}: {error}"}, indent=2), file=sys.stderr)
        raise SystemExit(1)
