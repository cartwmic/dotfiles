#!/usr/bin/env python3
"""Deterministic regression tests for bounded intent calibration."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPORT = HERE / "report.py"
WRAPPER = HERE / "judge_wrapper.py"
RUNNER = HERE / "executable_run.sh"
MANIFEST = HERE / "manifest.json"
CHECK_MANIFEST = HERE / "check_manifest.py"
ATTESTATION = HERE / "evidence" / "fidelity-attestation.json"
RUBRICS = "test-rubric-set"
AXIS_MODEL = "test/live-axis"
CONSENSUS_MODEL = "test/consensus"
EVIDENCE_SET = "test-evidence-set"
CANDIDATE = "sha256:test-candidate"


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stderr = self.root / "stderr.txt"
        self.stderr.write_text("")
        identity = "[rule=SC-INT-SA-001 condition=SC-INT-SA-001-PRODUCT-TARGET]"
        axis = {
            "axis": "solution-agnostic",
            "model": AXIS_MODEL,
            "passed": True,
            "reason": f"{identity} intent.json names product scope.",
            "rubrics": RUBRICS,
            "replayed": False,
        }
        consensus = {
            "model": CONSENSUS_MODEL,
            "passed": True,
            "reason": (
                f"{identity} [rule=SC-INT-DC-001 "
                "condition=SC-INT-DC-001-CORRECTLY-APPLIED-FINDING] finding stands."
            ),
            "rubrics": RUBRICS,
            "replayed": False,
            "axes": [
                {"axis": axis["axis"], "passed": axis["passed"], "reason": axis["reason"]}
            ],
        }
        self.response = {
            "kind": "verdicts",
            "verdicts": [
                {"gate_id": "intent-ready", "passed": True},
                {"gate_id": "intent-semantic", "passed": True},
            ],
            "evidence": [
                {"kind": "intent-judgment", "metadata": axis},
                {"kind": "intent-judgment-consensus", "metadata": consensus},
                {
                    "kind": "judge-rubrics",
                    "metadata": {
                        "gate_id": "intent-semantic",
                        "rubrics": RUBRICS,
                        "axis_model": AXIS_MODEL,
                        "consensus_model": CONSENSUS_MODEL,
                    },
                },
            ],
            "diagnostics": [],
        }
        self.manifest = json.loads(MANIFEST.read_text())

    def tearDown(self):
        self.temp.cleanup()

    def observe(self, response, *, case="sa-001-product-target", axis_model=AXIS_MODEL, route_log=None):
        response_path = self.root / "response.json"
        output_path = self.root / "observation.json"
        response_path.write_text(json.dumps({"result": response}))
        command = [
            "python3", str(REPORT), "observe",
            "--manifest", str(MANIFEST),
            "--case", case,
            "--mode", "targeted",
            "--attempt", "1",
            "--sequence", "1",
            "--response", str(response_path),
            "--stderr", str(self.stderr),
            "--output", str(output_path),
            "--axis-model", axis_model,
            "--consensus-model", CONSENSUS_MODEL,
            "--rubric-set", RUBRICS,
            "--provider-exit", "0",
            "--evidence-set-id", EVIDENCE_SET,
            "--candidate-id", CANDIDATE,
        ]
        if route_log is not None:
            command.extend(["--route-log", str(route_log)])
        completed = subprocess.run(command, text=True, capture_output=True)
        return completed, json.loads(output_path.read_text())

    def synthetic_record(self, case_id, attempt, classification="match", *, evidence_set=EVIDENCE_SET):
        case = next(case for case in self.manifest["cases"] if case["id"] == case_id)
        expected_axis = case["expected_axis"]["verdict"] == "pass"
        expected_final = case["expected_final"]["verdict"] == "pass"
        axis_identity = case["expected_axis"]
        if classification == "classification_variance":
            axis_identity = next(
                item["expected_axis"]
                for item in self.manifest["cases"]
                if item["selected_axis"] == case["selected_axis"]
                and item["expected_axis"]["verdict"] == "pass"
                and item["expected_axis"] != case["expected_axis"]
            )
        axis_passed = not expected_axis if classification == "verdict_mismatch" else expected_axis
        final_passed = not expected_final if classification == "verdict_mismatch" else expected_final
        axis_prefix = (
            "missing identity"
            if classification == "indeterminate"
            else f"[rule={axis_identity['rule']} condition={axis_identity['condition']}]"
        )
        axis = {
            "axis": case["selected_axis"],
            "model": AXIS_MODEL,
            "passed": axis_passed,
            "reason": f"{axis_prefix} synthetic axis.",
            "rubrics": RUBRICS,
            "replayed": False,
        }
        final_identity = case["expected_final"]
        final_axis_identity = axis_identity if classification == "classification_variance" else case["expected_final_axis"]
        consensus = {
            "model": CONSENSUS_MODEL,
            "passed": final_passed,
            "reason": (
                f"[rule={final_identity['rule']} condition={final_identity['condition']}] "
                f"[rule={final_axis_identity['rule']} condition={final_axis_identity['condition']}] "
                "synthetic consensus."
            ),
            "rubrics": RUBRICS,
            "replayed": False,
            "axes": [
                {"axis": axis["axis"], "passed": axis["passed"], "reason": axis["reason"]}
            ],
        }
        result = {
            "kind": "verdicts",
            "verdicts": [
                {"gate_id": "intent-ready", "passed": True},
                {"gate_id": "intent-semantic", "passed": final_passed},
            ],
            "evidence": [
                {"kind": "intent-judgment", "metadata": axis},
                {"kind": "intent-judgment-consensus", "metadata": consensus},
                {"kind": "judge-rubrics", "metadata": {
                    "gate_id": "intent-semantic",
                    "rubrics": RUBRICS,
                    "axis_model": AXIS_MODEL,
                    "consensus_model": CONSENSUS_MODEL,
                }},
            ],
            "diagnostics": [],
        }
        agreement = classification in {"match", "classification_variance"}
        return {
            "case": case_id,
            "lane": case["lane"],
            "mode": "targeted",
            "attempt": attempt,
            "sequence": self.manifest["release_core_cases"].index(case_id) * 3 + attempt,
            "evidence_set_id": evidence_set,
            "candidate_id": CANDIDATE,
            "observed_at": "2026-08-04T00:00:00+00:00",
            "classification": classification,
            "verdict_matches": agreement,
            "errors": [] if agreement else [classification],
            "notes": [],
            "expected_axis": case["expected_axis"],
            "expected_final_axis": case["expected_final_axis"],
            "expected_final": case["expected_final"],
            "observed_axis_verdict": axis_passed,
            "observed_final_verdict": final_passed,
            "requested_axis_model": AXIS_MODEL,
            "requested_consensus_model": CONSENSUS_MODEL,
            "rubric_set": RUBRICS,
            "provider_exit": 0,
            "response_path": "/tmp/response.json",
            "stderr_path": "/tmp/stderr.txt",
            "raw": {
                "provider_response_text": json.dumps({"result": result}),
                "stderr": "",
                "verdicts": {"intent-ready": True, "intent-semantic": final_passed},
                "axes": {case["selected_axis"]: axis},
                "consensus": consensus,
                "judge_rubrics": result["evidence"][2]["metadata"],
                "diagnostics": [],
                "routes": [],
            },
        }

    def write_release_records(self, overrides=None, *, evidence_set=EVIDENCE_SET):
        overrides = overrides or {}
        observations = self.root / "observations"
        for case_id in self.manifest["release_core_cases"]:
            case_dir = observations / case_id
            case_dir.mkdir(parents=True)
            for attempt in (1, 2, 3):
                classification = overrides.get((case_id, attempt), "match")
                record = self.synthetic_record(
                    case_id, attempt, classification, evidence_set=evidence_set
                )
                (case_dir / f"targeted-{attempt}.json").write_text(json.dumps(record))
        return observations

    def aggregate(
        self, profile, observations, *cases,
        evidence_set=EVIDENCE_SET, attestation=ATTESTATION,
    ):
        report = self.root / "run.json"
        command = [
            "python3", str(REPORT), "aggregate",
            "--profile", profile,
            "--manifest", str(MANIFEST),
            "--observations", str(observations),
            "--output", str(report),
            "--axis-model", AXIS_MODEL,
            "--consensus-model", CONSENSUS_MODEL,
            "--rubric-set", RUBRICS,
            "--evidence-set-id", evidence_set,
            "--candidate-id", CANDIDATE,
        ]
        if profile == "release-core" and attestation is not None:
            command.extend(["--attestation", str(attestation)])
        command.extend(cases)
        completed = subprocess.run(command, text=True, capture_output=True)
        return completed, json.loads(report.read_text())

    def test_valid_evidence_chain_matches(self):
        completed, observation = self.observe(self.response)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(observation["classification"], "match")
        self.assertTrue(observation["verdict_matches"])

    def test_declared_sibling_pass_is_classification_variance(self):
        response = copy.deepcopy(self.response)
        sibling = "[rule=SC-INT-SA-005 condition=SC-INT-SA-005-CAPABILITY-FENCE]"
        response["evidence"][0]["metadata"]["reason"] = f"{sibling} product capability fence."
        response["evidence"][1]["metadata"]["axes"][0]["reason"] = response["evidence"][0]["metadata"]["reason"]
        completed, observation = self.observe(response)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(observation["classification"], "classification_variance")
        self.assertTrue(observation["verdict_matches"])

    def test_wrong_verdict_is_verdict_mismatch(self):
        response = copy.deepcopy(self.response)
        response["verdicts"][1]["passed"] = False
        response["evidence"][0]["metadata"]["passed"] = False
        response["evidence"][1]["metadata"]["passed"] = False
        response["evidence"][1]["metadata"]["axes"][0]["passed"] = False
        completed, observation = self.observe(response)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(observation["classification"], "verdict_mismatch")
        self.assertFalse(observation["verdict_matches"])

    def test_unavailable_verdict_value_is_indeterminate(self):
        response = copy.deepcopy(self.response)
        response["evidence"][0]["metadata"]["passed"] = None
        response["evidence"][1]["metadata"]["axes"][0]["passed"] = None
        completed, observation = self.observe(response)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(observation["classification"], "indeterminate")

    def test_failed_intent_ready_is_indeterminate(self):
        response = copy.deepcopy(self.response)
        response["verdicts"][0]["passed"] = False
        completed, observation = self.observe(response)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(observation["classification"], "indeterminate")

    def test_binding_consensus_contradiction_is_indeterminate(self):
        response = copy.deepcopy(self.response)
        response["evidence"][1]["metadata"]["passed"] = False
        completed, observation = self.observe(response)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(observation["classification"], "indeterminate")

    def test_verdict_precedence_truth_table(self):
        spec = importlib.util.spec_from_file_location("intent_report_truth_table", REPORT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        rows = [
            (None, True, True, True, True, True, "indeterminate"),
            (False, True, True, True, True, True, "indeterminate"),
            (True, True, True, False, True, True, "indeterminate"),
            (True, False, True, True, True, True, "verdict_mismatch"),
            (True, True, False, False, True, True, "verdict_mismatch"),
            (True, True, True, True, True, True, "identity"),
            (True, False, True, True, False, True, "identity"),
        ]
        for row in rows:
            with self.subTest(row=row):
                self.assertEqual(module.verdict_stage(*row[:6])[0], row[6])

    def test_unknown_or_malformed_identity_is_indeterminate(self):
        response = copy.deepcopy(self.response)
        response["evidence"][0]["metadata"]["reason"] = "missing identity"
        response["evidence"][1]["metadata"]["axes"][0]["reason"] = "missing identity"
        completed, observation = self.observe(response)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(observation["classification"], "indeterminate")

    def test_malformed_provider_containers_are_retained_as_indeterminate(self):
        null_verdicts = copy.deepcopy(self.response)
        null_verdicts["verdicts"] = None
        null_evidence = copy.deepcopy(self.response)
        null_evidence["evidence"] = None
        scalar_evidence_item = copy.deepcopy(self.response)
        scalar_evidence_item["evidence"] = ["bad"]
        scalar_metadata = copy.deepcopy(self.response)
        scalar_metadata["evidence"][0]["metadata"] = "bad"
        malformed_diagnostic = {"kind": "evaluation_error", "diagnostics": ["bad"]}
        list_axis_id = copy.deepcopy(self.response)
        list_axis_id["evidence"][1]["metadata"]["axes"][0]["axis"] = ["bad"]
        list_axis_reason = copy.deepcopy(self.response)
        list_axis_reason["evidence"][0]["metadata"]["reason"] = ["bad"]
        list_axis_reason["evidence"][1]["metadata"]["axes"][0]["reason"] = ["bad"]
        list_consensus_reason = copy.deepcopy(self.response)
        list_consensus_reason["evidence"][1]["metadata"]["reason"] = ["bad"]
        rows = [
            ("null result", None),
            ("list result", []),
            ("null verdicts", null_verdicts),
            ("null evidence", null_evidence),
            ("scalar evidence item", scalar_evidence_item),
            ("scalar metadata", scalar_metadata),
            ("scalar diagnostic", malformed_diagnostic),
            ("list embedded axis id", list_axis_id),
            ("list axis reason", list_axis_reason),
            ("list consensus reason", list_consensus_reason),
        ]
        for name, response in rows:
            with self.subTest(name=name):
                (self.root / "observation.json").unlink(missing_ok=True)
                completed, observation = self.observe(response)
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(observation["classification"], "indeterminate")
                self.assertIn("provider_response_text", observation["raw"])

    def test_declared_failing_sibling_gets_no_variance_credit(self):
        case_id = "sa-001-implementation-location"
        record = self.synthetic_record(case_id, 1)
        response = json.loads(record["raw"]["provider_response_text"])["result"]
        sibling = "[rule=SC-INT-SA-002 condition=SC-INT-SA-002-INTERNAL-MECHANISM]"
        response["evidence"][0]["metadata"]["reason"] = f"{sibling} synthetic failing sibling."
        response["evidence"][1]["metadata"]["axes"][0]["reason"] = response["evidence"][0]["metadata"]["reason"]
        response["evidence"][1]["metadata"]["reason"] = (
            f"[rule=SC-INT-DC-001 condition=SC-INT-DC-001-CORRECTLY-APPLIED-FINDING] "
            f"{sibling} synthetic consensus."
        )
        completed, observation = self.observe(response, case=case_id)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(observation["classification"], "indeterminate")

    def test_duplicate_axis_evidence_is_indeterminate(self):
        response = copy.deepcopy(self.response)
        response["evidence"].insert(1, copy.deepcopy(response["evidence"][0]))
        completed, observation = self.observe(response)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(observation["classification"], "indeterminate")
        self.assertIn("expected exactly one solution-agnostic evidence record, found 2", observation["errors"])

    def test_release_qualifies_with_one_retained_mismatch_per_case(self):
        overrides = {
            (case_id, 3): "verdict_mismatch"
            for case_id in self.manifest["release_core_cases"]
        }
        completed, report = self.aggregate(
            "release-core", self.write_release_records(overrides)
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(report["qualification"], "qualified")
        self.assertEqual(sum(len(case["observations"]) for case in report["cases"]), 36)
        self.assertTrue(all(case["expected_verdict_count"] == 2 for case in report["cases"]))

    def test_release_qualifies_with_one_retained_indeterminate(self):
        case_id = self.manifest["release_core_cases"][0]
        completed, report = self.aggregate(
            "release-core",
            self.write_release_records({(case_id, 2): "indeterminate"}),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        case = next(item for item in report["cases"] if item["id"] == case_id)
        self.assertEqual(case["classification_counts"]["indeterminate"], 1)
        self.assertEqual(case["expected_verdict_count"], 2)

    def test_two_wrong_verdicts_fail_case_and_release(self):
        case_id = self.manifest["release_core_cases"][0]
        completed, report = self.aggregate(
            "release-core",
            self.write_release_records({
                (case_id, 1): "verdict_mismatch",
                (case_id, 2): "verdict_mismatch",
            }),
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(report["qualification"], "nonqualifying")
        case = next(item for item in report["cases"] if item["id"] == case_id)
        self.assertFalse(case["qualified"])

    def test_mixed_evidence_sets_cannot_qualify(self):
        observations = self.write_release_records()
        path = observations / self.manifest["release_core_cases"][0] / "targeted-3.json"
        record = json.loads(path.read_text())
        record["evidence_set_id"] = "replacement-run"
        path.write_text(json.dumps(record))
        completed, report = self.aggregate("release-core", observations)
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(any("evidence-set identity mismatch" in error for error in report["global_errors"]))

    def test_incomplete_cohort_cannot_qualify(self):
        observations = self.write_release_records()
        first = self.manifest["release_core_cases"][0]
        (observations / first / "targeted-3.json").unlink()
        completed, report = self.aggregate("release-core", observations)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(report["qualification"], "nonqualifying")

    def test_release_requires_supported_fidelity_attestation(self):
        completed, report = self.aggregate(
            "release-core", self.write_release_records(), attestation=None
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "release-core requires a fidelity attestation",
            report["global_errors"],
        )

    def test_verify_release_recomputes_majority(self):
        completed, report = self.aggregate("release-core", self.write_release_records())
        self.assertEqual(completed.returncode, 0)
        report["cases"][0]["observations"][0]["classification"] = "verdict_mismatch"
        report["cases"][0]["observations"][0]["verdict_matches"] = False
        report["cases"][0]["observations"][1]["classification"] = "verdict_mismatch"
        report["cases"][0]["observations"][1]["verdict_matches"] = False
        report_path = self.root / "tampered.json"
        report_path.write_text(json.dumps(report))
        verified = subprocess.run([
            "python3", str(REPORT), "verify-release", str(report_path),
            "--manifest", str(MANIFEST),
        ], text=True, capture_output=True)
        self.assertNotEqual(verified.returncode, 0)
        self.assertIn("lacks two expected verdicts", verified.stderr)
        self.assertIn("classification disagrees with retained raw evidence", verified.stderr)

    def test_aggregate_rejects_label_that_contradicts_raw_verdict(self):
        observations = self.write_release_records()
        case_id = self.manifest["release_core_cases"][0]
        path = observations / case_id / "targeted-1.json"
        record = json.loads(path.read_text())
        reply = json.loads(record["raw"]["provider_response_text"])
        semantic = next(
            item for item in reply["result"]["verdicts"]
            if item["gate_id"] == "intent-semantic"
        )
        semantic["passed"] = not semantic["passed"]
        consensus = next(
            item["metadata"] for item in reply["result"]["evidence"]
            if item["kind"] == "intent-judgment-consensus"
        )
        consensus["passed"] = semantic["passed"]
        record["raw"]["provider_response_text"] = json.dumps(reply)
        path.write_text(json.dumps(record))
        completed, report = self.aggregate("release-core", observations)
        self.assertNotEqual(completed.returncode, 0)
        case = next(item for item in report["cases"] if item["id"] == case_id)
        self.assertTrue(any(
            "classification disagrees with retained raw evidence" in error
            for error in case["errors"]
        ))

    def test_verify_release_binds_rows_to_case_summary(self):
        completed, report = self.aggregate("release-core", self.write_release_records())
        self.assertEqual(completed.returncode, 0)
        first = report["cases"][0]["observations"]
        second = report["cases"][1]["observations"]
        first[0], second[0] = second[0], first[0]
        report_path = self.root / "misbound.json"
        report_path.write_text(json.dumps(report))
        verified = subprocess.run([
            "python3", str(REPORT), "verify-release", str(report_path),
            "--manifest", str(MANIFEST),
        ], text=True, capture_output=True)
        self.assertNotEqual(verified.returncode, 0)
        self.assertIn("case does not match fixed release cohort", verified.stderr)

    def test_characterization_subset_completes_but_never_qualifies(self):
        case_id = self.manifest["release_core_cases"][0]
        observations = self.root / "characterization" / case_id
        observations.mkdir(parents=True)
        (observations / "targeted-1.json").write_text(
            json.dumps(self.synthetic_record(case_id, 1, "verdict_mismatch"))
        )
        completed, report = self.aggregate(
            "characterization", self.root / "characterization", case_id
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(report["qualification"], "characterization-complete")
        self.assertFalse(report["release_qualified"])

    def test_runner_refuses_existing_output_root_before_dispatch(self):
        output = self.root / "existing"
        output.mkdir()
        completed = subprocess.run(
            ["sh", str(RUNNER)],
            env=os.environ | {"SC_OUT": str(output), "SC_PROFILE": "characterization"},
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("artifacts are immutable", completed.stderr)

    def test_duplicate_route_multiplicity_is_indeterminate(self):
        axis_identity = "[rule=SC-INT-SA-002 condition=SC-INT-SA-002-INTERNAL-MECHANISM]"
        policy_identity = "[rule=SC-INT-DC-001 condition=SC-INT-DC-001-CORRECTLY-APPLIED-FINDING]"
        axis = {
            "axis": "solution-agnostic",
            "model": "intent-calibration/controlled-axis-v1",
            "passed": False,
            "reason": f"{axis_identity} internal mechanism.",
            "rubrics": RUBRICS,
            "replayed": False,
        }
        response = {
            "kind": "verdicts",
            "verdicts": [
                {"gate_id": "intent-ready", "passed": True},
                {"gate_id": "intent-semantic", "passed": False},
            ],
            "evidence": [
                {"kind": "intent-judgment", "metadata": axis},
                {"kind": "intent-judgment-consensus", "metadata": {
                    "model": CONSENSUS_MODEL,
                    "passed": False,
                    "reason": f"{axis_identity} {policy_identity} finding stands.",
                    "rubrics": RUBRICS,
                    "replayed": False,
                    "axes": [{"axis": axis["axis"], "passed": False, "reason": axis["reason"]}],
                }},
                {"kind": "judge-rubrics", "metadata": {
                    "gate_id": "intent-semantic",
                    "rubrics": RUBRICS,
                    "axis_model": axis["model"],
                    "consensus_model": CONSENSUS_MODEL,
                }},
            ],
            "diagnostics": [],
        }
        route = self.root / "routes.jsonl"
        records = [
            {"route": "intercepted", "model": axis["model"], "axis": axis["axis"]},
            {"route": "intercepted", "model": axis["model"], "axis": axis["axis"]},
            {"route": "intercepted", "model": axis["model"], "axis": axis["axis"]},
            {"route": "delegated", "model": CONSENSUS_MODEL, "axis": None},
        ]
        route.write_text("".join(json.dumps(record) + "\n" for record in records))
        completed, observation = self.observe(
            response,
            case="dc-correctly-applied",
            axis_model=axis["model"],
            route_log=route,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(observation["classification"], "indeterminate")
        self.assertIn(
            "expected one controlled solution-agnostic call, plus at most one provider retry; found 3",
            observation["errors"],
        )

    def test_unset_sc_bin_builds_candidate_before_describe(self):
        spec = importlib.util.spec_from_file_location("intent_check_manifest_test", CHECK_MANIFEST)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        binary = self.root / "software-change"
        binary.write_text("")
        module.DEFAULT_BIN = binary
        graph = {"states": []}
        replies = [
            mock.Mock(returncode=0, stdout="", stderr=""),
            mock.Mock(
                returncode=0,
                stdout=json.dumps({"result": {"kind": "description", "graph": graph}}),
                stderr="",
            ),
        ]
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SC_BIN", None)
            with mock.patch.object(module.subprocess, "run", side_effect=replies) as run:
                self.assertEqual(module.provider_graph(module.Problems()), graph)
        self.assertEqual(run.call_args_list[0].args[0][:4], ["cargo", "build", "--quiet", "--bin"])
        self.assertEqual(run.call_args_list[1].args[0], [str(binary)])

    def test_wrapper_intercepts_exact_controlled_axis(self):
        challenge = HERE / "challenges" / "dc-correctly-applied.json"
        route = self.root / "routes.jsonl"
        env = os.environ | {
            "SC_INTENT_CHALLENGE": str(challenge),
            "SC_INTENT_MODE": "targeted",
            "SC_INTENT_ROUTE_LOG": str(route),
            "SC_INTENT_REAL_CONSENSUS_MODEL": CONSENSUS_MODEL,
        }
        completed = subprocess.run([
            "python3", str(WRAPPER),
            "--model", "intent-calibration/controlled-axis-v1",
            "--system-prompt", "AXIS: solution-agnostic.",
        ], env=env, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout)["verdict"], "fail")
        self.assertEqual(json.loads(route.read_text())["route"], "intercepted")

    def test_wrapper_rejects_controlled_consensus_shape(self):
        route = self.root / "routes.jsonl"
        env = os.environ | {
            "SC_INTENT_ROUTE_LOG": str(route),
            "SC_INTENT_REAL_CONSENSUS_MODEL": CONSENSUS_MODEL,
        }
        completed = subprocess.run([
            "python3", str(WRAPPER),
            "--model", "intent-calibration/controlled-axis-v1",
            "--system-prompt", (
                "You are the DECIDING judge for a software-change INTENT. "
                "AXIS: solution-agnostic."
            ),
        ], env=env, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 64)
        self.assertIn("refusing to intercept consensus-shaped prompt", completed.stderr)


if __name__ == "__main__":
    unittest.main()
