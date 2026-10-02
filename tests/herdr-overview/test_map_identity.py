"""Focused identity rejection and current-frame decoder cases."""
import copy
import os
import unittest
from unittest.mock import patch
from map_identity import verified_metadata, rendered_text, wait_frame, ready_map, own_section
import proof


class ReadinessTests(unittest.TestCase):
    def test_native_border_and_old_output_are_not_viewer_ready(self):
        class Client:
            output = b'j/k select/scroll n blocked'
            def __init__(self): self.frames = iter(['Herdr Overview', 'Herdr Overview\nj/k select/scroll n blocked Esc/q'])
            def frame(self): return next(self.frames)
        client = Client()
        opened = []
        def wait(predicate, *_args, **_kwargs):
            self.assertIsNone(predicate())
            return predicate()
        with patch.object(proof, 'wait_for', side_effect=wait):
            self.assertEqual(ready_map(client, lambda: opened.append(True)), 'Herdr Overview\nj/k select/scroll n blocked Esc/q')
        self.assertEqual(opened, [True])

    def test_body_must_belong_to_its_visible_header(self):
        frame = '› One subject\nOWN ONE\nTwo subject\nOWN TWO'
        self.assertTrue(own_section(frame, 'One subject', 'OWN ONE', ['Two subject']))
        self.assertTrue(own_section(frame, 'Two subject', 'OWN TWO', ['One subject']))
        self.assertFalse(own_section(frame, 'One subject', 'OWN TWO', ['Two subject']))
        self.assertFalse(own_section(frame, 'Missing subject', 'OWN TWO', ['One subject','Two subject']))

    def test_all_current_markers_are_required(self):
        class Client:
            def frame(self): return 'CURRENT UUID only'
        with patch.object(proof, 'wait_for', side_effect=lambda predicate, *_args, **_kwargs: predicate()):
            self.assertIsNone(wait_frame(Client(), 'CURRENT UUID', 'NEW DIGEST'))


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {'panes': [{'pane_id': 'native-p', 'terminal_id': 'native-t'}]}
        self.record = {'schemaVersion': 1, 'socketPath': '/synthetic.sock',
            'terminalId': 'native-t', 'sessionId': '11111111-2222-3333-4444-555555555555',
            'publisherPid': os.getpid()}

    def joined(self, records=None):
        return verified_metadata(self.snapshot, records if records is not None else [self.record], '/synthetic.sock')

    def test_current_live_unique_terminal(self):
        self.assertEqual(len(self.joined()), 1)
        self.snapshot['panes'][0]['pane_id'] = 'rekeyed'
        self.assertEqual(self.joined()[0][0]['pane_id'], 'rekeyed')

    def test_wrong_socket_terminal_invalid_uuid_and_dead_publisher(self):
        for key, value in [('socketPath', '/wrong.sock'), ('terminalId', 'wrong'),
                           ('sessionId', 'synthetic-name-not-uuid'), ('publisherPid', -1)]:
            record = dict(self.record, **{key: value})
            self.assertEqual(self.joined([record]), [])

    def test_duplicate_records_and_terminals_rejected(self):
        self.assertEqual(self.joined([self.record, copy.deepcopy(self.record)]), [])
        self.snapshot['panes'].append({'pane_id': 'other', 'terminal_id': 'native-t'})
        self.assertEqual(self.joined(), [])

    def test_native_session_conflict_rejected(self):
        self.snapshot['panes'][0]['agent_session'] = 'wrong'
        self.assertEqual(self.joined(), [])

    def test_cell_updates_reconstruct_marker(self):
        self.assertIn('BODY-END', rendered_text(b'\x1b[3;2HBODY-OLD\x1b[3;7HEND'))
        self.assertNotIn('BODY-OLD', rendered_text(b'\x1b[3;2HBODY-OLD\x1b[3;7HEND'))

    def test_erase_rejects_old_frame(self):
        self.assertNotIn('OLD', rendered_text(b'OLD\x1b[2J\x1b[1;1HNEW'))
        self.assertNotIn('OLD', rendered_text(b'OLD\x1b[1;1H\x1b[2KNEW'))

    def test_unknown_cursor_operation_fails_closed(self):
        with self.assertRaises(proof.ProofFailure):
            rendered_text(b'\x1b[2A')


if __name__ == '__main__':
    unittest.main()
