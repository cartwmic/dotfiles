"""Exercise the actual mise task with a scripted download service and private HOME."""
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


@unittest.skipUnless(MISE, "mise is required")
class InstallKubectlTests(unittest.TestCase):
    def exercise(self, system, machine, *, broken_download=False, installed=False):
        with tempfile.TemporaryDirectory(prefix="kubectl-task-test-") as temporary:
            root = Path(temporary)
            home, project, mock = root / "home", root / "project", root / "mock"
            for directory in (home, project, mock):
                directory.mkdir()
            task = tomllib.loads((ROOT / "dot_config/mise/config.toml").read_text())["tasks"]["install-kubectl"]
            (project / "mise.toml").write_text(
                "[tasks.install-kubectl]\nrun = " + json.dumps(task["run"]) + "\n"
            )
            (root / "global.toml").write_text("")

            def executable(path, text):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                path.chmod(0o700)

            executable(mock / "uname", "#!/bin/sh\ncase \"$1\" in -s) echo \"$TEST_SYSTEM\";; -m) echo \"$TEST_MACHINE\";; *) exit 1;; esac\n")
            executable(mock / "curl", """#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
url = next(a for a in args if a.startswith('https://'))
with open(os.environ['TEST_REQUESTS'], 'a') as f:
    f.write(json.dumps(args) + '\\n')
if url.endswith('/stable.txt'):
    print('v1.35.0')
else:
    output = pathlib.Path(args[args.index('-o') + 1]) if '-o' in args else pathlib.Path('kubectl')
    code = '#!/bin/sh\\n[ "$1 $2" = "version --client" ] || exit 91\\n'
    code += 'exit 42\\n' if os.environ['TEST_BROKEN'] == '1' else 'echo client-ok\\n'
    output.write_text(code)
""".replace("#!/usr/bin/env python3", "#!" + os.sys.executable))
            if installed:
                executable(mock / "kubectl", "#!/bin/sh\n[ \"$1 $2\" = \"version --client\" ]\n")
            env = {
                "HOME": str(home), "PATH": str(mock) + ":/usr/bin:/bin",
                "XDG_CONFIG_HOME": str(root / "config"),
                "MISE_GLOBAL_CONFIG_FILE": str(root / "global.toml"),
                "MISE_DATA_DIR": str(root / "mise-data"), "MISE_CACHE_DIR": str(root / "mise-cache"),
                "MISE_TRUSTED_CONFIG_PATHS": str(project), "MISE_YES": "1",
                "TEST_SYSTEM": system, "TEST_MACHINE": machine,
                "TEST_REQUESTS": str(root / "requests.jsonl"), "TEST_BROKEN": str(int(broken_download)),
                "TMPDIR": str(root),
            }
            completed = subprocess.run(
                [MISE, "run", "install-kubectl"], cwd=project, env=env,
                text=True, capture_output=True, timeout=30,
            )
            log = root / "requests.jsonl"
            requests = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            destination = home / ".local/bin/kubectl"
            verified = subprocess.run([str(destination), "version", "--client"], capture_output=True).returncode if destination.exists() else None
            return completed, requests, destination.exists(), verified

    def test_host_download_and_completed_install(self):
        cases = [("Darwin", "arm64", "darwin/arm64"), ("Darwin", "x86_64", "darwin/amd64"),
                 ("Linux", "aarch64", "linux/arm64"), ("Linux", "x86_64", "linux/amd64")]
        for system, machine, platform in cases:
            with self.subTest(system=system, machine=machine):
                result, requests, exists, verified = self.exercise(system, machine)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                urls = [arg for request in requests for arg in request if arg.startswith("https://")]
                self.assertIn(f"https://dl.k8s.io/release/v1.35.0/bin/{platform}/kubectl", urls)
                self.assertTrue(exists)
                self.assertEqual(verified, 0)

    def test_nonworking_download_is_not_installed(self):
        result, _, exists, _ = self.exercise("Darwin", "arm64", broken_download=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(exists)

    def test_unsupported_host_fails_before_download(self):
        result, requests, exists, _ = self.exercise("FreeBSD", "riscv64")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(requests, [])
        self.assertFalse(exists)

    def test_existing_install_does_not_download(self):
        result, requests, exists, _ = self.exercise("Darwin", "arm64", installed=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(requests, [])
        self.assertFalse(exists)


if __name__ == "__main__":
    unittest.main()
