"""The mise chezmoi pin must equal the chezmoi version every CI installer line pins."""
from pathlib import Path
import re
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = "get.chezmoi.io"
INSTALLER_TAG = re.compile(r"-t\s+(v\d+\.\d+\.\d+)\b")


class ChezmoiPinTests(unittest.TestCase):
    def ci_installer_lines(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text()
        return [line.strip() for line in text.splitlines() if INSTALLER in line]

    def test_ci_has_chezmoi_installer_lines(self):
        self.assertTrue(self.ci_installer_lines(), "ci.yml has no chezmoi installer line")

    def test_mise_pin_equals_every_ci_installer_pin(self):
        tools = tomllib.loads((ROOT / "dot_config/mise/config.toml").read_text())["tools"]
        if "chezmoi" not in tools:
            self.fail("dot_config/mise/config.toml [tools] has no chezmoi pin")
        self.assertIsInstance(tools["chezmoi"], str)
        expected = "v" + tools["chezmoi"]
        installers = self.ci_installer_lines()
        self.assertTrue(installers, "ci.yml has no chezmoi installer line")
        for line in installers:
            with self.subTest(line=line):
                self.assertEqual(INSTALLER_TAG.findall(line), [expected],
                                 f"CI pins a different chezmoi than mise's {expected}")


if __name__ == "__main__":
    unittest.main()
