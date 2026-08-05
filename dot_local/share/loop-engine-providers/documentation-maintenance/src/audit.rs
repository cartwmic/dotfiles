//! Immutable audit reports assembled only from verified judgment records.
use crate::{
    bundle::FrozenBundle,
    codec,
    evidence::EvidenceCatalog,
    schema::RecordKind,
    storage::{ArtifactStore, RecordCategory, StoredRecord},
};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AuditAssemblyError {
    ProtocolEvaluationError(String),
    InvalidInput(String),
}

/// Production assembly trusts no caller-supplied finding, verdict, location, or
/// evidence. Disposition and findings come only from complete validated
/// `judgment.resolved`, frozen contracts, claims, and catalog facts.
pub fn assemble_verified(
    run_id: &str,
    manifest: &crate::codec::DecodedRecord,
    claims: &crate::codec::DecodedRecord,
    judgment: &crate::codec::DecodedRecord,
    bundle: &FrozenBundle,
    catalog: &EvidenceCatalog,
) -> Result<crate::codec::DecodedRecord, AuditAssemblyError> {
    crate::bundle::validate_frozen_bundle(bundle).map_err(AuditAssemblyError::InvalidInput)?;
    for (record, kind) in [
        (manifest, RecordKind::RepositoryManifest),
        (claims, RecordKind::ClaimSet),
        (judgment, RecordKind::JudgmentBundle),
    ] {
        if record.kind != kind {
            return Err(AuditAssemblyError::InvalidInput(
                "audit decoded record kind is invalid".into(),
            ));
        }
        crate::schema::validate(kind, &record.value).map_err(AuditAssemblyError::InvalidInput)?;
        if codec::sha256(
            &codec::canonicalize(&record.value).map_err(AuditAssemblyError::InvalidInput)?,
        ) != record.digest
        {
            return Err(AuditAssemblyError::InvalidInput(
                "audit decoded record digest is invalid".into(),
            ));
        }
        if record.value["run_id"] != run_id {
            return Err(AuditAssemblyError::InvalidInput(
                "audit run linkage is invalid".into(),
            ));
        }
    }
    crate::claims::verify_extracted_record(run_id, catalog, claims)
        .map_err(AuditAssemblyError::InvalidInput)?;
    if claims.value["manifest_digest"] != manifest.digest
        || judgment.value["manifest_digest"] != manifest.digest
        || catalog.manifest_digest() != manifest.digest
        || judgment.value["bundle_digest"] != bundle.digest
    {
        return Err(AuditAssemblyError::InvalidInput(
            "audit manifest or bundle linkage is invalid".into(),
        ));
    }
    if judgment.value["model_identity_digest"]
        != bundle.value["evaluator_identity"]["model_identity_digest"]
        || judgment.value["decoding_parameter_digest"]
            != bundle.value["evaluator_identity"]["decoding_parameter_digest"]
    {
        return Err(AuditAssemblyError::InvalidInput(
            "audit evaluator identity linkage is invalid".into(),
        ));
    }
    let expected = expected_subjects(claims, bundle)?;
    validate_judgment_votes(&judgment.value, &expected, catalog, manifest)?;
    let mut got = BTreeSet::new();
    let mut findings = Vec::new();
    let mut verdicts = Vec::new();
    for resolved in judgment.value["resolved"].as_array().ok_or_else(|| {
        AuditAssemblyError::InvalidInput("judgment resolved inventory missing".into())
    })? {
        let key = (
            required(resolved, "subject_kind")?.into(),
            required(resolved, "subject_id")?.into(),
        );
        let subject = expected.get(&key).ok_or_else(|| {
            AuditAssemblyError::InvalidInput("judgment has caller-substituted subject".into())
        })?;
        if !got.insert(key.clone()) {
            return Err(AuditAssemblyError::InvalidInput(
                "judgment resolves subject more than once".into(),
            ));
        }
        let verdict = required(resolved, "verdict")?;
        let reason = required(resolved, "controlling_reason")?;
        if !tuple_valid(subject, verdict, reason) {
            return Err(AuditAssemblyError::InvalidInput(
                "judgment verdict/reason tuple is invalid".into(),
            ));
        }
        validate_resolution_votes(resolved, &judgment.value, subject)?;
        validate_resolved_evidence(resolved, &judgment.value, subject)?;
        let facts = resolved_facts(resolved, subject, catalog, manifest)?;
        verdicts.push(verdict.to_string());
        if !matches!(verdict, "adhered" | "satisfied") {
            if facts.is_empty()
                && (verdict == "evaluation_error"
                    || (subject.kind == "role" && matches!(verdict, "deficient" | "unverifiable")))
            {
                findings.push(finding_without_fact(
                    &subject.document,
                    1,
                    1,
                    reason,
                    verdict,
                ));
            } else if !facts.is_empty() {
                findings.extend(findings_for_facts(verdict, reason, &facts));
            }
        }
    }
    // Current inventory authority violations are deterministic record facts,
    // not optional staged-only checks. They always require revision.
    let authority_findings = current_authority_findings(claims)?;
    for finding_input in &authority_findings {
        findings.push(finding_without_fact(
            &finding_input.path,
            finding_input.start_line,
            finding_input.end_line,
            &finding_input.reason_id,
            "deficient",
        ));
    }
    if got.len() != expected.len()
        || got.len() != judgment.value["resolved"].as_array().unwrap().len()
    {
        return Err(AuditAssemblyError::InvalidInput(
            "judgment subject inventory is incomplete".into(),
        ));
    }
    let disposition = if verdicts.iter().any(|v| v == "evaluation_error") {
        "evaluation_error"
    } else if verdicts.iter().any(|v| v == "breached") {
        "breach_confirmed"
    } else if !authority_findings.is_empty()
        || verdicts
            .iter()
            .any(|v| matches!(v.as_str(), "drifted" | "unverifiable" | "deficient"))
    {
        "revision_required"
    } else if verdicts
        .iter()
        .all(|v| matches!(v.as_str(), "adhered" | "satisfied"))
    {
        "clean"
    } else {
        return Err(AuditAssemblyError::InvalidInput(
            "judgment has unknown disposition".into(),
        ));
    };
    findings = deduplicate_findings(findings);
    findings.sort_by(|a, b| {
        (
            severity(a["_verdict"].as_str().unwrap()),
            a["primary_reason"].as_str(),
            a["document"].as_str(),
            a["finding_id"].as_str(),
        )
            .cmp(&(
                severity(b["_verdict"].as_str().unwrap()),
                b["primary_reason"].as_str(),
                b["document"].as_str(),
                b["finding_id"].as_str(),
            ))
    });
    for f in &mut findings {
        f.as_object_mut().unwrap().remove("_verdict");
        f.as_object_mut().unwrap().remove("_fact_id");
    }
    codec::encode_record(&json!({"schema":"audit-report-v1","run_id":run_id,"manifest_digest":manifest.digest,"claim_set_digest":claims.digest,"judgment_bundle_digest":judgment.digest,"disposition":disposition,"findings":findings}),RecordKind::AuditReport,run_id).map_err(AuditAssemblyError::InvalidInput)
}
#[derive(Debug, Clone)]
struct Subject {
    kind: String,
    id: String,
    document: String,
    start: u64,
    end: u64,
    binding_rule_semantic_digest: Option<String>,
    claim_digest: Option<String>,
    force: Option<String>,
    scope: Option<String>,
    role_reasons: BTreeMap<String, String>,
}
fn expected_subjects(
    claims: &crate::codec::DecodedRecord,
    bundle: &FrozenBundle,
) -> Result<BTreeMap<(String, String), Subject>, AuditAssemblyError> {
    let mut all = BTreeMap::new();
    for c in claims.value["claims"]
        .as_array()
        .ok_or_else(|| AuditAssemblyError::InvalidInput("claim inventory missing".into()))?
    {
        let id = required(c, "claim_id")?.to_string();
        let s = Subject {
            kind: "claim".into(),
            id: id.clone(),
            document: required(c, "document")?.into(),
            start: c["location"]["start_line"]
                .as_u64()
                .ok_or_else(|| AuditAssemblyError::InvalidInput("claim location missing".into()))?,
            end: c["location"]["end_line"]
                .as_u64()
                .ok_or_else(|| AuditAssemblyError::InvalidInput("claim location missing".into()))?,
            binding_rule_semantic_digest: (c["document"] == "docs/intent.md"
                && matches!(
                    c["force"].as_str(),
                    Some("binding-invariant" | "binding-boundary" | "binding-non-goal")
                ))
            .then(|| required(c, "semantic_digest").map(str::to_string))
            .transpose()?,
            claim_digest: Some(codec::sha256(
                &codec::canonicalize(c).map_err(AuditAssemblyError::InvalidInput)?,
            )),
            force: Some(required(c, "force")?.into()),
            scope: Some(required(c, "scope")?.into()),
            role_reasons: BTreeMap::new(),
        };
        if all.insert(("claim".into(), id), s).is_some() {
            return Err(AuditAssemblyError::InvalidInput(
                "claim identity duplicated".into(),
            ));
        }
    }
    for contract in bundle.value["profile"]["contracts"]
        .as_array()
        .ok_or_else(|| AuditAssemblyError::InvalidInput("frozen contracts missing".into()))?
    {
        let path = required(contract, "path")?;
        for clause in contract["clauses"]
            .as_array()
            .ok_or_else(|| AuditAssemblyError::InvalidInput("frozen clauses missing".into()))?
        {
            let clause_id = required(clause, "id")?;
            let id = format!("{path}:{clause_id}");
            let reasons = clause["reasons"]
                .as_object()
                .ok_or_else(|| {
                    AuditAssemblyError::InvalidInput("frozen clause reasons missing".into())
                })?
                .iter()
                .map(|(k, v)| {
                    v.as_str().map(|r| (k.clone(), r.into())).ok_or_else(|| {
                        AuditAssemblyError::InvalidInput("frozen clause reason invalid".into())
                    })
                })
                .collect::<Result<_, _>>()?;
            let s = Subject {
                kind: "role".into(),
                id: id.clone(),
                document: path.into(),
                start: 1,
                end: u64::MAX,
                binding_rule_semantic_digest: None,
                claim_digest: None,
                force: None,
                scope: None,
                role_reasons: reasons,
            };
            if all.insert(("role".into(), id), s).is_some() {
                return Err(AuditAssemblyError::InvalidInput(
                    "role identity duplicated".into(),
                ));
            }
        }
    }
    if all.is_empty() {
        return Err(AuditAssemblyError::InvalidInput(
            "audit subject inventory is empty".into(),
        ));
    }
    Ok(all)
}
fn required<'a>(v: &'a Value, key: &str) -> Result<&'a str, AuditAssemblyError> {
    v[key]
        .as_str()
        .filter(|x| !x.is_empty())
        .ok_or_else(|| AuditAssemblyError::InvalidInput(format!("missing {key}")))
}
fn tuple_valid(s: &Subject, v: &str, r: &str) -> bool {
    if v == "evaluation_error" {
        return r == "claim.evaluation-error";
    }
    match s.kind.as_str() {
        "claim" => {
            matches!(
                (v, r),
                ("adhered", "claim.adhered")
                    | ("drifted", "claim.drifted")
                    | ("unverifiable", "claim.unverifiable")
            ) || ((v, r) == ("breached", "claim.breached")
                && s.binding_rule_semantic_digest.is_some())
        }
        "role" => s.role_reasons.get(v).is_some_and(|x| x == r),
        _ => false,
    }
}
fn validate_judgment_votes(
    judgment: &Value,
    expected: &BTreeMap<(String, String), Subject>,
    catalog: &EvidenceCatalog,
    manifest: &crate::codec::DecodedRecord,
) -> Result<(), AuditAssemblyError> {
    for field in ["claim_votes", "role_votes"] {
        for vote in judgment[field]
            .as_array()
            .ok_or_else(|| AuditAssemblyError::InvalidInput("judgment votes missing".into()))?
        {
            let kind = required(vote, "subject_kind")?;
            let id = required(vote, "subject_id")?;
            let subject = expected.get(&(kind.into(), id.into())).ok_or_else(|| {
                AuditAssemblyError::InvalidInput(
                    "judgment has caller-substituted vote subject".into(),
                )
            })?;
            if !tuple_valid(
                subject,
                required(vote, "verdict")?,
                required(vote, "controlling_reason")?,
            ) {
                return Err(AuditAssemblyError::InvalidInput(
                    "judgment vote tuple is invalid".into(),
                ));
            }
            validate_cited_facts(vote, subject, catalog, manifest)?;
        }
    }
    let focused = judgment["focused_breach_adjudications"]
        .as_array()
        .ok_or_else(|| AuditAssemblyError::InvalidInput("focused judgments missing".into()))?;
    for item in focused {
        let subject = expected
            .get(&("claim".into(), required(item, "subject_id")?.into()))
            .ok_or_else(|| {
                AuditAssemblyError::InvalidInput(
                    "focused breach has caller-substituted subject".into(),
                )
            })?;
        if subject.binding_rule_semantic_digest.is_none()
            || item["binding_rule_semantic_digest"]
                != subject.binding_rule_semantic_digest.clone().unwrap()
            || item["claim_digest"] != subject.claim_digest.clone().unwrap()
            || item["binding_force"] != subject.force.clone().unwrap()
            || item["binding_scope"] != subject.scope.clone().unwrap()
        {
            return Err(AuditAssemblyError::InvalidInput(
                "focused breach identity is not exact binding claim identity".into(),
            ));
        }
        validate_cited_facts(item, subject, catalog, manifest)?;
        let subject_votes = judgment["claim_votes"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|vote| vote["subject_id"] == item["subject_id"])
            .collect::<Vec<_>>();
        let initial_trigger = subject_votes.iter().any(|vote| {
            vote["judge_ordinal"]
                .as_u64()
                .is_some_and(|ordinal| ordinal <= 2)
                && vote["verdict"] == "breached"
        });
        let breach_citations = subject_votes
            .iter()
            .filter(|vote| {
                vote["verdict"] == "breached"
                    && if initial_trigger {
                        vote["judge_ordinal"]
                            .as_u64()
                            .is_some_and(|ordinal| ordinal <= 2)
                    } else {
                        vote["judge_ordinal"] == 3
                    }
            })
            .flat_map(|vote| {
                vote["evidence_fact_ids"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .filter_map(Value::as_str)
            })
            .collect::<BTreeSet<_>>();
        let focused_citations = item["evidence_fact_ids"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(Value::as_str)
            .collect::<BTreeSet<_>>();
        if breach_citations.is_empty() || focused_citations != breach_citations {
            return Err(AuditAssemblyError::InvalidInput(
                "focused breach evidence is not cited breach-vote evidence".into(),
            ));
        }
    }
    Ok(())
}

fn validate_cited_facts(
    value: &Value,
    s: &Subject,
    catalog: &EvidenceCatalog,
    manifest: &crate::codec::DecodedRecord,
) -> Result<(), AuditAssemblyError> {
    let ids = value["evidence_fact_ids"].as_array().ok_or_else(|| {
        AuditAssemblyError::InvalidInput("judgment evidence facts missing".into())
    })?;
    let digests = value["evidence_digests"].as_array().ok_or_else(|| {
        AuditAssemblyError::InvalidInput("judgment evidence digests missing".into())
    })?;
    if ids.len() != digests.len() {
        return Err(AuditAssemblyError::InvalidInput(
            "judgment evidence identity/digest count differs".into(),
        ));
    }
    for (id, digest) in ids.iter().zip(digests) {
        let fact = catalog
            .fact(id.as_str().ok_or_else(|| {
                AuditAssemblyError::InvalidInput("judgment evidence identity invalid".into())
            })?)
            .ok_or_else(|| {
                AuditAssemblyError::InvalidInput("judgment evidence is not catalog-owned".into())
            })?;
        if fact.manifest_digest != manifest.digest
            || fact.result_digest != digest.as_str().unwrap_or_default()
            || !candidate_fact(s, fact)
        {
            return Err(AuditAssemblyError::InvalidInput(
                "judgment evidence is not subject candidate evidence".into(),
            ));
        }
    }
    Ok(())
}
fn candidate_fact(s: &Subject, fact: &crate::evidence::EvidenceFact) -> bool {
    if s.kind == "role" {
        return fact.source_path == s.document;
    }
    (fact.source_path == s.document && fact.end_line >= s.start && fact.start_line <= s.end)
        || matches!(
            fact.query_scope.as_str(),
            "source-behavior" | "configuration" | "test-behavior"
        )
}

fn validate_resolution_votes(
    resolved: &Value,
    judgment: &Value,
    subject: &Subject,
) -> Result<(), AuditAssemblyError> {
    let field = if subject.kind == "claim" {
        "claim_votes"
    } else {
        "role_votes"
    };
    let votes = judgment[field]
        .as_array()
        .ok_or_else(|| AuditAssemblyError::InvalidInput("judgment votes missing".into()))?
        .iter()
        .filter(|v| v["subject_id"] == subject.id)
        .collect::<Vec<_>>();
    let verdict = required(resolved, "verdict")?;
    let reason = required(resolved, "controlling_reason")?;
    let focused = judgment["focused_breach_adjudications"]
        .as_array()
        .ok_or_else(|| AuditAssemblyError::InvalidInput("focused judgments missing".into()))?
        .iter()
        .filter(|item| item["subject_id"] == subject.id)
        .collect::<Vec<_>>();
    if verdict == "evaluation_error" {
        let invalid = votes
            .iter()
            .any(|vote| vote["verdict"] == "evaluation_error")
            || focused
                .iter()
                .any(|item| item["verdict"] == "evaluation_error");
        let excludes_breach = focused
            .iter()
            .any(|item| item["verdict"] == "breach_not_confirmed");
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
        if invalid || no_quorum {
            return Ok(());
        }
        return Err(AuditAssemblyError::InvalidInput(
            "evaluation-error resolution lacks invalid vote or valid three-way disagreement".into(),
        ));
    }
    if votes
        .iter()
        .any(|vote| vote["verdict"] == "evaluation_error")
        || focused
            .iter()
            .any(|item| item["verdict"] == "evaluation_error")
    {
        return Err(AuditAssemblyError::InvalidInput(
            "content resolution includes evaluation-error vote".into(),
        ));
    }
    if verdict == "unverifiable" && focused.iter().any(|item| item["verdict"] == "unverifiable") {
        return Ok(());
    }
    if verdict == "breached" {
        let ordinary = votes
            .iter()
            .any(|v| v["verdict"] == "breached" && v["controlling_reason"] == "claim.breached");
        let focused_confirmed = focused.iter().any(|v| {
            v["verdict"] == "breach_confirmed"
                && v["controlling_reason"] == "breach.binding-rule.confirmed"
        });
        return if ordinary && focused_confirmed {
            Ok(())
        } else {
            Err(AuditAssemblyError::InvalidInput(
                "breach resolution lacks exact focused confirmation".into(),
            ))
        };
    }
    if votes
        .iter()
        .filter(|v| {
            !(focused
                .iter()
                .any(|item| item["verdict"] == "breach_not_confirmed")
                && v["verdict"] == "breached")
        })
        .filter(|v| v["verdict"] == verdict && v["controlling_reason"] == reason)
        .count()
        >= 2
    {
        Ok(())
    } else {
        Err(AuditAssemblyError::InvalidInput(
            "resolved verdict lacks exact quorum tuple".into(),
        ))
    }
}
fn validate_resolved_evidence(
    resolved: &Value,
    judgment: &Value,
    subject: &Subject,
) -> Result<(), AuditAssemblyError> {
    if resolved["verdict"] == "evaluation_error" {
        return Ok(());
    }
    let field = if subject.kind == "claim" {
        "claim_votes"
    } else {
        "role_votes"
    };
    let ids = &resolved["evidence_fact_ids"];
    let digests = &resolved["evidence_digests"];
    let matching_vote = judgment[field].as_array().unwrap().iter().any(|vote| {
        vote["subject_id"] == subject.id
            && vote["verdict"] == resolved["verdict"]
            && vote["controlling_reason"] == resolved["controlling_reason"]
            && vote["evidence_fact_ids"] == *ids
            && vote["evidence_digests"] == *digests
    });
    let matching_focused = subject.kind == "claim"
        && judgment["focused_breach_adjudications"]
            .as_array()
            .unwrap()
            .iter()
            .any(|vote| {
                vote["subject_id"] == subject.id
                    && matches!(
                        (resolved["verdict"].as_str(), vote["verdict"].as_str()),
                        (Some("breached"), Some("breach_confirmed"))
                            | (Some("unverifiable"), Some("unverifiable"))
                    )
                    && vote["evidence_fact_ids"] == *ids
                    && vote["evidence_digests"] == *digests
            });
    if matching_vote || matching_focused {
        Ok(())
    } else {
        Err(AuditAssemblyError::InvalidInput(
            "resolved evidence is not exact cited controlling vote evidence".into(),
        ))
    }
}

fn resolved_facts<'a>(
    resolved: &Value,
    s: &Subject,
    catalog: &'a EvidenceCatalog,
    manifest: &crate::codec::DecodedRecord,
) -> Result<Vec<&'a crate::evidence::EvidenceFact>, AuditAssemblyError> {
    let ids = resolved["evidence_fact_ids"].as_array().ok_or_else(|| {
        AuditAssemblyError::InvalidInput("resolved evidence facts missing".into())
    })?;
    let digests = resolved["evidence_digests"].as_array().ok_or_else(|| {
        AuditAssemblyError::InvalidInput("resolved evidence digests missing".into())
    })?;
    if ids.len() != digests.len() {
        return Err(AuditAssemblyError::InvalidInput(
            "resolved evidence identity/digest count differs".into(),
        ));
    }
    let mut seen = BTreeSet::new();
    let mut out = Vec::new();
    for (id, digest) in ids.iter().zip(digests) {
        let id = id.as_str().ok_or_else(|| {
            AuditAssemblyError::InvalidInput("resolved fact identity invalid".into())
        })?;
        let digest = digest.as_str().ok_or_else(|| {
            AuditAssemblyError::InvalidInput("resolved fact digest invalid".into())
        })?;
        if !seen.insert(id) {
            return Err(AuditAssemblyError::InvalidInput(
                "resolved fact duplicated".into(),
            ));
        }
        let fact = catalog.fact(id).ok_or_else(|| {
            AuditAssemblyError::InvalidInput("resolved fact is not catalog-owned".into())
        })?;
        if fact.manifest_digest != manifest.digest
            || fact.result_digest != digest
            || !candidate_fact(s, fact)
        {
            return Err(AuditAssemblyError::InvalidInput(
                "resolved evidence is not subject-derived catalog evidence".into(),
            ));
        }
        out.push(fact);
    }
    if out.is_empty()
        && resolved["verdict"] != "evaluation_error"
        && !(s.kind == "role"
            && matches!(
                resolved["verdict"].as_str(),
                Some("deficient" | "unverifiable")
            ))
    {
        return Err(AuditAssemblyError::InvalidInput(
            "resolved subject lacks cited catalog evidence".into(),
        ));
    }
    out.sort_by(|a, b| a.id.cmp(&b.id));
    Ok(out)
}
fn finding_without_fact(path: &str, start: u64, end: u64, reason: &str, verdict: &str) -> Value {
    let finding_id = codec::sha256(
        &codec::canonicalize(
            &json!({"path":path,"start":start,"end":end,"reason":reason,"verdict":verdict}),
        )
        .expect("canonical finding"),
    );
    json!({"finding_id":finding_id,"primary_reason":reason,"document":path,"location":{"path":path,"start_line":start,"end_line":end},"evidence_digests":[],"secondary_consequences":[],"_verdict":verdict,"_fact_id":format!("factless:{finding_id}")})
}

