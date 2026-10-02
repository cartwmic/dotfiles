"""Genuine wrapper CLI timezone journeys with a private allowlisted environment."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / 'dot_local/bin/executable_session-recap'
CLI = ROOT / 'dot_local/share/session-recap/session_recap.py'


class TimeZoneCliTests(unittest.TestCase):
    def test_public_timezone_presentation_preserves_records(self):
        with tempfile.TemporaryDirectory(prefix='recap-timezone-') as temporary:
            home = Path(temporary)
            config = home / 'config/session-recap'
            config.mkdir(parents=True)
            backend = home / 'backend.py'
            backend.write_text('import sys\nfrom pathlib import Path\nPath("calls").open("a").write("called\\n")\nprint("Observed: " + sys.stdin.read().strip() + "; next: review.")\n')
            (config / 'config.toml').write_text('command = ' + json.dumps([sys.executable, str(backend)]) + '\n')
            (config / 'single-prompt.md').write_text('[[TEXT]]')
            (config / 'group-prompt.md').write_text('[[MEMBERS]]')
            env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL') if k in os.environ}
            env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'), XDG_DATA_HOME=str(home / 'data'), SESSION_RECAP_IMPLEMENTATION=str(CLI), SESSION_RECAP_PYTHON=sys.executable, TZ='America/Los_Angeles')
            def run(*args, text=None, success=True):
                result = subprocess.run([str(WRAPPER), *args], input=text, text=True, capture_output=True, env=env, cwd=home, timeout=20)
                self.assertEqual(result.returncode == 0, success, result.stderr)
                return result.stdout
            first = run('create', '--kind', 'single', '--metadata-json', '{"caller":{"opaque":true}}', text='Orchard checks passed').strip()
            second = run('create', '--kind', 'single', text='Harbor review pending').strip()
            # Known-date fixtures are real generated records; only their fixture clocks change.
            files = list((home / 'data/session-recap/records').glob('*/*.json'))
            for path in files:
                record = json.loads(path.read_text())
                record['created_at'] = record['published_at'] = '2026-01-15T12:00:00Z' if record['record_id'] == first else '2026-07-15T12:00:00Z'
                path.write_text(json.dumps(record))
            before = {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (home / 'data').rglob('*') if p.is_file()}
            original = json.loads(run('read', first, '--json'))['record']
            self.assertEqual(run('read', first).strip(), original['summary'])
            for zone in ('local', 'UTC', 'America/New_York'):
                listed = json.loads(run('list', '--json', '--time-zone', zone))
                self.assertEqual(listed['presentation']['time_zone'], zone)
                for row in listed['records']:
                    read = json.loads(run('read', row['record_id'], '--json', '--time-zone', zone))
                    self.assertEqual(row, read['record'])
                    self.assertTrue(row['created_at'].endswith('Z'))
                displayed = listed['presentation']['records']
                if zone == 'America/New_York':
                    self.assertIn('07:00:00-05:00 EST', displayed[first]['created_at'])
                    self.assertIn('08:00:00-04:00 EDT', displayed[second]['created_at'])
                if zone == 'local':
                    self.assertIn('04:00:00-08:00 PST', displayed[first]['created_at'])
                    self.assertIn('05:00:00-07:00 PDT', displayed[second]['created_at'])
                self.assertIn('[' + zone + ']', run('list', '--time-zone', zone))
                self.assertIn('[' + zone + ']', run('read', first, '--with-metadata', '--time-zone', zone))
            (config / 'config.local.toml').write_text('time_zone = "America/New_York"\n')
            self.assertEqual(json.loads(run('read', first, '--json'))['presentation']['time_zone'], 'America/New_York')
            self.assertEqual(json.loads(run('read', first, '--json', '--time-zone', 'UTC'))['presentation']['time_zone'], 'UTC')
            calls_before = (home / 'calls').read_bytes()
            for args in [('create', '--kind', 'single'), ('list', '--json'), ('read', first, '--json')]:
                run(*args, '--time-zone', 'Not/AZone', text='must not run', success=False)
            self.assertEqual((home / 'calls').read_bytes(), calls_before)
            after = {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (home / 'data').rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            self.assertEqual(json.loads(run('read', first, '--json'))['record'], original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
