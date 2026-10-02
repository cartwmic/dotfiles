"""Fail-closed migration helpers: complete current cells and native subjects."""
import unittest
import proof
from map_frames import canvas, contains, card, selected_in_frame


def native_fixture(workspace='w2', count=3):
    return {'panes': [{'pane_id': f'{workspace}:p{n}', 'terminal_id': f'terminal-{n}',
        'tab_id': f'{workspace}:t{n}', 'label': f'Subject {n}'} for n in range(1,count+1)],
        'tabs': [{'tab_id': f'{workspace}:t{n}', 'number': n, 'label': f'Subject {n}'} for n in range(1,count+1)]}


def card_frame(number=1, selected=True, subject=None):
    rows = ['┌────────────────────┐','│                    │',
        f'│ {"›" if selected else " "} Tab {number}            │',
        '│ '+(subject or f'Subject {number}').ljust(18)+' │','│                    │',
        '│ READY              │','│                    │','└────────────────────┘']
    return 'Herdr Overview\n!0 W0 R1 · 1ws 1t\n'+'\n'.join(rows)+'\nj/k select/scroll · n blocked · Esc/q'


class FrameTests(unittest.TestCase):
    def test_border_or_missing_footer_is_not_completed_canvas(self):
        for frame in ('┌Herdr Overview────┐', 'Herdr Overview\npartial', card_frame().replace('Esc/q','partial')):
            with self.assertRaises(proof.ProofFailure): canvas(frame)

    def test_outer_chrome_cannot_supply_body_marker(self):
        frame='SIDEBAR SECRET │Herdr Overview         │\nSIDEBAR SECRET │body                   │\nSIDEBAR SECRET │j/k Esc/q              │\n               └───────────────────────┘'
        self.assertTrue(contains(frame,'body'))
        self.assertFalse(contains(frame,'SECRET'))

    def test_wrapped_markers_ignore_only_border_and_spacing(self):
        self.assertTrue(contains('Herdr Overview\n│ END-MAR │\n│ KER     │\nj/k Esc/q','END-MARKER'))
        self.assertFalse(contains('Herdr Overview\n│ END-MAR │\n│ WRONG   │\nj/k Esc/q','END-MARKER'))

    def test_selected_subject_resolves_native_target_not_focus(self):
        native=native_fixture()
        native['focused_pane_id']='w2:p3'
        self.assertTrue(selected_in_frame(card_frame(1),'w2:p1',native))
        self.assertFalse(selected_in_frame(card_frame(1),'w2:p3',native))
        self.assertFalse(selected_in_frame(card_frame(1,False),'w2:p1',native))
        self.assertEqual(card(card_frame(1),'w2:p1',native)['rows'][3].strip(),'READY')

    def test_prefix_requires_ellipsis_and_missing_target_fails(self):
        native=native_fixture();native['tabs'][0]['label']='Subject 1 with a long ending'
        self.assertFalse(selected_in_frame(card_frame(1),'w2:p1',native))
        self.assertTrue(selected_in_frame(card_frame(1,subject='Subject 1…'),'w2:p1',native))
        with self.assertRaises(proof.ProofFailure): selected_in_frame(card_frame(1),'missing',native)

    def test_duplicate_matching_card_fails_closed(self):
        frame=card_frame(1).replace('\nj/k select/scroll', '\n'+card_frame(1).split('\n',2)[2].rsplit('\n',1)[0]+'\nj/k select/scroll')
        with self.assertRaises(proof.ProofFailure): card(frame,'w2:p1',native_fixture())