fn deduplicate_findings(findings: Vec<Value>) -> Vec<Value> {
    let mut grouped = BTreeMap::<String, Vec<Value>>::new();
    for finding in findings {
        let key = finding["_fact_id"]
            .as_str()
            .expect("internal fact identity")
            .to_string();
        grouped.entry(key).or_default().push(finding);
    }
    grouped
        .into_values()
        .map(|mut group| {
            group.sort_by(|left, right| {
                (
                    severity(left["_verdict"].as_str().unwrap()),
                    left["primary_reason"].as_str(),
                )
                    .cmp(&(
                        severity(right["_verdict"].as_str().unwrap()),
                        right["primary_reason"].as_str(),
                    ))
            });
            let mut primary = group.remove(0);
            let mut secondary = group
                .into_iter()
                .map(|item| item["primary_reason"].as_str().unwrap().to_string())
                .collect::<Vec<_>>();
            secondary.sort();
            secondary.dedup();
            primary["secondary_consequences"] = json!(secondary);
            primary
        })
        .collect()
}

fn current_authority_findings(
    claims: &crate::codec::DecodedRecord,
) -> Result<Vec<crate::claims::AuthorityFinding>, AuditAssemblyError> {
    let parsed = claims.value["claims"]
        .as_array()
        .ok_or_else(|| AuditAssemblyError::InvalidInput("claim inventory missing".into()))?
        .iter()
        .map(|value| {
            Ok(crate::claims::Claim {
                claim_id: required(value, "claim_id")?.into(),
                source_unit_id: required(value, "source_unit_id")?.into(),
                semantic_digest: required(value, "semantic_digest")?.into(),
                document: required(value, "document")?.into(),
                start_line: value["location"]["start_line"].as_u64().ok_or_else(|| {
                    AuditAssemblyError::InvalidInput("claim location missing".into())
                })?,
                end_line: value["location"]["end_line"].as_u64().ok_or_else(|| {
                    AuditAssemblyError::InvalidInput("claim location missing".into())
                })?,
                ordinal: value["ordinal"].as_u64().ok_or_else(|| {
                    AuditAssemblyError::InvalidInput("claim ordinal missing".into())
                })?,
                proposition: required(value, "proposition")?.into(),
                force: required(value, "force")?.into(),
                scope: required(value, "scope")?.into(),
                evidence_digests: vec![],
                reason_id: required(value, "reason_id")?.into(),
            })
        })
        .collect::<Result<Vec<_>, AuditAssemblyError>>()?;
    Ok(crate::claims::current_authority_findings(&parsed))
}

