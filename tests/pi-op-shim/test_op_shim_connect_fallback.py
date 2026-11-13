"""Connect fallback (c2): when the Connect attempt fails, what the shim retries, what it prints, and how long it can take.

    python3 -m unittest discover -s tests/pi-op-shim -p 'test_op_shim_connect*.py' -k fallback -v

Every test name here contains 'fallback'. Black-box, as connect_support.py describes: the real shim and a fake op. The silent
host case takes about 4 s, the Connect attempt's limit.
"""
import time
import unittest

from connect_support import FAKE_CONNECT, ShimCase

CONNECT_ENV = {"OP_CONNECT_TOKEN": FAKE_CONNECT, "OP_CONNECT_HOST": "https://connect.example.test"}


class ConnectFallback(ShimCase):
    def setUp(self):
        super().setUp()
        self.write_service_token()

    def stderr_lines(self, result):
        return [line for line in result.stderr.splitlines() if line.strip()]

    def test_fallback_read_retries_once_on_the_service_account_and_returns_its_output(self):
        result = self.run_shim(["read", "op://v/i/f"], env={**CONNECT_ENV, "FAKE_CONNECT_MODE": "fail"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "from-service-account")
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertEqual((calls[0]["connect"], calls[0]["token"]), ("match", "unset"))
        self.assertEqual((calls[1]["connect"], calls[1]["token"]), ("unset", "match"))
        self.assert_no_secret_in_output(result)

    def test_fallback_item_get_json_retries_once_on_the_service_account(self):
        args = ["item", "get", "My Item", "--format", "json"]
        result = self.run_shim(args, env={**CONNECT_ENV, "FAKE_CONNECT_MODE": "fail"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "from-service-account")
        calls = self.calls()
        self.assertEqual([c["args"] for c in calls], [args, args])
        self.assertEqual([c["token"] for c in calls], ["unset", "match"])

    def test_fallback_inject_retries_on_the_service_account_with_the_same_stdin(self):
        template = "{{ op://v/i/f }}"
        result = self.run_shim(["inject", "", "a b"], env={**CONNECT_ENV, "FAKE_CONNECT_MODE": "fail", "FAKE_OP_READ_STDIN": "1"},
                               stdin=template)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "from-service-account")
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertEqual([c["stdin"] for c in calls], [template, template])
        self.assertEqual([c["args"] for c in calls], [["inject", "", "a b"], ["inject", "", "a b"]])

    def test_fallback_connect_output_is_not_printed_when_connect_fails(self):
        result = self.run_shim(["read", "op://v/i/f"],
                               env={**CONNECT_ENV, "FAKE_CONNECT_MODE": "fail", "FAKE_CONNECT_PARTIAL": "partial-connect-output"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "from-service-account")
        self.assertNotIn("partial", result.stdout + result.stderr)

    def test_fallback_op_run_is_not_retried_and_exits_with_the_connect_status(self):
        result = self.run_shim(["run", "--", "cmd"], env={**CONNECT_ENV, "FAKE_CONNECT_MODE": "fail", "FAKE_CONNECT_EXIT": "3"})
        self.assertEqual(result.returncode, 3, result.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 1, "a retry could run the wrapped command twice")
        self.assertEqual(calls[0]["connect"], "match")
        self.assertNotIn("retrying", result.stderr)

    def test_fallback_a_silent_connect_host_is_cut_off_and_the_service_account_answers_within_nine_seconds(self):
        started = time.monotonic()
        result = self.run_shim(["read", "op://v/i/f"], env={**CONNECT_ENV, "FAKE_CONNECT_MODE": "hang"})
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "from-service-account")
        self.assertLess(elapsed, 9, "the fallback took %.1f s" % elapsed)
        self.assertIn("timed out", result.stderr)
        self.assertEqual([c["token"] for c in self.calls()], ["unset", "match"])

    def test_fallback_the_service_account_call_gets_no_connect_variables(self):
        self.run_shim(["read", "op://v/i/f"], env={**CONNECT_ENV, "FAKE_CONNECT_MODE": "fail"})
        retry = self.calls()[1]
        self.assertEqual((retry["connect"], retry["connect_host"]), ("unset", ""))
        self.assertEqual(retry["token"], "match")

    def test_fallback_without_a_service_token_exits_with_the_connect_error_and_does_not_retry(self):
        (self.home / ".config/agent-harness/op-service-token").unlink()
        result = self.run_shim(["read", "op://v/i/f"],
                               env={**CONNECT_ENV, "FAKE_CONNECT_MODE": "fail", "FAKE_CONNECT_EXIT": "2",
                                    "FAKE_CONNECT_ERROR": "item not found"})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(self.calls()), 1)
        self.assertIn("item not found", result.stderr)
        self.assertIn("1Password Connect", result.stderr)
        self.assertIn("no service-account token to retry with", result.stderr)

    def test_fallback_an_item_missing_on_connect_and_on_the_service_account_gives_the_service_account_status(self):
        result = self.run_shim(["item", "get", "Missing", "--format", "json"],
                               env={**CONNECT_ENV, "FAKE_CONNECT_MODE": "fail", "FAKE_CONNECT_ERROR": "item not found",
                                    "FAKE_SA_EXIT": "5"})
        self.assertEqual(result.returncode, 5, result.stderr)
        self.assertEqual(len(self.calls()), 2)

    def test_fallback_writes_one_stderr_line_that_names_connect_and_the_reason(self):
        result = self.run_shim(["read", "op://v/i/f"],
                               env={**CONNECT_ENV, "FAKE_CONNECT_MODE": "fail", "FAKE_CONNECT_ERROR": "connection refused"})
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.stderr_lines(result)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("1Password Connect", lines[0])
        self.assertIn("connection refused", lines[0])
        self.assertIn("retrying on the service account", lines[0])

    def test_fallback_appends_the_same_line_with_a_time_to_the_fallback_log(self):
        result = self.run_shim(["read", "op://v/i/f"],
                               env={**CONNECT_ENV, "FAKE_CONNECT_MODE": "fail", "FAKE_CONNECT_ERROR": "connection refused"})
        self.assertEqual(result.returncode, 0, result.stderr)
        logged = self.fallback_log.read_text().splitlines()
        self.assertEqual(len(logged), 1, logged)
        self.assertRegex(logged[0], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ op: 1Password Connect .*connection refused; retrying on the service account$")

    def test_fallback_the_service_account_retry_runs_in_the_op_home_when_the_subcommand_takes_no_path(self):
        result = self.run_shim(["read", "op://v/i/f"], env={**CONNECT_ENV, "FAKE_CONNECT_MODE": "fail"}, cwd=self.caller)
        self.assertEqual(result.returncode, 0, result.stderr)
        retry = self.calls()[1]
        self.assertEqual(retry["token"], "match")
        self.assertEqual(retry["cwd"], self.op_home())


if __name__ == "__main__":
    unittest.main()
