"""Exercise desktop Herdr plugin bootstrap through real chezmoi apply with fake installers."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
CHEZMOI = shutil.which("chezmoi")


@unittest.skipUnless(CHEZMOI and shutil.which("jq"), "chezmoi and jq required")
class InstallHerdrOverviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="herdr-bootstrap-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "home"
        self.source = self.home / ".local/share/chezmoi"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for relative in (
            "run_onchange_after_10_mise_bootstrap.sh.tmpl",
            "dot_config/mise/config.toml",
            "dot_config/herdr/config.toml",
            "dot_termux/termux.properties",
            ".chezmoiignore",
            "dot_local/share/herdr-overview/herdr-plugin.toml",
            "dot_local/share/herdr-overview/check-herdr-api.mjs",
            "dot_local/share/herdr-overview/src/herdr-compat.mjs",
        ):
            destination = self.source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        config = self.home / ".config/chezmoi/chezmoi.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("data:\n  profile: personal\n")
        (self.home / ".config/herdr").mkdir(parents=True)
        self.link_log = self.root / "linked-source"
        install = self.root / "installed-herdr"
        install.mkdir()
        self.write_tool(install / "herdr", """
import json, os, pathlib, sys
args = sys.argv[1:]
if args == ['--version']:
    print('herdr ' + os.environ.get('FAKE_HERDR_VERSION', '0.9.1'))
elif args == ['api', 'schema', '--json']:
    assert not pathlib.Path(os.environ['HERDR_SOCKET_PATH']).exists()
    print(pathlib.Path(os.environ['FAKE_HERDR_SCHEMA']).read_text())
elif len(args) == 4 and args[:2] == ['plugin', 'link'] and args[3] == '--enabled':
    pathlib.Path(os.environ['LINK_LOG']).write_text(args[2])
elif args in (
    ['plugin', 'list', '--plugin', 'vjeantet.palette', '--json'],
    ['plugin', 'install', 'vjeantet/herdr-palette', '--ref', 'v0.2.2', '--yes'],
):
    socket = pathlib.Path(os.environ['HERDR_SOCKET_PATH'])
    assert socket.parent == pathlib.Path(os.environ['XDG_CONFIG_HOME']) / 'herdr'
    assert socket.name.startswith('.herdr-palette-install-') and not socket.exists()
    state = pathlib.Path(os.environ['PALETTE_STATE'])
    if args[1] == 'list':
        print(json.dumps({'result': {'plugins': json.loads(state.read_text()) if state.exists() else []}}))
    else:
        log = pathlib.Path(os.environ['PALETTE_LOG'])
        log.write_text((log.read_text() if log.exists() else '') + 'install\\n')
        root = state.parent / 'palette'
        binary = root / 'target/release/herdr-palette'
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.touch()
        binary.chmod(0o755)
        state.write_text(json.dumps([{
            'plugin_id': 'vjeantet.palette', 'version': '0.2.2', 'enabled': True,
            'plugin_root': str(root),
            'source': {'kind': 'github', 'owner': 'vjeantet', 'repo': 'herdr-palette',
                       'requested_ref': 'v0.2.2'},
        }]))
else:
    sys.exit('unexpected herdr call: ' + repr(args))
""")
        self.write_tool(self.bin / "mise", """
import os, pathlib, subprocess, sys, tomllib
args = sys.argv[1:]
if args == ['--version']:
    print('test mise')
elif args == ['where', 'github:herdrdev/herdr']:
    print(os.environ['FAKE_HERDR_DIR'])
elif args in (['run', 'bootstrap'], ['run', 'install-herdr-palette']):
    config = tomllib.loads(pathlib.Path(os.environ['HERDR_TEST_CONFIG']).read_text())
    tasks = ['install-herdr-overview', 'install-herdr-palette'] if args[1] == 'bootstrap' else [args[1]]
    if args[1] == 'bootstrap':
        assert all(task in config['tasks']['bootstrap']['depends'] for task in tasks)
        assert config['tasks']['install-herdr-palette']['depends'] == ['install-herdr-overview']
    for task in tasks:
        result = subprocess.run(['/bin/sh', '-c', config['tasks'][task]['run']])
        if result.returncode:
            sys.exit(result.returncode)
