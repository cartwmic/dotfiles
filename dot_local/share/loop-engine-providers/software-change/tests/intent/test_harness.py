#!/usr/bin/env python3
"""Deterministic regression tests for intent calibration evidence and routing."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import importlib.util

HERE = Path(__file__).resolve().parent
REPORT = HERE / "report.py"
WRAPPER = HERE / "judge_wrapper.py"
MANIFEST = HERE / "manifest.json"
CHECK_MANIFEST = HERE / "check_manifest.py"
RUBRICS = "test-rubric-set"
AXIS_MODEL = "test/live-axis"
CONSENSUS_MODEL = "test/consensus"


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stderr = self.root / "stderr.txt"
        self.stderr.write_text("")
        identity = "[rule=SC-INT-SA-001 condition=SC-INT-SA-001-PRODUCT-TARGET]"
        axis = {
            "axis": "solution-agnostic", "model": AXIS_MODEL, "passed": True,
            "reason": f"{identity} intent.json is named product scope.",
            "rubrics": RUBRICS, "replayed": False,
        }
        consensus = {
            "model": CONSENSUS_MODEL, "passed": True,
            "reason": f"{identity} [rule=SC-INT-DC-001 condition=SC-INT-DC-001-CORRECTLY-APPLIED-FINDING] finding stands.",
            "rubrics": RUBRICS, "replayed": False,
            "axes": [{"axis": axis["axis"], "passed": axis["passed"], "reason": axis["reason"]}],
        }
        self.response = {
            "kind": "verdicts",
            "verdicts": [{"gate_id": "intent-ready", "passed": True}, {"gate_id": "intent-semantic", "passed": True}],
            "evidence": [
                {"kind": "intent-judgment", "metadata": axis},
                {"kind": "intent-judgment-consensus", "metadata": consensus},
                {"kind": "judge-rubrics", "metadata": {
                    "gate_id": "intent-semantic", "rubrics": RUBRICS,
                    "axis_model": AXIS_MODEL, "consensus_model": CONSENSUS_MODEL,
                }},
            ],
            "diagnostics": [],
        }

    def tearDown(self):
        self.temp.cleanup()

    def observe(self, response, *, case="sa-001-product-target", axis_model=AXIS_MODEL, route_log=None):
        response_path = self.root / "response.json"
        output_path = self.root / "observation.json"
        response_path.write_text(json.dumps({"result": response}))
        command = [
            "python3", str(REPORT), "observe", "--manifest", str(MANIFEST),
            "--case", case, "--mode", "targeted", "--attempt", "1",
            "--sequence", "1", "--response", str(response_path), "--stderr", str(self.stderr),
            "--output", str(output_path), "--axis-model", axis_model,
            "--consensus-model", CONSENSUS_MODEL, "--rubric-set", RUBRICS, "--provider-exit", "0",
        ]
        if route_log is not None:
            command.extend(["--route-log", str(route_log)])
        completed = subprocess.run(command, text=True, capture_output=True)
        return completed, json.loads(output_path.read_text())

    def test_valid_evidence_chain_matches(self):
        completed, observation = self.observe(self.response)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(observation["classification"], "match")

    def test_smoke_aggregate_accepts_one_matching_targeted_observation(self):
        completed, observation = self.observe(self.response)
        self.assertEqual(completed.returncode, 0)
        observations = self.root / "observations" / "sa-001-product-target"
        observations.mkdir(parents=True)
        (observations / "targeted-1.json").write_text(json.dumps(observation))
        report = self.root / "run.json"
        aggregated = subprocess.run([
            "python3", str(REPORT), "aggregate", "--profile", "smoke",
            "--manifest", str(MANIFEST), "--observations", str(self.root / "observations"),
            "--output", str(report), "--axis-model", AXIS_MODEL,
            "--consensus-model", CONSENSUS_MODEL, "--rubric-set", RUBRICS,
            "sa-001-product-target",
        ], text=True, capture_output=True)
        self.assertEqual(aggregated.returncode, 0, aggregated.stderr)
        result = json.loads(report.read_text())
        self.assertEqual(result["qualification"], "diagnostic-pass")
        self.assertEqual(result["targeted_attempts_required"], 1)
        self.assertEqual(result["all_axis_attempts_required"], 0)
        self.assertFalse(result["complete_manifest"])

    def test_malformed_leading_identity_is_rejected(self):
        response = copy.deepcopy(self.response)
        response["evidence"][0]["metadata"]["reason"] = "rule=SC-INT-SA-001 condition=SC-INT-SA-001-PRODUCT-TARGET missing brackets"
        response["evidence"][1]["metadata"]["axes"][0]["reason"] = response["evidence"][0]["metadata"]["reason"]
        completed, observation = self.observe(response)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("selected axis reason does not begin with expected controlling identity", observation["errors"])

    def test_duplicate_axis_evidence_is_rejected(self):
        response = copy.deepcopy(self.response)
        response["evidence"].insert(1, copy.deepcopy(response["evidence"][0]))
        completed, observation = self.observe(response)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("expected exactly one solution-agnostic evidence record, found 2", observation["errors"])

    def test_duplicate_binding_verdict_is_rejected(self):
        response = copy.deepcopy(self.response)
        response["verdicts"].append({"gate_id": "intent-semantic", "passed": False})
        completed, observation = self.observe(response)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("expected exactly one intent-semantic verdict, found 2", observation["errors"])

    def test_consensus_axis_copy_must_match_outer_evidence(self):
        response = copy.deepcopy(self.response)
        response["evidence"][1]["metadata"]["axes"][0]["reason"] = "contradictory copied reason"
        completed, observation = self.observe(response)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("consensus embedded solution-agnostic finding differs from outer axis evidence", observation["errors"])

    def test_duplicate_route_multiplicity_is_rejected(self):
        axis_identity = "[rule=SC-INT-SA-002 condition=SC-INT-SA-002-INTERNAL-MECHANISM]"
        policy_identity = "[rule=SC-INT-DC-001 condition=SC-INT-DC-001-CORRECTLY-APPLIED-FINDING]"
        axis = {
            "axis": "solution-agnostic", "model": "intent-calibration/controlled-axis-v1",
            "passed": False, "reason": f"{axis_identity} internal mechanism.",
            "rubrics": RUBRICS, "replayed": False,
        }
        response = {
            "kind": "verdicts",
            "verdicts": [{"gate_id": "intent-ready", "passed": True}, {"gate_id": "intent-semantic", "passed": False}],
            "evidence": [
                {"kind": "intent-judgment", "metadata": axis},
                {"kind": "intent-judgment-consensus", "metadata": {
                    "model": CONSENSUS_MODEL, "passed": False,
                    "reason": f"{axis_identity} {policy_identity} finding stands.",
                    "rubrics": RUBRICS, "replayed": False,
                    "axes": [{"axis": axis["axis"], "passed": axis["passed"], "reason": axis["reason"]}],
                }},
                {"kind": "judge-rubrics", "metadata": {
                    "gate_id": "intent-semantic", "rubrics": RUBRICS,
                    "axis_model": axis["model"], "consensus_model": CONSENSUS_MODEL,
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
        completed, observation = self.observe(response, case="dc-correctly-applied", axis_model=axis["model"], route_log=route)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("expected one controlled solution-agnostic call, plus at most one provider retry; found 3", observation["errors"])

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
            mock.Mock(returncode=0, stdout=json.dumps({"result": {"kind": "description", "graph": graph}}), stderr=""),
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
            "SC_INTENT_CHALLENGE": str(challenge), "SC_INTENT_MODE": "targeted",
            "SC_INTENT_ROUTE_LOG": str(route), "SC_INTENT_REAL_CONSENSUS_MODEL": CONSENSUS_MODEL,
        }
        completed = subprocess.run([
            "python3", str(WRAPPER), "--model", "intent-calibration/controlled-axis-v1",
            "--system-prompt", "AXIS: solution-agnostic.",
        ], env=env, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout)["verdict"], "fail")
        self.assertEqual(json.loads(route.read_text())["route"], "intercepted")

    def test_wrapper_rejects_controlled_consensus_shape(self):
        route = self.root / "routes.jsonl"
        env = os.environ | {
            "SC_INTENT_ROUTE_LOG": str(route), "SC_INTENT_REAL_CONSENSUS_MODEL": CONSENSUS_MODEL,
        }
        completed = subprocess.run([
            "python3", str(WRAPPER), "--model", "intent-calibration/controlled-axis-v1",
            "--system-prompt", "You are the DECIDING judge for a software-change INTENT. AXIS: solution-agnostic.",
        ], env=env, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 64)
        self.assertIn("refusing to intercept consensus-shaped prompt", completed.stderr)


if __name__ == "__main__":
    unittest.main()
