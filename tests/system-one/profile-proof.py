#!/usr/bin/env python3
"""Source-only System One proof; never apply, install, or use owner config/hooks."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "https://github.com/cartwmic/system-one-tools"
DOCS = "dot_pi/private_agent/extensions/system-one"


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, choices=["personal", "axon-work-computer"])
    profile = parser.parse_args().profile
    chezmoi = shutil.which("chezmoi")
    require(chezmoi, "chezmoi required")
    # Inspect source removal policy before any source read. No removal is executed.
    removals = (ROOT / ".chezmoiremove").read_text()
    require(".pi/agent/extensions/system-one" not in removals, "System One removal conflict")
    require({p.name for p in (ROOT / DOCS).iterdir()} == {"AGENTS.md", "README.md"}, "directory must be docs-only")
    commands = []
    with tempfile.TemporaryDirectory(prefix="system-one-profile-") as temporary:
        temp = Path(temporary).resolve()
        home = temp / "home"
        config_home = temp / "config"
        cache = temp / "cache"
        state = temp / "state"
        for directory in [home, config_home, cache, state]:
            directory.mkdir(mode=0o700)
        require(not home.is_relative_to(Path.home().resolve()), "isolated HOME overlaps owner HOME")
        config = config_home / "chezmoi.json"
        data = {"data": {"profile": profile}}
        config.write_text(json.dumps(data))
        config.chmod(0o600)
        # Effective config preflight: this exact file, not the owner's config.
        inspected = json.loads(config.read_text())
        require("hooks" not in inspected and "privatePiGlmProviderRef" not in inspected["data"], "unsafe controlled config")
        env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(home),
               "XDG_CONFIG_HOME": str(config_home), "XDG_CACHE_HOME": str(cache),
               "XDG_STATE_HOME": str(state), "NO_COLOR": "1"}
        base = [chezmoi, "--source", str(ROOT), "--destination", str(home),
                "--config", str(config), "--cache", str(cache), "--persistent-state",
                str(state / "chezmoi.json"), "--no-tty", "--color=false", "--refresh-externals=never"]

        def invoke(args):
            commands.append(base + args)
            result = subprocess.run(base + args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
            require(result.returncode == 0, "controlled chezmoi command failed: " + args[0] + "\n" + result.stderr)
            return result.stdout

        settings = home / ".pi/agent/settings.json"
        settings.parent.mkdir(parents=True)
        seed = {"lastChangelogVersion": "0.99.2", "theme": "proof-theme", "hideThinkingBlock": True}
        settings.write_text(json.dumps(seed))
        targets = [settings, home / ".pi/agent/extensions/system-one/README.md", home / ".pi/agent/extensions/system-one/AGENTS.md"]
        sources = [ROOT / "dot_pi/private_agent/private_settings.json.tmpl", ROOT / DOCS / "README.md", ROOT / DOCS / "AGENTS.md"]
        managed = set(invoke(["managed", "--include=files", "--path-style=absolute"]).splitlines())
        require(all(str(t) in managed for t in targets), "missing managed target")
        require(str(home / "AGENTS.md") not in managed and str(home / "README.md") not in managed, "root docs must remain ignored")
        require(not any("/extensions/system-one/index." in p for p in managed), "duplicate loader")
        require(not any(p.startswith(str(home / "tests") + "/") for p in managed), "tests must remain ignored")
        rendered = []
        live_before = [t.read_bytes() if t.exists() else None for t in targets]
        for target, source in zip(targets, sources):
            require(Path(invoke(["source-path", str(target)]).strip()).resolve() == source.resolve(), "wrong source mapping")
            rendered.append(invoke(["cat", str(target)]))
        config_json = json.loads(rendered[0])
        require(config_json["packages"].count(PACKAGE) == 1, "expected exactly one Git entry")
        require(all(config_json[k] == v for k, v in seed.items()), "live UI/changelog preservation failed")
        personal = profile == "personal"
        require(config_json["defaultProvider"] == ("openai-codex" if personal else "private-glm"), "chat provider changed")
        require(config_json["defaultModel"] == ("gpt-6.1-sol" if personal else "glm-5.3-flash"), "chat model changed")
        require(config_json["codemode"] == {"mode": "only"} and config_json["defaultTools"] == ["+codemode"], "chat/tool configuration changed")
        require(("https://github.com/olixis/pi-openrouter-plus" in config_json["packages"]) == personal, "plus gate changed")
        require((str(home / ".pi/agent/extensions/openrouter-gate/index.ts") in managed) == personal, "personal gate changed")
        for text, source in zip(rendered[1:], sources[1:]):
            require(text == source.read_text(), "docs rendering differs from source")
        invoke(["apply", "--dry-run", "--verbose", *map(str, targets)])
        require(live_before == [t.read_bytes() if t.exists() else None for t in targets], "dry-run modified destinations")
        # Seed independently for unchanged-target dry-run; this is a file write,
        # never a chezmoi apply or package materialization.
        for target, text in zip(targets, rendered):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        unchanged = [t.read_bytes() for t in targets]
        invoke(["apply", "--dry-run", "--verbose", *map(str, targets)])
        require(unchanged == [t.read_bytes() for t in targets], "unchanged dry-run modified destinations")
        config.write_text(json.dumps({"data": {"profile": "termux"}}))
        termux = invoke(["managed", "--include=files", "--path-style=absolute"]).splitlines()
        require(not any(p == str(home / ".pi") or p.startswith(str(home / ".pi") + "/") for p in termux), "Termux must exclude .pi")
        print(json.dumps({"status": "PASS", "profile": profile, "commands": commands,
                          "assertions": ["one-package", "docs-only", "chat-preserved", "personal-gate-plus-preserved", "root-docs-tests-ignored", "Termux-no-pi", "changed-and-unchanged-dry-run"],
                          "ownerConfigInvoked": False, "hooks": False, "secretLookup": False,
                          "apply": False, "install": False, "temporaryHomeRemoved": True}, indent=2))


if __name__ == "__main__":
    main()
