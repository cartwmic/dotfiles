"""Run the real install-uv-tools mise task against a scripted uv in a private HOME."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
MISE = shutil.which("mise")

UV = """#!/bin/sh
echo "$*" >> "$TEST_CALLS"
case "$1 $2" in
  "tool list")
    [ -f "$TEST_STATE/vectorcode" ] && printf 'vectorcode v0.7.20\n- vectorcode\n'
    [ -f "$TEST_STATE/vibe" ] && printf 'mistral-vibe v2.23.2\n- vibe\n'
    exit 0 ;;
  "tool uninstall") rm -f "$TEST_STATE/$3"; exit 0 ;;
  "tool install") [ "$3" = mistral-vibe ] && : > "$TEST_STATE/vibe" && printf '#!/bin/sh\n' > "$TEST_BIN/vibe" && chmod +x "$TEST_BIN/vibe"; exit 0 ;;
esac
exit 90
"""


@unittest.skipUnless(MISE, "mise is required")
class InstallUvToolsTests(unittest.TestCase):
    def run_task(self, *, vectorcode, vibe, runs=1):
        with tempfile.TemporaryDirectory(prefix="uv-tools-task-test-") as temporary:
            root = Path(temporary)
            home, project, mock, state = root / "home", root / "project", root / "mock", root / "state"
            for directory in (home, project, mock, state):
                directory.mkdir()
            task = tomllib.loads((ROOT / "dot_config/mise/config.toml").read_text())["tasks"]["install-uv-tools"]
            (project / "mise.toml").write_text("[tasks.install-uv-tools]\nrun = " + json.dumps(task["run"]) + "\n")
            (root / "global.toml").write_text("")
            (mock / "uv").write_text(UV)
            (mock / "uv").chmod(0o700)
            if vectorcode:
                (state / "vectorcode").write_text("")
            if vibe:
                (state / "vibe").write_text("")
                (mock / "vibe").write_text("#!/bin/sh\n")
                (mock / "vibe").chmod(0o700)
            env = {
                "HOME": str(home), "PATH": str(mock) + ":/usr/bin:/bin",
                "XDG_CONFIG_HOME": str(root / "config"),
                "MISE_GLOBAL_CONFIG_FILE": str(root / "global.toml"),
                "MISE_DATA_DIR": str(root / "mise-data"), "MISE_CACHE_DIR": str(root / "mise-cache"),
                "MISE_TRUSTED_CONFIG_PATHS": str(project), "MISE_YES": "1",
                "TEST_CALLS": str(root / "calls"), "TEST_STATE": str(state), "TEST_BIN": str(mock),
                "TMPDIR": str(root),
            }
            results = []
            for _ in range(runs):
                done = subprocess.run([MISE, "run", "install-uv-tools"], cwd=project, env=env,
                                      text=True, capture_output=True, timeout=30)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                calls = (root / "calls").read_text().splitlines() if (root / "calls").exists() else []
                (root / "calls").write_text("")
                results.append(calls)
            return results, sorted(p.name for p in state.iterdir())

    def test_old_vectorcode_is_uninstalled_and_vibe_left_alone(self):
        (calls,), state = self.run_task(vectorcode=True, vibe=True)
        self.assertIn("tool uninstall vectorcode", calls)
        self.assertFalse(any(c.startswith("tool install") for c in calls), calls)
        self.assertEqual(state, ["vibe"])

    def test_fresh_machine_installs_only_vibe_then_does_nothing(self):
        (first, second), state = self.run_task(vectorcode=False, vibe=False, runs=2)
        self.assertEqual([c for c in first if not c.startswith("tool list")], ["tool install mistral-vibe"])
        self.assertFalse(any("vectorcode" in c and not c.startswith("tool list") for c in first + second))
        self.assertEqual([c for c in second if not c.startswith("tool list")], [])
        self.assertEqual(state, ["vibe"])


if __name__ == "__main__":
    unittest.main()
