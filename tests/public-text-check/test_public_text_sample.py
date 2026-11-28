"""Black-box test for scripts/public-text-sample.py: the false-hit sample over a repository's recent merged pull requests.

`gh` and the check are stand-ins on PATH; nothing reaches GitHub.

    python3 -m unittest discover -s tests/public-text-check -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/public-text-sample.py"

FAKE_GH = '#!/bin/sh\necho "$@" >> "$FAKE_GH_LOG"\ncat "$FAKE_PRS"\n'
# A stand-in check: refuses (1) a body holding REFUSEME with a class line, cannot run (2) on a body holding BROKEN, passes otherwise.
FAKE_CHECK = '''#!/bin/sh
for a; do case $a in body=*) f=${a#body=} ;; esac; done
if grep -q BROKEN "$f"; then echo "could not run" >&2; exit 2; fi
if grep -q REFUSEME "$f"; then echo "public-text-check: refused" >&2; echo "  body:3: home path" >&2; echo "  body:3: user name" >&2; exit 1; fi
exit 0
'''


class Sample(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="public-text-sample-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        for name, text in (("gh", FAKE_GH), ("check", FAKE_CHECK)):
            (self.dir / name).write_text(text)
            (self.dir / name).chmod(0o755)
        self.prs = self.dir / "prs.json"
        self.log = self.dir / "gh.log"

    def run_sample(self, prs, *args):
        self.prs.write_text(json.dumps(prs))
        env = dict(os.environ, PATH="%s:%s" % (self.dir, os.environ["PATH"]), FAKE_PRS=str(self.prs), FAKE_GH_LOG=str(self.log), PUBLIC_TEXT_CHECK=str(self.dir / "check"))
        return subprocess.run([sys.executable, str(SCRIPT), "someone/repo", *args], capture_output=True, text=True, env=env)

    def test_it_prints_each_refusal_by_class_and_line_and_one_count_line_with_its_selection_rule(self):
        done = self.run_sample([{"number": 7, "title": "t", "body": "clean"}, {"number": 8, "title": "t", "body": "REFUSEME"}, {"number": 9, "title": "t", "body": "BROKEN"}], "3")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.splitlines(), [
            "#8: body:3: home path; body:3: user name",
            "#9: could not be checked (exit 2)",
            "someone/repo: last 3 merged (gh pr list --state merged --limit 3): 3 selected, 2 checked, 1 refused, 1 unreadable"])
        self.assertNotIn("REFUSEME", done.stdout)
        self.assertEqual(self.log.read_text().splitlines(), ["pr list --repo someone/repo --state merged --limit 3 --json number,title,body"])  # one listing read

    def test_the_default_is_fifty_and_a_failed_listing_is_an_error(self):
        done = self.run_sample([])
        self.assertIn("last 50 merged", done.stdout)
        self.assertIn("--limit 50", self.log.read_text())
        (self.dir / "gh").write_text("#!/bin/sh\necho no >&2\nexit 1\n")
        done = subprocess.run([sys.executable, str(SCRIPT), "someone/repo"], capture_output=True, text=True, env=dict(os.environ, PATH="%s:%s" % (self.dir, os.environ["PATH"])))
        self.assertNotEqual(done.returncode, 0)


if __name__ == "__main__":
    unittest.main()
