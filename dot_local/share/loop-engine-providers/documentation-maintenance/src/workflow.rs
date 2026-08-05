//! Complete phase-P2 graph and guidance projected from stored contract bytes.

use crate::bundle::{self, BundleDecodeError, FrozenBundle};
use crate::codec;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

const AUTHORITY_PATHS: [&str; 3] = ["docs/intent.md", "AGENTS.md", "README.md"];

const STATES: [(&str, bool); 8] = [
    ("audit", false),
    ("triage", false),
    ("revise-a", false),
    ("revise-b", false),
    ("evaluation-remedy", false),
    ("breach-remedy", false),
    ("apply", false),
    ("end", true),
];

#[derive(Clone, Copy)]
struct Edge {
    source: &'static str,
    event: &'static str,
    target: &'static str,
    gates: &'static [&'static str],
}
const EDGES: &[Edge] = &[
    Edge {
        source: "audit",
        event: "audit-complete",
        target: "triage",
        gates: &["audit-ready", "audit-semantic"],
    },
    Edge {
        source: "triage",
        event: "baseline-clean",
        target: "end",
        gates: &["audit-clean"],
    },
    Edge {
        source: "triage",
        event: "revision-required",
        target: "revise-a",
        gates: &["audit-revision-required"],
    },
    Edge {
        source: "triage",
        event: "evaluation-failed",
        target: "evaluation-remedy",
        gates: &["audit-evaluation-error"],
    },
    Edge {
        source: "triage",
        event: "breach-confirmed",
        target: "breach-remedy",
        gates: &["audit-breach-confirmed"],
    },
    Edge {
        source: "triage",
        event: "request-changes",
        target: "revise-a",
        gates: &["staged-clean", "owner-requested-changes"],
    },
    Edge {
        source: "triage",
        event: "staged-approved",
        target: "apply",
        gates: &["staged-clean", "owner-approved"],
    },
    Edge {
        source: "triage",
        event: "restart-audit",
        target: "audit",
        gates: &["restart-permitted"],
    },
    Edge {
        source: "revise-a",
        event: "document-accepted",
        target: "revise-b",
        gates: &["revision-ready", "revision-semantic"],
    },
    Edge {
        source: "revise-a",
        event: "draft-changes-requested",
        target: "revise-b",
        gates: &["draft-present", "owner-requested-changes"],
    },
    Edge {
        source: "revise-a",
        event: "accepted-document-changes-requested",
        target: "revise-b",
        gates: &["accepted-draft-present", "owner-requested-changes"],
    },
    Edge {
        source: "revise-a",
        event: "staged-audit-complete",
        target: "triage",
        gates: &["staged-audit-ready", "staged-audit-semantic"],
    },
    Edge {
        source: "revise-a",
        event: "restart-audit",
        target: "audit",
        gates: &["restart-permitted"],
    },
    Edge {
        source: "revise-b",
        event: "document-accepted",
        target: "revise-a",
        gates: &["revision-ready", "revision-semantic"],
    },
    Edge {
        source: "revise-b",
        event: "draft-changes-requested",
        target: "revise-a",
        gates: &["draft-present", "owner-requested-changes"],
    },
    Edge {
        source: "revise-b",
        event: "accepted-document-changes-requested",
        target: "revise-a",
        gates: &["accepted-draft-present", "owner-requested-changes"],
    },
    Edge {
        source: "revise-b",
        event: "staged-audit-complete",
        target: "triage",
        gates: &["staged-audit-ready", "staged-audit-semantic"],
    },
    Edge {
        source: "revise-b",
        event: "restart-audit",
        target: "audit",
        gates: &["restart-permitted"],
    },
    Edge {
        source: "evaluation-remedy",
        event: "retry-ready",
        target: "audit",
        gates: &["evaluation-recovery-ready"],
    },
    Edge {
        source: "breach-remedy",
        event: "remediation-ready",
        target: "audit",
        gates: &["breach-remediation-ready"],
    },
    Edge {
        source: "apply",
        event: "application-verified",
        target: "end",
        gates: &["application-exact"],
    },
    Edge {
        source: "apply",
        event: "restart-audit",
        target: "audit",
        gates: &["restart-permitted"],
    },
];

pub fn graph() -> Result<Value, String> {
    let bundle = bundle::build_bundle()?;
    let mut states = Vec::new();
    let mut other_total = 0usize;
    for (id, final_state) in STATES {
        let text = static_guidance(id, &bundle)?;
        if text.len() > bundle::GUIDANCE_FIELD_MAX_BYTES {
            return Err(format!("{id} guidance exceeds individual field budget"));
        }
        if id == "audit" {
            if text.len() > bundle::AUDIT_GUIDANCE_MAX_BYTES {
                return Err("audit guidance exceeds budget".into());
            }
        } else {
            other_total += text.len();
        }
        states.push(json!({"id":id,"final":final_state,"static_guidance":{"kind":"text","text":text},"metadata":{"documentation_audit_bundle_digest":bundle.digest,"criteria_pointer":criteria_pointer(id)}}));
    }
    if other_total > bundle::OTHER_GUIDANCE_TOTAL_MAX_BYTES {
        return Err(format!(
            "other guidance total {other_total} exceeds {}",
            bundle::OTHER_GUIDANCE_TOTAL_MAX_BYTES
        ));
    }
    let transitions=EDGES.iter().map(|e|json!({"source_state":e.source,"event":e.event,"target_state":e.target,"gate_ids":e.gates})).collect::<Vec<_>>();
    let graph = json!({
     "initial_state":"audit","states":states,"transitions":transitions,
     "input_declarations":[{"id":"work_root","kind":"path","required":true},{"id":"artifact_root","kind":"path","required":true}],
     "live_guidance_supported":true,
     "metadata":{"workflow":"documentation-maintenance","workflow_version":"1","provider_phase":"P2","documentation_audit_bundle_v1":bundle.value,"documentation_audit_bundle_digest":bundle.digest,"encoded_budgets":{"canonical_graph":bundle::GRAPH_MAX_BYTES,"snapshot_envelope":bundle::SNAPSHOT_ENVELOPE_MAX_BYTES}}
    });
    enforce_metadata_depth(&graph["metadata"])?;
    let bytes = codec::canonicalize(&graph)?;
    if bytes.len() > bundle::GRAPH_MAX_BYTES {
        return Err(format!(
            "canonical graph is {} bytes, exceeds {}",
            bytes.len(),
            bundle::GRAPH_MAX_BYTES
        ));
    }
    if bytes.len() + 65_536 > bundle::SNAPSHOT_ENVELOPE_MAX_BYTES {
        return Err("graph does not retain required 65536-byte snapshot envelope headroom".into());
    }
    Ok(graph)
}

fn enforce_metadata_depth(metadata: &Value) -> Result<(), String> {
    let depth = bundle::metadata_depth(metadata);
    if depth > bundle::METADATA_MAX_DEPTH {
        return Err(format!(
            "graph metadata depth {depth} exceeds {}",
            bundle::METADATA_MAX_DEPTH
        ));
    }
    Ok(())
}

fn criteria_pointer(state: &str) -> &'static str {
    match state {
        "audit" => "/",
        "triage" => "/judgment_policy",
        "revise-a" | "revise-b" => "/claim_policy",
        "evaluation-remedy" | "breach-remedy" => "/recovery_policy",
        "apply" => "/claim_policy/authority_rule",
        "end" => "/compatibility",
        _ => "/",
    }
}

