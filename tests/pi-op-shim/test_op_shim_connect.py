"""Connect routing (c1): which op calls the shim sends to 1Password Connect, and which stay on the service account.

    python3 -m unittest discover -s tests/pi-op-shim -p 'test_op_shim_connect*.py' -v

Black-box: the real shim runs as a process with a fake op on PATH (see connect_support.py). Nothing here reaches a server.
The fallback cases are in test_op_shim_connect_fallback.py.
"""
import os
import shutil
import subprocess
import unittest

from connect_support import DEFAULT_HOST, FAKE_CONNECT, FAKE_SA, SHIM, ShimCase


class ConnectRouting(ShimCase):
    def test_read_inject_run_and_item_get_json_go_to_connect_and_not_the_service_account(self):
        self.write_service_token()
        for args in (["read", "op://v/i/f"], ["inject", "-i", "x"], ["run", "--", "cmd"],
                     ["item", "get", "My Item", "--vault", "dev", "--format", "json"],
                     ["item", "get", "My Item", "--format=json"]):
            with self.subTest(args=args):
                self.log.unlink(missing_ok=True)
                result = self.run_shim(args, env={"OP_CONNECT_TOKEN": FAKE_CONNECT})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "from-connect")
                calls = self.calls()
                self.assertEqual(len(calls), 1)
                self.assertEqual((calls[0]["connect"], calls[0]["token"]), ("match", "unset"))
                self.assertEqual(calls[0]["connect_host"], DEFAULT_HOST)
                self.assertEqual(calls[0]["args"], args)
                self.assert_no_secret_in_output(result)

    def test_every_other_command_stays_on_the_service_account_with_a_connect_token(self):
        self.write_service_token()
        for args in (["whoami"], ["signin", "--account", "my"], ["item", "get", "My Item", "--vault", "dev"],
                     ["item", "get", "My Item", "--format", "yaml"], ["item", "get", "My Item", "--format=yaml"],
                     ["item", "list"], ["vault", "list"], ["account", "list"],
                     ["document", "get", "doc", "--out-file", "f"]):
            with self.subTest(args=args):
                self.log.unlink(missing_ok=True)
                result = self.run_shim(args, env={"OP_CONNECT_TOKEN": FAKE_CONNECT})
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.calls()
                self.assertEqual(len(calls), 1)
                self.assertEqual((calls[0]["connect"], calls[0]["token"]), ("unset", "match"))
                self.assertEqual(calls[0]["connect_host"], "")
                self.assertEqual(calls[0]["args"], args)

    def test_a_connect_call_with_no_service_token_keeps_the_callers_home_and_directory(self):
        # Without a service-account token, a Connect call changes nothing about HOME or the directory (today's rule for
        # the no-token path). Under the real home this is what keeps the existing tests the same after seeding.
        for args in (["read", "op://v/i/f"], ["item", "get", "My Item", "--format", "json"]):
            with self.subTest(args=args):
                self.log.unlink(missing_ok=True)
                result = self.run_shim(args, env={"OP_CONNECT_TOKEN": FAKE_CONNECT}, cwd=self.caller)
                self.assertEqual(result.returncode, 0, result.stderr)
                call = self.calls()[0]
                self.assertEqual((call["connect"], call["token"]), ("match", "unset"))
                self.assertEqual(call["HOME"], str(self.home))
                self.assertEqual(os.path.realpath(call["cwd"]), os.path.realpath(self.caller))

    def test_a_connect_call_with_a_service_token_runs_in_the_op_home_when_the_subcommand_takes_no_path(self):
        self.write_service_token()
        env = {"OP_CONNECT_TOKEN": FAKE_CONNECT}
        cases = [(["read", "op://v/i/f"], True), (["item", "get", "My Item", "--format", "json"], True),
                 (["inject", "-i", "x"], False), (["run", "--", "cmd"], False)]
        for args, in_op_home in cases:
            with self.subTest(args=args):
                self.log.unlink(missing_ok=True)
                result = self.run_shim(args, env=env, cwd=self.caller)
                self.assertEqual(result.returncode, 0, result.stderr)
                call = self.calls()[0]
                self.assertNotEqual(call["HOME"], str(self.home))
                self.assertEqual(os.path.realpath(call["HOME"]), self.op_home())
                expected_dir = self.op_home() if in_op_home else os.path.realpath(self.caller)
                self.assertEqual(os.path.realpath(call["cwd"]), expected_dir)

    def test_the_connect_token_in_the_environment_is_used_before_the_token_file(self):
        path = self.write_connect_file("fake-connect-token-from-the-file")
        result = self.run_shim(["read", "op://v/i/f"], env={"OP_CONNECT_TOKEN": FAKE_CONNECT, "OP_CONNECT_TOKEN_FILE": str(path)})
        self.assertEqual(self.calls()[0]["connect"], "match")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_connect_token_file_is_used_when_the_environment_has_no_token(self):
        path = self.write_connect_file(FAKE_CONNECT)
        result = self.run_shim(["read", "op://v/i/f"], env={"OP_CONNECT_TOKEN_FILE": str(path)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[0]["connect"], "match")
        self.assertEqual(self.calls()[0]["token"], "unset")

    def test_a_connect_token_file_with_another_value_is_read_as_that_value(self):
        path = self.write_connect_file("fake-connect-token-from-the-file")
        self.run_shim(["read", "op://v/i/f"], env={"OP_CONNECT_TOKEN_FILE": str(path)})
        self.assertEqual(self.calls()[0]["connect"], "other")

    def test_op_connect_host_in_the_environment_replaces_the_default_host(self):
        other = "https://connect.example.test"
        self.run_shim(["read", "op://v/i/f"], env={"OP_CONNECT_TOKEN": FAKE_CONNECT, "OP_CONNECT_HOST": other})
        self.assertEqual(self.calls()[0]["connect_host"], other)

    def test_with_no_connect_token_a_supported_call_takes_the_service_account_as_before(self):
        self.write_service_token()
        for args in (["read", "op://v/i/f"], ["item", "get", "My Item", "--format", "json"], ["inject", "-i", "x"]):
            with self.subTest(args=args):
                self.log.unlink(missing_ok=True)
                result = self.run_shim(args)
                self.assertEqual(result.returncode, 0, result.stderr)
                call = self.calls()[0]
                self.assertEqual((call["connect"], call["token"]), ("unset", "match"))
                self.assertEqual(os.path.realpath(call["HOME"]), self.op_home())

    def test_inject_without_an_in_file_gives_connect_the_same_stdin(self):
        self.write_service_token()
        template = "{{ op://v/i/f }}"
        result = self.run_shim(["inject", "", "a b"], env={"OP_CONNECT_TOKEN": FAKE_CONNECT, "FAKE_OP_READ_STDIN": "1"},
                               stdin=template)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["connect"], "match")
        self.assertEqual(calls[0]["stdin"], template)
        self.assertEqual(calls[0]["args"], ["inject", "", "a b"])

    def test_a_connect_success_prints_only_connect_output_and_calls_op_once(self):
        self.write_service_token()
        result = self.run_shim(["read", "op://v/i/f"], env={"OP_CONNECT_TOKEN": FAKE_CONNECT})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "from-connect")
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(self.calls()), 1)

    def test_op_run_passes_its_arguments_to_connect_and_its_status_back(self):
        self.write_service_token()
        args = ["run", "--", "cmd", "", "a b", "--x=*"]
        result = self.run_shim(args, env={"OP_CONNECT_TOKEN": FAKE_CONNECT})
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.calls()[0]
        self.assertEqual(call["args"], args)
        self.assertEqual((call["connect"], call["token"]), ("match", "unset"))

    def test_op_run_replaces_the_shim_process_so_a_signal_reaches_op(self):
        # op run is not time-bounded, so the process that runs op must be the shim's own: no waiting parent to strand it.
        self.write_service_token()
        proc = subprocess.Popen(["op", "run", "--", "cmd"], env=self.shim_env({"OP_CONNECT_TOKEN": FAKE_CONNECT}),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.calls()[0]["connect"], "match")
        self.assertEqual(self.calls()[0]["pid"], str(proc.pid))

    def test_a_second_copy_of_the_shim_earlier_on_path_is_not_the_real_op(self):
        # Run from the zsh name (~/.local/share/op-shim/op) with no service-account token and no agent marker, the shim execs
        # the real op. The deployed copy is first on PATH, so it must be skipped, not run as "real" (where it would refuse).
        outer = self.tmp / "checkout/.local/share/op-shim/op"
        outer.parent.mkdir(parents=True)
        shutil.copy(SHIM, outer)
        outer.chmod(0o755)
        result = subprocess.run(["sh", str(outer), "whoami"], env=self.shim_env(), capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "from-service-account")
        self.assertEqual(len(self.calls()), 1)


if __name__ == "__main__":
    unittest.main()
