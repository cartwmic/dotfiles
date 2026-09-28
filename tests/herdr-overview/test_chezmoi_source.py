"""Drive proof.py's public scenario against a scripted external chezmoi."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROOF = ROOT / "tests/herdr-overview/proof.py"


class ChezmoiSourceTests(unittest.TestCase):
    def exercise(self, fail_apply=False):
        with tempfile.TemporaryDirectory(prefix="herdr-chezmoi-source-") as temporary:
            root = Path(temporary)
            mock = root / "bin"
            mock.mkdir()
            tool = mock / "chezmoi"
            tool.write_text("#!" + sys.executable + "\n" + r'''
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['CALL_LOG'], 'a') as f:
    f.write(json.dumps(args) + '\n')
source = args[args.index('--source') + 1] if '--source' in args else os.environ['DECOY_SOURCE']
profile = 'personal'
if '--override-data-file' in args:
    profile = json.loads(pathlib.Path(args[args.index('--override-data-file') + 1]).read_text())['profile']
if 'source-path' in args:
    print(str(pathlib.Path(source) / 'mapped-source'))
elif 'data' in args:
    print(json.dumps({'profile': profile}))
elif 'apply' in args:
    if '--dry-run' not in args:
        raise SystemExit('real apply forbidden in fixture')
    if os.environ['FAIL_APPLY'] == '1':
        raise SystemExit('scripted dry-run failure')
elif 'execute-template' in args:
    print('auto_publish = false' if '--file' in args else profile)
elif 'managed' in args:
    if profile == 'termux':
        print('bin/herdr-overview-proof\nbin/passage-review')
    else:
        print('.pi/agent/extensions/herdr-overview/index.ts')
else:
    raise SystemExit('unexpected command')
''')
            tool.chmod(0o700)
            env = {
                "HOME": str(root), "PATH": str(mock) + ":/usr/bin:/bin",
                "CALL_LOG": str(root / "calls.jsonl"), "DECOY_SOURCE": str(root / "configured-base"),
                "FAIL_APPLY": str(int(fail_apply)), "PYTHONDONTWRITEBYTECODE": "1",
            }
            result = subprocess.run([sys.executable, str(PROOF), "chezmoi-dry-run"],
                                    cwd=root, env=env, text=True, capture_output=True, timeout=30)
            calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
            return result, json.loads(result.stdout), calls

    def test_completed_scenario_uses_its_checkout_for_every_chezmoi_command(self):
        completed, receipt, calls = self.exercise()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(receipt['status'], 'PASS')
        self.assertTrue(receipt['targeted_dry_run'])
        self.assertFalse(receipt['real_apply'])
        for command in calls:
            self.assertIn('--source', command, command)
            self.assertEqual(command[command.index('--source') + 1], str(ROOT))
        for mapped in receipt['desktop_mappings_checked'].values():
            self.assertTrue(Path(mapped).is_relative_to(ROOT), mapped)

    def test_failed_external_preview_cannot_pass(self):
        completed, receipt, _ = self.exercise(fail_apply=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(receipt['status'], 'FAIL')
        self.assertIn('scripted dry-run failure', receipt['reason'])


if __name__ == '__main__':
    unittest.main()
