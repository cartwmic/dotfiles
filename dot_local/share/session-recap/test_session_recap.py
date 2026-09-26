from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CLI = REPO_ROOT / "dot_local" / "bin" / "executable_session-recap"
IMPLEMENTATION = REPO_ROOT / "dot_local" / "share" / "session-recap" / "session_recap.py"
FAKE_BACKEND = REPO_ROOT / "tests" / "herdr-overview" / "fake_recap_backend.py"
SUCCESS = "Recent work is complete. Present state: ready for the next step."


class SessionRecapCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base = Path(self.temp_dir.name)
        self.config_dir = self.base / "config" / "session-recap"
        self.data_dir = self.base / "data" / "session-recap"
        self.config_dir.mkdir(parents=True)
        self.capture = self.base / "backend-stdin"
        self.single_prompt = (
            REPO_ROOT / "dot_config" / "session-recap" / "single-prompt.md.tmpl"
        ).read_text(encoding="utf-8")
        self.group_prompt = (
            REPO_ROOT / "dot_config" / "session-recap" / "group-prompt.md.tmpl"
        ).read_text(encoding="utf-8")
        (self.config_dir / "single-prompt.md").write_text(self.single_prompt, encoding="utf-8")
        (self.config_dir / "group-prompt.md").write_text(self.group_prompt, encoding="utf-8")
        self.write_config("success")

    def environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env["XDG_CONFIG_HOME"] = str(self.base / "config")
        env["XDG_DATA_HOME"] = str(self.base / "data")
        env["FAKE_RECAP_CAPTURE"] = str(self.capture)
        return env

    def write_config(self, mode: str) -> None:
        command = [sys.executable, str(FAKE_BACKEND), mode]
        (self.config_dir / "config.toml").write_text(
            "command = " + json.dumps(command) + "\n", encoding="utf-8"
        )

    def run_cli(
        self,
        *args: str,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [str(CLI), *args],
            input=input_text,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.environment(),
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(f"CLI failed ({result.returncode}): {result.stderr}")
        return result

    def latest(self) -> dict:
        return json.loads((self.data_dir / "latest.json").read_text(encoding="utf-8"))

    def records(self) -> list[dict]:
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((self.data_dir / "records").glob("*/*.json"))
        ]

    def source_entry(self, source_kind: str, source_id: str) -> dict:
        return next(
            item
            for item in self.latest()["sources"]
            if item["source_kind"] == source_kind and item["source_id"] == source_id
        )

    def create_single(self, text: str) -> str:
        return self.run_cli("create", "--kind", "single", input_text=text).stdout.strip()

    def create_workspace_group(self, workspace_id: str, member_ids: list[str]) -> str:
        members = [
            {"text": f"Published input {index}", "record_id": record_id}
            for index, record_id in enumerate(member_ids, start=1)
        ]
        result = self.run_cli(
            "create",
            "--kind",
            "group",
            "--source-kind",
            "workspace",
            "--source-id",
            workspace_id,
            input_text=json.dumps({"members": members}),
        )
        return result.stdout.strip()

    def test_single_without_label_publishes_a_dated_record(self) -> None:
        text = "Fixed the café ordering flow; next, verify the receipt email."
        record_id = self.create_single(text)
        record = next(item for item in self.records() if item["record_id"] == record_id)

        self.assertRegex(record_id, r"^[0-9a-f]{32}$")
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["source_kind"], "manual")
        self.assertEqual(record["source_id"], record_id)
        self.assertEqual(record["kind"], "single")
        self.assertEqual(record["status"], "published")
        self.assertEqual(record["summary"], SUCCESS)
        self.assertNotIn("label", record)
        self.assertEqual(record["created_at"][:10], record["published_at"][:10])
        self.assertEqual(
            list((self.data_dir / "records" / record["created_at"][:10]).glob(f"{record_id}.json")),
            [self.data_dir / "records" / record["created_at"][:10] / f"{record_id}.json"],
        )
        self.assertIn(text, self.capture.read_text(encoding="utf-8"))
        entry = self.source_entry("manual", record_id)
        self.assertEqual(entry["latest_success_id"], record_id)
        self.assertEqual(entry["last_attempt_id"], record_id)

    def test_manual_group_and_coordinator_groups_retain_members_and_source_keys(self) -> None:
        first_id = self.create_single("Implemented the report export.")
        second_id = self.create_single("Added validation for the exported report.")
        manual_members = {
            "members": [
                {"text": "Implemented the report export.", "label": "Export", "record_id": first_id},
                {"text": "Added report validation.", "record_id": second_id},
            ]
        }
        manual_id = self.run_cli(
            "create", "--kind", "group", input_text=json.dumps(manual_members)
        ).stdout.strip()
        manual_record = next(item for item in self.records() if item["record_id"] == manual_id)
        self.assertEqual(manual_record["kind"], "group")
        self.assertEqual(manual_record["member_record_ids"], [first_id, second_id])
        self.assertIn("label: Export", self.capture.read_text(encoding="utf-8"))

        workspace_id = self.create_workspace_group("native-workspace-42", [first_id, second_id])
        session_id = self.run_cli(
            "create",
            "--kind",
            "group",
            "--source-kind",
            "herdr-session",
            "--source-id",
            "active",
            input_text=json.dumps(
                {"members": [{"text": "Current workspace recap", "record_id": workspace_id}]}
            ),
        ).stdout.strip()
        workspace_record = next(item for item in self.records() if item["record_id"] == workspace_id)
        session_record = next(item for item in self.records() if item["record_id"] == session_id)
        self.assertEqual(workspace_record["source_id"], "native-workspace-42")
        self.assertEqual(workspace_record["member_record_ids"], [first_id, second_id])
        self.assertEqual(session_record["source_kind"], "herdr-session")
        self.assertEqual(session_record["source_id"], "active")
        self.assertEqual(session_record["member_record_ids"], [workspace_id])

        # A separate CLI process reads the persisted source index before updating it.
        next_workspace_id = self.create_workspace_group("native-workspace-42", [first_id])
        entry = self.source_entry("workspace", "native-workspace-42")
        self.assertEqual(entry["latest_success_id"], next_workspace_id)
        self.assertEqual(entry["last_attempt_id"], next_workspace_id)
        self.assertTrue((self.data_dir / "records" / workspace_record["created_at"][:10] / f"{workspace_id}.json").is_file())
        self.assertEqual(workspace_record["member_record_ids"], [first_id, second_id])

    def test_blank_and_nonzero_attempts_do_not_replace_latest_success(self) -> None:
        member_id = self.create_single("Published member recap.")
        success_id = self.create_workspace_group("ws-failures", [member_id])
        entry = self.source_entry("workspace", "ws-failures")
        self.assertEqual(entry["latest_success_id"], success_id)

        for mode in ("blank", "nonzero"):
            self.write_config(mode)
            result = self.run_cli(
                "create",
                "--kind",
                "group",
                "--source-kind",
                "workspace",
                "--source-id",
                "ws-failures",
                input_text=json.dumps(
                    {"members": [{"text": "Published member recap.", "record_id": member_id}]}
                ),
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("session-recap:", result.stderr)
            entry = self.source_entry("workspace", "ws-failures")
            self.assertEqual(entry["latest_success_id"], success_id)
            self.assertNotEqual(entry["last_attempt_id"], success_id)
            failed = next(
                item for item in self.records() if item["record_id"] == entry["last_attempt_id"]
            )
            self.assertEqual(failed["status"], "failed")
            self.assertIn("failure", failed)

        self.assertEqual(self.source_entry("workspace", "ws-failures")["latest_success_id"], success_id)
        self.assertEqual(len(self.records()), 4)

    def test_prepare_publish_and_prompt_settle_are_separate_and_keep_optional_ids(self) -> None:
        session_id = "pi/session one"
        prepared_id = self.run_cli(
            "prepare",
            "--source-id",
            session_id,
            input_text="The Pi response has settled; publish only after workspace lookup.",
        ).stdout.strip()
        self.assertTrue((self.data_dir / "prepared" / f"{prepared_id}.json").is_file())
        self.assertFalse((self.data_dir / "latest.json").exists())

        self.run_cli("publish", "--prepared-id", prepared_id, "--workspace-id", "workspace-native-1")
        record = next(item for item in self.records() if item["record_id"] == prepared_id)
        self.assertEqual(record["source_kind"], "pi-session")
        self.assertEqual(record["source_id"], session_id)
        self.assertEqual(record["workspace_id"], "workspace-native-1")
        self.assertNotIn("pane_id", record)
        self.assertEqual(self.source_entry("pi-session", session_id)["latest_success_id"], prepared_id)

        second_prepared_id = self.run_cli(
            "prepare",
            "--source-id",
            "pi-session-with-pane",
            "--pane-id",
            "native-pane-2",
            input_text="A second settled response without workspace attribution.",
        ).stdout.strip()
        second_prepared = json.loads(
            (self.data_dir / "prepared" / f"{second_prepared_id}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(second_prepared["pane_id"], "native-pane-2")
        self.assertNotIn("workspace_id", second_prepared)
        self.run_cli("publish", "--prepared-id", second_prepared_id)
        second_record = next(item for item in self.records() if item["record_id"] == second_prepared_id)
        self.assertEqual(second_record["pane_id"], "native-pane-2")
        self.assertNotIn("workspace_id", second_record)

        prompt_path = self.data_dir / "prompts" / "pi%2Fsession%20one.json"
        prompt_text = "Investigate the open regression; do not confuse this with recap text."
        self.run_cli(
            "prompt", "set", "--session-id", session_id, input_text=prompt_text
        )
        working = json.loads(prompt_path.read_text(encoding="utf-8"))
        self.assertEqual(working["schema_version"], 1)
        self.assertEqual(working["session_id"], session_id)
        self.assertEqual(working["text"], prompt_text)
        self.assertTrue(working["working"])
        self.assertNotIn("pane_id", working)

        self.run_cli("prompt", "settle", "--session-id", session_id)
        settled = json.loads(prompt_path.read_text(encoding="utf-8"))
        self.assertEqual(settled["text"], prompt_text)
        self.assertEqual(settled["session_id"], session_id)
        self.assertFalse(settled["working"])
        self.assertGreaterEqual(settled["captured_at"], working["captured_at"])
        self.assertNotIn(prompt_text, record["summary"])

    def test_local_argv_override_and_both_editable_prompts_reach_backend(self) -> None:
        self.write_config("nonzero")
        override = [sys.executable, str(FAKE_BACKEND), "success"]
        (self.config_dir / "config.local.toml").write_text(
            "command = " + json.dumps(override) + "\n", encoding="utf-8"
        )
        (self.config_dir / "single-prompt.md").write_text(
            "host single [[LABEL]]\n[[TEXT]]\n", encoding="utf-8"
        )
        (self.config_dir / "group-prompt.md").write_text(
            "host group\n[[MEMBERS]]\n", encoding="utf-8"
        )

        self.run_cli("create", "--kind", "single", "--label", "label-a", input_text="text-a")
        self.assertEqual(self.capture.read_text(encoding="utf-8"), "host single label-a\ntext-a\n")

        group = {"members": [{"text": "text-b", "label": "label-b"}]}
        self.run_cli("create", "--kind", "group", input_text=json.dumps(group))
        self.assertEqual(
            self.capture.read_text(encoding="utf-8"),
            "host group\nMember 1 (label: label-b):\ntext-b\n",
        )

    def test_wrapper_uses_selected_python_when_a_hosted_agent_resets_path(self) -> None:
        env = self.environment()
        env["PATH"] = "/usr/bin:/bin"
        env["SESSION_RECAP_PYTHON"] = sys.executable
        result = subprocess.run(
            [str(CLI), "prompt", "set", "--session-id", "hosted-pi"],
            input="Current user prompt from Herdr-hosted Pi",
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = json.loads((self.data_dir / "prompts" / "hosted-pi.json").read_text(encoding="utf-8"))
        self.assertEqual(prompt["text"], "Current user prompt from Herdr-hosted Pi")

    def test_implementation_runs_under_python_and_cli_help_is_available(self) -> None:
        result = subprocess.run(
            [sys.executable, str(IMPLEMENTATION), "--help"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("prepare", result.stdout)
        self.assertIn("publish", result.stdout)


if __name__ == "__main__":
    unittest.main()
