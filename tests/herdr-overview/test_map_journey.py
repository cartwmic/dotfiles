"""Focused fail-closed and native invariant checks; no owner server."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import map_journey as journey


class JourneyTests(unittest.TestCase):
    def test_geometry_only_is_not_native_membership_change(self):
        before = {'panes': [{'pane_id': 'synthetic-p', 'label': 'Synthetic',
            'scroll': {'viewport_rows': 30}}], 'layouts': [{'area': {'width': 40},
            'panes': [{'pane_id': 'synthetic-p', 'rect': {'width': 40}}]}]}
        after = copy.deepcopy(before)
        after['panes'][0]['scroll']['viewport_rows'] = 31
        after['layouts'][0]['area']['width'] = 120
        after['layouts'][0]['panes'][0]['rect']['width'] = 120
        self.assertEqual(journey.native_signature(before), journey.native_signature(after))
        after['panes'][0]['label'] = 'Wrong name'
        self.assertNotEqual(journey.native_signature(before), journey.native_signature(after))

    def test_focus_and_order_are_not_filtered(self):
        before = {'panes': [{'pane_id': 'one'}, {'pane_id': 'two'}],
            'focused_pane_id': 'one'}
        after = copy.deepcopy(before); after['panes'].reverse()
        self.assertNotEqual(journey.native_signature(before), journey.native_signature(after))
        after = copy.deepcopy(before); after['focused_pane_id'] = 'two'
        self.assertNotEqual(journey.native_signature(before), journey.native_signature(after))

    def test_all_requires_both_real_assertion_sets(self):
        outcomes = {key: True for key in journey.INTERACTION_OUTCOMES | journey.IDENTITY_OUTCOMES}
        outcomes.update({key: True for key in ('both_clients_rendered', 'public_ui_busy_singleton',
            'native_structure_labels_focus_unchanged_while_open', 'close_reopen', 'viewer_passive')})
        for key in ('scripted_full_detail_markers', 'scripted_narrow_full_detail_markers'):
            outcomes[key] = ['ERROR-END', 'PROMPT-END', 'RECAP-END', 'TITLE-END']
        journey.require_completed_outcomes(outcomes, 'all')
        for key in journey.INTERACTION_OUTCOMES | journey.IDENTITY_OUTCOMES:
            missing = dict(outcomes); missing.pop(key)
            with self.assertRaises(journey.proof.ProofFailure):
                journey.require_completed_outcomes(missing, 'all')
        missing = dict(outcomes); missing['scripted_full_detail_markers'] = ['TITLE-END']
        with self.assertRaises(journey.proof.ProofFailure):
            journey.require_completed_outcomes(missing, 'all')

    def test_unfinished_path_does_not_become_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipts = Path(tmp) / 'receipts'
            with patch.object(journey.proof, 'setup_herdr_run',
                side_effect=journey.proof.ProofBlocked('synthetic unfinished setup')):
                self.assertEqual(journey.run(receipts, 'all'), 2)
            record = journey.proof.read_json(receipts / 'receipt.json')
            self.assertEqual(record['status'], 'BLOCKED')
            self.assertEqual(record['outcomes'], {})
            self.assertNotIn('cleanup', record)

    def test_failed_setup_cleans_only_created_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            outsider = parent / 'owner-state'; outsider.write_text('do not touch')
            receipts = parent / 'receipts'
            def partial_setup(run_id, base):
                journey.proof.run_root(run_id, base).mkdir(parents=True)
                raise journey.proof.ProofBlocked('fixture setup unfinished')
            def owned_cleanup(run_id, base):
                root = journey.proof.run_root(run_id, base)
                self.assertEqual(base, receipts / 'fixtures')
                root.rmdir()
                return {'temporary_root_removed': True}
            with patch.object(journey.proof, 'setup_herdr_run', side_effect=partial_setup), \
                 patch.object(journey.proof, 'scenario_cleanup', side_effect=owned_cleanup) as cleanup:
                self.assertEqual(journey.run(receipts, 'all'), 2)
                cleanup.assert_called_once()
            self.assertEqual(outsider.read_text(), 'do not touch')

    def test_existing_receipts_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileExistsError):
                journey.run(Path(tmp), 'all')

    def test_default_command_does_not_require_receipts_flag(self):
        with patch('sys.argv', ['map_journey.py', '--scenario', 'all']), \
             patch.object(journey, 'run', return_value=2) as run:
            self.assertEqual(journey.main(), 2)
        path, scenario = run.call_args.args
        self.assertEqual(scenario, 'all')
        self.assertTrue(path.name.startswith('hm-'))
        # macOS unix-domain sockets have a short sun_path limit.
        self.assertLess(len(str(path / 'fixtures' / ('a' * 16) / 'server/plugin-link-only.sock')), 104)

    def test_busy_probe_requires_public_ui_busy(self):
        with patch.object(journey.proof, 'api_request',
                side_effect=journey.proof.ProofFailure('API failed: ui_busy')):
            busy, response = journey.popup_busy({})
            self.assertTrue(busy)
            self.assertIn('ui_busy', response['error'])
        with patch.object(journey.proof, 'api_request',
                side_effect=journey.proof.ProofFailure('socket lost')):
            with self.assertRaises(journey.proof.ProofFailure):
                journey.popup_busy({})

    def test_successful_probe_is_not_busy(self):
        with patch.object(journey.proof, 'api_request', return_value={'opened': True}) as api:
            self.assertEqual(journey.popup_busy({}), (False, {'opened': True}))
            self.assertEqual(api.call_args.args[1], 'plugin.pane.open')
            self.assertEqual(api.call_args.args[2]['placement'], 'popup')

    def test_unexpected_open_preserves_receipt_and_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(journey, 'popup_busy', return_value=(False, {'opened': True})):
                with self.assertRaises(journey.proof.ProofFailure):
                    journey.require_busy({}, Path(tmp), 'unexpected-open')
            self.assertEqual(journey.proof.read_json(Path(tmp) / 'unexpected-open.json'),
                {'opened': True})

    def test_interactions_command_accepted_without_receipts_flag(self):
        with patch('sys.argv', ['map_journey.py', '--scenario', 'interactions']), \
             patch.object(journey, 'run', return_value=2) as run:
            self.assertEqual(journey.main(), 2)
        self.assertEqual(run.call_args.args[1], 'interactions')

    def test_other_pane_in_multi_detail_is_not_selection(self):
        from map_interactions import selected_in_frame
        from test_map_frames import card_frame, native_fixture
        frame=card_frame(1); native=native_fixture()
        self.assertTrue(selected_in_frame(frame, 'w2:p1', native))
        self.assertFalse(selected_in_frame(frame, 'w2:p2', native))
        self.assertFalse(selected_in_frame(card_frame(2,False), 'w2:p2', native))

    def test_current_screen_erases_old_marker(self):
        import pyte
        screen = pyte.Screen(40, 8)
        stream = pyte.ByteStream(screen)
        stream.feed(b'OLD-END-MARKER\x1b[2J\x1b[HCURRENT')
        frame = '\n'.join(screen.display)
        self.assertIn('CURRENT', frame)
        self.assertNotIn('OLD-END-MARKER', frame)

    def test_incremental_utf8_and_cursor_update(self):
        import pyte
        screen = pyte.Screen(40, 8)
        stream = pyte.ByteStream(screen)
        marker = '› PANE exact [p2]'.encode()
        stream.feed(marker[:1]); stream.feed(marker[1:])
        self.assertIn('› PANE exact [p2]', '\n'.join(screen.display))
        stream.feed(b'\x1b[1;1H\x1b[2KOTHER PANE')
        self.assertNotIn('[p2]', '\n'.join(screen.display))

    def test_empty_log_is_distinct_from_missing_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); before = journey.log_digest(root)
            (root / 'backend-captures.jsonl').touch()
            self.assertNotEqual(before, journey.log_digest(root))


if __name__ == '__main__':
    unittest.main()
