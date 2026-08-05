use crate::authority::{self, CurrentSnapshot};
use crate::boundary;
use crate::bundle::{self, BundleDecodeError};
use crate::storage::ArtifactStore;
use crate::workflow;
use crate::PROVIDER_VERSION;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::Path;

pub const PROTOCOL_MAJOR: u32 = 1;
pub const REQUEST_LIMIT_BYTES: usize = 4 * 1024 * 1024;
pub const RESULT_LIMIT_BYTES: usize = 1024 * 1024;

#[derive(Debug, Deserialize)]
pub struct RequestEnvelope {
    pub protocol_major: u32,
    pub role: String,
    pub invocation_id: String,
    pub registration: Registration,
    pub payload: Value,
}

#[derive(Debug, Deserialize)]
pub struct Registration {
    pub registration_id: String,
    pub config_revision: u64,
    pub executable: String,
    #[serde(default)]
    pub argv: Vec<String>,
    pub working_directory: String,
    pub timeout_seconds: u64,
}

#[derive(Debug, Serialize)]
pub struct ResultEnvelope {
    pub protocol_major: u32,
    pub role: String,
    pub invocation_id: String,
    pub provider_version: &'static str,
    pub result: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Evidence {
    pub id: String,
    pub kind: String,
    pub locator: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub digest: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub media_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub observed_at: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct Diagnostic {
    pub code: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
}

impl Diagnostic {
    fn new(code: &str, message: impl Into<String>) -> Self {
        Self {
            code: code.to_string(),
            message: message.into(),
            path: None,
        }
    }

    fn at(code: &str, message: impl Into<String>, path: impl Into<String>) -> Self {
        Self {
            code: code.to_string(),
            message: message.into(),
            path: Some(path.into()),
        }
    }
}

#[derive(Debug, Deserialize)]
struct RunSnapshot {
    run_id: String,
    registration_id: String,
    graph_revision: String,
    lifecycle: String,
    current_state: String,
    workflow_state_version: u64,
    lifecycle_version: u64,
    inputs: serde_json::Map<String, Value>,
    stored_graph: Value,
}

pub fn handle(request: RequestEnvelope) -> Result<ResultEnvelope, String> {
    if request.protocol_major != PROTOCOL_MAJOR {
        return Err(format!(
            "unsupported protocol_major {}",
            request.protocol_major
        ));
    }
    if request.invocation_id.is_empty() {
        return Err("invocation_id must not be empty".to_string());
    }
    validate_registration(&request.registration)?;
    let result = match request.role.as_str() {
        "describe" => description()?,
        "validate_inputs" => validate_inputs(&request.payload),
        "evaluate_gates" => evaluate_gates_for_invocation(&request.payload, &request.invocation_id),
        "live_guidance" => live_guidance(&request.payload),
        "check_compatibility" => check_compatibility(&request.payload),
        other => return Err(format!("unsupported role {other:?}")),
    };
    Ok(ResultEnvelope {
        protocol_major: PROTOCOL_MAJOR,
        role: request.role,
        invocation_id: request.invocation_id,
        provider_version: PROVIDER_VERSION,
        result,
    })
}

fn validate_registration(registration: &Registration) -> Result<(), String> {
    if registration.registration_id.is_empty()
        || registration.config_revision == 0
        || !Path::new(&registration.executable).is_absolute()
        || !Path::new(&registration.working_directory).is_absolute()
        || registration.timeout_seconds == 0
    {
        return Err(
            "registration is missing required protocol-v1 identity or absolute paths".to_string(),
        );
    }
    let _ = &registration.argv;
    Ok(())
}

fn description() -> Result<Value, String> {
    workflow::graph()
        .map(|graph| json!({"kind":"description","graph":graph}))
        .map_err(|error| format!("fatal provider construction failure: {error}"))
}

fn validate_inputs(payload: &Value) -> Value {
    let candidates = match payload.get("candidate_values").and_then(Value::as_object) {
        Some(candidates) => candidates,
        None => {
            return rejected(vec![Diagnostic::at(
                "input.type",
                "candidate_values must be an object",
                "/candidate_values",
            )])
        }
    };
    let Some(work) = candidates.get("work_root").and_then(Value::as_str) else {
        return rejected(vec![Diagnostic::at(
            "input.required",
            "work_root is required",
            "/candidate_values/work_root",
        )]);
    };
    let Some(artifact) = candidates.get("artifact_root").and_then(Value::as_str) else {
        return rejected(vec![Diagnostic::at(
            "input.required",
            "artifact_root is required",
            "/candidate_values/artifact_root",
        )]);
    };
    let roots = match boundary::validate_roots(Path::new(work), Path::new(artifact)) {
        Ok(roots) => roots,
        Err(error) => return rejected(vec![Diagnostic::at(error.code, error.message, error.path)]),
    };
    let mut artifact_entries = match std::fs::read_dir(&roots.artifact_root) {
        Ok(entries) => entries,
        Err(error) => {
            return rejected(vec![Diagnostic::at(
                "input.artifact-root.inspect",
                error.to_string(),
                roots.artifact_root.display().to_string(),
            )])
        }
    };
    if artifact_entries.next().is_some() {
        return rejected(vec![Diagnostic::at(
            "input.artifact-root.not-empty",
            "artifact_root must be empty before a run claims it",
            roots.artifact_root.display().to_string(),
        )]);
    }
    let mut normalized = candidates.clone();
    normalized.insert(
        "work_root".to_string(),
        Value::String(roots.work_root.to_string_lossy().into_owned()),
    );
    normalized.insert(
        "artifact_root".to_string(),
        Value::String(roots.artifact_root.to_string_lossy().into_owned()),
    );
    json!({"kind":"accepted","values":normalized})
}

#[cfg(test)]
fn evaluate_gates(payload: &Value) -> Value {
    evaluate_gates_for_invocation(payload, "direct-evaluate")
}

fn evaluate_gates_for_invocation(payload: &Value, invocation_id: &str) -> Value {
    let snapshot: RunSnapshot = match payload.get("snapshot").cloned().map(serde_json::from_value) {
        Some(Ok(snapshot)) => snapshot,
        Some(Err(error)) => {
            return evaluation_error(vec![Diagnostic::at(
                "snapshot.invalid",
                format!("snapshot does not satisfy protocol v1: {error}"),
                "/snapshot",
            )])
        }
        None => {
            return evaluation_error(vec![Diagnostic::at(
                "snapshot.missing",
                "snapshot is required",
                "/snapshot",
            )])
        }
    };
    if snapshot.registration_id.is_empty()
        || snapshot.lifecycle.is_empty()
        || snapshot.lifecycle_version == u64::MAX
        || !snapshot.stored_graph.is_object()
    {
        return evaluation_error(vec![Diagnostic::at(
            "snapshot.invalid",
            "snapshot identities are incomplete",
            "/snapshot",
        )]);
    }
    let frozen_bundle = match bundle::decode_stored_bundle(&snapshot.stored_graph) {
        Ok(bundle) => bundle,
        Err(BundleDecodeError::Unsupported(error)) => {
            return incompatible(vec![Diagnostic::new(
                "compatibility.unsupported-bundle",
                error,
            )])
        }
        Err(BundleDecodeError::Execution(error)) => {
            return evaluation_error(vec![Diagnostic::new("bundle.supported-execution", error)])
        }
    };
    let required_gates = match payload.get("required_gate_ids").and_then(Value::as_array) {
        Some(gates) if !gates.is_empty() => gates,
        _ => {
            return evaluation_error(vec![Diagnostic::at(
                "gates.required",
                "required_gate_ids must be a non-empty array",
                "/required_gate_ids",
            )])
        }
    };
    let verdicts = match required_gates
        .iter()
        .map(|gate| {
            gate.as_str()
                .filter(|gate| !gate.is_empty())
                .map(|gate| json!({"gate_id":gate,"passed":false}))
                .ok_or(())
        })
        .collect::<Result<Vec<_>, _>>()
    {
        Ok(verdicts) => verdicts,
        Err(()) => {
            return evaluation_error(vec![Diagnostic::at(
                "gates.required",
                "required_gate_ids contains an invalid gate ID",
                "/required_gate_ids",
            )])
        }
    };
    let Some(work) = snapshot.inputs.get("work_root").and_then(Value::as_str) else {
        return evaluation_error(vec![Diagnostic::at(
            "input.required",
            "work_root is required",
            "/snapshot/inputs/work_root",
        )]);
    };
    let Some(artifact) = snapshot.inputs.get("artifact_root").and_then(Value::as_str) else {
        return evaluation_error(vec![Diagnostic::at(
            "input.required",
            "artifact_root is required",
            "/snapshot/inputs/artifact_root",
        )]);
    };
    let roots = match boundary::validate_roots(Path::new(work), Path::new(artifact)) {
        Ok(roots) => roots,
        Err(error) => {
            return evaluation_error(vec![Diagnostic::at(error.code, error.message, error.path)])
        }
    };
    let store = match ArtifactStore::open(&roots.artifact_root, &snapshot.run_id) {
        Ok(store) => store,
        Err(error) => {
            return evaluation_error(vec![Diagnostic::at(
                "artifact-root.ownership",
                error,
                roots.artifact_root.display().to_string(),
            )])
        }
    };
    let selected: Vec<Evidence> = match serde_json::from_value(
        payload
            .get("selected_evidence")
            .cloned()
            .unwrap_or_else(|| json!([])),
    ) {
        Ok(selected) => selected,
        Err(error) => {
            return evaluation_error(vec![Diagnostic::at(
                "evidence.invalid",
                error.to_string(),
                "/selected_evidence",
            )])
        }
    };
    let current = CurrentSnapshot {
        run_id: &snapshot.run_id,
        graph_revision: &snapshot.graph_revision,
        current_state: &snapshot.current_state,
        workflow_state_version: snapshot.workflow_state_version,
        stored_graph: snapshot.stored_graph.clone(),
    };
    let authority = match authority::validate_selected_authority(&store, &current, &selected) {
        Ok(authority) => authority,
        Err(error) => {
            return evaluation_error(vec![Diagnostic::at(
                "authority.invalid",
                error,
                "/selected_evidence",
            )])
        }
    };
    let authority_slots = match authority.load_slots(&store) {
        Ok(slots) => slots,
        Err(error) => {
            return evaluation_error(vec![Diagnostic::at(
                "authority.slot-load",
                error,
                "/selected_evidence",
            )])
        }
    };
    // Execute complete P3 assessment pipeline. Missing P6 transport becomes
    // retained evaluator-error votes and a durable verified audit, never a
    // fabricated content verdict.
    let view = crate::repository::RepositoryView::new(&roots, &snapshot.run_id);
    let manifest = match view.capture_stable() {
        Ok(record) => record,
        Err(error) => return evaluation_error(vec![Diagnostic::new("repository.capture", error)]),
    };
    let catalog = match crate::evidence::EvidenceCatalog::from_manifest(&manifest) {
        Ok(catalog) => catalog,
        Err(error) => return evaluation_error(vec![Diagnostic::new("evidence.catalog", error)]),
    };
    let claims = match crate::claims::extract_core_claims(&snapshot.run_id, &catalog) {
        Ok(record) => record,
        Err(error) => return evaluation_error(vec![Diagnostic::new("claims.extract", error)]),
    };
    let recovery_input =
        match audit_recovery_input(&authority_slots, payload, &store, &snapshot.run_id) {
            Ok(input) => input,
            Err(error) => return evaluation_error(vec![Diagnostic::new("recovery.input", error)]),
        };
    let replay_report = match &recovery_input {
        Some(AuditRecoveryInput::Evaluation {
            record,
            inspected_digests,
        }) => match validate_evaluation_recovery_before_judgment(
            record,
            inspected_digests,
            &store,
            &snapshot.run_id,
            &frozen_bundle,
            &manifest,
            &claims,
        ) {
            Ok(report) => report,
            Err(error) => {
                return evaluation_error(vec![Diagnostic::new(
                    "recovery.evaluation.invalid",
                    error,
                )])
            }
        },
        _ => None,
    };
    let (judgment, base_report) = if let Some(report) = replay_report {
        let judgment = match load_linked(
            &store,
            crate::schema::RecordKind::JudgmentBundle,
            &report.value["judgment_bundle_digest"],
        ) {
            Ok(record) => record,
            Err(error) => return evaluation_error(vec![Diagnostic::new("recovery.replay", error)]),
        };
        let verified = match crate::audit::assemble_verified(
            &snapshot.run_id,
            &manifest,
            &claims,
            &judgment,
            &frozen_bundle,
            &catalog,
        ) {
            Ok(record) => record,
            Err(error) => {
                return evaluation_error(vec![Diagnostic::new(
                    "recovery.replay",
                    format!("{error:?}"),
                )])
            }
        };
        if verified.digest != report.digest || verified.value != report.value {
            return evaluation_error(vec![Diagnostic::new(
                "recovery.replay",
                "stored result differs from deterministic replay",
            )]);
        }
        (judgment, report)
    } else {
        let judgment = match crate::judgment::coordinate_stored_bundle(
            &view,
            &manifest,
            &claims,
            &frozen_bundle,
            &snapshot.run_id,
            &catalog,
        ) {
            Ok(record) => record,
            Err(error) => {
                return evaluation_error(vec![Diagnostic::new("judgment.coordinate", error)])
            }
        };
        let report = match crate::audit::assemble_verified(
            &snapshot.run_id,
            &manifest,
            &claims,
            &judgment,
            &frozen_bundle,
            &catalog,
        ) {
            Ok(record) => record,
            Err(error) => {
                return evaluation_error(vec![Diagnostic::new(
                    "audit.assemble",
                    format!("{error:?}"),
                )])
            }
        };
        (judgment, report)
    };
    let report = match bind_and_validate_recovery(
        recovery_input.as_ref(),
        &store,
        &snapshot.run_id,
        &frozen_bundle,
        &manifest,
        &claims,
        &catalog,
        &judgment,
        &base_report,
    ) {
        Ok(record) => record,
        Err(error) => return evaluation_error(vec![Diagnostic::new("recovery.bind", error)]),
    };
    for record in [&manifest, &claims, &judgment] {
        if let Err(error) = store.store(
            crate::storage::RecordCategory::Audits,
            invocation_id,
            record.kind,
            &record.value,
        ) {
            return evaluation_error(vec![Diagnostic::new("audit.store", error)]);
        }
    }
    if let Some(recovery) = &recovery_input {
        let record = match recovery {
            AuditRecoveryInput::Evaluation { record, .. }
            | AuditRecoveryInput::Breach { record } => record,
        };
        if let Err(error) = store.store(
            crate::storage::RecordCategory::Audits,
            invocation_id,
            record.kind,
            &record.value,
        ) {
            return evaluation_error(vec![Diagnostic::new("audit.store", error)]);
        }
    }
    let report_record = match store.store(
        crate::storage::RecordCategory::Audits,
        invocation_id,
        report.kind,
        &report.value,
    ) {
        Ok(value) => value,
        Err(error) => return evaluation_error(vec![Diagnostic::new("audit.store", error)]),
    };
    let evidence = vec![Evidence {
        id: format!("{invocation_id}-audit-report"),
        kind: "audit-report-v1".into(),
        locator: format!(
            "file://{}",
            roots
                .artifact_root
                .join(&report_record.relative_path)
                .display()
        ),
        digest: Some(report.digest.clone()),
        media_type: Some("application/json".into()),
        metadata: Some(
            json!({"schema":"audit-report-v1","disposition":report.value["disposition"],"manifest_digest":manifest.digest,"claim_set_digest":claims.digest,"judgment_bundle_digest":judgment.digest,"recovery_record_digest":report.value.get("recovery_record_digest"),"recovery_validation":report.value.get("recovery_validation")}),
        ),
        observed_at: None,
    }];
    json!({"kind":"verdicts","verdicts":verdicts,"evidence":evidence})
}

enum AuditRecoveryInput {
    Evaluation {
        record: crate::codec::DecodedRecord,
        inspected_digests: std::collections::BTreeSet<String>,
    },
    Breach {
        record: crate::codec::DecodedRecord,
    },
}

fn audit_recovery_input(
    slots: &std::collections::BTreeMap<String, Value>,
    payload: &Value,
    store: &ArtifactStore,
    run_id: &str,
) -> Result<Option<AuditRecoveryInput>, String> {
    let selected_evaluation = slots.get("evaluation-recovery");
    let selected_breach = slots.get("breach-remediation");
    if selected_evaluation.is_some() && selected_breach.is_some() {
        return Err("audit authority selects conflicting recovery records".into());
    }
    let inline: Vec<Evidence> = serde_json::from_value(
        payload
            .get("inline_evidence")
            .cloned()
            .unwrap_or_else(|| json!([])),
    )
    .map_err(|error| format!("inline recovery evidence is invalid: {error}"))?;
    let recovery_evidence = inline
        .iter()
        .filter(|evidence| evidence.kind == "evaluation-recovery-v1")
        .collect::<Vec<_>>();
    if recovery_evidence.len() > 1
        || (recovery_evidence.len() == 1
            && (selected_evaluation.is_some() || selected_breach.is_some()))
    {
        return Err("exactly one selected or inline recovery record is allowed".into());
    }
    if let Some(value) = selected_evaluation {
        let record = crate::codec::encode_record(
            value,
            crate::schema::RecordKind::EvaluationRecovery,
            run_id,
        )?;
        let inspected_digests = verified_stored_inspection_digests(store, &record.value)?;
        return Ok(Some(AuditRecoveryInput::Evaluation {
            record,
            inspected_digests,
        }));
    }
    if let Some(value) = selected_breach {
        return Ok(Some(AuditRecoveryInput::Breach {
            record: crate::codec::encode_record(
                value,
                crate::schema::RecordKind::BreachRemediation,
                run_id,
            )?,
        }));
    }
    let Some(evidence) = recovery_evidence.first() else {
        return Ok(None);
    };
    let value = evidence
        .metadata
        .as_ref()
        .ok_or("inline evaluation recovery has no record metadata")?;
    let record =
        crate::codec::encode_record(value, crate::schema::RecordKind::EvaluationRecovery, run_id)?;
    if evidence.digest.as_deref() != Some(record.digest.as_str()) {
        return Err("inline evaluation recovery digest differs from record".into());
    }
    let failed_identity = record.value["failed_identity"]
        .as_str()
        .ok_or("recovery.evaluation.identity-mismatch")?;
    let inspected_digests = inline
        .iter()
        .filter(|candidate| candidate.id != evidence.id)
        .filter(|candidate| {
            candidate.metadata.as_ref().is_some_and(|metadata| {
                metadata.get("failed_identity").and_then(Value::as_str) == Some(failed_identity)
                    || metadata.get("invocation_id").and_then(Value::as_str)
                        == Some(failed_identity)
            })
        })
        .filter_map(|candidate| candidate.digest.as_deref())
        .filter(|digest| crate::codec::validate_digest(digest).is_ok())
        .map(str::to_string)
        .collect();
    Ok(Some(AuditRecoveryInput::Evaluation {
        record,
        inspected_digests,
    }))
}

fn verified_stored_inspection_digests(
    store: &ArtifactStore,
    recovery: &Value,
) -> Result<std::collections::BTreeSet<String>, String> {
    let claimed = recovery["inspected_evidence_digests"]
        .as_array()
        .ok_or("recovery.evaluation.inspection-missing")?;
    let mut verified = std::collections::BTreeSet::new();
    for digest in claimed {
        let digest = digest
            .as_str()
            .ok_or("recovery.evaluation.inspection-missing")?;
        for kind in crate::schema::RecordKind::ALL {
            if store.load_digest(kind, digest)?.is_some() {
                verified.insert(digest.to_string());
                break;
            }
        }
    }
    Ok(verified)
}

fn validate_evaluation_recovery_before_judgment(
    recovery: &crate::codec::DecodedRecord,
    inspected_digests: &std::collections::BTreeSet<String>,
    store: &ArtifactStore,
    run_id: &str,
    frozen_bundle: &crate::bundle::FrozenBundle,
    manifest: &crate::codec::DecodedRecord,
    claims: &crate::codec::DecodedRecord,
) -> Result<Option<crate::codec::DecodedRecord>, String> {
    let current_key = crate::recovery::evaluation_key_digest(frozen_bundle, manifest, claims)?;
    let failed_identity = recovery.value["failed_identity"]
        .as_str()
        .ok_or("recovery.evaluation.identity-mismatch")?;
    let prior = if crate::codec::validate_digest(failed_identity).is_ok() {
        store.load_digest(crate::schema::RecordKind::AuditReport, failed_identity)?
    } else {
        store.load_invocation(
            crate::storage::RecordCategory::Audits,
            failed_identity,
            crate::schema::RecordKind::AuditReport,
        )?
    };
    let stored_key = if let Some(prior) = &prior {
        if !inspected_digests.contains(&prior.digest) {
            return Err("recovery.evaluation.inspection-missing".into());
        }
        let prior_manifest = load_linked(
            store,
            crate::schema::RecordKind::RepositoryManifest,
            &prior.decoded.value["manifest_digest"],
        )?;
        let prior_claims = load_linked(
            store,
            crate::schema::RecordKind::ClaimSet,
            &prior.decoded.value["claim_set_digest"],
        )?;
        let prior_judgment = load_linked(
            store,
            crate::schema::RecordKind::JudgmentBundle,
            &prior.decoded.value["judgment_bundle_digest"],
        )?;
        let prior_bundle_digest = prior_judgment.value["bundle_digest"]
            .as_str()
            .ok_or("recovery.evaluation.key-changed")?;
        crate::recovery::evaluation_key_digest_from_parts(
            prior_bundle_digest,
            &prior_manifest,
            &prior_claims,
        )?
    } else {
        current_key.clone()
    };
    let decision = crate::recovery::validate_evaluation_recovery(
        &recovery.value,
        run_id,
        failed_identity,
        &current_key,
        &stored_key,
        inspected_digests,
        store,
    )?;
    match decision {
        crate::recovery::EvaluationRecoveryDecision::Replay { result_digest } => {
            let prior = prior.ok_or("recovery.evaluation.replay-missing")?;
            if prior.digest != result_digest {
                return Err("recovery.evaluation.replay-mismatch".into());
            }
            Ok(Some(prior.decoded))
        }
        crate::recovery::EvaluationRecoveryDecision::RetryAuthorized => Ok(None),
    }
}

#[allow(clippy::too_many_arguments)]
fn bind_and_validate_recovery(
    recovery: Option<&AuditRecoveryInput>,
    store: &ArtifactStore,
    run_id: &str,
    frozen_bundle: &crate::bundle::FrozenBundle,
    manifest: &crate::codec::DecodedRecord,
    claims: &crate::codec::DecodedRecord,
    catalog: &crate::evidence::EvidenceCatalog,
    judgment: &crate::codec::DecodedRecord,
    report: &crate::codec::DecodedRecord,
) -> Result<crate::codec::DecodedRecord, String> {
    let Some(recovery) = recovery else {
        return Ok(report.clone());
    };
    let (schema, digest, validation, diagnostic) = match recovery {
        AuditRecoveryInput::Evaluation { record, .. } => (
            "evaluation-recovery-v1",
            record.digest.as_str(),
            "passed",
            None,
        ),
        AuditRecoveryInput::Breach { record } => {
            let prior_audit = load_linked(
                store,
                crate::schema::RecordKind::AuditReport,
                &record.value["prior_breach_digest"],
            )?;
            let prior_judgment = load_linked(
                store,
                crate::schema::RecordKind::JudgmentBundle,
                &prior_audit.value["judgment_bundle_digest"],
            )?;
            let old_manifest = load_linked(
                store,
                crate::schema::RecordKind::RepositoryManifest,
                &record.value["old_manifest_digest"],
            )?;
            let old_claims = load_linked(
                store,
                crate::schema::RecordKind::ClaimSet,
                &prior_audit.value["claim_set_digest"],
            )?;
            let old_catalog = crate::evidence::EvidenceCatalog::from_manifest(&old_manifest)?;
            let result = crate::recovery::validate_breach_remediation(
                &record.value,
                run_id,
                &prior_audit,
                &prior_judgment,
                &old_manifest,
                manifest,
                &old_claims,
                claims,
                &old_catalog,
                catalog,
                frozen_bundle,
                report,
                judgment,
            );
            match result {
                Ok(_) => (
                    "breach-remediation-v1",
                    record.digest.as_str(),
                    "passed",
                    None,
                ),
                Err(error) => (
                    "breach-remediation-v1",
                    record.digest.as_str(),
                    "failed",
                    Some(error),
                ),
            }
        }
    };
    let mut value = report.value.clone();
    value["recovery_record_schema"] = json!(schema);
    value["recovery_record_digest"] = json!(digest);
    value["recovery_validation"] = json!(validation);
    value["recovery_diagnostic"] = json!(diagnostic);
    crate::codec::encode_record(&value, crate::schema::RecordKind::AuditReport, run_id)
}

fn load_linked(
    store: &ArtifactStore,
    kind: crate::schema::RecordKind,
    digest: &Value,
) -> Result<crate::codec::DecodedRecord, String> {
    let digest = digest
        .as_str()
        .ok_or_else(|| format!("linked {kind} digest is missing"))?;
    store
        .load_digest(kind, digest)?
        .map(|record| record.decoded)
        .ok_or_else(|| format!("linked {kind} {digest} is absent"))
}

/// Staged/audit integration boundary for anti-laundering. It accepts only
/// decoded claim-set records and delegates canonical inventory comparison.
pub fn validate_staged_claim_authority(
    run_id: &str,
    baseline_catalog: &crate::evidence::EvidenceCatalog,
    proposed_catalog: &crate::evidence::EvidenceCatalog,
    baseline: &crate::codec::DecodedRecord,
    proposed: &crate::codec::DecodedRecord,
) -> Result<(), String> {
    let findings = crate::claims::verify_anti_laundering_records(
        run_id,
        baseline_catalog,
        proposed_catalog,
        baseline,
        proposed,
    )?;
    if findings.is_empty() {
        Ok(())
    } else {
        Err(format!(
            "authority anti-laundering refused: {}",
            findings
                .iter()
                .map(|f| f.reason_id.as_str())
                .collect::<Vec<_>>()
                .join(",")
        ))
    }
}

fn require_supported_bundle(stored_graph: &Value) -> Result<(), Value> {
    match bundle::decode_stored_bundle(stored_graph) {
        Ok(_) => Ok(()),
        Err(BundleDecodeError::Unsupported(error)) => Err(incompatible(vec![Diagnostic::new(
            "compatibility.unsupported-bundle",
            error,
        )])),
        Err(BundleDecodeError::Execution(error)) => Err(evaluation_error(vec![Diagnostic::new(
            "bundle.supported-execution",
            error,
        )])),
    }
}

fn live_guidance(payload: &Value) -> Value {
    let snapshot: RunSnapshot = match payload.get("snapshot").cloned().map(serde_json::from_value) {
        Some(Ok(snapshot)) => snapshot,
        Some(Err(error)) => {
            return evaluation_error(vec![Diagnostic::at(
                "snapshot.invalid",
                error.to_string(),
                "/snapshot",
            )])
        }
        None => {
            return evaluation_error(vec![Diagnostic::at(
                "snapshot.missing",
                "snapshot is required",
                "/snapshot",
            )])
        }
    };
    if let Err(response) = require_supported_bundle(&snapshot.stored_graph) {
        return response;
    }
    let Some(work) = snapshot.inputs.get("work_root").and_then(Value::as_str) else {
        return evaluation_error(vec![Diagnostic::at(
            "input.required",
            "work_root is required",
            "/snapshot/inputs/work_root",
        )]);
    };
    let Some(artifact) = snapshot.inputs.get("artifact_root").and_then(Value::as_str) else {
        return evaluation_error(vec![Diagnostic::at(
            "input.required",
            "artifact_root is required",
            "/snapshot/inputs/artifact_root",
        )]);
    };
    let roots = match boundary::validate_roots(Path::new(work), Path::new(artifact)) {
        Ok(roots) => roots,
        Err(error) => {
            return evaluation_error(vec![Diagnostic::at(error.code, error.message, error.path)])
        }
    };
    let store = match ArtifactStore::open(&roots.artifact_root, &snapshot.run_id) {
        Ok(store) => store,
        Err(error) => {
            return evaluation_error(vec![Diagnostic::at(
                "artifact-root.ownership",
                error,
                roots.artifact_root.display().to_string(),
            )])
        }
    };
    let selected: Vec<Evidence> = match serde_json::from_value(
        payload
            .get("selected_evidence")
            .cloned()
            .unwrap_or_else(|| json!([])),
    ) {
        Ok(selected) => selected,
        Err(error) => {
            return evaluation_error(vec![Diagnostic::at(
                "evidence.invalid",
                error.to_string(),
                "/selected_evidence",
            )])
        }
    };
    let current = CurrentSnapshot {
        run_id: &snapshot.run_id,
        graph_revision: &snapshot.graph_revision,
        current_state: &snapshot.current_state,
        workflow_state_version: snapshot.workflow_state_version,
        stored_graph: snapshot.stored_graph.clone(),
    };
    let authority = match authority::validate_selected_authority(&store, &current, &selected) {
        Ok(authority) => authority,
        Err(error) => {
            return evaluation_error(vec![Diagnostic::at(
                "authority.invalid",
                error,
                "/selected_evidence",
            )])
        }
    };
    let authority_slots = match authority.load_slots(&store) {
        Ok(slots) => slots,
        Err(error) => {
            return evaluation_error(vec![Diagnostic::at(
                "authority.slot-load",
                error,
                "/selected_evidence",
            )])
        }
    };
    match workflow::project_live(
        &snapshot.stored_graph,
        &snapshot.current_state,
        &authority.manifest().value,
        &authority_slots,
    ) {
        Ok(text) => json!({"kind":"guidance","text":text}),
        Err(BundleDecodeError::Unsupported(error)) => incompatible(vec![Diagnostic::new(
            "compatibility.unsupported-bundle",
            error,
        )]),
        Err(BundleDecodeError::Execution(error)) => {
            evaluation_error(vec![Diagnostic::new("guidance.supported-execution", error)])
        }
    }
}

fn check_compatibility(payload: &Value) -> Value {
    let requested: Vec<&str> = payload
        .get("capabilities")
        .and_then(Value::as_array)
        .map(|items| items.iter().filter_map(Value::as_str).collect())
        .unwrap_or_else(|| {
            vec![
                "protocol-v1",
                "run-boundary",
                "evaluate_gates",
                "live_guidance",
            ]
        });
    let stored = payload.get("stored_graph").unwrap_or(&Value::Null);
    let bundle_status = bundle::decode_stored_bundle(stored);
    if let Err(BundleDecodeError::Execution(error)) = &bundle_status {
        return evaluation_error(vec![Diagnostic::new("bundle.supported-execution", error)]);
    }
    let capabilities: Vec<Value> = requested
        .into_iter()
        .map(|capability| match capability {
            "protocol-v1" | "run-boundary" => json!({"capability":capability,"status":"compatible","diagnostics":[]}),
            "frozen-policy" | "state-graph" | "live_guidance" => match &bundle_status {
                Ok(_) => json!({"capability":capability,"status":"compatible","diagnostics":[]}),
                Err(BundleDecodeError::Unsupported(error)) => json!({"capability":capability,"status":"incompatible","diagnostics":[{"code":"compatibility.unsupported-bundle","message":error}]}),
                Err(BundleDecodeError::Execution(_)) => unreachable!("returned above"),
            },
            "evaluate_gates" => match &bundle_status {
                Ok(_) => json!({"capability":capability,"status":"compatible","diagnostics":[{"code":"judgment.transport-required","message":"P3 audit path is available; until P6 installs qualified transport, sealed broker persists a durable evaluation_error audit and fails every requested gate without fabricating a content verdict."}]}),
                Err(BundleDecodeError::Unsupported(error)) => json!({"capability":capability,"status":"incompatible","diagnostics":[{"code":"compatibility.unsupported-bundle","message":error}]}),
                Err(BundleDecodeError::Execution(_)) => unreachable!("returned above"),
            },
            _ => json!({
                "capability":capability,"status":"unknown",
                "diagnostics":[{"code":"compatibility.unknown","message":format!("capability {capability} is not recognized") }]
            }),
        })
        .collect();
    json!({"kind":"findings","capabilities":capabilities})
}

fn rejected(diagnostics: Vec<Diagnostic>) -> Value {
    json!({"kind":"rejected","diagnostics":diagnostics})
}
fn incompatible(diagnostics: Vec<Diagnostic>) -> Value {
    json!({"kind":"incompatible","diagnostics":diagnostics})
}
fn evaluation_error(diagnostics: Vec<Diagnostic>) -> Value {
    json!({"kind":"evaluation_error","diagnostics":diagnostics})
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::codec;
    use std::fs;
    use std::process::Command;
    use tempfile::tempdir;

    fn registration() -> Registration {
        Registration {
            registration_id: "reg-1".into(),
            config_revision: 1,
            executable: "/bin/provider".into(),
            argv: vec![],
            working_directory: "/tmp".into(),
            timeout_seconds: 60,
        }
    }

    #[test]
    fn bundle_compatibility_precedes_roots_and_authority() {
        let snapshot = |stored_graph: Value| {
            json!({
                "run_id":"run-1","registration_id":"reg-1","graph_revision":format!("sha256:{}", "1".repeat(64)),
                "lifecycle":"running","current_state":"triage","workflow_state_version":1,"lifecycle_version":1,
                "inputs":{"work_root":"/does/not/exist","artifact_root":"/also/missing"},"stored_graph":stored_graph
            })
        };
        let unsupported = json!({"metadata":{"documentation_audit_bundle_v1":{"schema":"documentation-audit-bundle-v2"}}});
        let evaluated = evaluate_gates(
            &json!({"snapshot":snapshot(unsupported.clone()),"selected_evidence":[]}),
        );
        assert_eq!(evaluated["kind"], "incompatible");
        assert_eq!(
            evaluated["diagnostics"][0]["code"],
            "compatibility.unsupported-bundle"
        );
        let guidance =
            live_guidance(&json!({"snapshot":snapshot(unsupported),"selected_evidence":[]}));
        assert_eq!(guidance["kind"], "incompatible");

        let mut malformed = workflow::graph().unwrap();
        malformed["metadata"]["documentation_audit_bundle_v1"]["profile"]["unknown"] = json!(true);
        let bytes =
            codec::canonicalize(&malformed["metadata"]["documentation_audit_bundle_v1"]).unwrap();
        malformed["metadata"]["documentation_audit_bundle_digest"] = json!(codec::sha256(&bytes));
        let evaluated =
            evaluate_gates(&json!({"snapshot":snapshot(malformed.clone()),"selected_evidence":[]}));
        assert_eq!(evaluated["kind"], "evaluation_error");
        assert_eq!(
            evaluated["diagnostics"][0]["code"],
            "bundle.supported-execution"
        );
        let compatibility = check_compatibility(
            &json!({"stored_graph":malformed,"capabilities":["frozen-policy"]}),
        );
        assert_eq!(compatibility["kind"], "evaluation_error");
    }

    #[test]
    fn no_p6_transport_commits_durable_evaluation_error_audit() {
        let work = tempdir().unwrap();
        let artifacts = tempdir().unwrap();
        Command::new("git")
            .args(["init", "-q"])
            .current_dir(work.path())
            .status()
            .unwrap();
        let before = Command::new("git")
            .args(["status", "--porcelain=v1", "--untracked-files=all"])
            .current_dir(work.path())
            .output()
            .unwrap()
            .stdout;
        let result = evaluate_gates(&json!({
            "snapshot":{
                "run_id":"run-1","registration_id":"reg-1","graph_revision":format!("sha256:{}", "1".repeat(64)),
                "lifecycle":"running","current_state":"audit","workflow_state_version":0,"lifecycle_version":1,
                "inputs":{"work_root":fs::canonicalize(work.path()).unwrap(),"artifact_root":fs::canonicalize(artifacts.path()).unwrap()},
                "stored_graph":workflow::graph().unwrap()
            },
            "required_gate_ids":["audit-semantic"]
        }));
        assert_eq!(result["kind"], "verdicts");
        assert_eq!(
            result["verdicts"][0],
            json!({"gate_id":"audit-semantic","passed":false})
        );
        assert_eq!(result["evidence"][0]["kind"], "audit-report-v1");
        let audit_dir = artifacts.path().join("provider/audits/direct-evaluate");
        assert_eq!(fs::read_dir(audit_dir).unwrap().count(), 4);
        let store =
            ArtifactStore::open(&fs::canonicalize(artifacts.path()).unwrap(), "run-1").unwrap();
        let report = store
            .load(
                "provider/audits/direct-evaluate/audit-report-v1.json",
                crate::schema::RecordKind::AuditReport,
                result["evidence"][0]["digest"].as_str().unwrap(),
            )
            .unwrap();
        assert_eq!(report.decoded.value["disposition"], "evaluation_error");
        let after = Command::new("git")
            .args(["status", "--porcelain=v1", "--untracked-files=all"])
            .current_dir(work.path())
            .output()
            .unwrap()
            .stdout;
        assert_eq!(before, after);
    }

    #[test]
    fn invocation_identity_replays_durable_result_without_transport() {
        let work = tempdir().unwrap();
        let artifacts = tempdir().unwrap();
        Command::new("git")
            .args(["init", "-q"])
            .current_dir(work.path())
            .status()
            .unwrap();
        let graph = workflow::graph().unwrap();
        let snapshot = json!({
            "run_id":"run-1","registration_id":"reg-1","graph_revision":format!("sha256:{}", "1".repeat(64)),
            "lifecycle":"running","current_state":"audit","workflow_state_version":0,"lifecycle_version":1,
            "inputs":{"work_root":fs::canonicalize(work.path()).unwrap(),"artifact_root":fs::canonicalize(artifacts.path()).unwrap()},
            "stored_graph":graph
        });
        crate::judgment::reset_fail_closed_invocation_count();
        let first = evaluate_gates_for_invocation(
            &json!({"snapshot":snapshot.clone(),"required_gate_ids":["audit-semantic"],"inline_evidence":[]}),
            "failed-invocation",
        );
        assert_eq!(first["kind"], "verdicts");
        let invocations = crate::judgment::fail_closed_invocation_count();
        assert!(invocations > 0);
        let store =
            ArtifactStore::open(&fs::canonicalize(artifacts.path()).unwrap(), "run-1").unwrap();
        let prior_report = store
            .load_invocation(
                crate::storage::RecordCategory::Audits,
                "failed-invocation",
                crate::schema::RecordKind::AuditReport,
            )
            .unwrap()
            .unwrap();
        let prior_manifest = load_linked(
            &store,
            crate::schema::RecordKind::RepositoryManifest,
            &prior_report.decoded.value["manifest_digest"],
        )
        .unwrap();
        let prior_claims = load_linked(
            &store,
            crate::schema::RecordKind::ClaimSet,
            &prior_report.decoded.value["claim_set_digest"],
        )
        .unwrap();
        let bundle = bundle::decode_stored_bundle(&snapshot["stored_graph"]).unwrap();
        let key = crate::recovery::evaluation_key_digest(&bundle, &prior_manifest, &prior_claims)
            .unwrap();
        let recovery = crate::codec::encode_record(
            &json!({"schema":"evaluation-recovery-v1","run_id":"run-1","failed_identity":"failed-invocation","evaluation_key_digest":key,"inspected_evidence_digests":[prior_report.digest],"diagnosed_cause":"qualified transport outage","changed_retry_condition":null,"transient_failure_rationale":"transport recovered","caller_retry_authorized":true}),
            crate::schema::RecordKind::EvaluationRecovery,
            "run-1",
        )
        .unwrap();
        let retry = evaluate_gates_for_invocation(
            &json!({
                "snapshot":snapshot,
                "required_gate_ids":["audit-semantic"],
                "inline_evidence":[
                    {"id":"recovery","kind":"evaluation-recovery-v1","locator":"inline:recovery","digest":recovery.digest,"metadata":recovery.value},
                    {"id":"inspected-report","kind":"audit-report-v1","locator":"provider:audit","digest":prior_report.digest,"metadata":{"invocation_id":"failed-invocation"}}
                ]
            }),
            "retry-invocation",
        );
        assert_eq!(retry["kind"], "verdicts");
        assert_eq!(crate::judgment::fail_closed_invocation_count(), invocations);
        let replayed = store
            .load_invocation(
                crate::storage::RecordCategory::Audits,
                "retry-invocation",
                crate::schema::RecordKind::AuditReport,
            )
            .unwrap()
            .unwrap();
        assert_eq!(replayed.decoded.value["recovery_validation"], "passed");
        assert_eq!(
            replayed.decoded.value["recovery_record_schema"],
            "evaluation-recovery-v1"
        );
    }

    #[test]
    fn malformed_gate_request_commits_no_artifacts() {
        let work = tempdir().unwrap();
        let artifacts = tempdir().unwrap();
        Command::new("git")
            .args(["init", "-q"])
            .current_dir(work.path())
            .status()
            .unwrap();
        let result = evaluate_gates(&json!({"snapshot":{
            "run_id":"run-1","registration_id":"reg-1","graph_revision":format!("sha256:{}", "1".repeat(64)),
            "lifecycle":"running","current_state":"audit","workflow_state_version":0,"lifecycle_version":1,
            "inputs":{"work_root":fs::canonicalize(work.path()).unwrap(),"artifact_root":fs::canonicalize(artifacts.path()).unwrap()},
            "stored_graph":workflow::graph().unwrap()
        },"required_gate_ids":[]}));
        assert_eq!(result["kind"], "evaluation_error");
        assert_eq!(result["diagnostics"][0]["code"], "gates.required");
        assert!(fs::read_dir(artifacts.path()).unwrap().next().is_none());
    }

    #[test]
    fn describe_emits_p3_graph_and_input_validation_reaches_dispatch() {
        let request = RequestEnvelope {
            protocol_major: 1,
            role: "describe".into(),
            invocation_id: "inv".into(),
            registration: registration(),
            payload: json!({}),
        };
        let response = handle(request).unwrap();
        assert_eq!(response.result["kind"], "description");
        assert_eq!(
            response.result["graph"]["transitions"]
                .as_array()
                .unwrap()
                .len(),
            22
        );
        assert_eq!(response.result["graph"]["metadata"]["provider_phase"], "P3");
        let compatibility = check_compatibility(
            &json!({"stored_graph":response.result["graph"].clone(),"capabilities":["evaluate_gates"]}),
        );
        assert_eq!(compatibility["capabilities"][0]["status"], "compatible");
        assert_eq!(
            compatibility["capabilities"][0]["diagnostics"][0]["code"],
            "judgment.transport-required"
        );

        let work = tempdir().unwrap();
        let artifacts = tempdir().unwrap();
        Command::new("git")
            .args(["init", "-q"])
            .current_dir(work.path())
            .status()
            .unwrap();
        let payload = json!({"declarations":[],"candidate_values":{
            "work_root":fs::canonicalize(work.path()).unwrap(),
            "artifact_root":fs::canonicalize(artifacts.path()).unwrap()
        }});
        let request = RequestEnvelope {
            protocol_major: 1,
            role: "validate_inputs".into(),
            invocation_id: "inv".into(),
            registration: registration(),
            payload,
        };
        assert_eq!(handle(request).unwrap().result["kind"], "accepted");
    }
}
