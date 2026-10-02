"""Current popup/map navigation contract; old dedicated/preset cases migrated."""
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
