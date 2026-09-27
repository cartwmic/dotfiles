import unittest
from unittest.mock import call, patch

import proof


class OverviewNavigationTest(unittest.TestCase):
    def test_reads_exact_current_header_not_a_later_presenter_mention(self):
        text = "\x1b[36mHerdr Overview\x1b[0m · Board · workspace\n" \
               "Herdr Overview · Mosaic was visible earlier"
        self.assertEqual(proof.overview_location(text), ("Board", "workspace"))
        self.assertEqual(proof.overview_location("Herdr Overview · Mosaic · workspace"), ("Mosaic", "workspace"))
        self.assertIsNone(proof.overview_location("old scrollback\nHerdr Overview · Mosaic"))

    def test_returns_from_board_detail_using_observed_headers(self):
        visible = [
            "Herdr Overview · Board · pane detail\nPane [w1:p2]",
            "Herdr Overview · Board · workspace\nAlpha [w1]",
            "Herdr Overview · Board\nAll workspaces",
        ]
        with patch.object(proof, "overview_text", side_effect=visible), \
                patch.object(proof, "send_overview_key") as send_key:
            result = proof.return_to_all_workspaces({}, {})
        self.assertEqual(proof.overview_location(result), ("Board", "all"))
        self.assertEqual(send_key.call_args_list, [call({}, {}, "esc"), call({}, {}, "esc")])

    def test_opens_board_pane_detail_and_checks_the_visible_native_id(self):
        visible = [
            "Herdr Overview · Board · workspace\nAlpha [w1]",
            "Herdr Overview · Board · pane detail\nPi task [w1:p3]",
        ]
        with patch.object(proof, "overview_text", side_effect=visible), \
                patch.object(proof, "send_overview_key") as send_key:
            result = proof.open_pane_from_workspace({}, {}, "w1:p3")
        self.assertEqual(proof.overview_location(result), ("Board", "detail"))
        send_key.assert_called_once_with({}, {}, "enter")

    def test_exhaustive_workspace_navigation_reaches_a_moved_pane_across_tabs(self):
        # Native active tab may be t2 while the overview cursor starts at t1.
        # The overview's own j sequence, not a native-tab offset, reaches t3.
        keys = []
        selected = 0
        level = "workspace"
        panes = ("w2:p1", "w2:p2", "w2:p3")

        def visible(_state, _env):
            header = "Herdr Overview · Board · pane detail" if level == "detail" else "Herdr Overview · Board · workspace"
            return f"{header}\nSelected [{panes[selected]}]"

        def key(_state, _env, value):
            nonlocal level, selected
            keys.append(value)
            if value == "enter":
                level = "detail"
            elif value == "esc":
                level = "workspace"
            elif value == "j":
                selected = (selected + 1) % len(panes)

        with patch.object(proof, "overview_text", side_effect=visible), \
                patch.object(proof, "send_overview_key", side_effect=key):
            result = proof.open_pane_from_workspace({}, {}, "w2:p3")
        self.assertIn("[w2:p3]", result)
        self.assertEqual(keys, ["enter", "esc", "j", "enter", "esc", "j", "enter"])

    def test_opens_mosaic_pane_detail(self):
        visible = [
            "Herdr Overview · Mosaic · workspace\nAlpha [w1]",
            "Herdr Overview · Mosaic · selected pane\nPi task [w1:p3]",
        ]
        with patch.object(proof, "overview_text", side_effect=visible), \
                patch.object(proof, "send_overview_key") as send_key:
            result = proof.open_pane_from_workspace({}, {}, "w1:p3")
        self.assertEqual(proof.overview_location(result), ("Mosaic", "detail"))
        send_key.assert_called_once_with({}, {}, "enter")

    def test_selects_workspace_in_board_without_assuming_mosaic(self):
        visible = [
            "Herdr Overview · Board\n› Pi [w1]",
            "Herdr Overview · Board · workspace\nPi [w1] · 2 tabs",
        ]
        state = {"fixture": {"workspaces": [{"workspace_id": "w1"}]}}
        workspace = {"workspace_id": "w1", "label": "Pi"}
        with patch.object(proof, "overview_text", side_effect=visible), \
                patch.object(proof, "send_overview_key") as send_key:
            result = proof.select_workspace(state, {}, workspace)
        self.assertEqual(proof.overview_location(result), ("Board", "workspace"))
        send_key.assert_called_once_with(state, {}, "enter")

    def test_current_prompt_detail_accepts_both_presenters_and_requires_full_visible_content(self):
        prompt = "After the move, report the complete current pane state."
        board = f"Herdr Overview · Board · pane detail\nPi [w2:p3]\nCurrent Pi prompt · settled\n{prompt}"
        mosaic = f"Herdr Overview · Mosaic · selected pane\nPi [w2:p3]\nCURRENT PI PROMPT\n{prompt}"
        self.assertTrue(proof.current_prompt_detail_visible(board, "w2:p3", prompt))
        self.assertTrue(proof.current_prompt_detail_visible(mosaic, "w2:p3", prompt))
        self.assertFalse(proof.current_prompt_detail_visible(board, "w1:p3", prompt))
        truncated = board.replace(prompt, prompt[:-8])
        self.assertFalse(proof.current_prompt_detail_visible(truncated, "w2:p3", prompt))

    def test_auto_name_proof_uses_public_scoped_pane_and_tab_action_contexts(self):
        with patch.object(proof, "api_request") as request:
            proof.invoke_auto_name({"socket_path": "/isolated/herdr.sock"}, "pane", "w1:p3")
            proof.invoke_auto_name({"socket_path": "/isolated/herdr.sock"}, "tab", "w1:t2")
        self.assertEqual(request.call_args_list, [
            call({"socket_path": "/isolated/herdr.sock"}, "plugin.action.invoke", {
                "action_id": "overview.auto_name_pane", "context": {"focused_pane_id": "w1:p3"},
            }),
            call({"socket_path": "/isolated/herdr.sock"}, "plugin.action.invoke", {
                "action_id": "overview.auto_name_tab", "context": {"tab_id": "w1:t2"},
            }),
        ])


if __name__ == "__main__":
    unittest.main()
