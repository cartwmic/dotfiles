"""The work profile never routes op through 1Password Connect (docs/profiles.md): the Connect server is the personal homelab's.

    python3 -m unittest discover -s tests/pi-op-shim -p 'test_op_shim_work_profile.py' -v

The shim is rendered by real chezmoi for each profile, then run as a process with a fake op on PATH (see connect_support.py).
Whatever Connect token a work machine has, in the environment or in the token file, op must run on the service account, and
the shim must not hand op the personal Connect host.
"""
import os
import unittest

from connect_support import DEFAULT_HOST, FAKE_CONNECT, SA_SHIM, SHIM, ShimCase, render_shim

OTHER_PROFILES = ("axon-work-computer", "termux")  # any profile but personal: none may get the Connect shim


class RenderedShim(unittest.TestCase):
    def test_personal_gets_the_connect_shim_and_every_other_profile_the_service_account_one(self):
        self.assertEqual(render_shim("personal"), SHIM.read_text())
        for profile in OTHER_PROFILES:
            with self.subTest(profile=profile):
                text = render_shim(profile)
                self.assertEqual(text, SA_SHIM.read_text())
                self.assertNotIn("OP_CONNECT_HOST", text)
                self.assertNotIn("op-connect.internal", text)

    def test_the_two_files_are_runnable_as_they_are(self):
        for path in (SHIM, SA_SHIM):
            self.assertTrue(os.access(path, os.X_OK), path)


class WorkShim(ShimCase):
    def setUp(self):
        super().setUp()
        self.shim.write_text(render_shim("axon-work-computer"))
        self.shim.chmod(0o755)

    def assert_on_the_service_account(self, result):
        calls = self.calls()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["token"], "match")
        self.assertEqual(calls[0]["connect_host"], "")  # the shim hands op no Connect host, least of all the personal one
        self.assertNotIn("Connect", result.stderr)
        self.assertFalse(self.fallback_log.exists())

    def test_a_connect_token_file_is_ignored(self):
        self.write_service_token()
        for args in (["read", "op://v/i/f"], ["item", "get", "My Item", "--format", "json"], ["inject", "-i", "x"]):
            with self.subTest(args=args):
                self.log.unlink(missing_ok=True)
                result = self.run_shim(args, env={"OP_CONNECT_TOKEN_FILE": str(self.write_connect_file())})
                self.assert_on_the_service_account(result)
                self.assertEqual(self.calls()[0]["connect"], "unset")
                self.assertEqual(result.stdout, "from-service-account")

    def test_a_connect_token_in_the_environment_gets_no_personal_host(self):
        self.write_service_token()
        result = self.run_shim(["read", "op://v/i/f"], env={"OP_CONNECT_TOKEN": FAKE_CONNECT})
        self.assert_on_the_service_account(result)

    def test_the_same_setup_on_the_personal_shim_does_reach_connect(self):
        # The control: it proves the cases above can see a Connect call, so a work shim that started routing there would fail them.
        self.shim.write_text(render_shim("personal"))
        self.shim.chmod(0o755)
        self.write_service_token()
        result = self.run_shim(["read", "op://v/i/f"], env={"OP_CONNECT_TOKEN_FILE": str(self.write_connect_file())})
        calls = self.calls()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((calls[0]["connect"], calls[0]["connect_host"]), ("match", DEFAULT_HOST))


if __name__ == "__main__":
    unittest.main()
