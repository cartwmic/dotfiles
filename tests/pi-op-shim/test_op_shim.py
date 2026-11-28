"""Black-box tests for .chezmoitemplates/op-shim-connect, the personal-profile op shim Pi's shells see (dot_pi/private_agent/bin/executable_op.tmpl picks it).

    python3 -m unittest discover -s tests/pi-op-shim -v

The real shim runs as a real process. op is a fake first found on PATH after the shim's own directory: it records its HOME,
arguments, stdin and whether it got the test's fake token, then exits with a status the test chose. No real op, token or
1Password account is used.
"""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SHIM = Path(__file__).resolve().parents[2] / ".chezmoitemplates/op-shim-connect"
FAKE_TOKEN = "ops_fake-token-for-the-shim-test"  # a stand-in service-account token; never a real one
NO_TOKEN = "1Password service account token not set; refusing to use the desktop app (playbook 78819cbd)"
MARKERS = {  # one per agent shell marker the shim reads; each is set to a non-empty value
    "CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "T3CODE_THREAD_ID": "thread-1",
    "CODEX_SANDBOX": "seatbelt", "CODEX_THREAD_ID": "019a-test",
}

FAKE_OP = """#!/bin/sh
out="$FAKE_OP_OUT"
printf 'HOME=%s\n' "$HOME" > "$out"
if [ "${OP_SERVICE_ACCOUNT_TOKEN-unset}" = unset ]; then echo "token=unset" >> "$out"
elif [ "$OP_SERVICE_ACCOUNT_TOKEN" = "$FAKE_TOKEN_EXPECTED" ]; then echo "token=the-test-token" >> "$out"
else echo "token=other" >> "$out"; fi
printf 'cwd=%s\n' "$(pwd -P)" >> "$out"
for a in "$@"; do printf 'arg=%s\n' "$a" >> "$out"; done
if [ -n "${FAKE_OP_READ_STDIN:-}" ]; then printf 'stdin=%s\n' "$(cat)" >> "$out"; fi
exit "${FAKE_OP_EXIT:-0}"
"""


