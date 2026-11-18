"""The work-glm key reaches pi from its environment, read once at launch (docs/profiles.md, "pi key from the environment").

pi runs a `!command` apiKey on every request with a hard 10 s execSync timeout, so a machine stall killed the key read
mid-turn. On the work profile models.json names the key as "$WORK_GLM_API_KEY" and dot_local/bin/private_executable_pi.tmpl
reads it once and execs pi's own launcher. Rendered with the real chezmoi; the rendered wrapper runs as a process with a
stand-in key script and a stand-in pi launcher. No real key, op or pi is used.

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
MODELS = ROOT / "dot_pi" / "private_agent" / "private_models.json.tmpl"
WRAPPER = ROOT / "dot_local" / "bin" / "private_executable_pi.tmpl"
KEY_REF = "op://test/gateway"
WORK = {"profile": "axon-work-computer", "workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test",
        "workGlmKeyRef": KEY_REF, "workGlmModelId": "test-model", "workAwsProfile": "test-aws",
        "workDevportalMcpUrlRef": "op://test/devportal"}


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not installed")
class PiKeyFromEnv(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pi-key-env-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.config = self.tmp / "chezmoi.yaml"
        self.config.write_text("{}\n")
        self.env = {k: v for k, v in os.environ.items() if k not in ("WORK_GLM_API_KEY", "OP_SERVICE_ACCOUNT_TOKEN")}
        self.env["HOME"] = str(self.home)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def render(self, template, data):
        done = subprocess.run(
            ["chezmoi", "--source", str(ROOT), "--config", str(self.config), "--persistent-state", str(self.tmp / "state.boltdb"),
             "--destination", str(self.home), "execute-template", "--override-data", json.dumps(data)],
            input=template.read_text(encoding="utf-8"), capture_output=True, text=True, timeout=120, env=self.env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def install(self, key_script, data=WORK):
        """The rendered wrapper, a stand-in key script and a stand-in pi launcher that prints what it got."""
        wrapper = self.tmp / "pi"
        wrapper.write_text(self.render(WRAPPER, data))
        wrapper.chmod(0o755)
        scripts = self.home / ".local/user_scripts"
        scripts.mkdir(parents=True)
        (scripts / "op_read_cached.sh").write_text(key_script)
        (scripts / "op_read_cached.sh").chmod(0o755)
        launcher = self.home / ".pi/agent/bin"
        launcher.mkdir(parents=True)
        (launcher / "pi").write_text('#!/bin/sh\nprintf "key=%s args=%s\\n" "${WORK_GLM_API_KEY-unset}" "$*"\n')
        (launcher / "pi").chmod(0o755)
        return wrapper

    def run_wrapper(self, wrapper, *args, env=None):
        return subprocess.run([str(wrapper), *args], capture_output=True, text=True, timeout=30, env={**self.env, **(env or {})})

    def test_models_json_names_the_work_glm_key_by_environment_variable_not_a_command(self):
        provider = json.loads(self.render(MODELS, WORK))["providers"]["work-glm"]
        self.assertEqual(provider["apiKey"], "$WORK_GLM_API_KEY")
        self.assertNotIn("op_read_cached", json.dumps(provider))

    def test_the_wrapper_reads_the_key_once_by_its_ref_and_execs_pi_with_it(self):
        calls = self.tmp / "calls"
        wrapper = self.install('#!/bin/sh\necho "$*" >> "%s"\nprintf fake-key-123\n' % calls)
        done = self.run_wrapper(wrapper, "-p", "hello")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "key=fake-key-123 args=-p hello")
        self.assertEqual(calls.read_text().splitlines(), [KEY_REF], "one read, by the ref from local data")

    def test_a_key_already_in_the_environment_is_kept_and_nothing_is_read(self):
        calls = self.tmp / "calls"
        wrapper = self.install('#!/bin/sh\necho "$*" >> "%s"\nprintf other\n' % calls)
        done = self.run_wrapper(wrapper, env={"WORK_GLM_API_KEY": "given"})
        self.assertEqual(done.stdout.strip(), "key=given args=")
        self.assertFalse(calls.exists())

    def test_a_failed_read_warns_and_still_starts_pi_without_the_key(self):
        wrapper = self.install("#!/bin/sh\nexit 1\n")
        done = self.run_wrapper(wrapper, "--version")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "key=unset args=--version")
        self.assertIn("[pi] WARN: could not read the work-glm key, so WORK_GLM_API_KEY is unset", done.stderr)

    def test_an_empty_read_counts_as_failed(self):
        wrapper = self.install("#!/bin/sh\nexit 0\n")
        done = self.run_wrapper(wrapper)
        self.assertEqual(done.stdout.strip(), "key=unset args=")
        self.assertIn("[pi] WARN: could not read the work-glm key, so WORK_GLM_API_KEY is unset", done.stderr)

    def test_without_the_key_ref_the_wrapper_reads_nothing_and_still_starts_pi(self):
        calls = self.tmp / "calls"
        data = {k: v for k, v in WORK.items() if k != "workGlmKeyRef"}
        wrapper = self.install('#!/bin/sh\necho "$*" >> "%s"\nprintf k\n' % calls, data=data)
        done = self.run_wrapper(wrapper, "--version")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "key=unset args=--version")
        self.assertFalse(calls.exists(), "no key ref, no read")

    def test_the_wrapper_is_work_only(self):
        ignored = self.render(ROOT / ".chezmoiignore", {**WORK, "profile": "personal"})
        self.assertIn(".local/bin/pi\n", ignored)
        self.assertNotIn(".local/bin/pi\n", self.render(ROOT / ".chezmoiignore", WORK))


if __name__ == "__main__":
    unittest.main()
