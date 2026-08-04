#!/usr/bin/env python3
"""Normalize intent observations and derive bounded release qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

AXES = [
    "solution-agnostic",
    "outside-verifiable",
    "scope-fenced",
    "constraints-are-limits",
    "problem-grounded",
]
IDENTITY = re.compile(r"\[rule=([^ ]+) condition=([^\]]+)\]")
CLASSIFICATIONS = {
    "match",
    "classification_variance",
    "verdict_mismatch",
    "indeterminate",
}
VERDICT_AGREEMENT = {"match", "classification_variance"}


def load(path):
    with open(path) as handle:
        return json.load(handle)


def identity_tuple(value):
    return value["rule"], value["condition"]


def identity_present(reason, expected):
    return identity_tuple(expected) in IDENTITY.findall(reason or "")


def leading_identity(reason):
    match = IDENTITY.match(reason or "")
    return match.groups() if match else None


def declared_pass_identities(manifest, axis):
    return {
        identity_tuple(case["expected_axis"])
        for case in manifest["cases"]
        if case["selected_axis"] == axis
        and case["expected_axis"]["verdict"] == "pass"
    }


def write_observation(args, case, category, errors, notes, raw, expected_final, expected_final_axis):
    observed_axis = (raw.get("axes", {}).get(case["selected_axis"]) or {}).get("passed")
    observed_final = raw.get("verdicts", {}).get("intent-semantic")
    observation = {
        "case": case["id"],
        "lane": case["lane"],
        "mode": args.mode,
        "attempt": args.attempt,
        "sequence": args.sequence,
        "evidence_set_id": args.evidence_set_id,
        "candidate_id": args.candidate_id,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "classification": category,
        "verdict_matches": category in VERDICT_AGREEMENT,
        "errors": errors,
        "notes": notes,
        "expected_axis": case["expected_axis"],
        "expected_final_axis": expected_final_axis,
        "expected_final": expected_final,
        "observed_axis_verdict": observed_axis,
        "observed_final_verdict": observed_final,
        "requested_axis_model": args.axis_model,
        "requested_consensus_model": args.consensus_model,
        "rubric_set": args.rubric_set,
        "provider_exit": args.provider_exit,
        "response_path": str(Path(args.response).resolve()),
        "stderr_path": str(Path(args.stderr).resolve()),
        "raw": raw,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(observation, indent=2) + "\n")
    marks = {
        "match": "ok",
        "classification_variance": "VAR",
        "verdict_mismatch": "MISS",
        "indeterminate": "????",
    }
    detail = "" if not errors else f" -- {errors[0]}"
    print(f"  {marks[category]:<4} {case['id']:<42} {args.mode} {args.attempt}{detail}")
    return 0 if category in VERDICT_AGREEMENT else 1


def classify(args):
    manifest = load(args.manifest)
    case = next(case for case in manifest["cases"] if case["id"] == args.case)
    expected_final = (
        case.get("expected_full_final", case["expected_final"])
        if args.mode == "all_axes"
        else case["expected_final"]
    )
    expected_final_axis = (
        case.get("expected_full_final_axis", case["expected_final_axis"])
        if args.mode == "all_axes"
        else case["expected_final_axis"]
    )
    errors = []
    notes = []
    routes = []
    raw = {
        "provider_response_text": "",
        "stderr": "",
        "verdicts": {},
        "axes": {},
        "consensus": None,
        "judge_rubrics": None,
        "diagnostics": [],
        "routes": routes,
    }

    try:
        raw["provider_response_text"] = Path(args.response).read_text()
        raw["stderr"] = Path(args.stderr).read_text()
        reply = json.loads(raw["provider_response_text"])
    except Exception as error:
        errors.append(f"malformed provider response: {error}")
        return write_observation(
            args, case, "indeterminate", errors, notes, raw,
            expected_final, expected_final_axis,
        )

    result = reply.get("result", {}) if isinstance(reply, dict) else {}
    diagnostics = result.get("diagnostics") or []
    raw["diagnostics"] = diagnostics
    if args.provider_exit != 0:
        errors.append(f"provider exited {args.provider_exit}")
    kind = result.get("kind")
    if kind == "evaluation_error":
        errors.extend(str(item.get("message", "")) for item in diagnostics)
        if not errors:
            errors.append("provider returned evaluation_error")
        return write_observation(
            args, case, "indeterminate", errors, notes, raw,
            expected_final, expected_final_axis,
        )
    if kind != "verdicts":
        errors.append(f"provider result kind is {kind!r}, expected verdicts")
        return write_observation(
            args, case, "indeterminate", errors, notes, raw,
            expected_final, expected_final_axis,
        )

    verdict_records = [row for row in result.get("verdicts", []) if isinstance(row, dict)]
    verdict_groups = {
        gate: [row for row in verdict_records if row.get("gate_id") == gate]
        for gate in ("intent-ready", "intent-semantic")
    }
    verdicts = {
        gate: rows[0].get("passed")
        for gate, rows in verdict_groups.items()
        if len(rows) == 1
    }
    evidence = result.get("evidence", []) if isinstance(result, dict) else []
    axis_records = {}
    consensus_records = []
    rubric_records = []
    for item in evidence:
        metadata = item.get("metadata") or {}
        if item.get("kind") == "intent-judgment" and metadata.get("axis"):
            axis_records.setdefault(metadata["axis"], []).append(metadata)
        elif item.get("kind") == "intent-judgment-consensus":
            consensus_records.append(metadata)
        elif item.get("kind") == "judge-rubrics" and metadata.get("gate_id") == "intent-semantic":
            rubric_records.append(metadata)
    axes = {axis: rows[0] for axis, rows in axis_records.items() if len(rows) == 1}
    consensus = consensus_records[0] if len(consensus_records) == 1 else None
    rubric_record = rubric_records[0] if len(rubric_records) == 1 else None
    raw.update({
        "verdicts": verdicts,
        "axes": axes,
        "consensus": consensus,
        "judge_rubrics": rubric_record,
    })

    expected_roster = [case["selected_axis"]] if args.mode == "targeted" else AXES
    for gate, rows in verdict_groups.items():
        if len(rows) != 1:
            errors.append(f"expected exactly one {gate} verdict, found {len(rows)}")
        elif not isinstance(rows[0].get("passed"), bool):
            errors.append(f"{gate} verdict is not boolean")
    for axis, rows in axis_records.items():
        if len(rows) != 1:
            errors.append(f"expected exactly one {axis} evidence record, found {len(rows)}")
        elif not isinstance(rows[0].get("passed"), bool):
            errors.append(f"{axis} evidence verdict is not boolean")
    if len(consensus_records) != 1:
        errors.append(f"expected exactly one consensus evidence record, found {len(consensus_records)}")
    elif not isinstance(consensus_records[0].get("passed"), bool):
        errors.append("consensus evidence verdict is not boolean")
    if len(rubric_records) != 1:
        errors.append(f"expected exactly one intent rubric evidence record, found {len(rubric_records)}")
    if set(axes) != set(expected_roster):
        errors.append(f"axis roster {sorted(axes)} != {sorted(expected_roster)}")

    selected = axes.get(case["selected_axis"])
    if not selected:
        errors.append("selected axis evidence missing")
    else:
        if selected.get("replayed"):
            errors.append("axis evidence replayed from cache")
        if selected.get("model") != args.axis_model:
            errors.append(f"axis model {selected.get('model')!r} != {args.axis_model!r}")
    if args.mode == "all_axes":
        for axis in AXES:
            if axis != case["selected_axis"] and not axes.get(axis, {}).get("passed"):
                errors.append(f"non-controlling axis {axis} did not pass")

    if not consensus:
        errors.append("consensus evidence missing")
    else:
        if consensus.get("replayed"):
            errors.append("consensus evidence replayed from cache")
        if consensus.get("model") != args.consensus_model:
            errors.append(
                f"consensus model {consensus.get('model')!r} != {args.consensus_model!r}"
            )
        embedded = consensus.get("axes")
        if not isinstance(embedded, list):
            errors.append("consensus embedded axis roster missing")
        else:
            embedded_by_axis = {
                row.get("axis"): row
                for row in embedded
                if isinstance(row, dict) and row.get("axis")
            }
            if len(embedded) != len(embedded_by_axis) or set(embedded_by_axis) != set(expected_roster):
                errors.append("consensus embedded axis roster is duplicate, missing, or unexpected")
            for axis, metadata in axes.items():
                row = embedded_by_axis.get(axis)
                if (
                    not row
                    or set(row) != {"axis", "passed", "reason"}
                    or not isinstance(row.get("passed"), bool)
                    or row.get("passed") != metadata.get("passed")
                    or row.get("reason") != metadata.get("reason")
                ):
                    errors.append(f"consensus embedded {axis} finding differs from outer axis evidence")

    for axis, metadata in axes.items():
        if metadata.get("rubrics") != args.rubric_set:
            errors.append(f"axis {axis} rubric identity mismatch")
    if consensus and consensus.get("rubrics") != args.rubric_set:
        errors.append("consensus rubric identity mismatch")
    if not rubric_record:
        errors.append("judge-rubrics evidence missing")
    else:
        if rubric_record.get("rubrics") != args.rubric_set:
            errors.append("judge-rubrics identity mismatch")
        if rubric_record.get("axis_model") != args.axis_model:
            errors.append("judge-rubrics axis model mismatch")
        if rubric_record.get("consensus_model") != args.consensus_model:
            errors.append("judge-rubrics consensus model mismatch")

    if args.route_log and Path(args.route_log).exists():
        for line in Path(args.route_log).read_text().splitlines():
            try:
                routes.append(json.loads(line))
            except json.JSONDecodeError:
                errors.append("route log contains malformed JSON")
    if case["lane"] == "challenge":
        delegated = [
            row for row in routes
            if row.get("route") == "delegated" and row.get("model") == args.consensus_model
        ]
        intercepted = [
            row for row in routes
            if row.get("route") == "intercepted" and row.get("model") == args.axis_model
        ]
        if not 1 <= len(delegated) <= 2:
            errors.append(
                "expected one delegated consensus call, plus at most one provider retry; "
                f"found {len(delegated)}"
            )
        fixture = load(Path(args.manifest).parent / case["fixture"])
        expected_intercepts = (
            {case["selected_axis"]}
            if args.mode == "targeted"
            else {
                axis for axis in AXES
                if not (axis == "constraints-are-limits" and "constraints" not in fixture)
            }
        )
        got_intercepts = {row.get("axis") for row in intercepted}
        if got_intercepts != expected_intercepts:
            errors.append(
                f"intercepted axes {sorted(got_intercepts)} != {sorted(expected_intercepts)}"
            )
        for axis in expected_intercepts:
            count = sum(row.get("axis") == axis for row in intercepted)
            if not 1 <= count <= 2:
                errors.append(
                    f"expected one controlled {axis} call, plus at most one provider retry; "
                    f"found {count}"
                )
        if any(row.get("route") not in {"delegated", "intercepted"} for row in routes):
            errors.append("route log contains unknown route")

    if errors:
        return write_observation(
            args, case, "indeterminate", errors, notes, raw,
            expected_final, expected_final_axis,
        )

    expected_axis_pass = case["expected_axis"]["verdict"] == "pass"
    expected_final_pass = expected_final["verdict"] == "pass"
    verdict_mismatches = []
    if selected.get("passed") != expected_axis_pass:
        verdict_mismatches.append("selected axis verdict mismatch")
    if verdicts.get("intent-semantic") != expected_final_pass:
        verdict_mismatches.append("binding intent-semantic verdict mismatch")
    if consensus.get("passed") != expected_final_pass:
        verdict_mismatches.append("consensus verdict mismatch")
    if verdict_mismatches:
        return write_observation(
            args, case, "verdict_mismatch", verdict_mismatches, notes, raw,
            expected_final, expected_final_axis,
        )

    selected_identity = leading_identity(selected.get("reason"))
    consensus_identities = set(IDENTITY.findall(consensus.get("reason") or ""))
    exact = (
        selected_identity == identity_tuple(case["expected_axis"])
        and identity_tuple(expected_final) in consensus_identities
        and identity_tuple(expected_final_axis) in consensus_identities
    )
    if exact:
        return write_observation(
            args, case, "match", [], notes, raw, expected_final, expected_final_axis
        )

    pass_identities = declared_pass_identities(manifest, case["selected_axis"])
    equivalent_pass = (
        expected_axis_pass
        and expected_final_pass
        and selected_identity in pass_identities
        and identity_tuple(expected_final) in consensus_identities
        and selected_identity in consensus_identities
    )
    if equivalent_pass:
        notes.append(
            "expected passing identity "
            f"{identity_tuple(case['expected_axis'])}, observed declared sibling pass {selected_identity}"
        )
        return write_observation(
            args, case, "classification_variance", [], notes, raw,
            expected_final, expected_final_axis,
        )

    if selected_identity is None:
        errors.append("selected axis reason lacks a leading rule/condition identity")
    elif selected_identity != identity_tuple(case["expected_axis"]):
        errors.append(
            f"selected identity {selected_identity} is not expected or an equivalent declared pass"
        )
    if identity_tuple(expected_final) not in consensus_identities:
        errors.append("consensus reason lacks expected policy identity")
    if identity_tuple(expected_final_axis) not in consensus_identities:
        errors.append("consensus reason lacks expected selected-axis identity")
    return write_observation(
        args, case, "indeterminate", errors, notes, raw,
        expected_final, expected_final_axis,
    )


def derive_release_classification(manifest, case, row):
    """Derive release classification again from retained raw provider bytes."""
    raw = row.get("raw")
    if not isinstance(raw, dict):
        return "indeterminate", None, None
    response_text = raw.get("provider_response_text")
    if not isinstance(response_text, str):
        return "indeterminate", None, None
    try:
        reply = json.loads(response_text)
    except Exception:
        return "indeterminate", None, None
    result = reply.get("result", {}) if isinstance(reply, dict) else {}
    if row.get("provider_exit") != 0 or result.get("kind") != "verdicts":
        return "indeterminate", None, None

    verdict_records = [item for item in result.get("verdicts", []) if isinstance(item, dict)]
    verdict_groups = {
        gate: [item for item in verdict_records if item.get("gate_id") == gate]
        for gate in ("intent-ready", "intent-semantic")
    }
    if any(len(items) != 1 for items in verdict_groups.values()):
        return "indeterminate", None, None
    if any(not isinstance(items[0].get("passed"), bool) for items in verdict_groups.values()):
        return "indeterminate", None, None
    verdicts = {gate: items[0].get("passed") for gate, items in verdict_groups.items()}

    evidence = result.get("evidence", []) if isinstance(result.get("evidence"), list) else []
    axis_records = {}
    consensus_records = []
    rubric_records = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") or {}
        if item.get("kind") == "intent-judgment" and metadata.get("axis"):
            axis_records.setdefault(metadata["axis"], []).append(metadata)
        elif item.get("kind") == "intent-judgment-consensus":
            consensus_records.append(metadata)
        elif item.get("kind") == "judge-rubrics" and metadata.get("gate_id") == "intent-semantic":
            rubric_records.append(metadata)
    selected_axis = case["selected_axis"]
    if (
        set(axis_records) != {selected_axis}
        or len(axis_records.get(selected_axis, [])) != 1
        or len(consensus_records) != 1
        or len(rubric_records) != 1
    ):
        return "indeterminate", None, verdicts.get("intent-semantic")

    selected = axis_records[selected_axis][0]
    consensus = consensus_records[0]
    rubric = rubric_records[0]
    if (
        not isinstance(selected.get("passed"), bool)
        or not isinstance(consensus.get("passed"), bool)
        or selected.get("replayed")
        or selected.get("model") != row.get("requested_axis_model")
        or selected.get("rubrics") != row.get("rubric_set")
        or consensus.get("replayed")
        or consensus.get("model") != row.get("requested_consensus_model")
        or consensus.get("rubrics") != row.get("rubric_set")
        or rubric.get("rubrics") != row.get("rubric_set")
        or rubric.get("axis_model") != row.get("requested_axis_model")
        or rubric.get("consensus_model") != row.get("requested_consensus_model")
    ):
        return "indeterminate", selected.get("passed"), verdicts.get("intent-semantic")

    embedded = consensus.get("axes")
    if not isinstance(embedded, list) or len(embedded) != 1:
        return "indeterminate", selected.get("passed"), verdicts.get("intent-semantic")
    embedded_selected = embedded[0]
    if (
        not isinstance(embedded_selected, dict)
        or set(embedded_selected) != {"axis", "passed", "reason"}
        or not isinstance(embedded_selected.get("passed"), bool)
        or embedded_selected.get("axis") != selected_axis
        or embedded_selected.get("passed") != selected.get("passed")
        or embedded_selected.get("reason") != selected.get("reason")
    ):
        return "indeterminate", selected.get("passed"), verdicts.get("intent-semantic")

    expected_axis_pass = case["expected_axis"]["verdict"] == "pass"
    expected_final_pass = case["expected_final"]["verdict"] == "pass"
    observed_axis = selected.get("passed")
    observed_final = verdicts.get("intent-semantic")
    if (
        observed_axis != expected_axis_pass
        or observed_final != expected_final_pass
        or consensus.get("passed") != expected_final_pass
    ):
        return "verdict_mismatch", observed_axis, observed_final

    selected_identity = leading_identity(selected.get("reason"))
    consensus_identities = set(IDENTITY.findall(consensus.get("reason") or ""))
    exact = (
        selected_identity == identity_tuple(case["expected_axis"])
        and identity_tuple(case["expected_final"]) in consensus_identities
        and identity_tuple(case["expected_final_axis"]) in consensus_identities
    )
    if exact:
        return "match", observed_axis, observed_final
    equivalent_pass = (
        expected_axis_pass
        and expected_final_pass
        and selected_identity in declared_pass_identities(manifest, selected_axis)
        and identity_tuple(case["expected_final"]) in consensus_identities
        and selected_identity in consensus_identities
    )
    if equivalent_pass:
        return "classification_variance", observed_axis, observed_final
    return "indeterminate", observed_axis, observed_final


def release_observation_errors(manifest, case, row, expected_sequence):
    label = f"{case['id']} attempt {row.get('attempt')}"
    errors = []
    expected_fields = {
        "case": case["id"],
        "lane": case["lane"],
        "mode": "targeted",
        "sequence": expected_sequence,
        "expected_axis": case["expected_axis"],
        "expected_final_axis": case["expected_final_axis"],
        "expected_final": case["expected_final"],
    }
    for field, expected in expected_fields.items():
        if row.get(field) != expected:
            errors.append(f"{label} {field} does not match fixed release cohort")
    derived, observed_axis, observed_final = derive_release_classification(manifest, case, row)
    if row.get("classification") != derived:
        errors.append(f"{label} classification disagrees with retained raw evidence")
    if row.get("verdict_matches") is not (derived in VERDICT_AGREEMENT):
        errors.append(f"{label} agreement flag disagrees with retained raw evidence")
    if row.get("observed_axis_verdict") != observed_axis:
        errors.append(f"{label} selected-axis verdict disagrees with retained raw evidence")
    if row.get("observed_final_verdict") != observed_final:
        errors.append(f"{label} final verdict disagrees with retained raw evidence")
    return errors


def fidelity_attestation_errors(attestation, manifest):
    errors = []
    if not isinstance(attestation, dict):
        return ["fidelity attestation must be an object"]
    if attestation.get("schema_version") != 1:
        errors.append("fidelity attestation schema_version must be 1")
    if attestation.get("disposition") != "supported":
        errors.append("fidelity attestation disposition must be supported")
    provenance = attestation.get("provenance")
    required_independence = {
        "intent-rubric-authorship",
        "manifest-authorship",
        "checker-authorship",
        "live-observation-authorship",
    }
    if not isinstance(provenance, dict) or provenance.get("independent") is not True:
        errors.append("fidelity attestation must declare independent provenance")
    elif set(provenance.get("independent_of", [])) != required_independence:
        errors.append("fidelity attestation independence boundary is incomplete")

    pairs = attestation.get("pairs")
    flattened = []
    if not isinstance(pairs, list) or len(pairs) != 6:
        errors.append("fidelity attestation must contain six boundary pairs")
        pairs = []
    for index, pair in enumerate(pairs, 1):
        if not isinstance(pair, dict):
            errors.append(f"fidelity attestation pair {index} is malformed")
            continue
        pass_case = pair.get("pass_case")
        fail_case = pair.get("fail_case")
        flattened.extend([pass_case, fail_case])
        if pair.get("disposition") != "supported":
            errors.append(f"fidelity attestation pair {index} is unsupported")
        if not isinstance(pair.get("boundary"), str) or not pair["boundary"].strip():
            errors.append(f"fidelity attestation pair {index} lacks boundary evidence")
        if not isinstance(pair.get("evidence"), str) or not pair["evidence"].strip():
            errors.append(f"fidelity attestation pair {index} lacks mapping evidence")
    if flattened != manifest["release_core_cases"]:
        errors.append("fidelity attestation pairs differ from fixed release cohort")

    reviews = attestation.get("source_reviews")
    if not isinstance(reviews, list) or not reviews:
        errors.append("fidelity attestation requires an independent source review")
        reviews = []
    for index, review in enumerate(reviews, 1):
        if not isinstance(review, dict):
            errors.append(f"fidelity source review {index} is malformed")
            continue
        if review.get("disposition") != "supported":
            errors.append(f"fidelity source review {index} is not supported")
        if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
            errors.append(f"fidelity source review {index} lacks reviewer provenance")
        if not isinstance(review.get("ref"), str) or not review["ref"].strip():
            errors.append(f"fidelity source review {index} lacks evidence reference")
        digest = review.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"fidelity source review {index} digest is malformed")
    return errors


def attestation_digest(attestation):
    canonical = json.dumps(attestation, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def aggregate(args):
    manifest = load(args.manifest)
    all_ids = [case["id"] for case in manifest["cases"]]
    core_ids = manifest["release_core_cases"]
    release = args.profile == "release-core"
    selected = core_ids if release else (args.cases or all_ids)
    global_errors = []
    attestation = None
    if release:
        if not args.attestation:
            global_errors.append("release-core requires a fidelity attestation")
        else:
            try:
                attestation = load(args.attestation)
            except Exception as error:
                global_errors.append(f"cannot load fidelity attestation: {error}")
            else:
                global_errors.extend(fidelity_attestation_errors(attestation, manifest))
    if release and args.cases:
        global_errors.append("release-core does not accept a case subset")
    if len(selected) != len(set(selected)):
        global_errors.append("selected cases contain duplicates")

    records = []
    malformed_paths = []
    for path in sorted(Path(args.observations).glob("*/*.json")):
        try:
            records.append(load(path))
        except Exception as error:
            malformed_paths.append(f"{path}: {error}")
    if malformed_paths:
        global_errors.extend(f"malformed observation: {item}" for item in malformed_paths)

    unexpected = sorted({row.get("case") for row in records if row.get("case") not in selected})
    if unexpected:
        global_errors.append(f"unexpected observation cases: {unexpected}")
    relevant = [row for row in records if row.get("case") in selected]
    keys = [(row.get("case"), row.get("mode"), row.get("attempt")) for row in relevant]
    if len(keys) != len(set(keys)):
        global_errors.append("observation case/mode/attempt keys are not unique")
    sequences = [row.get("sequence") for row in relevant]
    if len(sequences) != len(set(sequences)):
        global_errors.append("observation sequences are not unique")

    for row in relevant:
        if row.get("evidence_set_id") != args.evidence_set_id:
            global_errors.append(f"{row.get('case')} attempt {row.get('attempt')} evidence-set identity mismatch")
        if row.get("candidate_id") != args.candidate_id:
            global_errors.append(f"{row.get('case')} attempt {row.get('attempt')} candidate identity mismatch")
        if row.get("rubric_set") != args.rubric_set:
            global_errors.append(f"{row.get('case')} attempt {row.get('attempt')} rubric identity mismatch")
        if row.get("classification") not in CLASSIFICATIONS:
            global_errors.append(f"{row.get('case')} attempt {row.get('attempt')} classification invalid")
        if not isinstance(row.get("raw"), dict):
            global_errors.append(f"{row.get('case')} attempt {row.get('attempt')} raw evidence missing")
        if not isinstance(row.get("response_path"), str) or not row.get("response_path"):
            global_errors.append(f"{row.get('case')} attempt {row.get('attempt')} response path missing")
        if row.get("classification") in VERDICT_AGREEMENT and row.get("verdict_matches") is not True:
            global_errors.append(f"{row.get('case')} attempt {row.get('attempt')} agreement flag invalid")
        if row.get("classification") not in VERDICT_AGREEMENT and row.get("verdict_matches") is not False:
            global_errors.append(f"{row.get('case')} attempt {row.get('attempt')} disagreement flag invalid")

    by_case = {case_id: [] for case_id in selected}
    for row in relevant:
        by_case[row["case"]].append(row)

    summaries = []
    complete = not global_errors
    for case_id in selected:
        case = next(case for case in manifest["cases"] if case["id"] == case_id)
        rows = sorted(by_case[case_id], key=lambda row: row.get("attempt", 0))
        targeted = [row for row in rows if row.get("mode") == "targeted"]
        other_modes = [row for row in rows if row.get("mode") != "targeted"]
        required = 3 if release else 1
        errors = []
        if len(targeted) != required:
            errors.append(f"requires {required} targeted observations, found {len(targeted)}")
        if [row.get("attempt") for row in targeted] != list(range(1, required + 1)):
            errors.append(f"targeted attempts are not exactly 1..{required}")
        if other_modes:
            errors.append("non-targeted observations are not allowed in this profile")
        if release:
            case_offset = core_ids.index(case_id) * 3
            for row in targeted:
                attempt = row.get("attempt")
                expected_sequence = case_offset + attempt if isinstance(attempt, int) else None
                errors.extend(
                    release_observation_errors(manifest, case, row, expected_sequence)
                )
        agreement_count = sum(row.get("classification") in VERDICT_AGREEMENT for row in targeted)
        if release and agreement_count < 2:
            errors.append(f"requires two expected verdicts, found {agreement_count}")
        case_complete = not errors
        summaries.append({
            "id": case_id,
            "lane": case["lane"],
            "status": case["status"],
            "qualified": case_complete if release else False,
            "complete": case_complete,
            "expected_verdict_count": agreement_count,
            "classification_counts": dict(Counter(row.get("classification") for row in targeted)),
            "errors": errors,
            "observations": rows,
        })
        complete &= case_complete

    if release:
        if set(selected) != set(core_ids) or len(selected) != len(core_ids):
            global_errors.append("release-core selected cases differ from fixed cohort")
            complete = False
        if len(relevant) != 36:
            global_errors.append(f"release-core requires 36 observations, found {len(relevant)}")
            complete = False
        qualification = "qualified" if complete else "nonqualifying"
    else:
        qualification = "characterization-complete" if complete else "characterization-incomplete"

    report = {
        "schema_version": 2,
        "profile": args.profile,
        "qualification": qualification,
        "release_qualified": release and complete,
        "complete_cohort": release and complete,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_set_id": args.evidence_set_id,
        "candidate_id": args.candidate_id,
        "live_axis_model": args.axis_model,
        "challenge_axis_model": "intent-calibration/controlled-axis-v1",
        "consensus_model": args.consensus_model,
        "rubric_set": args.rubric_set,
        "fidelity_attestation": attestation if release else None,
        "fidelity_attestation_digest": (
            attestation_digest(attestation) if release and attestation is not None else None
        ),
        "targeted_attempts_required": 3 if release else 1,
        "all_axis_attempts_required": 0,
        "selected_cases": selected,
        "global_errors": global_errors,
        "cases": summaries,
    }
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"intent {args.profile}: {qualification} "
        f"({sum(case['complete'] for case in summaries)}/{len(selected)} complete cases)"
    )
    if release:
        return 0 if complete else 1
    return 0 if qualification == "characterization-complete" else 1


def release_report_errors(report, manifest):
    errors = []
    core_ids = manifest["release_core_cases"]
    if report.get("schema_version") != 2:
        errors.append("release report schema_version must be 2")
    if report.get("profile") != "release-core":
        errors.append("release report profile must be release-core")
    if report.get("selected_cases") != core_ids:
        errors.append("release report selected_cases differ from fixed cohort")
    if report.get("qualification") != "qualified" or report.get("release_qualified") is not True:
        errors.append("release report is not qualified")
    if report.get("global_errors"):
        errors.append("release report carries global errors")
    attestation = report.get("fidelity_attestation")
    errors.extend(fidelity_attestation_errors(attestation, manifest))
    if isinstance(attestation, dict):
        expected_digest = attestation_digest(attestation)
        if report.get("fidelity_attestation_digest") != expected_digest:
            errors.append("release report fidelity attestation digest mismatch")
    summaries = report.get("cases")
    if not isinstance(summaries, list) or [case.get("id") for case in summaries] != core_ids:
        errors.append("release report case summaries differ from fixed cohort")
        summaries = summaries if isinstance(summaries, list) else []
    records = []
    cases_by_id = {case["id"]: case for case in manifest["cases"]}
    for summary in summaries:
        summary_id = summary.get("id")
        rows = summary.get("observations")
        if not isinstance(rows, list):
            errors.append(f"{summary_id} observations missing")
            continue
        records.extend(rows)
        targeted = [row for row in rows if row.get("mode") == "targeted"]
        if len(targeted) != 3 or [row.get("attempt") for row in targeted] != [1, 2, 3]:
            errors.append(f"{summary_id} does not contain attempts 1..3")
        case = cases_by_id.get(summary_id)
        if case:
            case_offset = core_ids.index(summary_id) * 3
            for row in targeted:
                attempt = row.get("attempt")
                expected_sequence = case_offset + attempt if isinstance(attempt, int) else None
                errors.extend(
                    release_observation_errors(manifest, case, row, expected_sequence)
                )
        agreement = sum(row.get("classification") in VERDICT_AGREEMENT for row in targeted)
        if agreement < 2:
            errors.append(f"{summary.get('id')} lacks two expected verdicts")
        if summary.get("expected_verdict_count") != agreement:
            errors.append(f"{summary.get('id')} expected-verdict count disagrees with observations")
        if summary.get("qualified") is not True or summary.get("errors"):
            errors.append(f"{summary.get('id')} summary is nonqualifying")
    if len(records) != 36:
        errors.append(f"release report must retain 36 observations, found {len(records)}")
    keys = [(row.get("case"), row.get("mode"), row.get("attempt")) for row in records]
    if len(keys) != len(set(keys)):
        errors.append("release report observation keys are not unique")
    sequences = [row.get("sequence") for row in records]
    if len(sequences) != len(set(sequences)):
        errors.append("release report sequences are not unique")
    evidence_set = report.get("evidence_set_id")
    candidate = report.get("candidate_id")
    rubric = report.get("rubric_set")
    if not all(isinstance(value, str) and value for value in (evidence_set, candidate, rubric)):
        errors.append("release report identities must be nonempty strings")
    for row in records:
        label = f"{row.get('case')} attempt {row.get('attempt')}"
        if row.get("evidence_set_id") != evidence_set:
            errors.append(f"{label} evidence-set identity mismatch")
        if row.get("candidate_id") != candidate:
            errors.append(f"{label} candidate identity mismatch")
        if row.get("rubric_set") != rubric:
            errors.append(f"{label} rubric identity mismatch")
        if row.get("classification") not in CLASSIFICATIONS:
            errors.append(f"{label} classification invalid")
        if not isinstance(row.get("raw"), dict):
            errors.append(f"{label} raw evidence missing")
        if not isinstance(row.get("response_path"), str) or not row.get("response_path"):
            errors.append(f"{label} response path missing")
        expected_flag = row.get("classification") in VERDICT_AGREEMENT
        if row.get("verdict_matches") is not expected_flag:
            errors.append(f"{label} verdict-agreement flag invalid")
    return errors


def verify_release(args):
    report = load(args.report)
    manifest = load(args.manifest)
    errors = release_report_errors(report, manifest)
    for error in errors:
        print(f"release evidence: {error}", file=sys.stderr)
    if errors:
        return 1
    print(
        "release evidence: qualified fixed cohort, 12 cases, 36 retained observations, "
        f"candidate={report['candidate_id']} rubric={report['rubric_set']}"
    )
    return 0


def show(args):
    report = load(args.report)
    print(f"qualification: {report['qualification']}")
    print(f"candidate: {report.get('candidate_id')}")
    print(f"evidence set: {report.get('evidence_set_id')}")
    print(
        f"models: live-axis={report['live_axis_model']} "
        f"challenge-axis={report['challenge_axis_model']} consensus={report['consensus_model']}"
    )
    print(f"rubric set: {report['rubric_set']}")
    for error in report.get("global_errors", []):
        print(f"  REPORT ERROR: {error}")
    for case in report["cases"]:
        if report["profile"] == "release-core":
            mark = "PASS" if case["qualified"] else "FAIL"
        else:
            mark = "DONE" if case["complete"] else "MISS"
        print(
            f"  {mark} {case['id']} ({case['lane']}) "
            f"classes={case.get('classification_counts', {})}"
        )
        for error in case["errors"]:
            print(f"       {error}")
        if args.reasons:
            for observation in case["observations"]:
                print(
                    f"       {observation['mode']} {observation['attempt']}: "
                    f"{observation['classification']}"
                )
                for axis, data in observation.get("raw", {}).get("axes", {}).items():
                    print(f"         {axis}: {data.get('reason', '')}")
                consensus = observation.get("raw", {}).get("consensus") or {}
                if consensus:
                    print(f"         consensus: {consensus.get('reason', '')}")
    success = report["qualification"] in {"qualified", "characterization-complete"}
    return 0 if success else 1


def parser():
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)

    observe = sub.add_parser("observe")
    for name in (
        "manifest", "case", "mode", "response", "stderr", "output", "axis-model",
        "consensus-model", "rubric-set", "evidence-set-id", "candidate-id",
    ):
        observe.add_argument(f"--{name}", required=True)
    observe.add_argument("--attempt", type=int, required=True)
    observe.add_argument("--sequence", type=int, required=True)
    observe.add_argument("--provider-exit", type=int, required=True)
    observe.add_argument("--route-log")
    observe.set_defaults(func=classify)

    aggregate_parser = sub.add_parser("aggregate")
    for name in (
        "manifest", "observations", "output", "axis-model", "consensus-model",
        "rubric-set", "evidence-set-id", "candidate-id",
    ):
        aggregate_parser.add_argument(f"--{name}", required=True)
    aggregate_parser.add_argument(
        "--profile", choices=("release-core", "characterization"),
        default="characterization",
    )
    aggregate_parser.add_argument("--attestation")
    aggregate_parser.add_argument("cases", nargs="*")
    aggregate_parser.set_defaults(func=aggregate)

    verify = sub.add_parser("verify-release")
    verify.add_argument("report")
    verify.add_argument("--manifest", default=str(Path(__file__).with_name("manifest.json")))
    verify.set_defaults(func=verify_release)

    show_parser = sub.add_parser("show")
    show_parser.add_argument("report")
    show_parser.add_argument("--reasons", action="store_true")
    show_parser.set_defaults(func=show)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.func(arguments))
