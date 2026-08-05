use serde_json::Value;
use std::{fmt, str::FromStr};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum RecordKind {
    RepositoryManifest,
    ClaimSet,
    RoleAxisJudgment,
    JudgmentBundle,
    AuditReport,
    RevisionRequest,
    IntentSemanticDiff,
    RevisionRecord,
    RevisionLedger,
    OwnerAttestation,
    ApprovedBundle,
    ApplicationVerification,
    AuthorityManifest,
    TransitionCertificate,
    EvaluationRecovery,
    BreachRemediation,
    CalibrationReport,
}

impl RecordKind {
    pub const ALL: [Self; 17] = [
        Self::RepositoryManifest,
        Self::ClaimSet,
        Self::RoleAxisJudgment,
        Self::JudgmentBundle,
        Self::AuditReport,
        Self::RevisionRequest,
        Self::IntentSemanticDiff,
        Self::RevisionRecord,
        Self::RevisionLedger,
        Self::OwnerAttestation,
        Self::ApprovedBundle,
        Self::ApplicationVerification,
        Self::AuthorityManifest,
        Self::TransitionCertificate,
        Self::EvaluationRecovery,
        Self::BreachRemediation,
        Self::CalibrationReport,
    ];

    pub const fn name(self) -> &'static str {
        match self {
            Self::RepositoryManifest => "repository-manifest-v1",
            Self::ClaimSet => "claim-set-v1",
            Self::RoleAxisJudgment => "role-axis-judgment-v1",
            Self::JudgmentBundle => "judgment-bundle-v1",
            Self::AuditReport => "audit-report-v1",
            Self::RevisionRequest => "revision-request-v1",
            Self::IntentSemanticDiff => "intent-semantic-diff-v1",
            Self::RevisionRecord => "revision-record-v1",
            Self::RevisionLedger => "revision-ledger-v1",
            Self::OwnerAttestation => "owner-attestation-v1",
            Self::ApprovedBundle => "approved-bundle-v1",
            Self::ApplicationVerification => "application-verification-v1",
            Self::AuthorityManifest => "authority-manifest-v1",
            Self::TransitionCertificate => "transition-certificate-v1",
            Self::EvaluationRecovery => "evaluation-recovery-v1",
            Self::BreachRemediation => "breach-remediation-v1",
            Self::CalibrationReport => "calibration-report-v1",
        }
    }

    pub const fn schema_text(self) -> &'static str {
        match self {
            Self::RepositoryManifest => include_str!("../schemas/repository-manifest-v1.json"),
            Self::ClaimSet => include_str!("../schemas/claim-set-v1.json"),
            Self::RoleAxisJudgment => include_str!("../schemas/role-axis-judgment-v1.json"),
            Self::JudgmentBundle => include_str!("../schemas/judgment-bundle-v1.json"),
            Self::AuditReport => include_str!("../schemas/audit-report-v1.json"),
            Self::RevisionRequest => include_str!("../schemas/revision-request-v1.json"),
            Self::IntentSemanticDiff => include_str!("../schemas/intent-semantic-diff-v1.json"),
            Self::RevisionRecord => include_str!("../schemas/revision-record-v1.json"),
            Self::RevisionLedger => include_str!("../schemas/revision-ledger-v1.json"),
            Self::OwnerAttestation => include_str!("../schemas/owner-attestation-v1.json"),
            Self::ApprovedBundle => include_str!("../schemas/approved-bundle-v1.json"),
            Self::ApplicationVerification => {
                include_str!("../schemas/application-verification-v1.json")
            }
            Self::AuthorityManifest => include_str!("../schemas/authority-manifest-v1.json"),
            Self::TransitionCertificate => {
                include_str!("../schemas/transition-certificate-v1.json")
            }
            Self::EvaluationRecovery => include_str!("../schemas/evaluation-recovery-v1.json"),
            Self::BreachRemediation => include_str!("../schemas/breach-remediation-v1.json"),
            Self::CalibrationReport => include_str!("../schemas/calibration-report-v1.json"),
        }
    }
}

impl fmt::Display for RecordKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.name())
    }
}

impl FromStr for RecordKind {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::ALL
            .into_iter()
            .find(|kind| kind.name() == value)
            .ok_or_else(|| format!("unknown record schema {value:?}"))
    }
}

pub fn validate(kind: RecordKind, value: &Value) -> Result<(), String> {
    let schema: Value = serde_json::from_str(kind.schema_text())
        .map_err(|error| format!("embedded {} schema is invalid JSON: {error}", kind.name()))?;
    let validator = jsonschema::validator_for(&schema)
        .map_err(|error| format!("embedded {} schema does not compile: {error}", kind.name()))?;
    let errors: Vec<String> = validator
        .iter_errors(value)
        .take(32)
        .map(|error| error.to_string())
        .collect();
    if !errors.is_empty() {
        return Err(format!(
            "{} schema violation: {}",
            kind.name(),
            errors.join("; ")
        ));
    }
    validate_semantics(kind, value)
}

