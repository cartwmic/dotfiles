#!/usr/bin/env python3
"""Generate closed Draft 2020-12 record schemas and conformance fixtures."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT.parent / "fixtures" / "records"
DIGEST = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
ID = {"type": "string", "minLength": 1, "maxLength": 128}
PATH = {"type": "string", "minLength": 1, "maxLength": 4096}
TEXT = {"type": "string", "maxLength": 65536}


def arr(items, maximum=1024, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def obj(properties, required=None, **extra):
    out = {"type": "object", "additionalProperties": False, "properties": properties}
    out["required"] = list(properties) if required is None else required
    out.update(extra)
    return out


def record(name, properties, required=None):
    props = {"schema": {"const": name}, "run_id": ID, **properties}
    req = ["schema", "run_id"] + (list(properties) if required is None else required)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:documentation-maintenance:{name}",
        "title": name,
        **obj(props, req),
    }

artifact_ref = obj({"schema": ID, "artifact_id": ID, "digest": DIGEST, "relative_path": PATH})
location = obj({"path": PATH, "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}})
manifest_entry = obj({
    "path": PATH,
    "kind": {"enum": ["absent", "regular", "symlink", "gitlink", "fifo", "socket", "character-device", "block-device"]},
    "tracked": {"type": "boolean"},
    "git_status": {"type": "string", "minLength": 1, "maxLength": 32},
    "core_document": {"type": "boolean"},
    "identity": obj({}, [], maxProperties=16),
})
# identity is closed by explicit alternatives rather than an open property bag.
manifest_entry["properties"]["identity"] = {"oneOf": [
    obj({"kind": {"const": "absent"}}),
    obj({"kind": {"const": "regular"}, "mode": {"type": "integer", "minimum": 0, "maximum": 65535}, "size": {"type": "integer", "minimum": 0}, "sha256": DIGEST, "content_base64": {"type": "string"}}),
    obj({"kind": {"const": "symlink"}, "mode": {"type": "integer", "minimum": 0, "maximum": 65535}, "target_sha256": DIGEST, "target_base64": {"type": "string"}}),
    obj({"kind": {"const": "gitlink"}, "object_id": {"type": "string", "pattern": "^[0-9a-f]{40,64}$"}}),
    obj({"kind": {"enum": ["fifo", "socket"]}, "mode": {"type": "integer", "minimum": 0, "maximum": 65535}}),
    obj({"kind": {"enum": ["character-device", "block-device"]}, "mode": {"type": "integer", "minimum": 0, "maximum": 65535}, "device_major": {"type": "integer", "minimum": 0}, "device_minor": {"type": "integer", "minimum": 0}}),
]}

schemas = {}
valid = {}

schemas["repository-manifest-v1"] = record("repository-manifest-v1", {
    "manifest_kind": {"enum": ["baseline", "staged"]}, "work_root": PATH, "git_common_dir": PATH,
    "entries": arr(manifest_entry, 100000), "repository_fingerprint": DIGEST,
    "baseline_digest": {"oneOf": [DIGEST, {"type": "null"}]}, "overlay_paths": arr(PATH, 3, 0),
})
valid["repository-manifest-v1"] = {"schema":"repository-manifest-v1","run_id":"run-1","manifest_kind":"baseline","work_root":"/repo","git_common_dir":"/repo/.git","entries":[],"repository_fingerprint":"sha256:"+"0"*64,"baseline_digest":None,"overlay_paths":[]}

claim = obj({"claim_id": ID, "document": PATH, "location": location, "ordinal": {"type":"integer","minimum":0}, "proposition": TEXT, "force": {"enum":["purpose","tenet","binding-invariant","binding-boundary","binding-non-goal","aspiration","descriptive"]}, "evidence_digests": arr(DIGEST, 128), "reason_id": ID})
schemas["claim-set-v1"] = record("claim-set-v1", {"manifest_digest":DIGEST,"claims":arr(claim,10000)})
valid["claim-set-v1"]={"schema":"claim-set-v1","run_id":"run-1","manifest_digest":"sha256:"+"0"*64,"claims":[]}

role_vote = obj({"judgment_id":ID,"document":PATH,"clause_id":ID,"verdict":{"enum":["satisfied","deficient","unverifiable","evaluation_error"]},"controlling_reason":ID,"evidence_digests":arr(DIGEST,128),"judge_identity_digest":DIGEST,"decoding_parameters_digest":DIGEST})
schemas["role-axis-judgment-v1"] = record("role-axis-judgment-v1", {"manifest_digest":DIGEST,"bundle_digest":DIGEST,"judgments":arr(role_vote,10000,1)})
valid["role-axis-judgment-v1"]={"schema":"role-axis-judgment-v1","run_id":"run-1","manifest_digest":"sha256:"+"0"*64,"bundle_digest":"sha256:"+"1"*64,"judgments":[{"judgment_id":"j1","document":"README.md","clause_id":"R1","verdict":"satisfied","controlling_reason":"role.satisfied","evidence_digests":[],"judge_identity_digest":"sha256:"+"2"*64,"decoding_parameters_digest":"sha256:"+"3"*64}]}

claim_verdict = {"enum":["adhered","drifted","breached","unverifiable","evaluation_error"]}
role_verdict = {"enum":["satisfied","deficient","unverifiable","evaluation_error"]}
claim_vote = obj({"vote_id":ID,"subject_kind":{"const":"claim"},"subject_id":ID,"judge_ordinal":{"type":"integer","minimum":1,"maximum":3},"verdict":claim_verdict,"controlling_reason":ID,"evidence_digests":arr(DIGEST,128)})
role_bundle_vote = obj({"vote_id":ID,"subject_kind":{"const":"role"},"subject_id":ID,"judge_ordinal":{"type":"integer","minimum":1,"maximum":3},"verdict":role_verdict,"controlling_reason":ID,"evidence_digests":arr(DIGEST,128)})
breach_adjudication = obj({"adjudication_id":ID,"subject_kind":{"const":"claim"},"subject_id":ID,"verdict":{"enum":["breach_confirmed","breach_not_confirmed","unverifiable","evaluation_error"]},"controlling_reason":ID,"evidence_digests":arr(DIGEST,128)})
resolved = {"oneOf":[
    obj({"subject_kind":{"const":"claim"},"subject_id":ID,"verdict":claim_verdict,"controlling_reason":ID}),
    obj({"subject_kind":{"const":"role"},"subject_id":ID,"verdict":role_verdict,"controlling_reason":ID}),
]}
schemas["judgment-bundle-v1"] = record("judgment-bundle-v1", {"manifest_digest":DIGEST,"bundle_digest":DIGEST,"claim_votes":arr(claim_vote,30000),"role_votes":arr(role_bundle_vote,30000),"focused_breach_adjudications":arr(breach_adjudication,10000),"resolved":arr(resolved,10000)})
valid["judgment-bundle-v1"]={"schema":"judgment-bundle-v1","run_id":"run-1","manifest_digest":"sha256:"+"0"*64,"bundle_digest":"sha256:"+"1"*64,"claim_votes":[{"vote_id":"v1","subject_kind":"claim","subject_id":"c1","judge_ordinal":1,"verdict":"adhered","controlling_reason":"claim.supported","evidence_digests":[]},{"vote_id":"v2","subject_kind":"claim","subject_id":"c1","judge_ordinal":2,"verdict":"adhered","controlling_reason":"claim.supported","evidence_digests":[]}],"role_votes":[],"focused_breach_adjudications":[],"resolved":[{"subject_kind":"claim","subject_id":"c1","verdict":"adhered","controlling_reason":"claim.supported"}]}

finding=obj({"finding_id":ID,"primary_reason":ID,"document":PATH,"location":location,"evidence_digests":arr(DIGEST,128),"secondary_consequences":arr(ID,128)})
schemas["audit-report-v1"] = record("audit-report-v1", {"manifest_digest":DIGEST,"claim_set_digest":DIGEST,"judgment_bundle_digest":DIGEST,"disposition":{"enum":["clean","revision_required","breach_confirmed","evaluation_error"]},"findings":arr(finding,10000)})
valid["audit-report-v1"]={"schema":"audit-report-v1","run_id":"run-1","manifest_digest":"sha256:"+"0"*64,"claim_set_digest":"sha256:"+"1"*64,"judgment_bundle_digest":"sha256:"+"2"*64,"disposition":"clean","findings":[]}

schemas["revision-request-v1"] = record("revision-request-v1", {"audit_report_digest":DIGEST,"target_document":{"enum":["docs/intent.md","AGENTS.md","README.md"]},"reason":TEXT,"requested_changes":arr(TEXT,256,1)})
valid["revision-request-v1"]={"schema":"revision-request-v1","run_id":"run-1","audit_report_digest":"sha256:"+"0"*64,"target_document":"README.md","reason":"Correct stale command.","requested_changes":["Use supported command."]}

change=obj({"claim_id":ID,"change_kind":{"enum":["created","meaning","force","scope","rationale","operational-effect","breach-evidence","governance","classification","removed","weakened","neutral"]},"prior_digest":{"oneOf":[DIGEST,{"type":"null"}]},"proposed_digest":{"oneOf":[DIGEST,{"type":"null"}]},"material":{"type":"boolean"}})
schemas["intent-semantic-diff-v1"] = record("intent-semantic-diff-v1", {"prior_intent_digest":{"oneOf":[DIGEST,{"type":"null"}]},"proposed_intent_digest":DIGEST,"changes":arr(change,10000),"material":{"type":"boolean"}})
valid["intent-semantic-diff-v1"]={"schema":"intent-semantic-diff-v1","run_id":"run-1","prior_intent_digest":None,"proposed_intent_digest":"sha256:"+"0"*64,"changes":[],"material":False}

doctrine=obj({"clause_id":ID,"outcome":{"enum":["included","omitted","override-requested"]},"evidence_digests":arr(DIGEST,128),"absent_condition":{"oneOf":[TEXT,{"type":"null"}]}})
schemas["revision-record-v1"] = record("revision-record-v1", {"request_digest":DIGEST,"target_document":{"enum":["docs/intent.md","AGENTS.md","README.md"]},"draft_digest":DIGEST,"draft_mode":{"type":"integer","minimum":0,"maximum":65535},"predecessor_digest":{"oneOf":[DIGEST,{"type":"null"}]},"doctrine_proposals":arr(doctrine,64)})
valid["revision-record-v1"]={"schema":"revision-record-v1","run_id":"run-1","request_digest":"sha256:"+"0"*64,"target_document":"README.md","draft_digest":"sha256:"+"1"*64,"draft_mode":420,"predecessor_digest":None,"doctrine_proposals":[]}

ledger_entry=obj({"path":{"enum":["docs/intent.md","AGENTS.md","README.md"]},"revision_record_digest":DIGEST,"draft_digest":DIGEST,"mode":{"type":"integer","minimum":0,"maximum":65535}})
schemas["revision-ledger-v1"] = record("revision-ledger-v1", {"baseline_manifest_digest":DIGEST,"predecessor_digest":{"oneOf":[DIGEST,{"type":"null"}]},"accepted":arr(ledger_entry,3),"pending_document":{"oneOf":[{"enum":["docs/intent.md","AGENTS.md","README.md"]},{"type":"null"}]},"invalidated":arr(PATH,3)})
valid["revision-ledger-v1"]={"schema":"revision-ledger-v1","run_id":"run-1","baseline_manifest_digest":"sha256:"+"0"*64,"predecessor_digest":None,"accepted":[],"pending_document":None,"invalidated":[]}

target=obj({"path":{"enum":["docs/intent.md","AGENTS.md","README.md"]},"digest":DIGEST,"mode":{"type":"integer","minimum":0,"maximum":65535}})
schemas["owner-attestation-v1"] = record("owner-attestation-v1", {"owner_id":ID,"statement_version":{"const":1},"subject_kind":{"enum":["material-intent-diff","doctrine-shape-override","final-staged-bundle"]},"prior_digest":{"oneOf":[DIGEST,{"type":"null"}]},"proposed_digest":DIGEST,"manifest_digest":DIGEST,"doctrine_pack_digests":arr(DIGEST,16),"targets":arr(target,3,1),"revoked":{"type":"boolean"}})
valid["owner-attestation-v1"]={"schema":"owner-attestation-v1","run_id":"run-1","owner_id":"owner","statement_version":1,"subject_kind":"final-staged-bundle","prior_digest":None,"proposed_digest":"sha256:"+"0"*64,"manifest_digest":"sha256:"+"1"*64,"doctrine_pack_digests":[],"targets":[{"path":"README.md","digest":"sha256:"+"2"*64,"mode":420}],"revoked":False}

schemas["approved-bundle-v1"] = record("approved-bundle-v1", {"staged_manifest_digest":DIGEST,"clean_audit_report_digest":DIGEST,"owner_attestation_digest":DIGEST,"baseline_manifest_digest":DIGEST,"targets":arr(target,3,1)})
valid["approved-bundle-v1"]={"schema":"approved-bundle-v1","run_id":"run-1","staged_manifest_digest":"sha256:"+"0"*64,"clean_audit_report_digest":"sha256:"+"1"*64,"owner_attestation_digest":"sha256:"+"2"*64,"baseline_manifest_digest":"sha256:"+"3"*64,"targets":[{"path":"README.md","digest":"sha256:"+"4"*64,"mode":420}]}

mismatch=obj({"path":PATH,"kind":{"enum":["added","removed","type-changed","mode-changed","bytes-changed","target-changed","device-changed","status-changed"]},"expected_digest":{"oneOf":[DIGEST,{"type":"null"}]},"actual_digest":{"oneOf":[DIGEST,{"type":"null"}]}})
schemas["application-verification-v1"] = record("application-verification-v1", {"approved_bundle_digest":DIGEST,"observed_manifest_digest":DIGEST,"exact":{"type":"boolean"},"mismatches":arr(mismatch,100000)})
valid["application-verification-v1"]={"schema":"application-verification-v1","run_id":"run-1","approved_bundle_digest":"sha256:"+"0"*64,"observed_manifest_digest":"sha256:"+"1"*64,"exact":True,"mismatches":[]}

slot_names=["baseline-manifest","active-manifest","claim-set","role-axis-judgment","judgment-bundle","audit-report","revision-request","intent-semantic-diff","revision-record","revision-ledger","owner-attestation","approved-bundle","application-verification","evaluation-recovery","breach-remediation","calibration-report"]
schemas["authority-manifest-v1"] = record("authority-manifest-v1", {"predecessor_root_digest":{"oneOf":[DIGEST,{"type":"null"}]},"slots":{"type":"object","additionalProperties":False,"maxProperties":32,"properties":{name:artifact_ref for name in slot_names}}})
valid["authority-manifest-v1"]={"schema":"authority-manifest-v1","run_id":"run-1","predecessor_root_digest":None,"slots":{}}

schemas["transition-certificate-v1"] = record("transition-certificate-v1", {"graph_revision":DIGEST,"source_state":ID,"source_workflow_state_version":{"type":"integer","minimum":0},"event":ID,"target_state":ID,"expected_successor_workflow_state_version":{"type":"integer","minimum":1},"required_gate_ids":arr(ID,64,1),"predecessor_root_digest":DIGEST,"successor_root_digest":DIGEST,"delta_digest":DIGEST,"predecessor_certificate_digest":{"oneOf":[DIGEST,{"type":"null"}]},"all_pass":{"const":True},"reset":{"type":"boolean"}})
valid["transition-certificate-v1"]={"schema":"transition-certificate-v1","run_id":"run-1","graph_revision":"sha256:"+"0"*64,"source_state":"audit","source_workflow_state_version":0,"event":"audit-complete","target_state":"triage","expected_successor_workflow_state_version":1,"required_gate_ids":["audit-ready"],"predecessor_root_digest":"sha256:"+"1"*64,"successor_root_digest":"sha256:"+"2"*64,"delta_digest":"sha256:"+"3"*64,"predecessor_certificate_digest":None,"all_pass":True,"reset":False}

schemas["evaluation-recovery-v1"] = record("evaluation-recovery-v1", {"failed_identity":ID,"evaluation_key_digest":DIGEST,"inspected_evidence_digests":arr(DIGEST,128,1),"diagnosed_cause":TEXT,"changed_retry_condition":{"oneOf":[TEXT,{"type":"null"}]},"transient_failure_rationale":{"oneOf":[TEXT,{"type":"null"}]},"caller_retry_authorized":{"const":True}})
valid["evaluation-recovery-v1"]={"schema":"evaluation-recovery-v1","run_id":"run-1","failed_identity":"inv-1","evaluation_key_digest":"sha256:"+"0"*64,"inspected_evidence_digests":["sha256:"+"1"*64],"diagnosed_cause":"Transient model outage.","changed_retry_condition":None,"transient_failure_rationale":"Service recovered.","caller_retry_authorized":True}

schemas["breach-remediation-v1"] = record("breach-remediation-v1", {"prior_breach_digest":DIGEST,"binding_rule_semantic_digest":DIGEST,"binding_force":ID,"old_manifest_digest":DIGEST,"new_manifest_digest":DIGEST,"changed_non_core_paths":arr(PATH,10000,1),"cited_evidence_digests":arr(DIGEST,128,1),"rule_unweakened":{"const":True}})
valid["breach-remediation-v1"]={"schema":"breach-remediation-v1","run_id":"run-1","prior_breach_digest":"sha256:"+"0"*64,"binding_rule_semantic_digest":"sha256:"+"1"*64,"binding_force":"binding-invariant","old_manifest_digest":"sha256:"+"2"*64,"new_manifest_digest":"sha256:"+"3"*64,"changed_non_core_paths":["src/lib.rs"],"cited_evidence_digests":["sha256:"+"4"*64],"rule_unweakened":True}

case=obj({"case_id":ID,"fixture_digest":DIGEST,"expected_verdict":ID,"affected_identity":ID,"controlling_reason":ID,"observations":arr(obj({"ordinal":{"type":"integer","minimum":1,"maximum":3},"verdict":ID,"affected_identity":ID,"controlling_reason":ID}),3,3)})
schemas["calibration-report-v1"] = record("calibration-report-v1", {"bundle_digest":DIGEST,"model_identity_digest":DIGEST,"decoding_parameters_digest":DIGEST,"cases":arr(case,10000,1),"qualified":{"type":"boolean"}})
valid["calibration-report-v1"]={"schema":"calibration-report-v1","run_id":"run-1","bundle_digest":"sha256:"+"0"*64,"model_identity_digest":"sha256:"+"1"*64,"decoding_parameters_digest":"sha256:"+"2"*64,"cases":[{"case_id":"case-1","fixture_digest":"sha256:"+"3"*64,"expected_verdict":"adhered","affected_identity":"README.md","controlling_reason":"claim.supported","observations":[{"ordinal":1,"verdict":"adhered","affected_identity":"README.md","controlling_reason":"claim.supported"},{"ordinal":2,"verdict":"adhered","affected_identity":"README.md","controlling_reason":"claim.supported"},{"ordinal":3,"verdict":"adhered","affected_identity":"README.md","controlling_reason":"claim.supported"}]}],"qualified":True}

assert len(schemas) == 17
ROOT.mkdir(parents=True, exist_ok=True)
(FIXTURES / "valid").mkdir(parents=True, exist_ok=True)
(FIXTURES / "invalid").mkdir(parents=True, exist_ok=True)
for name, schema in sorted(schemas.items()):
    (ROOT / f"{name}.json").write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    (FIXTURES / "valid" / f"{name}.json").write_text(json.dumps(valid[name], indent=2, sort_keys=True) + "\n")

# Negative fixtures exercise parser and schema failure classes independently.
invalid = {
    "unknown-key.json": {**valid["claim-set-v1"], "unexpected": True},
    "missing-run-id.json": {k:v for k,v in valid["claim-set-v1"].items() if k != "run_id"},
    "wrong-type.json": {**valid["claim-set-v1"], "claims": "not-an-array"},
    "out-of-bound.json": {**valid["revision-ledger-v1"], "accepted": [{"path":"README.md","revision_record_digest":"sha256:"+"1"*64,"draft_digest":"sha256:"+"2"*64,"mode":420}]*4},
    "cross-record-substitution.json": valid["audit-report-v1"],
}
for name, fixture in invalid.items():
    (FIXTURES / "invalid" / name).write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")
# Duplicate-key fixture cannot be represented through json.dumps.
(FIXTURES / "invalid" / "duplicate-key.json").write_text('{"schema":"claim-set-v1","run_id":"run-1","run_id":"run-2","manifest_digest":"sha256:' + '0'*64 + '","claims":[]}\n')