fn static_guidance(state: &str, b: &FrozenBundle) -> Result<String, String> {
    if state == "audit" {
        let mut out=String::from("STATE audit\nRequired artifacts: active repository-manifest-v1, claim-set-v1, role-axis-judgment-v1, judgment-bundle-v1, audit-report-v1.\nOperator decision: none until whole-repository audit is stable and complete.\nAdvance: audit-complete only when audit-ready and audit-semantic pass.\nBlock: stale baseline, invalid schema/model output, unsupported evidence, unresolved judgment, or selected-authority mismatch.\nRecovery: stale baseline uses gated restart-audit; evaluator failure follows evaluation recovery; confirmed breach follows external remediation.\n\n");
        out.push_str(&bundle::human_contract(b)?);
        return Ok(out);
    }
    let (artifacts,decision,advance,blocks,recovery)=match state {
  "triage"=>("selected immutable audit-report-v1 and its authority slots","choose event matching recorded disposition; for staged-clean choose exact owner request or final-bundle approval","baseline-clean, revision-required, evaluation-failed, breach-confirmed, request-changes, staged-approved, or gated restart-audit only through named gates","disposition/event mismatch, unresolved conflict, breach on drafting path, absent exact owner subject, stale selected authority","evaluation_error → evaluation-remedy; breach → breach-remedy; stale non-breach baseline → gated restart; invalidated approval → re-audit"),
  "revise-a"|"revise-b"=>("selected revision ledger/request, one presented draft or accepted entry, and required exact material-intent attestation","accept exact draft, request changes against exact presented/accepted digest, submit zero-pending staged overlay, or restart","each authority change alternates revise-a/revise-b; staged-audit-complete targets triage","more than one new document, authority-order violation, unsupported replacement fact, violated proposed binding rule, changed higher-authority bytes without downstream invalidation","intent first; remove/narrow unverifiable claims; retain violated proposal as aspiration; persistent unverifiable/evaluation failure uses restart-audit"),
  "evaluation-remedy"=>("evaluation-recovery-v1 inline record bound to failed identity and unchanged evaluation key","authorize retry after cited inspection and diagnosed changed condition or explicit transient rationale","retry-ready through evaluation-recovery-ready","identical-key resampling, missing inspection/cause/authorization, changed semantic key","correct evaluator condition or attest transient failure; unchanged semantic key replays recorded result"),
  "breach-remedy"=>("breach-remediation-v1 binding prior breach/rule/evidence, old/new manifests, relevant non-core changes","confirm external remediation is ready for whole-repository reassessment","remediation-ready through breach-remediation-ready","identical fingerprint, documentation-only or irrelevant change, weakened/remapped rule, or still-confirmed breach","change relevant non-core repository content externally, preserve exact rule force/scope, then audit whole repository"),
  "apply"=>("selected approved-bundle-v1, exact final owner attestation, baseline and caller-applied worktree","apply is caller-owned; request verification only after exact bytes/modes are present","application-verified through application-exact","target byte/mode mismatch, any non-target path difference, revoked/invalidated approval, stale baseline","do not repair in provider; mismatch or invalid approval recovers only through gated restart-audit at new baseline"),
  "end"=>("terminal selected authority and completion evidence","none","none; final sink has no outgoing transitions","none","start a new run for a new baseline or contract"),
  _=>return Err(format!("unknown workflow state {state}")),
 };
    let excerpt = static_state_excerpt(state, b)?;
    let excerpt = String::from_utf8(codec::canonicalize(&excerpt)?).map_err(|e| e.to_string())?;
    Ok(format!("STATE {state}\nBundle digest: {}\nRequired artifacts: {artifacts}.\nOperator decision: {decision}.\nAdvance: {advance}.\nBlock: {blocks}.\nRecovery: {recovery}.\nExact stored state-local excerpt (JSON names included scope; no omitted examples are claimed):\n{excerpt}",b.digest))
}

fn static_state_excerpt(state: &str, bundle: &FrozenBundle) -> Result<Value, String> {
    let value = &bundle.value;
    Ok(match state {
        "triage" => json!({
            "judgment_policy":value["judgment_policy"],
            "disposition_criteria":value["judgment_policy"]["disposition_priority"],
            "role_mapping":value["judgment_policy"]["role_mapping"]
        }),
        "revise-a" | "revise-b" => {
            let contracts = value["profile"]["contracts"]
                .as_array()
                .ok_or("stored contract array missing")?;
            let doctrine_clauses = value["doctrine"]["clauses"]
                .as_array()
                .ok_or("stored doctrine clause array missing")?;
            let common_applicability = value["doctrine"]["packs"]
                .as_array()
                .and_then(|packs| packs.first())
                .map(|pack| pack["applicability"].clone())
                .ok_or("stored doctrine applicability missing")?;
            json!({
                "common_revision_rubric":{
                    "force_rule":value["claim_policy"]["force_rule"],
                    "material_change":value["claim_policy"]["material_change"],
                    "non_material_change":value["claim_policy"]["non_material_change"],
                    "authority_order":value["claim_policy"]["authority_order"],
                    "authority_rule":value["claim_policy"]["authority_rule"],
                    "anti_laundering":value["claim_policy"]["anti_laundering"],
                    "revision_order":value["claim_policy"]["revision_order"]
                },
                "document_revision_discriminators":contracts.iter().map(|contract| json!({
                    "id":contract["id"],"path":contract["path"],"revision_rules":contract["revision_rules"],
                    "clauses":contract["clauses"].as_array().into_iter().flatten().map(|clause| json!({
                        "id":clause["id"],"discriminators":clause["discriminators"]
                    })).collect::<Vec<_>>()
                })).collect::<Vec<_>>(),
                "doctrine_proposal_criteria":{
                    "common_applicability":common_applicability,
                    "packs":value["doctrine"]["packs"].as_array().into_iter().flatten().map(|pack| json!({
                        "id":pack["id"],"authority":pack["authority"],"clause_ids":pack["clause_ids"]
                    })).collect::<Vec<_>>(),
                    "clauses":doctrine_clauses.iter().map(|clause| json!({
                        "id":clause["id"],"force":clause["force"]
                    })).collect::<Vec<_>>()
                },
                "examples_included":false,
                "example_projection":"Full exact examples for selected target are repeated in live revise guidance."
            })
        }
        "evaluation-remedy" => value["recovery_policy"]["evaluation_recovery"].clone(),
        "breach-remedy" => value["recovery_policy"]["breach_remediation"].clone(),
        "apply" => json!({
            "authority_rule":value["claim_policy"]["authority_rule"],
            "application_policy":value["claim_policy"]["application_policy"]
        }),
        "end" => value["compatibility"].clone(),
        _ => return Err(format!("unknown workflow state {state}")),
    })
}

pub fn project_live(
    stored_graph: &Value,
    current_state: &str,
    authority_manifest: &Value,
    authority_slots: &BTreeMap<String, Value>,
) -> Result<String, BundleDecodeError> {
    let bundle = bundle::decode_stored_bundle(stored_graph)?;
    let states = stored_graph
        .get("states")
        .and_then(Value::as_array)
        .ok_or_else(|| BundleDecodeError::Execution("stored graph states missing".into()))?;
    let state = states
        .iter()
        .find(|s| s.get("id").and_then(Value::as_str) == Some(current_state))
        .ok_or_else(|| {
            BundleDecodeError::Execution(format!(
                "current state {current_state:?} absent from stored graph"
            ))
        })?;
    let state_digest = state
        .pointer("/metadata/documentation_audit_bundle_digest")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            BundleDecodeError::Execution("state guidance has no bundle digest".into())
        })?;
    if state_digest != bundle.digest {
        return Err(BundleDecodeError::Execution(
            "state guidance bundle digest differs from stored bundle bytes".into(),
        ));
    }
    let text = state
        .pointer("/static_guidance/text")
        .and_then(Value::as_str)
        .ok_or_else(|| BundleDecodeError::Execution("stored state has no text guidance".into()))?;
    let slots = authority_manifest
        .get("slots")
        .and_then(Value::as_object)
        .ok_or_else(|| {
            BundleDecodeError::Execution("selected authority manifest has no slots".into())
        })?;
    let names = slots
        .keys()
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    let manifest_slot_names = slots.keys().cloned().collect::<BTreeSet<_>>();
    let loaded_slot_names = authority_slots.keys().cloned().collect::<BTreeSet<_>>();
    if manifest_slot_names != loaded_slot_names {
        return Err(BundleDecodeError::Execution(
            "selected authority manifest slots differ from loaded selected values".into(),
        ));
    }
    let facts = project_authority_state(current_state, authority_manifest, authority_slots)?;
    let authority_summary = if names.is_empty() {
        "empty canonical root".into()
    } else {
        names.join(", ")
    };
    let projected = if current_state == "audit" {
        // Audit static guidance already embeds the complete exact canonical
        // bundle. Repeating it would exceed the per-guidance protocol budget.
        format!("{text}\n\nSELECTED AUTHORITY (snapshot-validated): {authority_summary}. Filesystem-only and unselected records have no authority. Bundle criteria source: snapshot.stored_graph.metadata.documentation_audit_bundle_v1; digest {}.\nSTATE-AWARE TARGET/BLOCKERS/ADVANCEMENT/RECOVERY:\n{facts}\nThe complete exact run-frozen contract and examples appear byte-for-byte in audit static guidance above.", bundle.digest)
    } else {
        let excerpt = live_exact_excerpt(&bundle, current_state, authority_slots)?;
        format!("{text}\n\nSELECTED AUTHORITY (snapshot-validated): {authority_summary}. Filesystem-only and unselected records have no authority. Bundle criteria source: snapshot.stored_graph.metadata.documentation_audit_bundle_v1; digest {}.\nSTATE-AWARE TARGET/BLOCKERS/ADVANCEMENT/RECOVERY:\n{facts}\nEXACT RUN-FROZEN APPLICABLE CONTRACT/EXAMPLE/DOCTRINE/RECOVERY EXCERPT:\n{excerpt}", bundle.digest)
    };
    if projected.len() > bundle::GUIDANCE_FIELD_MAX_BYTES {
        return Err(BundleDecodeError::Execution(
            "projected live guidance exceeds guidance budget".into(),
        ));
    }
    Ok(projected)
}