fn validate_semantics(kind: RecordKind, value: &Value) -> Result<(), String> {
    if kind == RecordKind::RepositoryManifest {
        let mut previous: Option<&str> = None;
        for entry in value["entries"].as_array().expect("schema checked entries") {
            let path = entry["path"].as_str().expect("schema checked path");
            if previous.is_some_and(|prior| prior >= path) {
                return Err(format!(
                    "repository manifest entries must be uniquely sorted: {path}"
                ));
            }
            previous = Some(path);
            if entry["kind"] != entry["identity"]["kind"] {
                return Err(format!(
                    "repository manifest identity kind differs at {path}"
                ));
            }
        }
    }
    if kind == RecordKind::TransitionCertificate {
        let gates = value["required_gate_ids"]
            .as_array()
            .expect("schema checked gates");
        let mut previous: Option<&str> = None;
        for gate in gates {
            let gate = gate.as_str().expect("schema checked gate");
            if previous.is_some_and(|prior| prior >= gate) {
                return Err("transition certificate gate IDs must be uniquely sorted".to_string());
            }
            previous = Some(gate);
        }
        let source = value["source_workflow_state_version"].as_u64().unwrap();
        let target = value["expected_successor_workflow_state_version"]
            .as_u64()
            .unwrap();
        if target != source + 1 {
            return Err(
                "transition certificate successor version must equal source version plus one"
                    .to_string(),
            );
        }
    }
    if kind == RecordKind::EvaluationRecovery {
        let changed = value["changed_retry_condition"].as_str();
        let transient = value["transient_failure_rationale"].as_str();
        if changed.is_some() == transient.is_some() {
            return Err("evaluation recovery requires exactly one retry alternative".to_string());
        }
    }
    if kind == RecordKind::BreachRemediation {
        if value["old_manifest_digest"] == value["new_manifest_digest"] {
            return Err("breach remediation refuses identical repository fingerprints".to_string());
        }
        if value["new_manifest_digest"] != value["reassessment_manifest_digest"]
            || value["binding_rule_semantic_digest"] != value["reassessment_rule_semantic_digest"]
        {
            return Err("breach remediation reassessment binding does not match new manifest and exact prior rule".to_string());
        }
        let core = ["README.md", "AGENTS.md", "docs/intent.md"];
        if value["changed_non_core_paths"]
            .as_array()
            .expect("schema checked changed paths")
            .iter()
            .all(|path| path.as_str().is_some_and(|path| core.contains(&path)))
        {
            return Err("breach remediation requires a changed non-core path".to_string());
        }
    }
    if kind == RecordKind::AuthorityManifest {
        let slots = value["slots"].as_object().expect("schema checked slots");
        for (slot, artifact) in slots {
            let expected =
                slot_schema(slot).ok_or_else(|| format!("unsupported authority slot {slot}"))?;
            if artifact["schema"] != expected {
                return Err(format!("authority slot {slot} requires schema {expected}"));
            }
        }
    }
    Ok(())
}

