"""Driver control-flow tests, not product acceptance evidence."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('recap_proof', Path(__file__).with_name('proof.py'))
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


class DriverTests(unittest.TestCase):
    def test_group_failure_survives_successful_cleanup(self):
        calls = []
        def fake(name, criteria, argv, timeout=180):
            calls.append((name, argv))
            return dict(case=name, status='FAIL' if name == 'pi-grouped' else 'PASS',
                        stdout='{"run_id":"0123456789abcdef"}')
        with patch.object(proof, 'execute', fake):
            rows = proof.overview()
        self.assertEqual([x[0] for x in calls], ['overview-prepare', 'herdr-wide', 'pi-grouped', 'overview-cleanup'])
        self.assertEqual(rows[2]['status'], 'FAIL')
        state_bases = [argv[argv.index('--state-base') + 1] for _, argv in calls]
        self.assertEqual(len(set(state_bases)), 1)
        self.assertFalse(Path(state_bases[0]).exists())

    def test_wide_failure_still_cleans_and_skips_group(self):
        def fake(name, criteria, argv, timeout=180):
            return dict(case=name, status='FAIL' if name == 'herdr-wide' else 'PASS',
                        stdout='{"run_id":"0123456789abcdef"}')
        with patch.object(proof, 'execute', fake):
            rows = proof.overview()
        self.assertEqual([x['case'] for x in rows], ['overview-prepare', 'herdr-wide', 'overview-cleanup'])
        self.assertEqual(rows[1]['status'], 'FAIL')

    def test_lifecycle_executes_new_public_gaps_and_preserves_old_cases_fail_closed(self):
        calls = []
        def fake(name, criteria, argv, timeout=180):
            calls.append((name, argv))
            return dict(case=name, status='FAIL' if 'supersession' in name else 'PASS')
        output = io.StringIO()
        with patch.object(proof.sys, 'argv', ['proof.py', 'lifecycle']), patch.object(proof, 'execute', fake), contextlib.redirect_stdout(output):
            result = proof.main()
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue())['status'], 'FAIL')
        paths = [str(argv[-1]) for _, argv in calls]
        for path in ('recursion.py', 'supersession.py', 'departure.py', 'busy.py', 'manual.py'):
            self.assertIn(str(proof.ROOT / 'tests/pi-recap' / path), paths)
        self.assertEqual(paths.count(str(proof.ROOT / 'tests/pi-recap/lifecycle.py')), 3)
        limits = [argv[-1] for _, argv in calls if str(proof.ROOT / 'tests/pi-recap/limits.py') in [str(x) for x in argv]]
        self.assertEqual(set(limits), {'python-explicit', 'python-fallback', 'length-final', 'length-reduction', 'budget-physical-default', 'budget-physical-explicit', 'budget-virtual-default', 'budget-virtual-explicit', 'budget-virtual-preflight', 'budget-refusal'})
        self.assertIn('pi-settings-oversized-manual-automatic-recursion-deadline-followup-public', [name for name, _ in calls])
        self.assertIn('surviving-old-job-new-original-session-supersession-public', [name for name, _ in calls])

    def test_virtual_metadata_compaction_and_guard_cases_are_dispatched(self):
        for section, expected in (
            ('tui', {'manual', 'automatic'}),
            ('lifecycle', {'guard-' + case for case in ('switch', 'reload', 'cancel', 'shutdown', 'newer', 'failure-current', 'failure-stale')}),
        ):
            calls = []
            def fake(name, criteria, argv, timeout=180):
                if str(proof.ROOT / 'tests/pi-recap/compaction.py') in [str(x) for x in argv]:
                    calls.append((argv[-1], criteria))
                return dict(case=name, status='PASS')
            with patch.object(proof.sys, 'argv', ['proof.py', section]), patch.object(proof, 'execute', fake), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(proof.main(), 0)
            self.assertEqual({case for case, _ in calls}, expected)
            self.assertTrue(all('AC-13' in criteria for _, criteria in calls))

    def test_scoped_case_runs_only_selected_public_case(self):
        for name, expected in (('supervised-preflight-cancel-public', ['supervised-preflight-cancel-public']),
                               ('unknown-case', [])):
            calls = []
            def fake(name, criteria, argv, timeout=180):
                calls.append(name)
                return dict(case=name, status='PASS')
            output = io.StringIO()
            with patch.object(proof.sys, 'argv', ['proof.py', 'lifecycle', '--case', name]), patch.object(proof, 'execute', fake), contextlib.redirect_stdout(output):
                result = proof.main()
            self.assertEqual(calls, expected)
            self.assertEqual(result, 0 if expected else 1)
            self.assertEqual(json.loads(output.getvalue())['status'], 'PASS' if expected else 'FAIL')

    def test_large_retained_history_is_wired_into_tui_and_scope_selectable(self):
        name = 'large-retained-history-public'
        calls = []
        def fake(case, criteria, argv, timeout=180):
            calls.append((case, criteria, argv, timeout))
            return dict(case=case, status='PASS')
        with patch.object(proof.sys, 'argv', ['proof.py', 'tui', '--case', name]), patch.object(proof, 'execute', fake), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(proof.main(), 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], name)
        self.assertEqual(set(calls[0][1]), {'AC-1', 'AC-2', 'AC-3', 'AC-6', 'AC-7', 'AC-10', 'AC-12', 'AC-13'})
        self.assertEqual(calls[0][2][-1], proof.ROOT / 'tests/pi-recap/history_transport.py')
        self.assertEqual(calls[0][3], 240)

    def test_history_viewer_width_is_a_public_tui_case(self):
        calls = []
        def fake(name, criteria, argv, timeout=180):
            calls.append((name, criteria, argv))
            return dict(case=name, status='PASS')
        with patch.object(proof.sys, 'argv', ['proof.py', 'tui', '--case', 'history-viewer-phone-wide-width-public']), patch.object(proof, 'execute', fake), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(proof.main(), 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], ['AC-3'])
        self.assertEqual(calls[0][2][-1], proof.ROOT / 'tests/pi-recap/viewer_width.py')

    def test_missing_receipt_cannot_pass(self):
        with patch.object(proof, 'execute', return_value=dict(status='PASS', stdout='{}')):
            rows = proof.overview()
        self.assertEqual(rows[-1]['status'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