fn project_authority_state(
    state: &str,
    manifest: &Value,
    slots: &BTreeMap<String, Value>,
) -> Result<String, BundleDecodeError> {
    match state {
        "audit" => {
            if slots.is_empty() {
                return Ok("Target: complete baseline repository. Selected authority shape: canonical initial/reset empty root. Blockers: incomplete whole-repository assessment. Advancement: audit-ready plus audit-semantic. Recovery: evaluator failure requires evaluation recovery; confirmed breach requires external remediation.".into());
            }
            let evaluation = slots.contains_key("evaluation-recovery");
            let breach = slots.contains_key("breach-remediation");
            if evaluation == breach {
                return execution("audit authority must be empty or select exactly one evaluation-recovery or breach-remediation record");
            }
            if evaluation {
                validate_evaluation_recovery(slots)?;
                Ok("Target: whole-repository retry after exact selected evaluation recovery. Advancement: rerun audit under unchanged semantic key only after corrected condition or explicit transient rationale.".into())
            } else {
                validate_breach_remediation(slots)?;
                Ok("Target: whole-repository reassessment at selected remediated manifest under exact unchanged binding rule. Advancement: rerun complete audit; residual confirmed breach remains blocked.".into())
            }
        }
        "triage" => project_triage_authority(manifest, slots),
        "revise-a" | "revise-b" => project_revision_authority(manifest, slots),
        "evaluation-remedy" => {
            validate_evaluation_recovery(slots)?;
            Ok("Target: exact selected evaluation-recovery record. Advancement: evaluation-recovery-ready only. Recovery: correct evaluator condition or bind explicit transient rationale; unchanged semantic key replays recorded result.".into())
        }
        "breach-remedy" => {
            validate_breach_remediation(slots)?;
            Ok("Target: exact prior breach/rule/scope on complete changed repository. Advancement: breach-remediation-ready only for new manifest and whole-repository reassessment. Recovery: residual confirmed breach remains blocked.".into())
        }
        "apply" => {
            let count = validate_apply_authority(manifest, slots)?;
            Ok(format!("Target count: {count}; owner attestation is explicitly nonrevoked and exactly consistent with selected approved bundle. Blockers: target byte/mode mismatch, non-target change, or stale baseline. Advancement: application-exact only. Recovery: gated restart at new baseline; provider performs no repair."))
        }
        "end" => {
            if let Some(verification) = slots.get("application-verification") {
                let count = validate_apply_authority(manifest, slots)?;
                if verification.get("schema").and_then(Value::as_str)
                    != Some("application-verification-v1")
                    || verification.get("exact").and_then(Value::as_bool) != Some(true)
                    || !required_array(verification, "mismatches", "application-verification")?
                        .is_empty()
                    || required_string(
                        verification,
                        "approved_bundle_digest",
                        "application-verification",
                    )? != selected_digest(manifest, "approved-bundle")?
                {
                    return execution("end application-verification is not exact or consistent with selected approval");
                }
                Ok(format!("Target: terminal exact application of {count} approved targets. Advancement: none. Recovery: new run for new baseline or contract."))
            } else {
                let audit = selected_record(slots, "audit-report", "audit-report-v1")?;
                if required_string(audit, "disposition", "audit-report")? != "clean" {
                    return execution(
                        "end without application-verification requires selected clean audit-report",
                    );
                }
                Ok("Target: terminal clean baseline selected by exact audit-report. Advancement: none. Recovery: new run for new baseline or contract.".into())
            }
        }
        other => execution(format!("unknown workflow state {other}")),
    }
}

fn project_triage_authority(
    manifest: &Value,
    slots: &BTreeMap<String, Value>,
) -> Result<String, BundleDecodeError> {
    let audit = selected_record(slots, "audit-report", "audit-report-v1")?;
    let active = selected_repository_manifest(slots, "active-manifest")?;
    let active_digest = selected_digest(manifest, "active-manifest")?;
    if required_string(audit, "manifest_digest", "audit-report")? != active_digest {
        return execution("selected audit-report does not bind selected active-manifest digest");
    }
    let disposition = required_string(audit, "disposition", "audit-report")?;
    let manifest_kind = required_string(active, "manifest_kind", "active-manifest")?;
    let event = match disposition {
        "clean" if manifest_kind == "baseline" => "baseline-clean",
        "clean" if manifest_kind == "staged" => {
            let request = slots.get("revision-request");
            let approval = slots.get("owner-attestation");
            if request.is_some() == approval.is_some() {
                return execution("clean staged triage requires exactly one owner change request or final staged approval subject");
            }
            if let Some(request) = request {
                if request.get("schema").and_then(Value::as_str) != Some("revision-request-v1")
                    || required_string(request, "subject_kind", "revision-request")?
                        != "clean-staged-bundle"
                    || required_string(request, "subject_digest", "revision-request")?
                        != active_digest
                    || required_string(request, "audit_report_digest", "revision-request")?
                        != selected_digest(manifest, "audit-report")?
                {
                    return execution("clean staged revision request does not bind selected audit and staged manifest subject");
                }
                "request-changes"
            } else {
                let approval = approval.expect("exclusive staged approval candidate");
                if approval.get("schema").and_then(Value::as_str) != Some("owner-attestation-v1")
                    || approval.get("revoked").and_then(Value::as_bool) != Some(false)
                    || required_string(approval, "subject_kind", "owner-attestation")?
                        != "final-staged-bundle"
                    || required_string(approval, "manifest_digest", "owner-attestation")?
                        != active_digest
                    || required_string(approval, "proposed_digest", "owner-attestation")?
                        != active_digest
                {
                    return execution("clean staged owner approval does not bind exact nonrevoked final staged subject");
                }
                "staged-approved"
            }
        }
        "clean" => {
            return execution("selected active-manifest manifest_kind is not baseline or staged")
        }
        "revision_required" => "revision-required",
        "evaluation_error" => "evaluation-failed",
        "breach_confirmed" => "breach-confirmed",
        _ => return execution("selected audit-report disposition is not closed"),
    };
    Ok(format!("Target: selected {manifest_kind} active-manifest digest {active_digest} with audit disposition {disposition}. Blockers: any audit/manifest or subject mismatch and every ambiguous staged decision shape. Advancement: {event} only. Recovery: evaluation_error to evaluation-remedy; breach_confirmed to breach-remedy; stale non-breach through gated restart."))
}