fn findings_for_facts(
    verdict: &str,
    reason: &str,
    facts: &[&crate::evidence::EvidenceFact],
) -> Vec<Value> {
    let mut evidence = facts
        .iter()
        .map(|f| f.result_digest.clone())
        .collect::<Vec<_>>();
    evidence.sort();
    evidence.dedup();
    facts
        .iter()
        .map(|fact| {
            json!({"finding_id":codec::sha256(&codec::canonicalize(&json!({"fact_id":fact.id,"verdict":verdict,"reason":reason})).expect("canonical finding")),"primary_reason":reason,"document":fact.source_path,"location":{"path":fact.source_path,"start_line":fact.start_line,"end_line":fact.end_line},"evidence_digests":evidence.clone(),"secondary_consequences":[],"_verdict":verdict,"_fact_id":fact.id})
        })
        .collect()
}
fn severity(v: &str) -> u8 {
    match v {
        "evaluation_error" => 0,
        "breached" => 1,
        "drifted" | "unverifiable" | "deficient" => 2,
        _ => 3,
    }
}
pub fn store_immutable(
    store: &ArtifactStore,
    invocation_id: &str,
    report: &crate::codec::DecodedRecord,
) -> Result<StoredRecord, String> {
    if report.kind != RecordKind::AuditReport {
        return Err("immutable audit storage requires audit-report-v1".into());
    }
    store.store(
        RecordCategory::Audits,
        invocation_id,
        RecordKind::AuditReport,
        &report.value,
    )
}
