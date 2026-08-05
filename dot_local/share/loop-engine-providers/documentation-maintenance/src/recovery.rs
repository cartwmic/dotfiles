//! Durable evaluation replay and binding-breach remediation validation.
use crate::{codec, evidence::EvidenceCatalog, schema::RecordKind};
use serde_json::Value;
use std::collections::BTreeSet;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EvaluationRecoveryDecision {
    Replay { result_digest: String },
    RetryAuthorized,
}

/// Bind replay to verified canonical result; authorize retry only for a
/// inspected protocol failure with no durable result.
pub fn validate_evaluation_recovery(
    recovery: &Value,
    run_id: &str,
    failed_identity: &str,
    evaluation_key_digest: &str,
    stored_evaluation_key_digest: &str,
    inspected_identities: &BTreeSet<String>,
    artifact_store: &crate::storage::ArtifactStore,
) -> Result<EvaluationRecoveryDecision, String> {
    crate::schema::validate(RecordKind::EvaluationRecovery, recovery)?;
    if recovery["run_id"] != run_id || recovery["failed_identity"] != failed_identity {
        return Err("recovery.evaluation.identity-mismatch".into());
    }
    if recovery["evaluation_key_digest"] != evaluation_key_digest
        || stored_evaluation_key_digest != evaluation_key_digest
    {
        return Err("recovery.evaluation.key-changed".into());
    }
    let inspected = recovery["inspected_evidence_digests"]
        .as_array()
        .ok_or("recovery.evaluation.inspection-missing")?
        .iter()
        .map(|v| {
            v.as_str()
                .map(str::to_string)
                .ok_or("recovery.evaluation.inspection-missing")
        })
        .collect::<Result<BTreeSet<_>, _>>()?;
    if inspected.is_empty()
        || !inspected.is_subset(inspected_identities)
        || !inspected.contains(failed_identity)
        || !inspected_identities.contains(failed_identity)
    {
        return Err("recovery.evaluation.inspection-missing".into());
    }
    if recovery["diagnosed_cause"]
        .as_str()
        .is_none_or(str::is_empty)
    {
        return Err("recovery.evaluation.cause-missing".into());
    }
    if recovery["caller_retry_authorized"] != true {
        return Err("recovery.evaluation.authorization-missing".into());
    }
    if artifact_store.run_id() != run_id {
        return Err("recovery.evaluation.identity-mismatch".into());
    }
    match artifact_store.load_digest(RecordKind::AuditReport, failed_identity)? {
        Some(stored) => {
            let result = &stored.decoded;
            if result.value["disposition"] != "evaluation_error"
                || codec::sha256(&codec::canonicalize(&result.value)?) != result.digest
                || result.value["run_id"] != run_id
            {
                return Err("recovery.evaluation.identity-mismatch".into());
            }
            Ok(EvaluationRecoveryDecision::Replay {
                result_digest: result.digest.clone(),
            })
        }
        None => Ok(EvaluationRecoveryDecision::RetryAuthorized),
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BreachRemediationRoute {
    WholeRepositoryReassessment {
        manifest_digest: String,
        rule_semantic_digest: String,
    },
}

/// Derive binding authority and reassessment result solely from verified records.
/// Caller booleans/strings cannot establish prior rule continuity or clearance.
#[allow(clippy::too_many_arguments)]
pub fn validate_breach_remediation(
    remediation: &Value,
    run_id: &str,
    prior_audit: &crate::codec::DecodedRecord,
    prior_judgment: &crate::codec::DecodedRecord,
    old_manifest: &crate::codec::DecodedRecord,
    new_manifest: &crate::codec::DecodedRecord,
    old_claims: &crate::codec::DecodedRecord,
    new_claims: &crate::codec::DecodedRecord,
    old_catalog: &EvidenceCatalog,
    new_catalog: &EvidenceCatalog,
    frozen_bundle: &crate::bundle::FrozenBundle,
    reassessment_audit: &crate::codec::DecodedRecord,
    reassessment_judgment: &crate::codec::DecodedRecord,
) -> Result<BreachRemediationRoute, String> {
    crate::schema::validate(RecordKind::BreachRemediation, remediation)?;
    for (record, kind) in [
        (prior_audit, RecordKind::AuditReport),
        (prior_judgment, RecordKind::JudgmentBundle),
        (old_manifest, RecordKind::RepositoryManifest),
        (new_manifest, RecordKind::RepositoryManifest),
        (old_claims, RecordKind::ClaimSet),
        (new_claims, RecordKind::ClaimSet),
        (reassessment_audit, RecordKind::AuditReport),
        (reassessment_judgment, RecordKind::JudgmentBundle),
    ] {
        verify(record, kind, run_id)?;
    }
    if !crate::claims::verify_anti_laundering_records(
        run_id,
        old_catalog,
        new_catalog,
        old_claims,
        new_claims,
    )?
    .is_empty()
    {
        return Err("recovery.breach.rule-weakened".into());
    }
    let verified_prior = crate::audit::assemble_verified(
        run_id,
        old_manifest,
        old_claims,
        prior_judgment,
        frozen_bundle,
        old_catalog,
    )
    .map_err(|error| format!("recovery.breach.invalid-prior-audit:{error:?}"))?;
    let verified_reassessment = crate::audit::assemble_verified(
        run_id,
        new_manifest,
        new_claims,
        reassessment_judgment,
        frozen_bundle,
        new_catalog,
    )
    .map_err(|error| format!("recovery.breach.invalid-reassessment:{error:?}"))?;
    if verified_prior.digest != prior_audit.digest
        || verified_prior.value != prior_audit.value
        || verified_reassessment.digest != reassessment_audit.digest
        || verified_reassessment.value != reassessment_audit.value
        || prior_audit.value["disposition"] != "breach_confirmed"
        || prior_audit.value["manifest_digest"] != old_manifest.digest
        || prior_audit.value["judgment_bundle_digest"] != prior_judgment.digest
        || prior_audit.value["claim_set_digest"] != old_claims.digest
        || prior_judgment.value["manifest_digest"] != old_manifest.digest
        || old_claims.value["manifest_digest"] != old_manifest.digest
        || new_claims.value["manifest_digest"] != new_manifest.digest
    {
        return Err("recovery.breach.identity-mismatch".into());
    }
    if remediation["run_id"] != run_id
        || remediation["prior_breach_digest"] != prior_audit.digest
        || remediation["old_manifest_digest"] != old_manifest.digest
        || remediation["new_manifest_digest"] != new_manifest.digest
    {
        return Err("recovery.breach.identity-mismatch".into());
    }
    if old_manifest.value["repository_fingerprint"] == new_manifest.value["repository_fingerprint"]
    {
        return Err("recovery.breach.identical-fingerprint".into());
    }
    let requested_semantic = required(remediation, "binding_rule_semantic_digest")?;
    let focused = prior_judgment.value["focused_breach_adjudications"]
        .as_array()
        .ok_or("recovery.breach.identity-mismatch")?
        .iter()
        .find(|v| {
            v["verdict"] == "breach_confirmed"
                && v["controlling_reason"] == "breach.binding-rule.confirmed"
                && v["binding_rule_semantic_digest"] == requested_semantic
                && prior_judgment.value["resolved"]
                    .as_array()
                    .is_some_and(|resolved| {
                        resolved.iter().any(|result| {
                            result["subject_kind"] == "claim"
                                && result["subject_id"] == v["subject_id"]
                                && result["verdict"] == "breached"
                                && result["controlling_reason"] == "claim.breached"
                        })
                    })
        })
        .ok_or("recovery.breach.identity-mismatch")?;
    let semantic = required(focused, "binding_rule_semantic_digest")?;
    let force = required(focused, "binding_force")?;
    let scope = required(focused, "binding_scope")?;
    let prior_subject = required(focused, "subject_id")?;
    let prior_claim_digest = required(focused, "claim_digest")?;
    if remediation["binding_rule_semantic_digest"] != semantic
        || remediation["binding_force"] != force
        || remediation["binding_scope"] != scope
        || remediation["rule_unweakened"] != true
    {
        return Err("recovery.breach.rule-weakened".into());
    }
    let old = claim_exact(old_claims, semantic, force, scope)?;
    let new = claim_exact(new_claims, semantic, force, scope)?;
    if old["claim_id"] != prior_subject
        || codec::sha256(&codec::canonicalize(old)?) != prior_claim_digest
        || old["document"] != "docs/intent.md"
        || new["document"] != old["document"]
        || old["proposition"] != new["proposition"]
    {
        return Err("recovery.breach.rule-weakened".into());
    }
    let changed = crate::repository::compare(&old_manifest.value, &new_manifest.value)?
        .into_iter()
        .map(|c| c.path)
        .collect::<BTreeSet<_>>();
    let declared = remediation["changed_non_core_paths"]
        .as_array()
        .ok_or("recovery.breach.documentation-only")?
        .iter()
        .map(|v| {
            v.as_str()
                .map(str::to_string)
                .ok_or("recovery.breach.documentation-only")
        })
        .collect::<Result<BTreeSet<_>, _>>()?;
    if declared.is_empty()
        || declared.iter().any(|p| is_core(p))
        || !declared.iter().all(|p| changed.contains(p))
    {
        return Err("recovery.breach.documentation-only".into());
    }
    let cited = remediation["cited_evidence_digests"]
        .as_array()
        .ok_or("recovery.breach.irrelevant-change")?
        .iter()
        .map(|v| v.as_str().ok_or("recovery.breach.irrelevant-change"))
        .collect::<Result<BTreeSet<_>, _>>()?;
    let focused_ids = focused["evidence_fact_ids"]
        .as_array()
        .ok_or("recovery.breach.irrelevant-change")?;
    let focused_digests = focused["evidence_digests"]
        .as_array()
        .ok_or("recovery.breach.irrelevant-change")?;
    if focused_ids.is_empty() || focused_ids.len() != focused_digests.len() {
        return Err("recovery.breach.irrelevant-change".into());
    }
    let mut seen_ids = BTreeSet::new();
    let mut relevant_digests = BTreeSet::new();
    let mut evidenced_paths = BTreeSet::new();
    for (id, digest) in focused_ids.iter().zip(focused_digests) {
        let id = id.as_str().ok_or("recovery.breach.irrelevant-change")?;
        let digest = digest.as_str().ok_or("recovery.breach.irrelevant-change")?;
        if !seen_ids.insert(id) {
            return Err("recovery.breach.irrelevant-change".into());
        }
        let fact = old_catalog
            .fact(id)
            .ok_or("recovery.breach.irrelevant-change")?;
        if fact.manifest_digest != old_manifest.digest || fact.result_digest != digest {
            return Err("recovery.breach.irrelevant-change".into());
        }
        if declared.contains(&fact.source_path) {
            relevant_digests.insert(digest);
            evidenced_paths.insert(fact.source_path.as_str());
        }
    }
    if evidenced_paths.len() != declared.len() || relevant_digests != cited {
        return Err("recovery.breach.irrelevant-change".into());
    }
    if remediation["reassessment_scope"] != "whole-repository"
        || reassessment_audit.value["claim_set_digest"] != new_claims.digest
        || remediation["reassessment_manifest_digest"] != new_manifest.digest
        || remediation["reassessment_rule_semantic_digest"] != semantic
        || reassessment_audit.value["manifest_digest"] != new_manifest.digest
        || reassessment_audit.value["judgment_bundle_digest"] != reassessment_judgment.digest
        || reassessment_judgment.value["manifest_digest"] != new_manifest.digest
    {
        return Err("recovery.breach.reassessment-missing".into());
    }
    if matches!(
        reassessment_audit.value["disposition"].as_str(),
        Some("breach_confirmed" | "evaluation_error")
    ) {
        return Err("recovery.breach.still-confirmed".into());
    }
    // Reassessment binds new claim inventory identity, not stale prior subject
    // identity; source movement may legitimately change claim_id.
    let reassessed = reassessment_judgment.value["resolved"]
        .as_array()
        .ok_or("recovery.breach.reassessment-missing")?
        .iter()
        .find(|v| v["subject_kind"] == "claim" && v["subject_id"] == new["claim_id"])
        .ok_or("recovery.breach.reassessment-missing")?;
    if reassessed["verdict"] != "adhered" || reassessed["controlling_reason"] != "claim.adhered" {
        return Err("recovery.breach.still-confirmed".into());
    }
    Ok(BreachRemediationRoute::WholeRepositoryReassessment {
        manifest_digest: new_manifest.digest.clone(),
        rule_semantic_digest: semantic.into(),
    })
}
fn verify(record: &crate::codec::DecodedRecord, kind: RecordKind, run: &str) -> Result<(), String> {
    if record.kind != kind || record.value["run_id"] != run {
        return Err("recovery.breach.identity-mismatch".into());
    }
    crate::schema::validate(kind, &record.value)?;
    if codec::sha256(&codec::canonicalize(&record.value)?) != record.digest {
        return Err("recovery.breach.identity-mismatch".into());
    }
    Ok(())
}
fn required<'a>(value: &'a Value, field: &str) -> Result<&'a str, String> {
    value[field]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or_else(|| "recovery.breach.identity-mismatch".into())
}
fn claim_exact<'a>(
    claims: &'a crate::codec::DecodedRecord,
    semantic: &str,
    force: &str,
    scope: &str,
) -> Result<&'a Value, String> {
    let matches = claims.value["claims"]
        .as_array()
        .ok_or("recovery.breach.rule-weakened")?
        .iter()
        .filter(|c| c["semantic_digest"] == semantic && c["force"] == force && c["scope"] == scope)
        .collect::<Vec<_>>();
    if matches.len() != 1 {
        return Err("recovery.breach.rule-weakened".into());
    }
    Ok(matches[0])
}
fn is_core(path: &str) -> bool {
    matches!(path, "README.md" | "AGENTS.md" | "docs/intent.md")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn digest(c: char) -> String {
        format!("sha256:{}", c.to_string().repeat(64))
    }
    #[test]
    fn replay_requires_result_digest_and_unchanged_stored_key() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().canonicalize().unwrap();
        let store = crate::storage::ArtifactStore::open(&root, "run").unwrap();
        let manifest = crate::codec::encode_record(&json!({"schema":"repository-manifest-v1","run_id":"run","manifest_kind":"baseline","work_root":"/repo","git_common_dir":"/repo/.git","entries":[],"repository_fingerprint":digest('a'),"baseline_digest":null,"overlay_paths":[]}), RecordKind::RepositoryManifest, "run").unwrap();
        let claims = crate::codec::encode_record(&json!({"schema":"claim-set-v1","run_id":"run","manifest_digest":manifest.digest.clone(),"claims":[]}), RecordKind::ClaimSet, "run").unwrap();
        let judgment = crate::codec::encode_record(&json!({"schema":"judgment-bundle-v1","run_id":"run","manifest_digest":manifest.digest.clone(),"bundle_digest":digest('b'),"model_identity_digest":digest('c'),"decoding_parameter_digest":digest('d'),"claim_votes":[],"role_votes":[],"focused_breach_adjudications":[],"resolved":[]}), RecordKind::JudgmentBundle, "run").unwrap();
        let result = crate::codec::encode_record(&json!({"schema":"audit-report-v1","run_id":"run","manifest_digest":manifest.digest.clone(),"claim_set_digest":claims.digest.clone(),"judgment_bundle_digest":judgment.digest.clone(),"disposition":"evaluation_error","findings":[]}), RecordKind::AuditReport, "run").unwrap();
        for (kind, value) in [
            (RecordKind::RepositoryManifest, &manifest.value),
            (RecordKind::ClaimSet, &claims.value),
            (RecordKind::JudgmentBundle, &judgment.value),
            (RecordKind::AuditReport, &result.value),
        ] {
            store
                .store(
                    crate::storage::RecordCategory::Audits,
                    "failed",
                    kind,
                    value,
                )
                .unwrap();
        }
        let recovery = json!({"schema":"evaluation-recovery-v1","run_id":"run","failed_identity":result.digest,"evaluation_key_digest":digest('d'),"inspected_evidence_digests":[result.digest.clone(),digest('e')],"diagnosed_cause":"timeout","changed_retry_condition":null,"transient_failure_rationale":"outage","caller_retry_authorized":true});
        let inspected = BTreeSet::from([result.digest.clone(), digest('e')]);
        assert!(matches!(
            validate_evaluation_recovery(
                &recovery,
                "run",
                &result.digest,
                &digest('d'),
                &digest('d'),
                &inspected,
                &store
            )
            .unwrap(),
            EvaluationRecoveryDecision::Replay { .. }
        ));
        assert_eq!(
            validate_evaluation_recovery(
                &recovery,
                "run",
                &result.digest,
                &digest('d'),
                &digest('f'),
                &inspected,
                &store
            )
            .unwrap_err(),
            "recovery.evaluation.key-changed"
        );
    }
    #[test]
    fn retry_requires_inspected_failed_identity() {
        let recovery = json!({"schema":"evaluation-recovery-v1","run_id":"run","failed_identity":digest('a'),"evaluation_key_digest":digest('b'),"inspected_evidence_digests":[digest('c')],"diagnosed_cause":"transport","changed_retry_condition":"configured","transient_failure_rationale":null,"caller_retry_authorized":true});
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().canonicalize().unwrap();
        let store = crate::storage::ArtifactStore::open(&root, "run").unwrap();
        assert_eq!(
            validate_evaluation_recovery(
                &recovery,
                "run",
                &digest('a'),
                &digest('b'),
                &digest('b'),
                &BTreeSet::from([digest('c')]),
                &store
            )
            .unwrap_err(),
            "recovery.evaluation.inspection-missing"
        );
    }
}
