#!/usr/bin/env python3
"""Deterministic conformance check for intent release corpus. No model calls."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MANIFEST = HERE / "manifest.json"
DEFAULT_BIN = ROOT / "target/debug/software-change"
AXES = [
    "solution-agnostic",
    "outside-verifiable",
    "scope-fenced",
    "constraints-are-limits",
    "problem-grounded",
]
OVERVIEW_SHA256 = "d83372371efa243dd524f629f3abd2c662e8bdadb85cdbd7e639a981acc8c8f4"
BRANCH = re.compile(
    r"^RULE (SC-INT-[A-Z]+-\d{3}) / CONDITION (SC-INT-[A-Z]+-\d{3}-[A-Z0-9-]+) "
    r"/ VERDICT (PASS|FAIL|AFFIRM|CORRECT|FORBIDDEN) / REASON ([^\n]+?) / FIELDS ([^\n]+)\.$",
    re.M,
)
IDENTITY = re.compile(r"^\[rule=([^ ]+) condition=([^\]]+)\]")

# Accepted reviewed corpus anchors. Unique bytes do not prove semantic isolation;
# these hashes prevent silent fixture drift after live full-roster review.
ACCEPTED_FIXTURE_DIGESTS = {'cases/sa-001-product-target.json': '26501060a8fb425fab462276ef446321ad75c40aacb25b525851430b25c6ddbb',
 'cases/sa-001-implementation-location.json': 'c44eec9e630673d3464479fdbca36ee6465d45149efc33c7e8aa7dce2a91d918',
 'cases/sa-002-observable-behavior.json': '831e8d6af20fa457072148f5aae70440c86feb4c674dff58f1a45722b2f299f1',
 'cases/sa-002-externally-imposed-mechanism.json': '3a9ad8393be16b38231533e9033bdd3d437274fb6ecdfc18e3fadb2339461c20',
 'cases/sa-002-internal-mechanism.json': 'd0380cff0908e1c494b872d3b1d92db8dc735f2e6ffe1bd163f74a98785e1415',
 'cases/sa-003-public-contract.json': '9bb4c3b86ea4b0c326bd9c72d7f405f5f06bd30173066818efcaf01c781f044d',
 'cases/sa-003-incidental-channel.json': '43bfa06074e51bfe975d535c7d6f85ec1877a1a74b8836f74d7a5e98a6d250ee',
 'cases/sa-004-named-preservation.json': '56f12167fefe0a43d3457391d00c417172bdb0ff4715c4a5ea794803eb3df17a',
 'cases/sa-005-capability-fence.json': '35ed02856c1f005b4b3afcfff244f96ebbf1323c7bcff9e368532dbda6b671b5',
 'cases/sa-005-mechanism-ban.json': 'dd301da06f9170591cc638419b2fc7f307be331bc177f8999e9326ce7d59029d',
 'cases/ov-001-release-property.json': '8bcfbbdfef39f5a611ec7b334831e3797db1204e894d53b082edbef2c4bccd0b',
 'cases/ov-001-work-instruction.json': '72ab2927dc88f1bb04cff7267fd04f9cdb2aa0fb068303c0c180747e6b67c9ac',
 'cases/ov-002-defined-result.json': '02312b2ea9fc48188c7c8f3396f15e9b1317e3cec6302a26b6feb557c378d9f4',
 'cases/ov-002-undefined-qualifier.json': '6f84afcd281c5c144c5b35ba328f52d95dbb334f69e93eaac00b81ae2f287327',
 'cases/ov-003-named-regression.json': '48ad668c37607058a5bc1138f377025455d8608be2afe89cbb667f8ff3781637',
 'cases/ov-003-universal-not-relied.json': '1380e6fb986f8e2070bf56c39c25ee2673228a65a3c5243a301b09284e479a84',
 'cases/ov-003-universal-relied.json': '066bf1887e76bc9ee1fde772ee39aa08b6f54afebe1c4e92bdae2efd99c081a0',
 'cases/sf-001-closed-empty-scope.json': '122605988c734f3c94bb06292464573becda66fd6d5c77c1775a05c1464dae94',
 'cases/sf-001-open-empty-scope.json': '43e318cb69e25095741723614c895320830c4dd2a53bb83082f65c3f4f0fae71',
 'cases/sf-002-effective-fence.json': '8b00f0b732ac319c4bf967dc41153d565b5dace9e44cf92331f54f4389fc3711',
 'cases/sf-002-vacuous-fence.json': '96180547109f96dc82b49205607ce5ac9a0792ffe46a9b53c911457a687b529c',
 'cases/sf-003-identifiable-scope.json': 'b16303990c39575db0f49dd71dcf64916d86b1b9f8ca689390eec72dfe7b9520',
 'cases/sf-003-ungrounded-referent.json': 'e182d9b6ee009a603fe303d6525d0100ae9acb4b5ab45b364b43da1ae7b8435a',
 'cases/sf-004-capability-scope.json': '2f654865f7b0095642b6c18019dfcc392601d17b3d2d3544021dbd805dc3b4d5',
 'cases/sf-004-task-list.json': 'e5b7e39808b9cf2ffeaed8495ba8e5d14af8b83f5fbd993299db1808181d9617',
 'cases/cl-001-no-constraints.json': 'bf65964d6a846aeb31f4e3a98ef12df552d9927dc3387fbd2572d04a70c9bf54',
 'cases/cl-002-external-limit.json': 'a06d2139c4b711bc883ff38936690cf5b878854b62eab415bce42b427b0dbf52',
 'cases/cl-002-solution-preference.json': 'cfda462518a91373c39f40a7b2cc0ab5bd221a0922dac2ef784fa66d386562eb',
 'cases/cl-003-property-limit.json': '273686cb3520329a2ca878f179743e60f5cff35963e4c90f7a2f801b7854e28e',
 'cases/cl-003-sourced-mechanism.json': '718846cde4b63c07f2ef7879269942198a0a777a66b9a9719d1694fe145f4b09',
 'cases/cl-003-unsourced-mechanism.json': '61777da2049e99161bab7e5cb54816c257d76fc07b4094ccfe1dd952e05e3518',
 'cases/pg-001-grounded-consequence.json': '9a74f791cb066d74ac08515df89dffe881b24d7a2cfd54363c2c80b22f47c468',
 'cases/pg-001-code-fact.json': '4a4d40c772e98f16548a70b24f6050268df36349f600401c507fddb9f3425ee7',
 'cases/pg-002-problem-only.json': 'd9accae1daf4f4b675990db45afbcf8c0de59bc92b22dc4880b035cada34320d',
 'cases/pg-002-work-or-solution.json': '11622f2c2e14f29a31c4005c5460311568bd1a3235fb21985caeaac5aeae464a',
 'cases/pg-003-identifiable-party-situation.json': '7ada0ef9ce6a204a33cd081b96b278027c1e4ffb8c830ce2eda9857f3edae2b4',
 'cases/pg-003-generic-placeholder.json': 'cd1060ce0ddd0176acbe41ab2ec9f59f1b1979bc651cbd37fd4d8176ebdbf0b9',
 'cases/ho-001-outcome-misses-problem.json': 'dc240edf7f1be8f9fbc2f5ea339cdc080cc62c358f260b24a76db8bd5e70a506',
 'cases/ho-002-acceptance-misses-outcome.json': 'c5640402e3f3de78478d91aa80d5d2181bac25696ee3589863f84ccbabd14139',
 'cases/ho-003-field-contradiction.json': '72b783ddd62e8a875edef2a917e700e0ccee7b6a4a4b68206b497cfe4c2b8e30',
 'cases/ho-005-judge-manipulation.json': '00e895ced45d4cc97d75fb21123937fad619afa217062db24e97039619b1d89b'}
ACCEPTED_CHALLENGE_DIGESTS = {'challenges/dc-correctly-applied.json': 'b6495b75eff766ef60e35c0bedfdbcca29158d1060c62074e060453842229ab9',
 'challenges/dc-category-error.json': '6c622736157b56d1f664fb56f21b93ced6f8e2b0640e4aa1eaa593742eca03bf',
 'challenges/dc-defect-waiver.json': '6b510d28794eb34a890df863e2eb32c670a149bf6d014b2b106cf9c14c8ed754',
 'challenges/ho-004-hidden-work.json': 'e656d2f7650082425447c767ed16aba2d1f9132bb8b424e623a2ea51e504c6e8'}

# Independent accepted-release anchor. Removing executable authority and its
# manifest row together must still fail this checker.
REQUIRED_CONDITIONS = {
    "SC-INT-SA-001-PRODUCT-TARGET", "SC-INT-SA-001-IMPLEMENTATION-LOCATION",
    "SC-INT-SA-002-OBSERVABLE-BEHAVIOR", "SC-INT-SA-002-EXTERNALLY-IMPOSED-MECHANISM",
    "SC-INT-SA-002-INTERNAL-MECHANISM", "SC-INT-SA-003-PUBLIC-CONTRACT",
    "SC-INT-SA-003-INCIDENTAL-CHANNEL", "SC-INT-SA-004-NAMED-PRESERVATION",
    "SC-INT-SA-005-CAPABILITY-FENCE", "SC-INT-SA-005-MECHANISM-BAN",
    "SC-INT-OV-001-RELEASE-PROPERTY", "SC-INT-OV-001-WORK-INSTRUCTION",
    "SC-INT-OV-002-DEFINED-RESULT", "SC-INT-OV-002-UNDEFINED-QUALIFIER",
    "SC-INT-OV-003-NAMED-REGRESSION", "SC-INT-OV-003-UNIVERSAL-NOT-RELIED",
    "SC-INT-OV-003-UNIVERSAL-RELIED", "SC-INT-SF-001-CLOSED-EMPTY-SCOPE",
    "SC-INT-SF-001-OPEN-EMPTY-SCOPE", "SC-INT-SF-002-EFFECTIVE-FENCE",
    "SC-INT-SF-002-VACUOUS-FENCE", "SC-INT-SF-003-IDENTIFIABLE-SCOPE",
    "SC-INT-SF-003-UNGROUNDED-REFERENT", "SC-INT-SF-004-CAPABILITY-SCOPE",
    "SC-INT-SF-004-TASK-LIST", "SC-INT-CL-001-NO-CONSTRAINTS",
    "SC-INT-CL-002-EXTERNAL-LIMIT", "SC-INT-CL-002-SOLUTION-PREFERENCE",
    "SC-INT-CL-003-PROPERTY-LIMIT", "SC-INT-CL-003-SOURCED-MECHANISM",
    "SC-INT-CL-003-UNSOURCED-MECHANISM", "SC-INT-PG-001-GROUNDED-CONSEQUENCE",
    "SC-INT-PG-001-CODE-FACT", "SC-INT-PG-002-PROBLEM-ONLY",
    "SC-INT-PG-002-WORK-OR-SOLUTION", "SC-INT-PG-003-IDENTIFIABLE-PARTY-SITUATION",
    "SC-INT-PG-003-GENERIC-PLACEHOLDER", "SC-INT-DC-001-CORRECTLY-APPLIED-FINDING",
    "SC-INT-DC-002-DEMONSTRATED-CATEGORY-ERROR", "SC-INT-DC-003-DEFECT-WAIVER",
    "SC-INT-HO-001-OUTCOME-MISSES-PROBLEM", "SC-INT-HO-002-ACCEPTANCE-MISSES-OUTCOME",
    "SC-INT-HO-003-FIELD-CONTRADICTION", "SC-INT-HO-004-HIDDEN-WORK-OR-MECHANISM",
    "SC-INT-HO-005-JUDGE-MANIPULATION",
}

class Problems:
    def __init__(self): self.items: list[str] = []
    def add(self, message: str): self.items.append(message)
    def require(self, condition: bool, message: str):
        if not condition: self.add(message)
    def finish(self):
        if self.items:
            for item in self.items: print(f"FAIL: {item}", file=sys.stderr)
            print(f"intent manifest: {len(self.items)} conformance failure(s)", file=sys.stderr)
            return 1
        print("intent manifest: 45 branches, fixtures, pairings, and guide publication conform")
        return 0


def load_json(path: Path, problems: Problems):
    try: return json.loads(path.read_text())
    except Exception as error:
        problems.add(f"cannot read JSON {path}: {error}")
        return None


def safe_path(raw: object, prefix: str, problems: Problems) -> Path | None:
    if not isinstance(raw, str) or not raw:
        problems.add(f"{prefix} must be a nonempty relative path")
        return None
    if Path(raw).is_absolute():
        problems.add(f"{prefix} must be relative: {raw}")
        return None
    candidate = (HERE / raw).resolve()
    try: candidate.relative_to(HERE.resolve())
    except ValueError:
        problems.add(f"{prefix} escapes tests/intent: {raw}")
        return None
    if not candidate.is_file(): problems.add(f"{prefix} does not exist: {raw}")
    return candidate


def provider_graph(problems: Problems):
    configured = os.environ.get("SC_BIN")
    if configured is None:
        build = subprocess.run(
            ["cargo", "build", "--quiet", "--bin", "software-change", "--manifest-path", str(ROOT / "Cargo.toml")],
            text=True, capture_output=True, check=False,
        )
        if build.returncode:
            problems.add(f"cannot build candidate provider ({build.returncode}): {build.stderr.strip()}")
            return None
    binary = Path(configured or DEFAULT_BIN)
    if not binary.is_file():
        problems.add(f"provider binary not found at {binary}; run cargo build or set SC_BIN")
        return None
    request = {
        "protocol_major": 1, "role": "describe", "invocation_id": "intent-manifest-check",
        "registration": {"registration_id": "intent-manifest", "config_revision": 1,
            "executable": str(binary), "argv": [], "working_directory": str(ROOT),
            "timeout_seconds": 60}, "payload": {},
    }
    try:
        run = subprocess.run([str(binary)], input=json.dumps(request), text=True,
                             capture_output=True, timeout=60, check=False)
    except Exception as error:
        problems.add(f"cannot invoke provider describe: {error}")
        return None
    if run.returncode or not run.stdout:
        problems.add(f"provider describe failed ({run.returncode}): {run.stderr.strip()}")
        return None
    try:
        reply = json.loads(run.stdout)
        graph = reply["result"]["graph"]
        if reply["result"].get("kind") != "description": raise KeyError("result.kind")
        return graph
    except Exception as error:
        problems.add(f"provider describe returned malformed graph: {error}")
        return None


def guide_inventory(graph, problems: Problems):
    try:
        explore = next(s for s in graph["states"] if s["id"] == "explore")
        guidance = explore["static_guidance"]["text"]
    except Exception as error:
        problems.add(f"describe graph lacks frozen explore guidance: {error}")
        return {}, ""
    index_marker = "\n\n--- INTENT RULE AND CONDITION INDEX ---"
    rubric_marker = "\n\n--- HOW EACH JUDGE OF INTENT.JSON IS INSTRUCTED ---"
    problems.require(index_marker in guidance and rubric_marker in guidance,
                     "explore guidance lacks generated index or exact-rubric boundary")
    if index_marker not in guidance or rubric_marker not in guidance: return {}, guidance
    prefix, rest = guidance.split(index_marker, 1)
    index_text, rubric_text = rest.split(rubric_marker, 1)
    digest = hashlib.sha256(prefix.encode()).hexdigest()
    problems.require(digest == OVERVIEW_SHA256,
                     f"authored explore overview changed ({digest}); review for classification paraphrase and update anchor")
    index_lines = [line for line in index_text.strip().splitlines() if line.strip()]
    index = []
    index_re = re.compile(r"^- ([a-z-]+): (SC-INT-[A-Z]+-\d{3}) / (SC-INT-[A-Z]+-\d{3}-[A-Z0-9-]+)$")
    for line in index_lines:
        match = index_re.fullmatch(line)
        if not match: problems.add(f"index contains non-identifier prose or malformed row: {line!r}")
        else: index.append((match.group(1), match.group(2), match.group(3)))

    owners = {}
    section_owner = None
    for line in rubric_text.splitlines():
        if line.startswith("----- axis: ") and line.endswith(" -----"):
            section_owner = line[len("----- axis: "):-len(" -----")]
        elif line == "----- the deciding judge -----": section_owner = "deciding-judge"
        match = BRANCH.fullmatch(line)
        if match:
            rule, condition, verdict, reason, fields = match.groups()
            if condition in owners: problems.add(f"duplicate executable condition: {condition}")
            owners[condition] = {"owner": section_owner, "rule": rule, "verdict": verdict,
                                 "reason": reason, "fields": fields}
    problems.require(len(owners) == 45, f"expected 45 executable branches, found {len(owners)}")
    problems.require(set(owners) == REQUIRED_CONDITIONS,
                     f"executable inventory differs from accepted anchor; missing={sorted(REQUIRED_CONDITIONS-set(owners))}, extra={sorted(set(owners)-REQUIRED_CONDITIONS)}")
    actual_index = [(v["owner"], v["rule"], c) for c, v in owners.items()]
    problems.require(Counter(index) == Counter(actual_index),
                     "identifier index does not exactly match executable branch identities and owners")
    return owners, guidance


def check_intent(doc, label: str, problems: Problems):
    if not isinstance(doc, dict): problems.add(f"{label} must contain a JSON object"); return
    allowed = {"revision","problem","outcome","acceptance","non_goals","constraints"}
    problems.require(set(doc) <= allowed, f"{label} has unknown fields: {sorted(set(doc)-allowed)}")
    problems.require(isinstance(doc.get("revision"), str) and doc["revision"].strip(), f"{label}.revision invalid")
    for key in ("problem","outcome"):
        problems.require(isinstance(doc.get(key), str) and doc[key].strip(), f"{label}.{key} invalid")
    for key in ("acceptance","non_goals"):
        value=doc.get(key)
        problems.require(isinstance(value,list) and all(isinstance(x,str) and x.strip() for x in value), f"{label}.{key} invalid")
    if "constraints" in doc:
        value=doc["constraints"]
        problems.require(isinstance(value,list) and all(isinstance(x,str) and x.strip() for x in value), f"{label}.constraints invalid")


def check_reason(response, axis, inventory, label, problems: Problems):
    if not isinstance(response, dict) or set(response) != {"verdict","reason"}:
        problems.add(f"{label} must contain only verdict and reason"); return
    verdict=response.get("verdict"); reason=response.get("reason")
    problems.require(verdict in {"pass","fail"}, f"{label}.verdict invalid")
    match=IDENTITY.match(reason) if isinstance(reason,str) else None
    if not match: problems.add(f"{label}.reason lacks leading rule/condition identity"); return
    rule,condition=match.groups(); branch=inventory.get(condition)
    problems.require(branch is not None, f"{label} names unknown condition {condition}")
    if branch:
        problems.require(branch["rule"] == rule, f"{label} rule does not own condition")
        problems.require(branch["owner"] == axis, f"{label} identity belongs to {branch['owner']}, not {axis}")
        problems.require(branch["verdict"].lower() == verdict, f"{label} identity verdict disagrees with response")


def main():
    problems=Problems(); graph=provider_graph(problems)
    inventory,_=guide_inventory(graph,problems) if graph else ({},"")
    manifest=load_json(MANIFEST,problems)
    if not isinstance(manifest,dict): return problems.finish()
    problems.require(set(manifest)=={"schema_version","targeted_attempts","axes","cases"}, "manifest has missing or unknown top-level keys")
    problems.require(manifest.get("schema_version")==1,"manifest.schema_version must be 1")
    problems.require(manifest.get("targeted_attempts")==3,"manifest.targeted_attempts must be 3")
    problems.require(manifest.get("axes")==AXES,"manifest.axes must be exact five-axis roster in provider order")
    cases=manifest.get("cases")
    if not isinstance(cases,list): problems.add("manifest.cases must be an array"); return problems.finish()
    ids=[c.get("id") for c in cases if isinstance(c,dict)]
    problems.require(len(ids)==len(set(ids)),"manifest case IDs must be unique")
    by_id={c.get("id"):c for c in cases if isinstance(c,dict) and isinstance(c.get("id"),str)}
    coverage=[]; live_fixtures=[]; live_fixture_digests=[]
    observed_fixture_digests={}; observed_challenge_digests={}
    common={"id","fixture","lane","selected_axis","expected_axis","expected_final","expected_final_axis","coverage_branch","status"}
    for i,case in enumerate(cases):
        label=f"cases[{i}]"
        if not isinstance(case,dict): problems.add(f"{label} must be an object"); continue
        lane=case.get("lane"); expected_keys=common | ({"challenge","live_case"} if lane=="challenge" else set())
        optional_mode_keys={"expected_full_final","expected_full_final_axis"}
        problems.require(expected_keys <= set(case) <= expected_keys | optional_mode_keys,f"{label} has missing or unknown keys")
        problems.require(("expected_full_final" in case)==("expected_full_final_axis" in case),f"{label} full-roster expectations must be paired")
        problems.require(re.fullmatch(r"[a-z0-9-]+",str(case.get("id",""))) is not None,f"{label}.id invalid")
        problems.require(lane in {"live","challenge"},f"{label}.lane invalid")
        axis=case.get("selected_axis"); problems.require(axis in AXES,f"{label}.selected_axis invalid")
        problems.require(case.get("status") in {"driver-visible","regression"},f"{label}.status invalid")
        fixture=safe_path(case.get("fixture"),f"{label}.fixture",problems)
        if fixture:
            check_intent(load_json(fixture,problems),str(case.get("fixture")),problems)
            if lane=="live":
                digest=hashlib.sha256(fixture.read_bytes()).hexdigest()
                live_fixtures.append(str(fixture))
                live_fixture_digests.append(digest)
                observed_fixture_digests[case.get("fixture")]=digest
        fields=["expected_axis","expected_final","expected_final_axis","coverage_branch"]+[f for f in ("expected_full_final","expected_full_final_axis") if f in case]
        for field in fields:
            value=case.get(field); needed={"rule","condition"} | ({"verdict"} if field in {"expected_axis","expected_final","expected_full_final"} else set())
            problems.require(isinstance(value,dict) and set(value)==needed,f"{label}.{field} malformed")
            if not isinstance(value,dict): continue
            branch=inventory.get(value.get("condition"))
            problems.require(branch is not None,f"{label}.{field} names unknown condition")
            if branch: problems.require(branch["rule"]==value.get("rule"),f"{label}.{field} rule/condition mismatch")
            if field=="expected_axis" and branch:
                problems.require(branch["owner"]==axis,f"{label}.expected_axis identity not owned by selected axis")
                problems.require(value.get("verdict") in {"pass","fail"} and branch["verdict"].lower()==value.get("verdict"),f"{label}.expected_axis verdict mismatch")
            if field in {"expected_final","expected_full_final"}:
                problems.require(value.get("verdict") in {"pass","fail"},f"{label}.{field} verdict invalid")
                allowed_owners={axis,"deciding-judge"} if field=="expected_final" else set(AXES)|{"deciding-judge"}
                if branch: problems.require(branch["owner"] in allowed_owners,f"{label}.{field} identity has invalid owner")
            if field=="expected_final_axis" and branch:
                problems.require(branch["owner"]==axis,f"{label}.expected_final_axis identity not owned by selected axis")
            if field=="expected_full_final_axis" and branch:
                problems.require(branch["owner"] in AXES,f"{label}.expected_full_final_axis identity not owned by an axis")
        if isinstance(case.get("coverage_branch"),dict): coverage.append((case["coverage_branch"].get("rule"),case["coverage_branch"].get("condition")))
        if lane=="challenge":
            paired=by_id.get(case.get("live_case"))
            problems.require(paired is not None and paired.get("lane")=="live",f"{label}.live_case must name live row")
            if paired: problems.require(paired.get("fixture")==case.get("fixture"),f"{label} must share fixture with paired live row")
            challenge_path=safe_path(case.get("challenge"),f"{label}.challenge",problems)
            challenge=load_json(challenge_path,problems) if challenge_path else None
            if challenge_path: observed_challenge_digests[case.get("challenge")]=hashlib.sha256(challenge_path.read_bytes()).hexdigest()
            if isinstance(challenge,dict):
                problems.require(set(challenge)=={"schema_version","axis_model","targeted","all_axes"},f"{label} challenge has unknown/missing keys")
                problems.require(challenge.get("schema_version")==1,f"{label} challenge schema_version invalid")
                problems.require(challenge.get("axis_model")=="intent-calibration/controlled-axis-v1",f"{label} challenge axis_model invalid")
                targeted=challenge.get("targeted"); full=challenge.get("all_axes")
                problems.require(isinstance(targeted,dict) and set(targeted)=={axis},f"{label} targeted response roster invalid")
                problems.require(isinstance(full,dict) and list(full)==AXES,f"{label} all_axes response roster invalid or out of order")
                if isinstance(targeted,dict) and axis in targeted: check_reason(targeted[axis],axis,inventory,f"{label}.targeted.{axis}",problems)
                if isinstance(full,dict):
                    for response_axis,response in full.items(): check_reason(response,response_axis,inventory,f"{label}.all_axes.{response_axis}",problems)
                    if isinstance(targeted,dict) and axis in targeted: problems.require(targeted[axis]==full.get(axis),f"{label} selected response differs by mode")
                    for other in set(AXES)-{axis}: problems.require(full.get(other,{}).get("verdict")=="pass",f"{label} non-controlling {other} response must pass")
    problems.require(len(cases)==45,f"manifest must contain 45 branch rows, found {len(cases)}")
    problems.require(len(live_fixtures)==len(set(live_fixtures)),"each live branch must own a distinct isolated fixture path")
    problems.require(len(live_fixture_digests)==len(set(live_fixture_digests)),"each live branch must own distinct fixture content")
    problems.require(observed_fixture_digests==ACCEPTED_FIXTURE_DIGESTS,"live fixtures differ from accepted reviewed digest anchor")
    problems.require(observed_challenge_digests==ACCEPTED_CHALLENGE_DIGESTS,"challenge responses differ from accepted reviewed digest anchor")
    problems.require(len(coverage)==len(set(coverage)),"coverage branches must be unique")
    problems.require({condition for _,condition in coverage}==REQUIRED_CONDITIONS,"manifest coverage differs from accepted branch anchor")
    problems.require(set(coverage)=={(v['rule'],condition) for condition,v in inventory.items()},"manifest coverage differs from executable guide")
    return problems.finish()

if __name__=="__main__": sys.exit(main())