fn project_revision_authority(
    manifest: &Value,
    slots: &BTreeMap<String, Value>,
) -> Result<String, BundleDecodeError> {
    let ledger = selected_record(slots, "revision-ledger", "revision-ledger-v1")?;
    let accepted = required_array(ledger, "accepted", "revision-ledger")?;
    let invalidated = required_array(ledger, "invalidated", "revision-ledger")?;
    let accepted_paths = accepted
        .iter()
        .map(|entry| required_string(entry, "path", "revision-ledger accepted entry"))
        .collect::<Result<Vec<_>, _>>()?;
    let accepted_ranks = accepted_paths
        .iter()
        .map(|path| {
            AUTHORITY_PATHS
                .iter()
                .position(|candidate| candidate == path)
                .ok_or_else(|| {
                    BundleDecodeError::Execution(format!(
                        "revision-ledger accepted unsupported path {path:?}"
                    ))
                })
        })
        .collect::<Result<Vec<_>, _>>()?;
    if accepted_ranks.windows(2).any(|pair| pair[0] >= pair[1])
        || accepted_paths.iter().collect::<BTreeSet<_>>().len() != accepted_paths.len()
    {
        return execution(
            "revision-ledger accepted paths are duplicated or outside strict authority order",
        );
    }
    let invalidated_paths = invalidated
        .iter()
        .map(|value| {
            value.as_str().ok_or_else(|| {
                BundleDecodeError::Execution(
                    "revision-ledger invalidated path is missing or not a string".into(),
                )
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    if invalidated_paths.iter().collect::<BTreeSet<_>>().len() != invalidated_paths.len() {
        return execution("revision-ledger has ambiguous duplicate invalidated path");
    }

    match ledger.get("pending_document") {
        Some(Value::String(pending)) if !pending.is_empty() => {
            let presented = selected_record(slots, "revision-record", "revision-record-v1")?;
            let request = selected_record(slots, "revision-request", "revision-request-v1")?;
            let target = required_string(presented, "target_document", "revision-record")?;
            if pending != target
                || required_string(request, "target_document", "revision-request")? != target
                || required_string(presented, "request_digest", "revision-record")?
                    != selected_digest(manifest, "revision-request")?
            {
                return execution("pending ledger, selected revision record, and exact selected request digest/target are inconsistent");
            }
            let target_rank = AUTHORITY_PATHS
                .iter()
                .position(|candidate| candidate == &target)
                .ok_or_else(|| {
                    BundleDecodeError::Execution(format!(
                        "pending revision target {target:?} is unsupported"
                    ))
                })?;
            if accepted_paths != AUTHORITY_PATHS[..target_rank] {
                return execution(
                    "pending revision requires exactly the higher-authority accepted prefix",
                );
            }
            let subject_kind = required_string(request, "subject_kind", "revision-request")?;
            let subject_digest = required_string(request, "subject_digest", "revision-request")?;
            match subject_kind {
                "presented-draft" | "accepted-draft" => {
                    if presented.get("predecessor_digest").and_then(Value::as_str)
                        != Some(subject_digest)
                    {
                        return execution("presented/accepted-draft request subject digest must equal revision-record predecessor digest");
                    }
                }
                "clean-staged-bundle" => {
                    let active = selected_repository_manifest(slots, "active-manifest")?;
                    if required_string(active, "manifest_kind", "active-manifest")? != "staged"
                        || selected_digest(manifest, "active-manifest")? != subject_digest
                    {
                        return execution("clean-staged-bundle request subject must equal selected staged active-manifest digest");
                    }
                }
                _ => return execution("revision-request subject_kind is unsupported"),
            }
            Ok(format!("Target document: {target}. Accepted entries: {}; invalidated entries: {}. Request subject: {subject_kind} at {subject_digest}. Blockers: authority-order violation, any presented/pending/request ambiguity, unsupported replacement fact, missing material-intent attestation, or unrepresented downstream invalidation. Advancement: document-accepted only for exact selected {target} draft/request pair. Recovery: revise exact target; persistent unverifiable/evaluation failure uses gated restart.", accepted.len(), invalidated.len()))
        }
        Some(Value::Null) => {
            if slots.contains_key("revision-record") || slots.contains_key("revision-request") {
                return execution("zero-pending revision ledger must not select a presented revision record or request candidate");
            }
            if accepted_paths != AUTHORITY_PATHS || !invalidated_paths.is_empty() {
                return execution("zero-pending revision ledger requires all three accepted documents in exact authority order and no invalidated paths");
            }
            Ok("Target: complete staged overlay with docs/intent.md, AGENTS.md, and README.md accepted in authority order. Blockers: any pending/presented/request candidate, missing or reordered accepted document, or invalidated path. Advancement: staged-audit-complete only. Recovery: gated restart for stale or invalid staged authority.".into())
        }
        _ => execution(
            "revision-ledger pending_document must be a supported non-empty target string or null",
        ),
    }
}

fn selected_repository_manifest<'a>(
    slots: &'a BTreeMap<String, Value>,
    slot: &str,
) -> Result<&'a Value, BundleDecodeError> {
    selected_record(slots, slot, "repository-manifest-v1")
}

fn execution<T>(message: impl Into<String>) -> Result<T, BundleDecodeError> {
    Err(BundleDecodeError::Execution(message.into()))
}

fn selected_record<'a>(
    slots: &'a BTreeMap<String, Value>,
    slot: &str,
    schema: &str,
) -> Result<&'a Value, BundleDecodeError> {
    let record = slots.get(slot).ok_or_else(|| {
        BundleDecodeError::Execution(format!("state requires selected {slot} record"))
    })?;
    if record.get("schema").and_then(Value::as_str) != Some(schema) {
        return execution(format!(
            "selected {slot} does not carry exact {schema} schema"
        ));
    }
    Ok(record)
}

fn required_string<'a>(
    value: &'a Value,
    field: &str,
    subject: &str,
) -> Result<&'a str, BundleDecodeError> {
    value
        .get(field)
        .and_then(Value::as_str)
        .filter(|text| !text.is_empty())
        .ok_or_else(|| {
            BundleDecodeError::Execution(format!(
                "{subject} requires non-empty string field {field}"
            ))
        })
}

fn required_array<'a>(
    value: &'a Value,
    field: &str,
    subject: &str,
) -> Result<&'a Vec<Value>, BundleDecodeError> {
    value.get(field).and_then(Value::as_array).ok_or_else(|| {
        BundleDecodeError::Execution(format!("{subject} requires array field {field}"))
    })
}

fn selected_digest<'a>(manifest: &'a Value, slot: &str) -> Result<&'a str, BundleDecodeError> {
    manifest
        .pointer(&format!("/slots/{slot}/digest"))
        .and_then(Value::as_str)
        .ok_or_else(|| {
            BundleDecodeError::Execution(format!(
                "selected {slot} authority reference has no digest"
            ))
        })
}

fn validate_evaluation_recovery(slots: &BTreeMap<String, Value>) -> Result<(), BundleDecodeError> {
    let record = selected_record(slots, "evaluation-recovery", "evaluation-recovery-v1")?;
    required_string(record, "failed_identity", "evaluation-recovery")?;
    required_string(record, "evaluation_key_digest", "evaluation-recovery")?;
    required_string(record, "diagnosed_cause", "evaluation-recovery")?;
    if required_array(record, "inspected_evidence_digests", "evaluation-recovery")?.is_empty() {
        return execution("evaluation-recovery requires at least one inspected evidence digest");
    }
    if record
        .get("caller_retry_authorized")
        .and_then(Value::as_bool)
        != Some(true)
    {
        return execution("evaluation-recovery requires explicit caller retry authorization");
    }
    let changed = record
        .get("changed_retry_condition")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty());
    let transient = record
        .get("transient_failure_rationale")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty());
    if changed.is_some() == transient.is_some() {
        return execution("evaluation-recovery requires exactly one non-empty retry alternative");
    }
    Ok(())
}

fn validate_breach_remediation(slots: &BTreeMap<String, Value>) -> Result<(), BundleDecodeError> {
    let record = selected_record(slots, "breach-remediation", "breach-remediation-v1")?;
    for field in [
        "prior_breach_digest",
        "binding_rule_semantic_digest",
        "binding_force",
        "binding_scope",
        "old_manifest_digest",
        "new_manifest_digest",
        "reassessment_manifest_digest",
        "reassessment_rule_semantic_digest",
    ] {
        required_string(record, field, "breach-remediation")?;
    }
    if required_string(record, "old_manifest_digest", "breach-remediation")?
        == required_string(record, "new_manifest_digest", "breach-remediation")?
    {
        return execution("breach-remediation old and new manifest digests are identical");
    }
    if record.get("rule_unweakened").and_then(Value::as_bool) != Some(true)
        || record.get("reassessment_scope").and_then(Value::as_str) != Some("whole-repository")
        || required_string(record, "reassessment_manifest_digest", "breach-remediation")?
            != required_string(record, "new_manifest_digest", "breach-remediation")?
        || required_string(
            record,
            "reassessment_rule_semantic_digest",
            "breach-remediation",
        )? != required_string(record, "binding_rule_semantic_digest", "breach-remediation")?
        || required_array(record, "changed_non_core_paths", "breach-remediation")?.is_empty()
        || required_array(record, "cited_evidence_digests", "breach-remediation")?.is_empty()
    {
        return execution("breach-remediation lacks exact unchanged-rule whole-repository reassessment consistency");
    }
    Ok(())
}