class OpShim(unittest.TestCase):
    shim_source = SHIM  # test_op_shim_service_account.py runs this same class against the work-profile variant

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="op-shim-"))
        self.home = self.tmp / "home"
        (self.home / ".config/agent-harness").mkdir(parents=True)
        # The shim as chezmoi deploys it: ~/.pi/agent/bin/op, executable.
        self.bin = self.home / ".pi/agent/bin"
        self.bin.mkdir(parents=True)
        self.shim = self.bin / "op"
        shutil.copy(self.shim_source, self.shim)
        self.shim.chmod(0o755)
        self.real_dir = self.tmp / "real-bin"
        self.real_dir.mkdir()
        fake = self.real_dir / "op"
        fake.write_text(FAKE_OP)
        fake.chmod(0o755)
        self.out = self.tmp / "op-call.txt"
        self.guard_log = self.tmp / "guard.jsonl"
        self.tmpdir = self.tmp / "tmpdir"
        self.tmpdir.mkdir()
        # The same file under the zsh name, as dot_zshenv puts it on every zsh's PATH.
        self.zsh_dir = self.home / ".local/share/op-shim"
        self.zsh_dir.mkdir(parents=True)
        (self.zsh_dir / "op").symlink_to(self.shim)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_token(self):
        token = self.home / ".config/agent-harness/op-service-token"
        token.write_text(FAKE_TOKEN + "\n")
        token.chmod(0o600)

    def no_connect_env(self):
        """These tests cover the shim without a Connect token. The shim finds that token through the passwd home, which a
        temporary HOME does not hide, so point it at a file that does not exist, and keep fallback lines out of the real log."""
        return {
            "OP_CONNECT_TOKEN_FILE": str(self.tmp / "no-connect-token-here"),
            "OP_CONNECT_FALLBACK_LOG": str(self.tmp / "connect-fallback.log"),
            "AGENT_HARNESS_GUARD_LOG": str(self.guard_log),  # keep refusal lines out of the real guard log
        }

    def run_zsh_name(self, args, env=None, cwd=None):
        """Run op through the zsh name: its directory first on PATH, as in every zsh; the real op after it."""
        base = {
            "HOME": str(self.home), "TMPDIR": str(self.tmpdir), "PATH": f"{self.zsh_dir}:{self.real_dir}:/usr/bin:/bin",
            "FAKE_OP_OUT": str(self.out), "FAKE_TOKEN_EXPECTED": FAKE_TOKEN,
            **self.no_connect_env(),
        }
        base.update(env or {})
        return subprocess.run(["op", *args], env=base, cwd=cwd, capture_output=True, text=True, timeout=30)

    def run_shim(self, args, env=None, path=None, stdin=None, cwd=None):
        base = {
            "HOME": str(self.home),
            "TMPDIR": str(self.tmpdir),
            # Pi's order: its bin directory first, then the rest (here: the fake op, then the system tools).
            "PATH": path or f"{self.bin}:{self.real_dir}:/usr/bin:/bin",
            "FAKE_OP_OUT": str(self.out),
            "FAKE_TOKEN_EXPECTED": FAKE_TOKEN,
            **self.no_connect_env(),
        }
        base.update(env or {})
        return subprocess.run(["op", *args], env=base, input=stdin, cwd=cwd, capture_output=True, text=True, timeout=30)

    def call(self):
        lines = self.out.read_text().splitlines()
        return {
            "home": lines[0].removeprefix("HOME="),
            "token": lines[1].removeprefix("token="),
            "cwd": lines[2].removeprefix("cwd="),
            "args": [l.removeprefix("arg=") for l in lines if l.startswith("arg=")],
            "stdin": next((l.removeprefix("stdin=") for l in lines if l.startswith("stdin=")), None),
        }

    def assert_no_token_in_output(self, result):
        self.assertNotIn(FAKE_TOKEN, result.stdout + result.stderr)

    def caller_dir(self):
        """The directory the caller (an agent's repo, say) is in: its own directory, not the op home."""
        d = self.tmp / "caller"
        d.mkdir(exist_ok=True)
        return d

    def assert_op_ran_in(self, expected):
        self.assertEqual(os.path.realpath(self.call()["cwd"]), os.path.realpath(expected))

    def test_with_the_token_file_op_runs_with_an_empty_home_and_the_service_account(self):
        self.write_token()
        result = self.run_shim(["item", "get", "My Item", "--vault", "dev"])
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.call()
        self.assertEqual(call["token"], "the-test-token")
        self.assertEqual(call["args"], ["item", "get", "My Item", "--vault", "dev"])
        self.assertNotEqual(call["home"], str(self.home))
        op_home = Path(call["home"])
        self.assertTrue(op_home.is_dir())
        self.assertEqual(op_home.parent, self.tmpdir)
        self.assertEqual(list(op_home.iterdir()), [], "the HOME op sees holds nothing (no desktop-app data)")
        self.assertEqual(stat.S_IMODE(op_home.stat().st_mode), 0o700)
        self.assert_no_token_in_output(result)

    def test_a_token_already_in_the_environment_is_used_as_it_is(self):
        result = self.run_shim(["whoami"], env={"OP_SERVICE_ACCOUNT_TOKEN": FAKE_TOKEN})
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.call()
        self.assertEqual(call["token"], "the-test-token")
        self.assertNotEqual(call["home"], str(self.home))

    def test_without_a_token_the_pi_name_refuses_and_op_never_runs(self):
        # Pi's bash tool and Retro's PATH reach this file by the Pi name: always an agent, so no desktop-app fallback.
        result = self.run_shim(["signin", "--account", "my"])
        self.assertEqual(result.returncode, 69, result.stderr)
        self.assertEqual(result.stderr, NO_TOKEN + "\n")
        self.assertEqual(result.stdout, "")
        self.assertFalse(self.out.exists(), "op never ran")

    def test_zsh_name_clean_terminal_without_a_token_runs_the_real_op_unchanged(self):
        # Michael's own terminal: no agent marker, so the desktop-app path is kept.
        result = self.run_zsh_name(["signin", "--account", "my"])
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.call()
        self.assertEqual(call["home"], str(self.home))
        self.assertEqual(call["token"], "unset")
        self.assertEqual(call["args"], ["signin", "--account", "my"])
        self.assertNotIn("refusing", result.stderr)

    def test_zsh_name_in_an_agent_shell_without_a_token_refuses_for_each_marker(self):
        for name, value in MARKERS.items():
            with self.subTest(marker=name):
                if self.out.exists():
                    self.out.unlink()
                result = self.run_zsh_name(["whoami"], env={name: value})
                self.assertEqual(result.returncode, 69, (name, result.stderr))
                self.assertEqual(result.stderr, NO_TOKEN + "\n", name)
                self.assertFalse(self.out.exists(), f"{name}: op never ran")

    # A refusal leaves one line in the guard log (design principle 14): {ts, action, rule, tool, cwd, matched} as the bash_rules
    # refusals write it, plus reason (which marker matched) and session. Nothing from the arguments goes in it but a subcommand
    # name from a fixed list.

    SECRETS = ("op://Vault-Secret/Item-Secret/field", "SESSIONSECRET123", "Vault-Secret", "Item-Secret", "TOKENVALUE456")

    def guard_lines(self):
        return self.guard_log.read_text().splitlines() if self.guard_log.exists() else []

    def test_a_refusal_leaves_one_line_in_the_guard_log_with_the_marker_and_no_secret(self):
        for name, value in MARKERS.items():
            with self.subTest(marker=name):
                if self.guard_log.exists():
                    self.guard_log.unlink()
                result = self.run_zsh_name(["read", "op://Vault-Secret/Item-Secret/field", "--session=SESSIONSECRET123"], env={name: value})
                self.assertEqual(result.returncode, 69, result.stderr)
                lines = self.guard_lines()
                self.assertEqual(len(lines), 1, lines)
                record = json.loads(lines[0])
                self.assertEqual({k: record[k] for k in ("action", "rule", "tool", "matched", "reason")},
                                 {"action": "refuse", "rule": "op-shim", "tool": "op", "matched": "read", "reason": "marker " + name})
                self.assertRegex(record["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
                for secret in self.SECRETS:
                    self.assertNotIn(secret, lines[0])

    def test_a_refusal_by_the_pi_name_logs_that_name_as_the_reason(self):
        result = self.run_shim(["item", "get", "Item-Secret", "--vault", "Vault-Secret"])
        self.assertEqual(result.returncode, 69, result.stderr)
        record = json.loads(self.guard_lines()[0])
        self.assertEqual((record["matched"], record["reason"], record["session"]), ("item", "pi name", None))
        for secret in self.SECRETS:
            self.assertNotIn(secret, self.guard_lines()[0])

    def test_the_log_line_names_the_session_the_environment_gives(self):
        result = self.run_zsh_name(["whoami"], env={"CLAUDECODE": "1", "T3CODE_THREAD_ID": "thread-1"})
        self.assertEqual(result.returncode, 69, result.stderr)
        self.assertEqual(json.loads(self.guard_lines()[0])["session"], "thread-1")
        self.guard_log.unlink()
        self.run_zsh_name(["whoami"], env={"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "sess-9"})
        self.assertEqual(json.loads(self.guard_lines()[0])["session"], "sess-9")

    def test_a_t3_thread_id_of_the_delegated_task_form_is_logged_whole(self):
        # Delegated threads (builders, leads) carry ":" and "%" in the id; stripping them would match no thread or ledger source.
        thread = "thread:delegated-task:command%3Amcp%3Af636143a-2bc5%3Adelegate-task%3Aonepassword-guard-1b"
        for run in (lambda: self.run_zsh_name(["whoami"], env={"T3CODE_THREAD_ID": thread}), lambda: self.run_shim(["whoami"], env={"T3CODE_THREAD_ID": thread})):
            if self.guard_log.exists():
                self.guard_log.unlink()
            self.assertEqual(run().returncode, 69)
            self.assertEqual(json.loads(self.guard_lines()[0])["session"], thread)

    def test_the_first_marker_and_the_first_session_variable_win(self):
        # Order as agent_shell checks the markers; the session is T3's, then Codex's, then Claude's.
        env = {"CODEX_SANDBOX": "seatbelt", "CODEX_THREAD_ID": "codex-1", "T3CODE_THREAD_ID": "t3-1", "CLAUDE_CODE_ENTRYPOINT": "cli", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "claude-1"}
        self.run_zsh_name(["whoami"], env=env)
        record = json.loads(self.guard_lines()[0])
        self.assertEqual((record["reason"], record["session"]), ("marker CLAUDECODE", "t3-1"))
        self.guard_log.unlink()
        self.run_zsh_name(["whoami"], env={k: v for k, v in env.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "T3CODE_THREAD_ID")})
        record = json.loads(self.guard_lines()[0])
        self.assertEqual((record["reason"], record["session"]), ("marker CODEX_THREAD_ID", "codex-1"))
        self.guard_log.unlink()
        self.run_zsh_name(["whoami"], env={"CODEX_SANDBOX": "seatbelt", "CLAUDE_CODE_SESSION_ID": "claude-1"})
        record = json.loads(self.guard_lines()[0])
        self.assertEqual((record["reason"], record["session"]), ("marker CODEX_SANDBOX", "claude-1"))

    def test_a_first_argument_that_is_not_a_subcommand_is_not_logged(self):
        # A flag first (op --session=TOKEN read ...) or any word outside the fixed list logs matched null, never the text.
        for args in (["--session=TOKENVALUE456", "read", "op://Vault-Secret/Item-Secret/field"], ["Vault-Secret"], []):
            with self.subTest(args=args):
                if self.guard_log.exists():
                    self.guard_log.unlink()
                result = self.run_shim(args)
                self.assertEqual(result.returncode, 69, result.stderr)
                self.assertEqual(len(self.guard_lines()), 1)
                self.assertIsNone(json.loads(self.guard_lines()[0])["matched"])
                for secret in self.SECRETS:
                    self.assertNotIn(secret, self.guard_lines()[0])

    def test_a_session_id_with_odd_characters_still_gives_one_json_line(self):
        self.run_zsh_name(["whoami"], env={"CLAUDECODE": "1", "T3CODE_THREAD_ID": 'a"b\\c d'})
        self.assertEqual(json.loads(self.guard_lines()[0])["session"], "abcd")

    def test_a_run_that_is_not_refused_writes_no_log_line(self):
        self.write_token()
        self.run_zsh_name(["whoami"], env={"CLAUDECODE": "1"})
        self.run_zsh_name(["whoami"], env={"CLAUDECODE": ""})
        self.assertEqual(self.guard_lines(), [])

    def test_the_shim_still_refuses_when_the_log_cannot_be_written(self):
        # A regular file as the log's parent folder: the write fails even for root.
        blocker = self.tmp / "not-a-folder"
        blocker.write_text("x")
        env = {"AGENT_HARNESS_GUARD_LOG": str(blocker / "guard.jsonl")}
        for run in (lambda: self.run_zsh_name(["whoami"], env={**env, "CLAUDECODE": "1"}), lambda: self.run_shim(["whoami"], env=env)):
            result = run()
            self.assertEqual(result.returncode, 69, result.stderr)
            self.assertEqual(result.stderr, NO_TOKEN + "\n")
            self.assertFalse(self.out.exists(), "op never ran")

    def test_codex_with_its_sandbox_off_refuses_without_a_token(self):
        # Codex sets CODEX_THREAD_ID in every shell it runs. With its sandbox off it sets no CODEX_SANDBOX, so this is the
        # only marker there is (playbook 78819cbd). run_zsh_name builds the environment from scratch: CODEX_SANDBOX is unset.
        result = self.run_zsh_name(["whoami"], env={"CODEX_THREAD_ID": "019a-test"})
        self.assertEqual(result.returncode, 69, result.stderr)
        self.assertEqual(result.stderr, NO_TOKEN + "\n")
        self.assertFalse(self.out.exists(), "op never ran")

    def test_an_empty_marker_is_not_an_agent_shell(self):
        result = self.run_zsh_name(["whoami"], env={"CLAUDECODE": ""})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.call()["token"], "unset")

    def test_zsh_name_in_an_agent_shell_with_the_token_uses_the_service_account(self):
        self.write_token()
        result = self.run_zsh_name(["whoami"], env={"CLAUDECODE": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.call()
        self.assertEqual(call["token"], "the-test-token")
        self.assertNotEqual(call["home"], str(self.home))
        self.assert_no_token_in_output(result)

    def test_read_only_subcommands_run_in_the_op_home_whatever_the_callers_directory(self):
        # The subcommands that take no file path: op runs in its empty HOME, so it never reads the caller's directory.
        self.write_token()
        for args in (["read", "op://v/i/f"], ["whoami"], ["item", "get", "My Item", "--vault", "dev"],
                     ["item", "list"], ["vault", "list"], ["account", "list"]):
            with self.subTest(args=args):
                if self.out.exists():
                    self.out.unlink()
                result = self.run_shim(args, cwd=self.caller_dir())
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.call()["args"], args)
                self.assert_op_ran_in(self.call()["home"])
                self.assertNotEqual(self.call()["home"], str(self.home))

    def test_other_subcommands_keep_the_callers_directory(self):
        # They may take relative paths (inject -i, run, document get --out-file), so op runs where the caller is.
        self.write_token()
        for args in (["inject", "-i", "x"], ["run", "--", "cmd"], ["document", "get", "doc", "--out-file", "f"]):
            with self.subTest(args=args):
                if self.out.exists():
                    self.out.unlink()
                result = self.run_shim(args, cwd=self.caller_dir())
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_op_ran_in(self.caller_dir())

    def test_a_read_only_subcommand_with_a_path_option_keeps_the_callers_directory(self):
        self.write_token()
        for args in (["read", "--out-file", "f", "op://v/i/f"], ["read", "--out-file=f", "op://v/i/f"],
                     ["read", "op://v/i/f", "--out", "f"], ["read", "op://v/i/f", "--out=f"],
                     ["read", "op://v/i/f", "-o", "f"], ["item", "get", "My Item", "--in-file", "f"],
                     ["item", "get", "My Item", "-i", "f"]):
            with self.subTest(args=args):
                if self.out.exists():
                    self.out.unlink()
                result = self.run_shim(args, cwd=self.caller_dir())
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_op_ran_in(self.caller_dir())

    def test_without_a_token_read_only_subcommands_keep_the_callers_directory(self):
        # Michael's own terminal: no change of directory, the same as before.
        for args in (["read", "op://v/i/f"], ["item", "get", "My Item"], ["whoami"]):
            with self.subTest(args=args):
                if self.out.exists():
                    self.out.unlink()
                result = self.run_zsh_name(args, cwd=self.caller_dir())
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.call()["home"], str(self.home))
                self.assert_op_ran_in(self.caller_dir())

    def test_an_unreadable_token_file_counts_as_no_token(self):
        if os.geteuid() == 0:
            self.skipTest("root reads any file")
        self.write_token()
        (self.home / ".config/agent-harness/op-service-token").chmod(0)
        result = self.run_shim(["whoami"])
        self.assertEqual(result.returncode, 69, result.stderr)
        self.assertFalse(self.out.exists(), "op never ran")

    def test_exit_status_stdin_and_odd_arguments_pass_through(self):
        self.write_token()
        result = self.run_shim(["inject", "", "a b", "--x=*", "$HOME"], env={"FAKE_OP_EXIT": "6", "FAKE_OP_READ_STDIN": "1"}, stdin="{{ op://v/i/f }}")
        self.assertEqual(result.returncode, 6)
        call = self.call()
        self.assertEqual(call["args"], ["inject", "", "a b", "--x=*", "$HOME"])
        self.assertEqual(call["stdin"], "{{ op://v/i/f }}")

    def test_the_shim_never_runs_itself_even_when_its_directory_is_on_path_twice(self):
        self.write_token()
        result = self.run_shim(["whoami"], path=f"{self.bin}:{self.bin}/:{self.real_dir}:/usr/bin:/bin")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.call()["token"], "the-test-token")

    def test_no_real_op_is_an_error_naming_the_cli(self):
        result = self.run_shim(["whoami"], path=f"{self.bin}:/usr/bin:/bin")
        self.assertEqual(result.returncode, 127)
        self.assertIn("1Password CLI is not installed", result.stderr)
        self.assertFalse(self.out.exists())

    def test_a_shell_without_the_pi_bin_directory_never_sees_the_shim(self):
        # A terminal outside Pi: its PATH has no ~/.pi/agent/bin, so op is the real one and the token file is not read.
        self.write_token()
        env = {"HOME": str(self.home), "PATH": f"{self.real_dir}:/usr/bin:/bin", "FAKE_OP_OUT": str(self.out), "FAKE_TOKEN_EXPECTED": FAKE_TOKEN}
        result = subprocess.run(["sh", "-c", 'command -v op; op whoami'], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.stdout.strip(), str(self.real_dir / "op"))
        call = self.call()
        self.assertEqual((call["home"], call["token"]), (str(self.home), "unset"))


if __name__ == "__main__":
    unittest.main()