elif args in (['install'], ['install', 'github:herdrdev/herdr'], ['run', 'setup-ubuntu-essentials']):
    pass
else:
    sys.exit('unexpected mise call: ' + repr(args))
""")
        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith(("CHEZMOI_", "HERDR_OVERVIEW_", "HERDR_PALETTE_", "OP_")):
                self.env.pop(key)
        self.env.update({
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "XDG_STATE_HOME": str(self.home / ".local/state"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "PATH": str(self.bin) + os.pathsep + self.env.get("PATH", "/usr/bin:/bin"),
            "FAKE_HERDR_DIR": str(install),
            "HERDR_TEST_CONFIG": str(self.source / "dot_config/mise/config.toml"),
            "LINK_LOG": str(self.link_log),
            "PALETTE_LOG": str(self.root / "palette-installs"),
            "PALETTE_STATE": str(self.root / "palette-state.json"),
            "FAKE_HERDR_SCHEMA": str(self.root / "schema.json"),
        })
        self.write_schema()

    def write_schema(self, protocol=22, drop_method=None):
        """A schema offering exactly what the plugin's API contract lists."""
        script = (
            "import { HERDR_API_CONTRACT as c, manifestEvents } from " + json.dumps(str(self.source / "dot_local/share/herdr-overview/src/herdr-compat.mjs")) + ";"
            "const defs = {}; const oneOf = Object.entries(c.methods).filter(([m]) => m !== process.argv[2]).map(([m, p], i) => {"
            " defs['P' + i] = { properties: Object.fromEntries(p.map((n) => [n, {}])) };"
            " return { properties: { method: { const: m }, params: { $ref: '#/schemas/request/$defs/P' + i } } }; });"
            "const res = Object.fromEntries(Object.entries(c.results).map(([n, f]) => [n, { properties: Object.fromEntries(f.map((x) => [x, {}])) }]));"
            "res.ResponseResult = { oneOf: c.resultTypes.map((t) => ({ properties: { type: { const: t } } })) };"
            "res.EventKind = { enum: manifestEvents().map((e) => e.replace('.', '_')) };"
            "console.log(JSON.stringify({ protocol: Number(process.argv[1]), schemas: { request: { oneOf, $defs: defs }, success_response: { $defs: res } } }));"
        )
        schema = subprocess.run(["node", "--input-type=module", "-e", script, str(protocol), drop_method or ""],
                                check=True, capture_output=True, text=True).stdout
        Path(self.env["FAKE_HERDR_SCHEMA"]).write_text(schema)

    @staticmethod
    def write_tool(path, body):
        path.write_text("#!" + sys.executable + "\n" + body)
        path.chmod(0o755)

    def test_apply_bootstrap_links_the_active_source_without_nested_chezmoi_lock(self):
        completed = subprocess.run(
            [CHEZMOI, "--source", str(self.source), "apply"],
            cwd=self.root, env=self.env, capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(self.link_log.read_text(), str(self.source / "dot_local/share/herdr-overview"))
        self.assertIn("mise bootstrap complete", completed.stderr)

    def test_palette_installs_for_both_desktop_profiles_and_skips_a_second_run(self):
        for profile in ("personal", "axon-work-computer"):
            with self.subTest(profile=profile):
                config = self.home / ".config/chezmoi/chezmoi.yaml"
                config.write_text(f"data:\n  profile: {profile}\n")
                for key in ("PALETTE_STATE", "PALETTE_LOG"):
                    Path(self.env[key]).unlink(missing_ok=True)
                completed = subprocess.run(
                    [CHEZMOI, "--source", str(self.source), "apply"],
                    cwd=self.root, env=self.env, capture_output=True, text=True, timeout=45,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertEqual(Path(self.env["PALETTE_LOG"]).read_text(), "install\n")
                keys = tomllib.loads((self.home / ".config/herdr/config.toml").read_text())["keys"]
                self.assertEqual(
                    [entry["key"] for entry in keys["command"] if entry["command"] == "vjeantet.palette.open"],
                    ["prefix+space"],
                )
                self.assertFalse((self.home / ".termux/termux.properties").exists())
                repeated = subprocess.run(
                    ["mise", "run", "install-herdr-palette"], cwd=self.root, env=self.env,
                    capture_output=True, text=True, timeout=20,
                )
                self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
                self.assertIn("already installed", repeated.stdout)
                self.assertEqual(Path(self.env["PALETTE_LOG"]).read_text(), "install\n")
                # Ensure the onchange script runs again for the other profile.
                script = self.source / "run_onchange_after_10_mise_bootstrap.sh.tmpl"
                script.write_text(script.read_text() + f"\n# Tested profile: {profile}\n")

    def test_palette_skips_termux_and_its_config_is_not_managed(self):
        config = self.home / ".config/chezmoi/chezmoi.yaml"
        config.write_text("data:\n  profile: termux\n")
        completed = subprocess.run(
            [CHEZMOI, "--source", str(self.source), "apply"],
            cwd=self.root, env=self.env, capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertFalse((self.home / ".config/herdr/config.toml").exists())
        properties = (self.home / ".termux/termux.properties").read_text()
        extra_keys = next(line.split("=", 1)[1].strip() for line in properties.splitlines()
                          if line.startswith("extra-keys ="))
        layout = json.loads(re.sub(r"(\w+):", r'"\1":', extra_keys).replace("'", '"'))
        self.assertEqual(layout[0][1], {
            "key": "CTRL", "display": "ctrl",
            "popup": {"macro": "CTRL b SPACE", "display": "palette"},
        })
        self.assertEqual(layout[0][2], {
            "key": "ALT", "display": "alt",
            "popup": {"macro": "CTRL o", "display": "ctrl-o"},
        })
        self.assertEqual(
            [[entry.get("key", entry.get("macro")) if isinstance(entry, dict) else entry
              for entry in row] for row in layout],
            [["ESC", "CTRL", "ALT", "UP", "KEYBOARD", "ENTER"],
             ["SHIFT", "TAB", "LEFT", "DOWN", "RIGHT", "CTRL ]"]],
        )
        skipped = subprocess.run(
            ["mise", "run", "install-herdr-palette"], cwd=self.root, env=self.env,
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(skipped.returncode, 0, skipped.stdout + skipped.stderr)
        self.assertIn("skipping profile termux", skipped.stdout)
        self.assertFalse(Path(self.env["PALETTE_LOG"]).exists())

    def test_apply_uses_the_active_worktree_instead_of_the_configured_checkout(self):
        worktree = self.root / "feature worktree"
        shutil.copytree(self.source, worktree)
        env = dict(self.env, HERDR_TEST_CONFIG=str(worktree / "dot_config/mise/config.toml"))
        completed = subprocess.run(
            [CHEZMOI, "--source", str(worktree), "apply"],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(self.link_log.read_text(), str(worktree / "dot_local/share/herdr-overview"))

    def test_standalone_task_uses_configured_source_not_cwd(self):
        task = tomllib.loads((self.source / "dot_config/mise/config.toml").read_text())["tasks"]["install-herdr-overview"]["run"]
        completed = subprocess.run(
            ["/bin/sh", "-c", task], cwd=self.root, env=self.env,
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(self.link_log.read_text(), str(self.source / "dot_local/share/herdr-overview"))

    def test_task_links_any_version_whose_api_meets_the_plugin_needs(self):
        task = tomllib.loads((self.source / "dot_config/mise/config.toml").read_text())["tasks"]["install-herdr-overview"]["run"]
        for version, protocol, drop, linked in (
            ("0.9.3", 22, None, True),
            ("2.0.0", 31, None, True),
            ("0.9.3", 22, "pane.focus", False),
        ):
            with self.subTest(version=version, protocol=protocol, drop=drop):
                self.write_schema(protocol, drop)
                self.link_log.unlink(missing_ok=True)
                completed = subprocess.run(
                    ["/bin/sh", "-c", task], cwd=self.root, env=dict(self.env, FAKE_HERDR_VERSION=version),
                    capture_output=True, text=True, timeout=20,
                )
                self.assertEqual(completed.returncode == 0, linked, completed.stdout + completed.stderr)
                self.assertEqual(self.link_log.exists(), linked)
                if not linked:
                    self.assertIn("method pane.focus is missing", completed.stderr)
                    self.assertIn(f"herdr {version} does not offer the API Herdr Overview uses", completed.stderr)


if __name__ == "__main__":
    unittest.main()