fn validate_apply_authority(
    manifest: &Value,
    slots: &BTreeMap<String, Value>,
) -> Result<usize, BundleDecodeError> {
    let approved = selected_record(slots, "approved-bundle", "approved-bundle-v1")?;
    let attestation = selected_record(slots, "owner-attestation", "owner-attestation-v1")?;
    let audit = selected_record(slots, "audit-report", "audit-report-v1")?;
    let staged = selected_repository_manifest(slots, "active-manifest")?;
    let baseline = selected_repository_manifest(slots, "baseline-manifest")?;
    let staged_digest = selected_digest(manifest, "active-manifest")?;
    let baseline_digest = selected_digest(manifest, "baseline-manifest")?;
    let audit_digest = selected_digest(manifest, "audit-report")?;
    if required_string(audit, "disposition", "audit-report")? != "clean"
        || required_string(audit, "manifest_digest", "audit-report")? != staged_digest
        || required_string(staged, "manifest_kind", "active-manifest")? != "staged"
        || required_string(baseline, "manifest_kind", "baseline-manifest")? != "baseline"
        || required_string(staged, "baseline_digest", "active-manifest")? != baseline_digest
        || required_string(approved, "clean_audit_report_digest", "approved-bundle")?
            != audit_digest
        || required_string(approved, "staged_manifest_digest", "approved-bundle")? != staged_digest
        || required_string(approved, "baseline_manifest_digest", "approved-bundle")?
            != baseline_digest
        || attestation.get("revoked").and_then(Value::as_bool) != Some(false)
        || attestation.get("subject_kind").and_then(Value::as_str) != Some("final-staged-bundle")
        || required_string(approved, "owner_attestation_digest", "approved-bundle")?
            != selected_digest(manifest, "owner-attestation")?
        || required_string(approved, "staged_manifest_digest", "approved-bundle")?
            != required_string(attestation, "manifest_digest", "owner-attestation")?
        || required_string(approved, "staged_manifest_digest", "approved-bundle")?
            != required_string(attestation, "proposed_digest", "owner-attestation")?
        || approved.get("targets") != attestation.get("targets")
    {
        return execution("approved bundle, clean audit, selected staged/baseline manifests, and nonrevoked final owner attestation are inconsistent");
    }
    let targets = required_array(approved, "targets", "approved-bundle")?;
    if targets.is_empty() {
        return execution("approved-bundle requires at least one exact target");
    }
    Ok(targets.len())
}

