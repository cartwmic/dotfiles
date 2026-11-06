"""Render dot_pi/private_agent/private_models.json.tmpl with the real chezmoi and a stand-in op.

The work profile's privatePiProviderRef read must go through the op shim with the service account only, and must
not call op at all without a token. fake_op/op is the first op on PATH. It logs its HOME, whether
OP_SERVICE_ACCOUNT_TOKEN is set (never the value) and its arguments, then prints fixed JSON. No real op, token or
1Password account is used.

    python3 -m unittest discover -s tests/pi-settings-render -v
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "dot_pi" / "private_agent" / "private_models.json.tmpl"
STAND_IN = Path(__file__).resolve().parent / "fake_op" / "op"

FAKE_TOKEN = "ops_FAKE_TEST"
REF = "op://test-vault/test-item/credential"
WORK_DATA = {"profile": "axon-work-computer", "workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test",
             "workGlmKeyRef": "op://test/gateway", "workGlmModelId": "test-model", "workAwsProfile": "test-aws",
             "workDevportalMcpUrlRef": "op://test/devportal", "privatePiProviderRef": REF}


def work_data(ref=True):
    data = dict(WORK_DATA)
    if not ref:
        del data["privatePiProviderRef"]
    return data


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not installed")
class ModelsOpRead(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="models-render-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        (self.tmp / "tmpdir").mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        shutil.copy(STAND_IN, self.bin / "op")
        (self.bin / "op").chmod(0o755)
        self.log = self.tmp / "op-calls.log"
        self.config = self.tmp / "chezmoi.yaml"
        self.config.write_text("{}\n")  # no hooks or data from the developer's own config
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("OP_SERVICE_ACCOUNT_TOKEN", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")}
        self.env.update(HOME=str(self.home), TMPDIR=str(self.tmp / "tmpdir"), FAKE_OP_LOG=str(self.log),
                        PATH=f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def token_file(self):
        return self.home / ".config/agent-harness/op-service-token"

    def write_token_file(self, text=FAKE_TOKEN + "\n", mode=0o600):
        self.token_file().parent.mkdir(parents=True, exist_ok=True)
        self.token_file().write_text(text)
        self.token_file().chmod(mode)

    def render(self, data, token_env=None):
        env = dict(self.env)
        if token_env is not None:
            env["OP_SERVICE_ACCOUNT_TOKEN"] = token_env
        return subprocess.run(
            ["chezmoi", "--source", str(ROOT), "--config", str(self.config), "--persistent-state",
             str(self.tmp / "state.boltdb"), "--destination", str(self.home), "execute-template",
             "--override-data", json.dumps(data)],
            input=TEMPLATE.read_text(encoding="utf-8"), capture_output=True, text=True, timeout=120, env=env)

    def op_calls(self):
        """One dict per stand-in call: HOME, token (set or unset) and the arguments."""
        calls = []
        if self.log.exists():
            for line in self.log.read_text().splitlines():
                key, _, value = line.partition("=")
                if key == "HOME":
                    calls.append({"HOME": value, "token": None, "args": []})
                elif key == "token":
                    calls[-1]["token"] = value
                elif key == "arg":
                    calls[-1]["args"].append(value)
        return calls

    def assert_one_service_account_call(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.op_calls()
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(calls[0]["args"], ["read", REF])
        self.assertEqual(calls[0]["token"], "set")
        # The shim runs the real op under its own empty HOME, never the real one or the test's.
        self.assertTrue(calls[0]["HOME"].startswith(str(self.tmp / "tmpdir")), calls[0]["HOME"])
        self.assertNotEqual(calls[0]["HOME"], os.path.expanduser("~"))
        provider = json.loads(result.stdout)["providers"]["work-anthropic"]
        self.assertEqual(provider["baseUrl"], "https://provider.test/v1")

    def assert_fails_before_any_op_call(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(self.token_file()), result.stderr)
        self.assertIn("docs/profiles.md", result.stderr)
        self.assertEqual(self.op_calls(), [])

    def test_token_in_env_reads_once_through_the_shim(self):
        self.assert_one_service_account_call(self.render(work_data(), token_env=FAKE_TOKEN))

    def test_token_only_in_file_reads_once_through_the_shim(self):
        self.write_token_file()
        self.assert_one_service_account_call(self.render(work_data()))

    def test_no_token_fails_before_any_op_call(self):
        self.assert_fails_before_any_op_call(self.render(work_data()))

    def test_empty_token_file_fails_before_any_op_call(self):
        self.write_token_file(text="\n")
        self.assert_fails_before_any_op_call(self.render(work_data()))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read a mode 000 file")
    def test_unreadable_token_file_fails_before_any_op_call(self):
        self.write_token_file(mode=0o000)
        result = self.render(work_data())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(self.token_file()), result.stderr)  # the read's own error names the file
        self.assertEqual(self.op_calls(), [])

    def test_work_profile_without_a_provider_ref_never_calls_op(self):
        result = self.render(work_data(ref=False))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.op_calls(), [])

    def test_personal_and_termux_never_call_op(self):
        for profile in ("personal", "termux"):
            with self.subTest(profile=profile):
                self.log.unlink(missing_ok=True)
                result = self.render({"profile": profile, "privatePiProviderRef": REF})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.op_calls(), [])
                self.assertNotIn("work-anthropic", json.loads(result.stdout)["providers"])


if __name__ == "__main__":
    unittest.main()
