"""Both desktop profiles deploy the Cursor instruction rule, the Cursor hook file (which carries the Shell guard entry) and the guard adapter,
so none of them has a row in docs/profiles.md. Same `chezmoi managed` run as test_coverage.py."""
import unittest

from test_coverage import PROFILES, managed

CURSOR = (".cursor/rules/agent-harness.mdc", ".cursor/hooks.json", ".cursor/hooks/shell_guard.py")


class CursorPaths(unittest.TestCase):
    def test_both_desktop_profiles_deploy_the_cursor_files(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                self.assertEqual(sorted(set(CURSOR) - managed(profile)), [])


if __name__ == "__main__":
    unittest.main()
