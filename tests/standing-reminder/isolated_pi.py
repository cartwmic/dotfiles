#!/usr/bin/env python3
"""Run Pi scenarios against a private copy with the origin bridge patched."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "dot_local/share/pi-patches/standing-reminder-origin/patch.mjs"
SIBLING_PATCH = ROOT / "dot_local/share/pi-patches/headless-extension-drain/patch.mjs"
HEADLESS_MARKER = "chezmoi-pi-patch:headless-extension-drain v1"
ORIGIN_MARKER = "chezmoi-pi-patch:standing-reminder-origin"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def installed_package(explicit: Path | None) -> Path:
    if explicit:
        package = explicit.expanduser().resolve()
    else:
        pi = os.environ.get("PI_BIN") or shutil.which("pi")
        require(bool(pi), "Pi is not on PATH; supply --source-package or install Pi")
        executable = Path(pi).expanduser().resolve()
        package = executable.parents[2] if executable.name == "cli.js" and executable.parent.name == "bundle" else None
        if package is None or not (package / "package.json").is_file():
            try:
                npm_root = subprocess.run(
                    ["npm", "root", "-g"], check=True, text=True, capture_output=True
                ).stdout.strip()
                package = Path(npm_root) / "@earendil-works/pi-coding-agent"
            except (OSError, subprocess.CalledProcessError) as exc:
                raise RuntimeError(f"cannot locate the installed Pi package: {exc}") from exc
    require((package / "package.json").is_file(), f"Pi package not found at {package}")
    metadata = json.loads((package / "package.json").read_text(encoding="utf-8"))
    require(metadata.get("name") == "@earendil-works/pi-coding-agent", f"unexpected package at {package}")
    return package


def invoke(command: list[str], env: dict[str, str], *, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, env=env, text=True, capture_output=not expect_success)
    if expect_success and result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}")
    if not expect_success and result.returncode == 0:
        raise RuntimeError(f"command unexpectedly succeeded: {' '.join(command)}")
    return result


def patch_env(package: Path, profile: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PI_CHEZMOI_PROFILE"] = profile
    env["PI_STANDING_REMINDER_ORIGIN_PACKAGE"] = str(package)
    return env


def run_patch(node: str, package: Path, profile: str, *, check: bool = False) -> None:
    env = patch_env(package, profile)
    invoke([node, str(PATCH), *( ["--check"] if check else [])], env)


def read_bundle_and_session(package: Path) -> tuple[Path, Path]:
    candidates = [
        path for path in (package / "dist/bundle/chunks").glob("*.js")
        if "async _queueUserInput(text,images,behavior,source){" in path.read_text(encoding="utf-8")
    ]
    require(len(candidates) == 1, f"expected one CLI bundle anchor, found {len(candidates)}")
    session = package / "dist/core/agent-session.js"
    return candidates[0], session


def assert_sibling_patch(package: Path, expected: bool) -> None:
    bundle, session = read_bundle_and_session(package)
    for path in (bundle, session):
        content = path.read_text(encoding="utf-8")
        present = HEADLESS_MARKER in content
        require(present == expected, f"sibling patch marker state changed unexpectedly in {path}")


def package_fingerprint(package: Path) -> dict[str, str]:
    bundle, session = read_bundle_and_session(package)
    targets = [bundle, session, package / "dist/core/extensions/types.d.ts"]
    return {
        str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in targets
    }


def main() -> int:
    argv = sys.argv[1:]
    if "--" in argv:
        separator = argv.index("--")
        own_args, child_command = argv[:separator], argv[separator + 1 :]
    else:
        own_args, child_command = argv, []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-package", type=Path, help="installed package root to copy (defaults to the package behind pi on PATH)")
    args = parser.parse_args(own_args)
    if not child_command:
        child_command = [sys.executable, str(ROOT / "tests/standing-reminder/feasibility.py")]

    try:
        node = shutil.which("node")
        require(bool(node), "Node.js is required to apply the isolated Pi patch")
        source = installed_package(args.source_package)
        version = json.loads((source / "package.json").read_text(encoding="utf-8"))["version"]
        source_fingerprint = package_fingerprint(source)
        with tempfile.TemporaryDirectory(prefix="pi-standing-origin-") as temporary:
            stage = Path(temporary) / "pi-coding-agent"
            shutil.copytree(source, stage, symlinks=True)

            # Ensure the existing shared-file patch is present in the test copy,
            # even when the source install came from a clean Pi package.
            sibling_env = os.environ.copy()
            sibling_env["PI_HEADLESS_PATCH_PACKAGE"] = str(stage)
            invoke([node, str(SIBLING_PATCH)], sibling_env)
            invoke([node, str(SIBLING_PATCH), "--check"], sibling_env)
            assert_sibling_patch(stage, True)
            # The installed source may already carry the origin bridge. Normalize
            # only our private copy before recording the sibling-only baseline.
            run_patch(node, stage, "termux")
            run_patch(node, stage, "termux", check=True)
            sibling_fingerprint = package_fingerprint(stage)

            run_patch(node, stage, "personal")
            patched_fingerprint = package_fingerprint(stage)
            run_patch(node, stage, "personal")
            require(package_fingerprint(stage) == patched_fingerprint, "reapplying the desktop patch changed its files")
            run_patch(node, stage, "personal", check=True)
            # Both desktop profiles must resolve to the same patched state;
            # apply under each profile to cover the full gate, not just --check.
            run_patch(node, stage, "axon-work-computer", check=True)
            run_patch(node, stage, "axon-work-computer")
            run_patch(node, stage, "personal", check=True)
            assert_sibling_patch(stage, True)

            bundle, session = read_bundle_and_session(stage)
            cli = stage / "dist/bundle/cli.js"
            require(cli.is_file(), f"staged Pi executable is missing: {cli}")
            declarations = (stage / "dist/core/extensions/types.d.ts").read_text(encoding="utf-8")
            require("source?: InputSource;" in declarations, "staged extension event declaration omits source")
            child_env = os.environ.copy()
            child_env.update({
                "PI_BIN": str(cli),
                "PI_CHEZMOI_PROFILE": "personal",
                "PI_STANDING_REMINDER_ORIGIN_PACKAGE": str(stage),
            })
            print(f"Using isolated Pi {version} from {stage}", flush=True)
            child = subprocess.run(child_command, env=child_env, text=True)
            if child.returncode != 0:
                return child.returncode

            # A changed upstream anchor must fail closed in the isolated copy.
            changed_stage = Path(temporary) / "changed-anchor-package"
            shutil.copytree(stage, changed_stage, symlinks=True)
            declaration_path = changed_stage / "dist/core/extensions/types.d.ts"
            declaration = declaration_path.read_text(encoding="utf-8")
            declaration_path.write_text(declaration.replace("source?: InputSource;", "source?: string;", 1), encoding="utf-8")
            changed_before = package_fingerprint(changed_stage)
            changed = invoke([node, str(PATCH), "--check"], patch_env(changed_stage, "personal"), expect_success=False)
            require("Changed or ambiguous anchor" in (changed.stderr or ""), "changed patch anchor did not fail closed")
            require(package_fingerprint(changed_stage) == changed_before, "failed anchor validation modified Pi files")

            # Verify profile-off reverses only this patch, not the existing
            # headless-extension-drain changes in shared files.
            termux_stage = Path(temporary) / "termux-package"
            shutil.copytree(stage, termux_stage, symlinks=True)
            run_patch(node, termux_stage, "termux")
            run_patch(node, termux_stage, "termux", check=True)
            invoke([node, str(PATCH), "--check"], patch_env(termux_stage, "personal"), expect_success=False)
            assert_sibling_patch(termux_stage, True)
            require(package_fingerprint(termux_stage) == sibling_fingerprint,
                    "Termux unpatch did not restore the sibling-only package state")
            for path in (termux_stage / "dist/core/agent-session.js", termux_stage / "dist/core/extensions/types.d.ts", read_bundle_and_session(termux_stage)[0]):
                require(ORIGIN_MARKER not in path.read_text(encoding="utf-8"), f"Termux retained the origin patch in {path}")
            run_patch(node, termux_stage, "axon-work-computer")
            run_patch(node, termux_stage, "axon-work-computer", check=True)
            run_patch(node, termux_stage, "termux")
            run_patch(node, termux_stage, "termux", check=True)
            assert_sibling_patch(termux_stage, True)

        require(package_fingerprint(source) == source_fingerprint, "installed Pi dist changed during isolated validation")
        print("PASS: installed Pi files remained unchanged")
        print("PASS: isolated package checks, desktop/Termux profile gate, and sibling-patch composition")
        return 0
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
