"""Current popup/map navigation and independent saved-recap joins."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch
import proof
from test_map_frames import native_fixture, card_frame


def canvas(body='Synthetic workspace'):
    return 'Herdr Overview\n!0 W0 R1 · 1ws 1t\n' + body + '\nj/k select/scroll · n blocked · Esc/q'


class OverviewNavigationTest(unittest.TestCase):
    def test_overview_lifecycle_probe_uses_native_popup_allocation_not_pane_process(self):
        from map_journey import popup_busy
        with patch.object(proof, 'api_request', side_effect=proof.ProofFailure('ui_busy')):
            self.assertTrue(popup_busy({})[0])
        with patch.object(proof, 'api_request', return_value={'pane_id': None}) as request:
            self.assertFalse(popup_busy({})[0])
            self.assertEqual(request.call_args.args[2]['placement'], 'popup')

    def test_native_recap_lookup_projects_annotations_and_reads_terminal_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            day = data / 'records' / '2026-10-01'
            day.mkdir(parents=True)
            published = {'record_id': 'good', 'source_kind': 'pi', 'source_id': 'session',
                         'status': 'published', 'created_at': '2026-10-01T00:00:00Z',
                         'metadata': {'pi': {'nativeSessionId': 'session'}},
                         'annotations': {'herdr': {'pane_id': 'p1', 'workspace_id': 'w1'}}}
            failed = {**published, 'record_id': 'failed', 'status': 'failed',
                      'created_at': '2026-10-01T00:01:00Z', 'annotations': {}, 'attempt': 2}
            for record in (published, failed):
                (day / (record['record_id'] + '.json')).write_text(json.dumps(record))
            (data / 'latest.json').write_text(json.dumps({'sources': [{
                'source_kind': 'pi', 'source_id': 'session', 'latest_success_id': 'good',
                'last_attempt_id': 'good'}]}))
            latest, attempt = proof.read_latest_pi_record(data, 'p1')
            self.assertEqual((latest['source_id'], latest['pane_id'], latest['workspace_id']),
                             ('session', 'p1', 'w1'))
            self.assertEqual((attempt['record_id'], attempt['attempt']), ('failed', 2))
            self.assertEqual(json.loads((day / 'good.json').read_text()), published)


    def test_native_prompt_uses_overview_store_not_legacy_recap_store(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            recap = data / "session-recap"
            legacy = recap / "prompts"
            native = data / "herdr-overview" / "prompts"
            legacy.mkdir(parents=True)
            native.mkdir(parents=True)
            (legacy / "old.json").write_text(json.dumps({"pane_id": "p1", "text": "stale"}))
            current = {"pane_id": "p1", "text": "current", "working": True}
            (native / "current.json").write_text(json.dumps(current))
            self.assertEqual(proof.read_pi_prompt(recap, "p1"), current)
            self.assertIsNone(proof.read_pi_prompt(recap, "missing"))

    def test_reads_current_canvas_not_a_later_presenter_mention(self):
        self.assertEqual(proof.overview_location(canvas()), ('Map', 'all'))
        self.assertEqual(proof.overview_location(canvas('Latest good recap\nSubject 3')), ('Map', 'detail'))
        self.assertIsNone(proof.overview_location('old scrollback\nHerdr Overview · Mosaic'))

    def test_returns_from_digest_and_inline_detail_using_layered_escape(self):
        visible = [canvas('Session digest · Synthetic'), canvas('Latest good recap\nSubject 3'), canvas()]
        with patch.object(proof, 'invoke_overview'), patch.object(proof, 'overview_text', side_effect=visible), patch.object(proof, 'send_overview_key') as send:
            self.assertEqual(proof.overview_location(proof.return_to_all_workspaces({}, {})), ('Map', 'all'))
        self.assertEqual(send.call_args_list, [call({}, {}, 'esc'), call({}, {}, 'esc')])

    def test_opens_inline_detail_and_checks_selected_native_id(self):
        native=native_fixture('w1');detail=canvas('Subject 3\nLatest good recap')
        with patch.object(proof, 'return_to_all_workspaces'), patch.object(proof, 'snapshot', return_value=native), patch.object(proof, 'overview_text', side_effect=[card_frame(3),detail]), patch.object(proof, 'send_overview_key') as send:
            self.assertEqual(detail, proof.open_pane_from_workspace({}, {}, 'w1:p3'))
        send.assert_called_once_with({}, {}, 'enter')

    def test_exhaustive_native_order_reaches_moved_pane_across_tabs(self):
        visible=[card_frame(n) for n in (1,2,3)]+[canvas('Subject 3\nLatest good recap')]
        with patch.object(proof, 'return_to_all_workspaces'), patch.object(proof, 'snapshot', return_value=native_fixture()), patch.object(proof, 'overview_text', side_effect=visible), patch.object(proof, 'send_overview_key') as send:
            self.assertIn('Subject 3', proof.open_pane_from_workspace({}, {}, 'w2:p3'))
        self.assertEqual([c.args[2] for c in send.call_args_list], [']',']','enter'])

    def test_full_prompt_does_not_substitute_for_selected_native_identity(self):
        prompt='Synthetic complete prompt'
        with patch.object(proof, 'return_to_all_workspaces'), patch.object(proof, 'snapshot', return_value=native_fixture()), patch.object(proof, 'overview_text', return_value=card_frame(1)), patch.object(proof, 'send_overview_key'):
            with self.assertRaises(proof.ProofFailure):
                proof.open_pane_from_workspace({}, {}, 'w2:p3', lambda text: prompt in text)

    def test_multi_pane_detail_does_not_accept_unselected_member(self):
        native=native_fixture('w1');native['panes'][1]['tab_id']='w1:t1'
        frame=card_frame(1).replace('Tab 1','Pane ')
        with patch.object(proof, 'return_to_all_workspaces'), patch.object(proof, 'snapshot', return_value=native), patch.object(proof, 'overview_text', return_value=frame), patch.object(proof, 'send_overview_key'):
            with self.assertRaises(proof.ProofFailure): proof.open_pane_from_workspace({}, {}, 'w1:p2')

    def test_selects_workspace_by_member_card_without_preset(self):
        with patch.object(proof, 'snapshot', return_value={'panes':[{'pane_id':'w1:p1','workspace_id':'w1'}]}), patch.object(proof, 'open_pane_from_workspace') as open_pane, patch.object(proof, 'send_overview_key') as send, patch.object(proof, 'overview_text', return_value=canvas()):
            proof.select_workspace({}, {}, {'workspace_id':'w1'})
        open_pane.assert_called_once_with({}, {}, 'w1:p1'); send.assert_called_once_with({}, {}, 'esc')

    def test_published_recap_requires_inline_detail_and_full_wrapped_body(self):
        summary='Synthetic complete recap'
        frame=canvas('Latest good recap\nSubject 3\nLatest good recap\nSynthetic complete\nrecap')
        self.assertTrue(proof.published_recap_detail_visible(frame, summary))
        self.assertFalse(proof.published_recap_detail_visible(frame.replace('recap\n','wrong\n'), summary))
        self.assertFalse(proof.published_recap_detail_visible(canvas(summary), summary))

    def test_wrapped_public_content_uses_only_current_popup_canvas_not_native_chrome(self):
        body = ['Herdr Overview', 'Latest good recap', 'Subject 3',
                'Synthetic complete', 'recap', 'Supplied prompt',
                'Synthetic complete', 'current prompt', 'j/k select/scroll · Esc/q']
        frame = '\n'.join(f'{("Chrome" + str(n)):8}│{line:50}│' for n, line in enumerate(body))
        self.assertTrue(proof.published_recap_detail_visible(frame, 'Synthetic complete recap'))
        self.assertTrue(proof.current_prompt_detail_visible(frame, 'w2:p3', 'Synthetic complete current prompt', native_snapshot=native_fixture()))
        self.assertFalse(proof.published_recap_detail_visible(frame, 'Chrome3'))

    def test_current_prompt_requires_supplied_heading_full_content_and_id(self):
        prompt='Synthetic complete current prompt'
        frame=canvas('Subject 3\nLatest good recap\nSupplied prompt\n'+prompt)
        self.assertTrue(proof.current_prompt_detail_visible(frame, 'w2:p3', prompt, native_snapshot=native_fixture()))
        self.assertFalse(proof.current_prompt_detail_visible(frame, 'w1:p3', prompt, native_snapshot=native_fixture()))
        self.assertFalse(proof.current_prompt_detail_visible(frame.replace('current prompt\n','current\n'), 'w2:p3', prompt, native_snapshot=native_fixture()))

    def test_auto_name_uses_public_scoped_action_contexts(self):
        with patch.object(proof, 'api_request') as request:
            proof.invoke_auto_name({}, 'pane', 'w1:p3'); proof.invoke_auto_name({}, 'tab', 'w1:t2')
        self.assertEqual(request.call_args_list, [call({}, 'plugin.action.invoke', {'action_id':'overview.auto_name_pane','context':{'focused_pane_id':'w1:p3'}}), call({}, 'plugin.action.invoke', {'action_id':'overview.auto_name_tab','context':{'tab_id':'w1:t2'}})])

    def test_popup_open_is_passive_and_distinct_from_reconcile(self):
        with patch.object(proof, 'popup_client'), patch('map_identity.wait_frame'), patch.object(proof, 'api_request') as request:
            proof.invoke_overview({}, {})
        request.assert_called_once_with({}, 'plugin.action.invoke', {'action_id':'overview.open'})

if __name__ == '__main__': unittest.main()
