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
    if kind == RecordKind::ClaimSet {
        for claim in value["claims"].as_array().expect("schema checked claims") {
            let proposition = normalize_claim_text(claim["proposition"].as_str().unwrap());
            let force = claim["force"].as_str().unwrap();
            let scope = normalize_claim_text(claim["scope"].as_str().unwrap());
            let expected = crate::codec::sha256(&crate::codec::canonicalize(
                &serde_json::json!({"proposition":proposition,"force":force,"scope":scope}),
            )?);
            if claim["semantic_digest"] != expected
                || claim["location"]["path"] != claim["document"]
            {
                return Err("claim semantic digest or document location is invalid".into());
            }
        }
    }
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
    if kind == RecordKind::JudgmentBundle {
        let mut vote_ids = std::collections::BTreeSet::new();
        let mut invocations = std::collections::BTreeSet::new();
        let mut subjects = std::collections::BTreeSet::new();
        for field in ["claim_votes", "role_votes"] {
            for vote in value[field].as_array().expect("schema checked votes") {
                let vote_id = vote["vote_id"].as_str().expect("schema checked vote ID");
                let invocation = vote["invocation_id"]
                    .as_str()
                    .expect("schema checked invocation");
                if !vote_ids.insert(vote_id) || !invocations.insert(invocation) {
                    return Err("judgment bundle vote or invocation identity is duplicated".into());
                }
                let ids = vote["evidence_fact_ids"]
                    .as_array()
                    .expect("schema checked evidence facts");
                let mut facts = std::collections::BTreeSet::new();
                if ids
                    .iter()
                    .any(|id| !facts.insert(id.as_str().expect("schema checked fact ID")))
                {
                    return Err("judgment vote repeats an evidence fact identity".into());
                }
                let kind = vote["subject_kind"].as_str().unwrap();
                let verdict = vote["verdict"].as_str().unwrap();
                let reason = vote["controlling_reason"].as_str().unwrap();
                if (verdict == "evaluation_error") != vote["evaluation_diagnostic"].is_string() {
                    return Err(
                        "judgment evaluation diagnostic presence differs from failure verdict"
                            .into(),
                    );
                }
                if kind == "claim"
                    && !matches!(
                        (verdict, reason),
                        ("adhered", "claim.adhered")
                            | ("drifted", "claim.drifted")
                            | ("breached", "claim.breached")
                            | ("unverifiable", "claim.unverifiable")
                            | ("evaluation_error", "claim.evaluation-error")
                    )
                {
                    return Err("claim judgment verdict/reason tuple is invalid".into());
                }
                subjects.insert((kind, vote["subject_id"].as_str().unwrap()));
            }
        }
        let mut resolved = std::collections::BTreeSet::new();
        for result in value["resolved"]
            .as_array()
            .expect("schema checked resolved")
        {
            let subject = (
                result["subject_kind"].as_str().unwrap(),
                result["subject_id"].as_str().unwrap(),
            );
            if !resolved.insert(subject) || !subjects.contains(&subject) {
                return Err("judgment resolved subject is duplicated or has no vote".into());
            }
            if result["subject_kind"] == "claim"
                && !matches!(
                    (
                        result["verdict"].as_str().unwrap(),
                        result["controlling_reason"].as_str().unwrap()
                    ),
                    ("adhered", "claim.adhered")
                        | ("drifted", "claim.drifted")
                        | ("breached", "claim.breached")
                        | ("unverifiable", "claim.unverifiable")
                        | ("evaluation_error", "claim.evaluation-error")
                )
            {
                return Err("resolved claim verdict/reason tuple is invalid".into());
            }
        }
        let mut votes_by_subject = std::collections::BTreeMap::<(&str, &str), Vec<&Value>>::new();
        let mut ordinal_keys = std::collections::BTreeSet::new();
        for field in ["claim_votes", "role_votes"] {
            for vote in value[field].as_array().expect("schema checked votes") {
                let kind = vote["subject_kind"].as_str().unwrap();
                let subject = vote["subject_id"].as_str().unwrap();
                let ordinal = vote["judge_ordinal"].as_u64().unwrap();
                if !ordinal_keys.insert((kind, subject, ordinal)) {
                    return Err("judgment vote subject ordinal is duplicated".into());
                }
                if vote["evidence_fact_ids"].as_array().unwrap().len()
                    != vote["evidence_digests"].as_array().unwrap().len()
                {
                    return Err("judgment vote evidence identity/digest count differs".into());
                }
                votes_by_subject
                    .entry((kind, subject))
                    .or_default()
                    .push(vote);
            }
        }
        for votes in votes_by_subject.values() {
            let ordinals = votes
                .iter()
                .map(|vote| vote["judge_ordinal"].as_u64().unwrap())
                .collect::<std::collections::BTreeSet<_>>();
            if !matches!(
                ordinals.iter().copied().collect::<Vec<_>>().as_slice(),
                [1, 2] | [1, 2, 3]
            ) {
                return Err("judgment votes must have exactly ordinals {1,2} or {1,2,3}".into());
            }
        }
        let mut focused_by_subject = std::collections::BTreeMap::<&str, &Value>::new();
        let mut adjudication_ids = std::collections::BTreeSet::new();
        for adjudication in value["focused_breach_adjudications"]
            .as_array()
            .expect("schema checked adjudications")
        {
            let invocation = adjudication["invocation_id"].as_str().unwrap();
            let subject = adjudication["subject_id"].as_str().unwrap();
            if !invocations.insert(invocation)
                || !adjudication_ids.insert(adjudication["adjudication_id"].as_str().unwrap())
                || focused_by_subject.insert(subject, adjudication).is_some()
            {
                return Err("focused adjudication identity is duplicated".into());
            }
            if !subjects.contains(&("claim", subject)) {
                return Err("focused adjudication has no claim vote".into());
            }
            if adjudication["evidence_fact_ids"].as_array().unwrap().len()
                != adjudication["evidence_digests"].as_array().unwrap().len()
            {
                return Err("focused breach evidence identity/digest count differs".into());
            }
            if (adjudication["verdict"] == "evaluation_error")
                != adjudication["evaluation_diagnostic"].is_string()
            {
                return Err(
                    "focused evaluation diagnostic presence differs from failure verdict".into(),
                );
            }
            if !matches!(
                (
                    adjudication["verdict"].as_str().unwrap(),
                    adjudication["controlling_reason"].as_str().unwrap()
                ),
                ("breach_confirmed", "breach.binding-rule.confirmed")
                    | ("breach_not_confirmed", "breach.binding-rule.not-confirmed")
                    | ("unverifiable", "breach.binding-rule.unverifiable")
                    | ("evaluation_error", "breach.adjudication.evaluation-error")
            ) {
                return Err("focused breach verdict/reason tuple is invalid".into());
            }
        }
        for ((kind, subject), votes) in &votes_by_subject {
            let has_breach =
                *kind == "claim" && votes.iter().any(|vote| vote["verdict"] == "breached");
            let initial_has_breach = *kind == "claim"
                && votes.iter().any(|vote| {
                    vote["judge_ordinal"]
                        .as_u64()
                        .is_some_and(|ordinal| ordinal <= 2)
                        && vote["verdict"] == "breached"
                });
            let has_invalid = votes
                .iter()
                .any(|vote| vote["verdict"] == "evaluation_error");
            let focus = focused_by_subject.get(subject);
            if has_invalid {
                let invalid_ordinals = votes
                    .iter()
                    .filter(|vote| vote["verdict"] == "evaluation_error")
                    .map(|vote| vote["judge_ordinal"].as_u64().unwrap())
                    .collect::<Vec<_>>();
                let valid_initial_failure = votes.len() == 2
                    && focus.is_some() == initial_has_breach
                    && invalid_ordinals.iter().all(|ordinal| *ordinal <= 2);
                let first = votes
                    .iter()
                    .find(|vote| vote["judge_ordinal"] == 1)
                    .unwrap();
                let second = votes
                    .iter()
                    .find(|vote| vote["judge_ordinal"] == 2)
                    .unwrap();
                let initial_disagreement = first["verdict"] != second["verdict"]
                    || first["controlling_reason"] != second["controlling_reason"];
                let prescribed_third_path =
                    (!initial_has_breach && initial_disagreement && focus.is_none())
                        || (initial_has_breach
                            && focus.is_some_and(|item| item["verdict"] == "breach_not_confirmed"));
                let valid_third_failure =
                    votes.len() == 3 && invalid_ordinals == [3] && prescribed_third_path;
                if !valid_initial_failure && !valid_third_failure {
                    return Err(
                        "invalid required vote is not on prescribed initial or third path".into(),
                    );
                }
                continue;
            }
            if has_breach != focus.is_some() {
                return Err("focused breach count and breached claim linkage are invalid".into());
            }
            let first = votes
                .iter()
                .find(|vote| vote["judge_ordinal"] == 1)
                .unwrap();
            let second = votes
                .iter()
                .find(|vote| vote["judge_ordinal"] == 2)
                .unwrap();
            let has_third = votes.iter().any(|vote| vote["judge_ordinal"] == 3);
            let initial_disagreement = first["verdict"] != second["verdict"]
                || first["controlling_reason"] != second["controlling_reason"];
            let third_required = (!initial_has_breach && initial_disagreement)
                || (initial_has_breach
                    && focus.is_some_and(|item| item["verdict"] == "breach_not_confirmed"));
            if has_third != third_required {
                return Err(
                    "judgment third-vote presence differs from prescribed disagreement path".into(),
                );
            }
        }
        for result in value["resolved"]
            .as_array()
            .expect("schema checked resolved")
        {
            let kind = result["subject_kind"].as_str().unwrap();
            let subject = result["subject_id"].as_str().unwrap();
            let votes = votes_by_subject
                .get(&(kind, subject))
                .expect("resolved subject vote checked");
            let verdict = result["verdict"].as_str().unwrap();
            let reason = result["controlling_reason"].as_str().unwrap();
            let invalid = votes
                .iter()
                .any(|vote| vote["verdict"] == "evaluation_error")
                || focused_by_subject
                    .get(subject)
                    .is_some_and(|vote| vote["verdict"] == "evaluation_error");
            if verdict == "evaluation_error" {
                let excludes_breach = focused_by_subject
                    .get(subject)
                    .is_some_and(|focus| focus["verdict"] == "breach_not_confirmed");
                let eligible = votes
                    .iter()
                    .filter(|vote| !(excludes_breach && vote["verdict"] == "breached"))
                    .collect::<Vec<_>>();
                let no_quorum = votes.len() == 3
                    && !eligible.iter().any(|vote| {
                        eligible
                            .iter()
                            .filter(|other| {
                                other["verdict"] == vote["verdict"]
                                    && other["controlling_reason"] == vote["controlling_reason"]
                            })
                            .count()
                            >= 2
                    });
                if !invalid && !no_quorum {
                    return Err("evaluation-error resolution lacks invalid vote or valid three-way disagreement".into());
                }
                continue;
            }
            if invalid {
                return Err("content resolution cannot include evaluation-error vote".into());
            }
            if verdict == "breached" {
                let focused = focused_by_subject
                    .get(subject)
                    .is_some_and(|vote| vote["verdict"] == "breach_confirmed");
                let ordinary = votes.iter().any(|vote| {
                    vote["verdict"] == "breached" && vote["controlling_reason"] == "claim.breached"
                });
                if !focused || !ordinary {
                    return Err("breached resolution lacks exact focused confirmation".into());
                }
                continue;
            }
            if verdict == "unverifiable"
                && focused_by_subject
                    .get(subject)
                    .is_some_and(|focus| focus["verdict"] == "unverifiable")
            {
                continue;
            }
            let eligible = votes.iter().filter(|vote| {
                !(focused_by_subject
                    .get(subject)
                    .is_some_and(|focus| focus["verdict"] == "breach_not_confirmed")
                    && vote["verdict"] == "breached")
            });
            let count = eligible
                .filter(|vote| vote["verdict"] == verdict && vote["controlling_reason"] == reason)
                .count();
            if count < 2 {
                return Err("resolved verdict lacks exact quorum tuple".into());
            }
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

fn normalize_claim_text(value: &str) -> String {
    value
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_ascii_lowercase()
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
    fn invalid_required_third_vote_is_retained_as_evaluation_error() {
        let path = format!(
            "{}/fixtures/records/valid/judgment-bundle-v1.json",
            env!("CARGO_MANIFEST_DIR")
        );
        let mut value: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        value["claim_votes"][1]["verdict"] = serde_json::json!("drifted");
        value["claim_votes"][1]["controlling_reason"] = serde_json::json!("claim.drifted");
        let mut third = value["claim_votes"][1].clone();
        third["vote_id"] = serde_json::json!("v3");
        third["judge_ordinal"] = serde_json::json!(3);
        third["verdict"] = serde_json::json!("evaluation_error");
        third["controlling_reason"] = serde_json::json!("claim.evaluation-error");
        third["invocation_id"] = serde_json::json!(format!("sha256:{}", "8".repeat(64)));
        third["request_digest"] = serde_json::json!(format!("sha256:{}", "9".repeat(64)));
        third["evaluation_diagnostic"] = serde_json::json!("invalid third output");
        value["claim_votes"].as_array_mut().unwrap().push(third);
        value["resolved"][0]["verdict"] = serde_json::json!("evaluation_error");
        value["resolved"][0]["controlling_reason"] = serde_json::json!("claim.evaluation-error");
        validate(RecordKind::JudgmentBundle, &value).unwrap();
        value["claim_votes"][1]["verdict"] = serde_json::json!("adhered");
        value["claim_votes"][1]["controlling_reason"] = serde_json::json!("claim.adhered");
        assert!(validate(RecordKind::JudgmentBundle, &value).is_err());
    }

    #[test]
    fn invalid_initial_vote_fails_closed_but_valid_breach_peer_is_focused() {
        let path = format!(
            "{}/fixtures/records/valid/judgment-bundle-v1.json",
            env!("CARGO_MANIFEST_DIR")
        );
        for peer_verdict in ["adhered", "breached"] {
            let mut value: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
            value["claim_votes"][0]["verdict"] = serde_json::json!("evaluation_error");
            value["claim_votes"][0]["controlling_reason"] =
                serde_json::json!("claim.evaluation-error");
            value["claim_votes"][0]["evaluation_diagnostic"] =
                serde_json::json!("invalid closed output");
            value["claim_votes"][1]["verdict"] = serde_json::json!(peer_verdict);
            value["claim_votes"][1]["controlling_reason"] =
                serde_json::json!(if peer_verdict == "breached" {
                    "claim.breached"
                } else {
                    "claim.adhered"
                });
            value["resolved"][0]["verdict"] = serde_json::json!("evaluation_error");
            value["resolved"][0]["controlling_reason"] =
                serde_json::json!("claim.evaluation-error");
            if peer_verdict == "breached" {
                assert!(validate(RecordKind::JudgmentBundle, &value).is_err());
                value["focused_breach_adjudications"] = serde_json::json!([{
                    "adjudication_id":"c1:focused","subject_kind":"claim","subject_id":"c1",
                    "verdict":"breach_confirmed","controlling_reason":"breach.binding-rule.confirmed",
                    "evidence_digests":[],"evidence_fact_ids":[],
                    "invocation_id":format!("sha256:{}", "a".repeat(64)),
                    "request_digest":format!("sha256:{}", "b".repeat(64)),
                    "evaluation_diagnostic":null,
                    "binding_rule_semantic_digest":format!("sha256:{}", "c".repeat(64)),
                    "binding_force":"binding-invariant","binding_scope":"repository",
                    "claim_digest":format!("sha256:{}", "d".repeat(64))
                }]);
            }
            validate(RecordKind::JudgmentBundle, &value).unwrap();
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
            "evidence_digests":[],
            "evidence_fact_ids":[],
            "invocation_id":format!("sha256:{}", "a".repeat(64)),
            "request_digest":format!("sha256:{}", "b".repeat(64)),
            "evaluation_diagnostic":null
        }]);
        let mut second_role = value["role_votes"][0].clone();
        second_role["vote_id"] = serde_json::json!("r2");
        second_role["judge_ordinal"] = serde_json::json!(2);
        second_role["invocation_id"] = serde_json::json!(format!("sha256:{}", "c".repeat(64)));
        second_role["request_digest"] = serde_json::json!(format!("sha256:{}", "d".repeat(64)));
        value["role_votes"]
            .as_array_mut()
            .unwrap()
            .push(second_role);
        value["resolved"]
            .as_array_mut()
            .unwrap()
            .push(serde_json::json!({
                "subject_kind":"role",
                "subject_id":"README.md:R1",
                "verdict":"satisfied",
                "controlling_reason":"role.r1.satisfied",
                "evidence_fact_ids":[],
                "evidence_digests":[]
            }));
        validate(RecordKind::JudgmentBundle, &value).unwrap();

        value["claim_votes"][0]["verdict"] = Value::String("satisfied".to_string());
        assert!(validate(RecordKind::JudgmentBundle, &value).is_err());

        let path = format!(
            "{}/fixtures/records/valid/judgment-bundle-v1.json",
            env!("CARGO_MANIFEST_DIR")
        );
        let mut value: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        for vote in value["claim_votes"].as_array_mut().unwrap() {
            vote["verdict"] = serde_json::json!("breached");
            vote["controlling_reason"] = serde_json::json!("claim.breached");
        }
        value["resolved"][0]["verdict"] = serde_json::json!("breached");
        value["resolved"][0]["controlling_reason"] = serde_json::json!("claim.breached");
        value["focused_breach_adjudications"] = serde_json::json!([{
            "adjudication_id":"a1",
            "subject_kind":"claim",
            "subject_id":"c1",
            "verdict":"breach_confirmed",
            "controlling_reason":"breach.binding-rule.confirmed",
            "evidence_digests":[],
            "evidence_fact_ids":[],
            "invocation_id":format!("sha256:{}", "a".repeat(64)),
            "request_digest":format!("sha256:{}", "b".repeat(64)),
            "evaluation_diagnostic":null,
            "binding_rule_semantic_digest":format!("sha256:{}", "c".repeat(64)),
            "binding_force":"binding-invariant",
            "binding_scope":"repository",
            "claim_digest":format!("sha256:{}", "d".repeat(64))
        }]);
        validate(RecordKind::JudgmentBundle, &value).unwrap();
        value["focused_breach_adjudications"][0]["verdict"] = Value::String("breached".to_string());
        assert!(validate(RecordKind::JudgmentBundle, &value).is_err());
    }

    #[test]
    fn judgment_semantics_reject_duplicate_ordinals_and_unfounded_evaluation_error() {
        let path = format!(
            "{}/fixtures/records/valid/judgment-bundle-v1.json",
            env!("CARGO_MANIFEST_DIR")
        );
        let mut duplicate: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        duplicate["claim_votes"][1]["judge_ordinal"] = serde_json::json!(1);
        assert!(validate(RecordKind::JudgmentBundle, &duplicate).is_err());

        let mut unfounded: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        unfounded["resolved"][0]["verdict"] = serde_json::json!("evaluation_error");
        unfounded["resolved"][0]["controlling_reason"] =
            serde_json::json!("claim.evaluation-error");
        assert!(validate(RecordKind::JudgmentBundle, &unfounded).is_err());
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

        let mut partial_report = load("audit-report-v1");
        partial_report["recovery_record_digest"] =
            Value::String(format!("sha256:{}", "8".repeat(64)));
        assert!(validate(RecordKind::AuditReport, &partial_report).is_err());

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