pub fn slot_schema(slot: &str) -> Option<&'static str> {
    Some(match slot {
        "baseline-manifest" | "active-manifest" => "repository-manifest-v1",
        "claim-set" => "claim-set-v1",
        "role-axis-judgment" => "role-axis-judgment-v1",
        "judgment-bundle" => "judgment-bundle-v1",
        "audit-report" => "audit-report-v1",
        "revision-request" => "revision-request-v1",
        "intent-semantic-diff" => "intent-semantic-diff-v1",
        "revision-record" => "revision-record-v1",
        "revision-ledger" => "revision-ledger-v1",
        "owner-attestation" => "owner-attestation-v1",
        "approved-bundle" => "approved-bundle-v1",
        "application-verification" => "application-verification-v1",
        "evaluation-recovery" => "evaluation-recovery-v1",
        "breach-remediation" => "breach-remediation-v1",
        "calibration-report" => "calibration-report-v1",
        _ => return None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn every_schema_accepts_its_fixture_and_rejects_cross_subjects() {
        for kind in RecordKind::ALL {
            let path = format!(
                "{}/fixtures/records/valid/{}.json",
                env!("CARGO_MANIFEST_DIR"),
                kind.name()
            );
            let bytes = fs::read(path).unwrap();
            let value: Value = serde_json::from_slice(&bytes).unwrap();
            validate(kind, &value).unwrap_or_else(|error| panic!("{}: {error}", kind.name()));
            for other in RecordKind::ALL {
                if other != kind {
                    assert!(
                        validate(other, &value).is_err(),
                        "{} accepted {}",
                        other,
                        kind
                    );
                }
            }
        }
    }

    #[test]
    fn judgment_bundle_discriminates_claim_role_and_focused_breach_outputs() {
        let path = format!(
            "{}/fixtures/records/valid/judgment-bundle-v1.json",
            env!("CARGO_MANIFEST_DIR")
        );
        let mut value: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        value["role_votes"] = serde_json::json!([{
            "vote_id":"r1",
            "subject_kind":"role",
            "subject_id":"README.md:R1",
            "judge_ordinal":1,
            "verdict":"satisfied",
            "controlling_reason":"role.r1.satisfied",
            "evidence_digests":[]
        }]);
        value["resolved"]
            .as_array_mut()
            .unwrap()
            .push(serde_json::json!({
                "subject_kind":"role",
                "subject_id":"README.md:R1",
                "verdict":"satisfied",
                "controlling_reason":"role.r1.satisfied"
            }));
        validate(RecordKind::JudgmentBundle, &value).unwrap();

        value["claim_votes"][0]["verdict"] = Value::String("satisfied".to_string());
        assert!(validate(RecordKind::JudgmentBundle, &value).is_err());

        let path = format!(
            "{}/fixtures/records/valid/judgment-bundle-v1.json",
            env!("CARGO_MANIFEST_DIR")
        );
        let mut value: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        value["focused_breach_adjudications"] = serde_json::json!([{
            "adjudication_id":"a1",
            "subject_kind":"claim",
            "subject_id":"c1",
            "verdict":"breach_confirmed",
            "controlling_reason":"breach.binding-rule.confirmed",
            "evidence_digests":[]
        }]);
        validate(RecordKind::JudgmentBundle, &value).unwrap();
        value["focused_breach_adjudications"][0]["verdict"] = Value::String("breached".to_string());
        assert!(validate(RecordKind::JudgmentBundle, &value).is_err());
    }

    #[test]
    fn recovery_alternatives_and_reassessment_bindings_are_exact() {
        let load = |name: &str| -> Value {
            serde_json::from_slice(
                &fs::read(format!(
                    "{}/fixtures/records/valid/{name}.json",
                    env!("CARGO_MANIFEST_DIR")
                ))
                .unwrap(),
            )
            .unwrap()
        };
        let evaluation = load("evaluation-recovery-v1");
        validate(RecordKind::EvaluationRecovery, &evaluation).unwrap();
        let mut both = evaluation.clone();
        both["changed_retry_condition"] = Value::String("service configuration corrected".into());
        assert!(validate(RecordKind::EvaluationRecovery, &both).is_err());
        let mut neither = evaluation.clone();
        neither["changed_retry_condition"] = Value::Null;
        neither["transient_failure_rationale"] = Value::Null;
        assert!(validate(RecordKind::EvaluationRecovery, &neither).is_err());
        let mut empty_cause = evaluation;
        empty_cause["diagnosed_cause"] = Value::String(String::new());
        assert!(validate(RecordKind::EvaluationRecovery, &empty_cause).is_err());

        let remediation = load("breach-remediation-v1");
        validate(RecordKind::BreachRemediation, &remediation).unwrap();
        let mut wrong_scope = remediation.clone();
        wrong_scope["reassessment_scope"] = Value::String("changed-paths-only".into());
        assert!(validate(RecordKind::BreachRemediation, &wrong_scope).is_err());
        let mut wrong_rule = remediation;
        wrong_rule["reassessment_rule_semantic_digest"] =
            Value::String(format!("sha256:{}", "9".repeat(64)));
        assert!(validate(RecordKind::BreachRemediation, &wrong_rule).is_err());
    }

    #[test]
    fn negative_schema_fixtures_cover_required_failure_classes() {
        let cases = [
            ("unknown-key.json", RecordKind::ClaimSet),
            ("missing-run-id.json", RecordKind::ClaimSet),
            ("wrong-type.json", RecordKind::ClaimSet),
            ("out-of-bound.json", RecordKind::RevisionLedger),
            ("cross-record-substitution.json", RecordKind::ClaimSet),
        ];
        for (path, kind) in cases {
            let bytes = fs::read(format!(
                "{}/fixtures/records/invalid/{path}",
                env!("CARGO_MANIFEST_DIR")
            ))
            .unwrap();
            let value: Value = serde_json::from_slice(&bytes).unwrap();
            assert!(
                validate(kind, &value).is_err(),
                "fixture {path} unexpectedly passed"
            );
        }
    }
}
