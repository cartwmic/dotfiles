import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import proof


class ScriptedProviderLifecycleTest(unittest.TestCase):
    def test_starts_once_reuses_matching_record_and_refuses_dead_process(self):
        with tempfile.TemporaryDirectory(prefix="herdr-provider-test-") as directory:
            root = Path(directory).resolve()
            port = 43210
            provider = {
                "pid": 123,
                "root": str(root),
                "port": port,
                "url": f"http://127.0.0.1:{port}/v1",
                "release_file": str(root / "scripted-provider-release-first"),
            }
            (root / "scripted-provider-ready.json").write_text(json.dumps({
                "pid": provider["pid"], "root": str(root), "host": "127.0.0.1", "port": port,
            }), encoding="utf-8")
            state = {"run_id": "0123456789abcdef", "root": str(root)}

            with patch.object(proof, "start_scripted_provider", return_value=provider) as start, \
                    patch.object(proof, "provider_process_matches", return_value=True):
                self.assertEqual(proof.ensure_scripted_provider(root, state, {}), provider)
                self.assertEqual(proof.read_json(root / proof.PROOF_MARKER)["scripted_provider"], provider)
                self.assertEqual(proof.ensure_scripted_provider(root, state, {}), provider)
                start.assert_called_once_with(root, {})

            with patch.object(proof, "start_scripted_provider") as start, \
                    patch.object(proof, "provider_process_matches", return_value=False):
                with self.assertRaisesRegex(proof.ProofFailure, "not running or does not match"):
                    proof.ensure_scripted_provider(root, state, {})
                start.assert_not_called()

    def test_refuses_wrong_run_record_without_starting_replacement(self):
        with tempfile.TemporaryDirectory(prefix="herdr-provider-test-") as directory:
            root = Path(directory).resolve()
            state = {"scripted_provider": {"pid": 123, "root": str(root.parent)}}
            with patch.object(proof, "start_scripted_provider") as start:
                with self.assertRaisesRegex(proof.ProofFailure, "not scoped to this isolated run"):
                    proof.ensure_scripted_provider(root, state, {})
                start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
