"""The mise chezmoi pin must equal the chezmoi version CI installs (scripts/ci-tool-pins.txt), and ci.yml must install through the pinned script."""
from pathlib import Path
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT / "scripts" / "ci-tool-pins.txt"


def pinned_versions(tool):
    rows = [l.split() for l in PINS.read_text().splitlines() if l.strip() and not l.startswith("#")]
    return {row[1] for row in rows if row[0] == tool}


class ChezmoiPinTests(unittest.TestCase):
    def test_ci_installs_chezmoi_through_the_pinned_script(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("scripts/ci-install-tool.sh chezmoi", text)
        self.assertNotIn("get.chezmoi.io", text)
        self.assertNotIn("mise.run", text)

    def test_mise_pin_equals_every_ci_chezmoi_pin(self):
        tools = tomllib.loads((ROOT / "dot_config/mise/config.toml").read_text())["tools"]
        if "chezmoi" not in tools:
            self.fail("dot_config/mise/config.toml [tools] has no chezmoi pin")
        self.assertIsInstance(tools["chezmoi"], str)
        self.assertEqual(pinned_versions("chezmoi"), {"v" + tools["chezmoi"]},
                         "scripts/ci-tool-pins.txt pins a different chezmoi than mise's pin")


if __name__ == "__main__":
    unittest.main()