fn live_exact_excerpt(
    bundle: &FrozenBundle,
    state: &str,
    slots: &BTreeMap<String, Value>,
) -> Result<String, BundleDecodeError> {
    let value = &bundle.value;
    let excerpt = match state {
        "audit" => value.clone(),
        "triage" => json!({
            "judgment_policy": value["judgment_policy"],
            "document_rubrics_and_examples": value["profile"],
            "doctrine_rubrics_and_examples": value["doctrine"],
        }),
        "revise-a" | "revise-b" => {
            let ledger = selected_record(slots, "revision-ledger", "revision-ledger-v1")?;
            let contracts = value["profile"]["contracts"].as_array().ok_or_else(|| {
                BundleDecodeError::Execution("stored contracts are invalid".into())
            })?;
            match ledger.get("pending_document") {
                Some(Value::String(target)) => {
                    let selected = contracts
                        .iter()
                        .find(|contract| contract["path"] == target.as_str())
                        .cloned()
                        .ok_or_else(|| {
                            BundleDecodeError::Execution(format!(
                                "revision target {target:?} has no frozen document contract"
                            ))
                        })?;
                    json!({
                        "selected_target_contract_with_all_examples": selected,
                        "claim_policy": value["claim_policy"],
                        "doctrine": if target == "docs/intent.md" { value["doctrine"].clone() } else { Value::Null },
                        "recovery": value["recovery_policy"],
                    })
                }
                Some(Value::Null) => json!({
                    "completed_contracts_with_all_examples": value["profile"],
                    "claim_policy": value["claim_policy"],
                    "doctrine": value["doctrine"],
                    "recovery": value["recovery_policy"],
                }),
                _ => {
                    return execution(
                        "revision-ledger pending_document has invalid live excerpt shape",
                    )
                }
            }
        }
        "evaluation-remedy" => value
            .pointer("/recovery_policy/evaluation_recovery")
            .cloned()
            .ok_or_else(|| {
                BundleDecodeError::Execution("stored evaluation recovery contract missing".into())
            })?,
        "breach-remedy" => value
            .pointer("/recovery_policy/breach_remediation")
            .cloned()
            .ok_or_else(|| {
                BundleDecodeError::Execution("stored breach recovery contract missing".into())
            })?,
        "apply" => json!({
            "authority_rule":value["claim_policy"]["authority_rule"],
            "application_policy":value["claim_policy"]["application_policy"],
            "approved_bundle":selected_record(slots, "approved-bundle", "approved-bundle-v1")?,
            "owner_attestation":selected_record(slots, "owner-attestation", "owner-attestation-v1")?
        }),
        "end" => value["compatibility"].clone(),
        other => {
            return Err(BundleDecodeError::Execution(format!(
                "unknown workflow state {other}"
            )))
        }
    };
    let bytes = codec::canonicalize(&excerpt).map_err(BundleDecodeError::Execution)?;
    String::from_utf8(bytes).map_err(|error| BundleDecodeError::Execution(error.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(digit: char) -> String {
        format!("sha256:{}", digit.to_string().repeat(64))
    }

    fn repository_manifest(kind: &str, baseline_digest: Value) -> Value {
        json!({
            "schema":"repository-manifest-v1",
            "manifest_kind":kind,
            "baseline_digest":baseline_digest
        })
    }

    #[test]
    fn graph_has_complete_distinct_gated_topology() {
        let g = graph().unwrap();
        assert_eq!(g["states"].as_array().unwrap().len(), 8);
        assert_eq!(g["transitions"].as_array().unwrap().len(), 22);
        let mut keys = BTreeSet::new();
        for e in g["transitions"].as_array().unwrap() {
            let s = e["source_state"].as_str().unwrap();
            let t = e["target_state"].as_str().unwrap();
            assert_ne!(s, t);
            assert!(!e["gate_ids"].as_array().unwrap().is_empty());
            assert!(keys.insert((s, e["event"].as_str().unwrap())));
        }
        assert!(g["transitions"]
            .as_array()
            .unwrap()
            .iter()
            .all(|e| e["source_state"] != "end"));
    }
    #[test]
    fn graph_bundle_and_all_encoded_budgets_hold() {
        let g = graph().unwrap();
        let b = bundle::decode_stored_bundle(&g).unwrap();
        let graph_bytes = codec::canonicalize(&g).unwrap().len();
        println!(
            "budgets: bundle={}/{} graph={}/{} envelope={}/{}",
            b.canonical_bytes.len(),
            bundle::MACHINE_BUNDLE_MAX_BYTES,
            graph_bytes,
            bundle::GRAPH_MAX_BYTES,
            graph_bytes + 65_536,
            bundle::SNAPSHOT_ENVELOPE_MAX_BYTES
        );
        assert!(b.canonical_bytes.len() <= bundle::MACHINE_BUNDLE_MAX_BYTES);
        assert!(graph_bytes <= bundle::GRAPH_MAX_BYTES);
        assert!(bundle::metadata_depth(&g["metadata"]) <= bundle::METADATA_MAX_DEPTH);
        assert!(
            codec::canonicalize(&g).unwrap().len() + 65_536 <= bundle::SNAPSHOT_ENVELOPE_MAX_BYTES
        );
        let audit = g["states"]
            .as_array()
            .unwrap()
            .iter()
            .find(|s| s["id"] == "audit")
            .unwrap()["static_guidance"]["text"]
            .as_str()
            .unwrap();
        assert!(audit.len() <= bundle::AUDIT_GUIDANCE_MAX_BYTES);
        assert!(audit.contains(&b.digest));
        let contract_start = audit
            .find("{\"budgets\"")
            .expect("audit guidance carries exact canonical contract");
        assert_eq!(
            &audit.as_bytes()[contract_start..],
            b.canonical_bytes.as_slice()
        );
        assert_eq!(codec::sha256(&audit.as_bytes()[contract_start..]), b.digest);
    }
    #[test]
    fn static_non_audit_guidance_uses_common_or_state_exact_excerpts_without_partial_example() {
        let graph = graph().unwrap();
        let text = |state: &str| {
            graph["states"]
                .as_array()
                .unwrap()
                .iter()
                .find(|entry| entry["id"] == state)
                .unwrap()["static_guidance"]["text"]
                .as_str()
                .unwrap()
        };
        let revise = text("revise-a");
        assert!(
            revise.contains("docs/intent.md")
                && revise.contains("AGENTS.md")
                && revise.contains("README.md")
        );
        assert!(revise.contains("common_revision_rubric"));
        assert!(revise.contains("document_revision_discriminators"));
        assert!(revise.contains("doctrine_proposal_criteria"));
        assert!(revise.contains("\"examples_included\":false"));
        assert!(revise.contains("no omitted examples are claimed"));
        assert!(!revise.contains("example_excerpts"));
        assert!(!revise.contains("README states `./run_tests.sh all`"));
        assert!(text("triage").contains("disposition_priority"));
        assert!(text("triage").contains("focused_breach_outputs"));
        assert!(text("apply").contains("application_policy"));
        assert!(text("apply")
            .contains("Application verification binds selected approved-bundle digest"));
    }

    #[test]
    fn runtime_metadata_depth_guard_rejects_overflow() {
        let mut metadata = json!(true);
        for _ in 0..=bundle::METADATA_MAX_DEPTH {
            metadata = json!({"nested":metadata});
        }
        assert!(enforce_metadata_depth(&metadata).is_err());
        assert!(enforce_metadata_depth(&json!({"ok":true})).is_ok());
    }

    #[test]
    fn guidance_uses_stored_bytes_selected_authority_and_rejects_mismatch() {
        let g = graph().unwrap();
        let audit_live = project_live(&g, "audit", &json!({"slots":{}}), &BTreeMap::new()).unwrap();
        assert!(audit_live.len() <= bundle::GUIDANCE_FIELD_MAX_BYTES);
        assert_eq!(
            audit_live
                .matches("DOCUMENTATION AUDIT CONTRACT documentation-audit-bundle-v1")
                .count(),
            1
        );
        let audit_digest = digest('1');
        let active_digest = digest('2');
        let manifest = json!({"slots":{
            "audit-report":{"digest":audit_digest},
            "active-manifest":{"digest":active_digest}
        }});
        let slots = BTreeMap::from([
            (
                "audit-report".to_string(),
                json!({"schema":"audit-report-v1","disposition":"clean","manifest_digest":active_digest}),
            ),
            (
                "active-manifest".to_string(),
                repository_manifest("baseline", Value::Null),
            ),
        ]);
        let text = project_live(&g, "triage", &manifest, &slots).unwrap();
        assert!(text.contains("audit-report"));
        assert!(text.contains("snapshot.stored_graph"));
        let frozen = bundle::decode_stored_bundle(&g).unwrap();
        let exact_profile =
            String::from_utf8(codec::canonicalize(&frozen.value["profile"]).unwrap()).unwrap();
        assert!(text.contains(&exact_profile));
        let mut changed = g.clone();
        changed["states"][1]["metadata"]["documentation_audit_bundle_digest"] =
            json!("sha256:0000000000000000000000000000000000000000000000000000000000000000");
        assert!(project_live(&changed, "triage", &manifest, &slots).is_err());
        assert!(project_live(&g, "unknown", &manifest, &slots).is_err());
    }
    #[test]
    fn live_projection_is_selected_state_aware_and_repeats_exact_excerpts() {
        let g = graph().unwrap();
        let request_digest = digest('3');
        let predecessor_digest = digest('4');
        let manifest = json!({"slots":{
            "revision-ledger":{},"revision-record":{},
            "revision-request":{"digest":request_digest}
        }});
        let slots = BTreeMap::from([
            (
                "revision-ledger".into(),
                json!({"schema":"revision-ledger-v1","accepted":[{"path":"docs/intent.md"}],"invalidated":["README.md"],"pending_document":"AGENTS.md"}),
            ),
            (
                "revision-record".into(),
                json!({"schema":"revision-record-v1","target_document":"AGENTS.md","request_digest":request_digest,"predecessor_digest":predecessor_digest}),
            ),
            (
                "revision-request".into(),
                json!({"schema":"revision-request-v1","target_document":"AGENTS.md","subject_kind":"presented-draft","subject_digest":predecessor_digest}),
            ),
        ]);
        let text = project_live(&g, "revise-a", &manifest, &slots).unwrap();
        assert!(text.contains("Target document: AGENTS.md"));
        assert!(text.contains("Accepted entries: 1; invalidated entries: 1"));
        let bundle = bundle::decode_stored_bundle(&g).unwrap();
        let agents = bundle.value["profile"]["contracts"]
            .as_array()
            .unwrap()
            .iter()
            .find(|contract| contract["path"] == "AGENTS.md")
            .unwrap();
        let exact = String::from_utf8(codec::canonicalize(agents).unwrap()).unwrap();
        assert!(text.contains(&exact));
        assert!(text.contains("evaluation_recovery"));
        assert!(text.contains("breach_remediation"));
        let exact_example =
            String::from_utf8(codec::canonicalize(&agents["clauses"][0]["examples"]).unwrap())
                .unwrap();
        assert!(text.contains(&exact_example));
    }

    #[test]
    fn state_authority_projection_fails_closed_for_missing_and_inconsistent_values() {
        let empty = BTreeMap::new();
        assert!(project_authority_state("triage", &json!({"slots":{}}), &empty).is_err());
        assert!(project_authority_state("revise-a", &json!({"slots":{}}), &empty).is_err());
        assert!(
            project_authority_state("evaluation-remedy", &json!({"slots":{}}), &empty).is_err()
        );
        assert!(project_authority_state("breach-remedy", &json!({"slots":{}}), &empty).is_err());
        assert!(project_authority_state("apply", &json!({"slots":{}}), &empty).is_err());
        assert!(project_authority_state("end", &json!({"slots":{}}), &empty).is_err());
        assert!(project_authority_state("audit", &json!({"slots":{}}), &empty).is_ok());

        let triage = BTreeMap::from([("audit-report".into(), json!({"schema":"audit-report-v1"}))]);
        assert!(
            project_authority_state("triage", &json!({"slots":{"audit-report":{}}}), &triage)
                .is_err()
        );

        let ledger = json!({"schema":"revision-ledger-v1","pending_document":"README.md","accepted":[],"invalidated":[]});
        let presented = json!({"schema":"revision-record-v1","target_document":"AGENTS.md","request_digest":format!("sha256:{}", "1".repeat(64))});
        let revision = BTreeMap::from([
            ("revision-ledger".into(), ledger),
            ("revision-record".into(), presented),
        ]);
        assert!(project_authority_state(
            "revise-a",
            &json!({"slots":{"revision-ledger":{},"revision-record":{}}}),
            &revision
        )
        .is_err());
    }

    #[test]
    fn live_apply_returns_exact_selected_approval_and_application_criteria() {
        let graph = graph().unwrap();
        let targets = json!([{"path":"README.md","digest":digest('6'),"mode":420}]);
        let owner_digest = digest('7');
        let staged_digest = digest('9');
        let baseline_digest = digest('5');
        let audit_digest = digest('4');
        let approved = json!({"schema":"approved-bundle-v1","owner_attestation_digest":owner_digest,
            "staged_manifest_digest":staged_digest,"baseline_manifest_digest":baseline_digest,
            "clean_audit_report_digest":audit_digest,"targets":targets});
        let attestation = json!({"schema":"owner-attestation-v1","revoked":false,
            "subject_kind":"final-staged-bundle","manifest_digest":staged_digest,
            "proposed_digest":staged_digest,"targets":targets});
        let slots = BTreeMap::from([
            ("approved-bundle".into(), approved.clone()),
            ("owner-attestation".into(), attestation.clone()),
            (
                "audit-report".into(),
                json!({"schema":"audit-report-v1","disposition":"clean","manifest_digest":staged_digest}),
            ),
            (
                "active-manifest".into(),
                repository_manifest("staged", json!(baseline_digest)),
            ),
            (
                "baseline-manifest".into(),
                repository_manifest("baseline", Value::Null),
            ),
        ]);
        let manifest = json!({"slots":{
            "approved-bundle":{"digest":digest('8')},
            "owner-attestation":{"digest":owner_digest},
            "audit-report":{"digest":audit_digest},
            "active-manifest":{"digest":staged_digest},
            "baseline-manifest":{"digest":baseline_digest}
        }});
        let text = project_live(&graph, "apply", &manifest, &slots).unwrap();
        let frozen = bundle::decode_stored_bundle(&graph).unwrap();
        for exact in [
            codec::canonicalize(&frozen.value["claim_policy"]["application_policy"]).unwrap(),
            codec::canonicalize(&approved).unwrap(),
            codec::canonicalize(&attestation).unwrap(),
        ] {
            assert!(text.contains(&String::from_utf8(exact).unwrap()));
        }
    }

    #[test]
    fn recovery_apply_audit_and_end_authority_shapes_require_exact_records() {
        let evaluation = json!({
            "schema":"evaluation-recovery-v1","failed_identity":"inv-1",
            "evaluation_key_digest":digest('1'),"inspected_evidence_digests":[digest('2')],
            "diagnosed_cause":"transient outage","changed_retry_condition":null,
            "transient_failure_rationale":"service recovered","caller_retry_authorized":true
        });
        let evaluation_slots = BTreeMap::from([("evaluation-recovery".into(), evaluation.clone())]);
        assert!(project_authority_state(
            "evaluation-remedy",
            &json!({"slots":{"evaluation-recovery":{}}}),
            &evaluation_slots
        )
        .is_ok());
        let mut bad_evaluation = evaluation_slots.clone();
        bad_evaluation.get_mut("evaluation-recovery").unwrap()["diagnosed_cause"] = json!("");
        assert!(project_authority_state(
            "evaluation-remedy",
            &json!({"slots":{"evaluation-recovery":{}}}),
            &bad_evaluation
        )
        .is_err());
        assert!(project_authority_state(
            "audit",
            &json!({"slots":{"evaluation-recovery":{}}}),
            &evaluation_slots
        )
        .is_ok());

        let remediation = json!({
            "schema":"breach-remediation-v1","prior_breach_digest":digest('1'),
            "binding_rule_semantic_digest":digest('2'),"binding_force":"binding-invariant",
            "binding_scope":"repository","old_manifest_digest":digest('3'),"new_manifest_digest":digest('4'),
            "changed_non_core_paths":["src/lib.rs"],"cited_evidence_digests":[digest('5')],
            "rule_unweakened":true,"reassessment_scope":"whole-repository",
            "reassessment_manifest_digest":digest('4'),"reassessment_rule_semantic_digest":digest('2')
        });
        let remediation_slots =
            BTreeMap::from([("breach-remediation".into(), remediation.clone())]);
        assert!(project_authority_state(
            "breach-remedy",
            &json!({"slots":{"breach-remediation":{}}}),
            &remediation_slots
        )
        .is_ok());
        let mut bad_remediation = remediation_slots;
        bad_remediation.get_mut("breach-remediation").unwrap()["new_manifest_digest"] =
            json!(digest('3'));
        assert!(project_authority_state(
            "breach-remedy",
            &json!({"slots":{"breach-remediation":{}}}),
            &bad_remediation
        )
        .is_err());

        let targets = json!([{"path":"README.md","digest":digest('6'),"mode":420}]);
        let owner_digest = digest('7');
        let approved_digest = digest('8');
        let staged_digest = digest('9');
        let baseline_digest = digest('a');
        let audit_digest = digest('b');
        let approved = json!({"schema":"approved-bundle-v1","owner_attestation_digest":owner_digest,
            "staged_manifest_digest":staged_digest,"baseline_manifest_digest":baseline_digest,
            "clean_audit_report_digest":audit_digest,"targets":targets});
        let attestation = json!({"schema":"owner-attestation-v1","revoked":false,
            "subject_kind":"final-staged-bundle","manifest_digest":staged_digest,
            "proposed_digest":staged_digest,"targets":targets});
        let apply_slots = BTreeMap::from([
            ("approved-bundle".into(), approved),
            ("owner-attestation".into(), attestation),
            (
                "audit-report".into(),
                json!({"schema":"audit-report-v1","disposition":"clean","manifest_digest":staged_digest}),
            ),
            (
                "active-manifest".into(),
                repository_manifest("staged", json!(baseline_digest)),
            ),
            (
                "baseline-manifest".into(),
                repository_manifest("baseline", Value::Null),
            ),
        ]);
        let apply_manifest = json!({"slots":{
            "approved-bundle":{"digest":approved_digest},
            "owner-attestation":{"digest":owner_digest},
            "audit-report":{"digest":audit_digest},
            "active-manifest":{"digest":staged_digest},
            "baseline-manifest":{"digest":baseline_digest}
        }});
        assert!(project_authority_state("apply", &apply_manifest, &apply_slots).is_ok());
        let mut revoked = apply_slots.clone();
        revoked.get_mut("owner-attestation").unwrap()["revoked"] = json!(true);
        assert!(project_authority_state("apply", &apply_manifest, &revoked).is_err());

        let mut verified_slots = apply_slots.clone();
        verified_slots.insert(
            "application-verification".into(),
            json!({"schema":"application-verification-v1","approved_bundle_digest":approved_digest,"exact":true,"mismatches":[]}),
        );
        let mut verified_manifest = apply_manifest.clone();
        verified_manifest["slots"]["application-verification"] = json!({"digest":digest('c')});
        assert!(project_authority_state("end", &verified_manifest, &verified_slots).is_ok());
        verified_slots.get_mut("application-verification").unwrap()["mismatches"] =
            json!([{"path":"README.md"}]);
        assert!(project_authority_state("end", &verified_manifest, &verified_slots).is_err());

        let clean_end = BTreeMap::from([(
            "audit-report".into(),
            json!({"schema":"audit-report-v1","disposition":"clean"}),
        )]);
        assert!(
            project_authority_state("end", &json!({"slots":{"audit-report":{}}}), &clean_end)
                .is_ok()
        );
        let nonclean_end = BTreeMap::from([(
            "audit-report".into(),
            json!({"schema":"audit-report-v1","disposition":"revision_required"}),
        )]);
        assert!(project_authority_state(
            "end",
            &json!({"slots":{"audit-report":{}}}),
            &nonclean_end
        )
        .is_err());
    }

    #[test]
    fn triage_derives_exact_event_from_audit_active_manifest_and_owner_subject() {
        let audit_digest = digest('1');
        let baseline_digest = digest('2');
        let staged_digest = digest('3');

        for (disposition, expected_event) in [
            ("revision_required", "revision-required"),
            ("evaluation_error", "evaluation-failed"),
            ("breach_confirmed", "breach-confirmed"),
        ] {
            let manifest = json!({"slots":{
                "audit-report":{"digest":audit_digest},
                "active-manifest":{"digest":baseline_digest}
            }});
            let slots = BTreeMap::from([
                (
                    "audit-report".into(),
                    json!({"schema":"audit-report-v1","disposition":disposition,"manifest_digest":baseline_digest}),
                ),
                (
                    "active-manifest".into(),
                    repository_manifest("baseline", Value::Null),
                ),
            ]);
            let projected = project_authority_state("triage", &manifest, &slots).unwrap();
            assert!(projected.contains(&format!("Advancement: {expected_event} only")));
        }

        let baseline_manifest = json!({"slots":{
            "audit-report":{"digest":audit_digest},
            "active-manifest":{"digest":baseline_digest}
        }});
        let baseline_slots = BTreeMap::from([
            (
                "audit-report".into(),
                json!({"schema":"audit-report-v1","disposition":"clean","manifest_digest":baseline_digest}),
            ),
            (
                "active-manifest".into(),
                repository_manifest("baseline", Value::Null),
            ),
        ]);
        assert!(
            project_authority_state("triage", &baseline_manifest, &baseline_slots)
                .unwrap()
                .contains("Advancement: baseline-clean only")
        );

        let staged_manifest = json!({"slots":{
            "audit-report":{"digest":audit_digest},
            "active-manifest":{"digest":staged_digest},
            "revision-request":{}
        }});
        let request_slots = BTreeMap::from([
            (
                "audit-report".into(),
                json!({"schema":"audit-report-v1","disposition":"clean","manifest_digest":staged_digest}),
            ),
            (
                "active-manifest".into(),
                repository_manifest("staged", json!(baseline_digest)),
            ),
            (
                "revision-request".into(),
                json!({
                    "schema":"revision-request-v1","subject_kind":"clean-staged-bundle",
                    "subject_digest":staged_digest,"audit_report_digest":audit_digest
                }),
            ),
        ]);
        assert!(
            project_authority_state("triage", &staged_manifest, &request_slots)
                .unwrap()
                .contains("Advancement: request-changes only")
        );

        let approval_manifest = json!({"slots":{
            "audit-report":{"digest":audit_digest},
            "active-manifest":{"digest":staged_digest},
            "owner-attestation":{}
        }});
        let approval_slots = BTreeMap::from([
            (
                "audit-report".into(),
                json!({"schema":"audit-report-v1","disposition":"clean","manifest_digest":staged_digest}),
            ),
            (
                "active-manifest".into(),
                repository_manifest("staged", json!(baseline_digest)),
            ),
            (
                "owner-attestation".into(),
                json!({
                    "schema":"owner-attestation-v1","subject_kind":"final-staged-bundle",
                    "manifest_digest":staged_digest,"proposed_digest":staged_digest,"revoked":false
                }),
            ),
        ]);
        assert!(
            project_authority_state("triage", &approval_manifest, &approval_slots)
                .unwrap()
                .contains("Advancement: staged-approved only")
        );

        let mut mismatched = baseline_slots;
        mismatched.get_mut("audit-report").unwrap()["manifest_digest"] = json!(digest('9'));
        assert!(project_authority_state("triage", &baseline_manifest, &mismatched).is_err());
        let mut ambiguous = request_slots;
        ambiguous.insert(
            "owner-attestation".into(),
            approval_slots["owner-attestation"].clone(),
        );
        assert!(project_authority_state("triage", &staged_manifest, &ambiguous).is_err());
    }

    #[test]
    fn revise_accepts_only_exact_pending_or_zero_pending_complete_shapes() {
        let request_digest = digest('1');
        let predecessor_digest = digest('2');
        let pending_manifest = json!({"slots":{
            "revision-ledger":{},"revision-record":{},
            "revision-request":{"digest":request_digest}
        }});
        let pending_slots = BTreeMap::from([
            (
                "revision-ledger".into(),
                json!({"schema":"revision-ledger-v1","pending_document":"AGENTS.md","accepted":[{"path":"docs/intent.md"}],"invalidated":[]}),
            ),
            (
                "revision-record".into(),
                json!({"schema":"revision-record-v1","target_document":"AGENTS.md","request_digest":request_digest,"predecessor_digest":predecessor_digest}),
            ),
            (
                "revision-request".into(),
                json!({"schema":"revision-request-v1","target_document":"AGENTS.md","subject_kind":"presented-draft","subject_digest":predecessor_digest}),
            ),
        ]);
        assert!(
            project_authority_state("revise-a", &pending_manifest, &pending_slots)
                .unwrap()
                .contains("Advancement: document-accepted only")
        );
        for missing in ["revision-record", "revision-request"] {
            let mut partial = pending_slots.clone();
            partial.remove(missing);
            assert!(project_authority_state("revise-a", &pending_manifest, &partial).is_err());
        }
        let mut bad_digest = pending_slots.clone();
        bad_digest.get_mut("revision-record").unwrap()["request_digest"] = json!(digest('9'));
        assert!(project_authority_state("revise-a", &pending_manifest, &bad_digest).is_err());
        let mut bad_subject = pending_slots.clone();
        bad_subject.get_mut("revision-request").unwrap()["subject_digest"] = json!(digest('9'));
        assert!(project_authority_state("revise-a", &pending_manifest, &bad_subject).is_err());
        let mut bad_prefix = pending_slots.clone();
        bad_prefix.get_mut("revision-ledger").unwrap()["accepted"] = json!([]);
        assert!(project_authority_state("revise-a", &pending_manifest, &bad_prefix).is_err());

        let complete_manifest = json!({"slots":{"revision-ledger":{}}});
        let complete_slots = BTreeMap::from([(
            "revision-ledger".into(),
            json!({"schema":"revision-ledger-v1","pending_document":null,"accepted":[
                {"path":"docs/intent.md"},{"path":"AGENTS.md"},{"path":"README.md"}
            ],"invalidated":[]}),
        )]);
        assert!(
            project_authority_state("revise-b", &complete_manifest, &complete_slots)
                .unwrap()
                .contains("Advancement: staged-audit-complete only")
        );
        let mut partial = complete_slots.clone();
        partial.get_mut("revision-ledger").unwrap()["accepted"] =
            json!([{"path":"docs/intent.md"},{"path":"AGENTS.md"}]);
        assert!(project_authority_state("revise-b", &complete_manifest, &partial).is_err());
        let mut invalidated = complete_slots.clone();
        invalidated.get_mut("revision-ledger").unwrap()["invalidated"] = json!(["README.md"]);
        assert!(project_authority_state("revise-b", &complete_manifest, &invalidated).is_err());
        let mut presented = complete_slots;
        presented.insert(
            "revision-record".into(),
            pending_slots["revision-record"].clone(),
        );
        assert!(project_authority_state("revise-b", &complete_manifest, &presented).is_err());
    }

    #[test]
    fn apply_rejects_missing_or_mismatched_clean_audit_and_manifest_slots() {
        let targets = json!([{"path":"README.md","digest":digest('1'),"mode":420}]);
        let owner_digest = digest('2');
        let audit_digest = digest('3');
        let staged_digest = digest('4');
        let baseline_digest = digest('5');
        let manifest = json!({"slots":{
            "approved-bundle":{"digest":digest('6')},"owner-attestation":{"digest":owner_digest},
            "audit-report":{"digest":audit_digest},"active-manifest":{"digest":staged_digest},
            "baseline-manifest":{"digest":baseline_digest}
        }});
        let slots = BTreeMap::from([
            (
                "approved-bundle".into(),
                json!({"schema":"approved-bundle-v1","owner_attestation_digest":owner_digest,"clean_audit_report_digest":audit_digest,"staged_manifest_digest":staged_digest,"baseline_manifest_digest":baseline_digest,"targets":targets}),
            ),
            (
                "owner-attestation".into(),
                json!({"schema":"owner-attestation-v1","revoked":false,"subject_kind":"final-staged-bundle","manifest_digest":staged_digest,"proposed_digest":staged_digest,"targets":targets}),
            ),
            (
                "audit-report".into(),
                json!({"schema":"audit-report-v1","disposition":"clean","manifest_digest":staged_digest}),
            ),
            (
                "active-manifest".into(),
                repository_manifest("staged", json!(baseline_digest)),
            ),
            (
                "baseline-manifest".into(),
                repository_manifest("baseline", Value::Null),
            ),
        ]);
        assert_eq!(validate_apply_authority(&manifest, &slots).unwrap(), 1);
        for required in ["audit-report", "active-manifest", "baseline-manifest"] {
            let mut missing = slots.clone();
            missing.remove(required);
            assert!(
                validate_apply_authority(&manifest, &missing).is_err(),
                "{required}"
            );
        }
        for field in [
            "clean_audit_report_digest",
            "staged_manifest_digest",
            "baseline_manifest_digest",
        ] {
            let mut mismatch = slots.clone();
            mismatch.get_mut("approved-bundle").unwrap()[field] = json!(digest('9'));
            assert!(
                validate_apply_authority(&manifest, &mismatch).is_err(),
                "{field}"
            );
        }
        let mut nonclean = slots;
        nonclean.get_mut("audit-report").unwrap()["disposition"] = json!("revision_required");
        assert!(validate_apply_authority(&manifest, &nonclean).is_err());
    }

    #[test]
    fn revision_states_are_behaviorally_identical_but_alternate() {
        let g = graph().unwrap();
        let edges = g["transitions"].as_array().unwrap();
        for event in [
            "document-accepted",
            "draft-changes-requested",
            "accepted-document-changes-requested",
        ] {
            assert!(edges.iter().any(|e| e["source_state"] == "revise-a"
                && e["event"] == event
                && e["target_state"] == "revise-b"));
            assert!(edges.iter().any(|e| e["source_state"] == "revise-b"
                && e["event"] == event
                && e["target_state"] == "revise-a"));
        }
    }
}
