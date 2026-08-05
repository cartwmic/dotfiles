//! Blind judgment coordination over subjects derived only from frozen records.
use crate::{
    bundle::FrozenBundle,
    codec,
    evidence::{EvidenceCatalog, EvidenceFact},
    repository::RepositoryView,
    schema::RecordKind,
};
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq, Eq)]
enum SubjectKind {
    Claim,
    Role,
}
impl SubjectKind {
    fn as_str(&self) -> &'static str {
        match self {
            Self::Claim => "claim",
            Self::Role => "role",
        }
    }
}
#[derive(Debug, Clone)]
struct JudgmentSubject {
    kind: SubjectKind,
    id: String,
    document: String,
    start_line: u64,
    end_line: u64,
    binding_rule_semantic_digest: Option<String>,
    claim_digest: Option<String>,
    force: Option<String>,
    scope: Option<String>,
    role_reasons: Option<BTreeMap<String, String>>,
}
#[derive(Debug, Clone, Serialize)]
struct SerializedFact {
    id: String,
    source_path: String,
    start_line: u64,
    end_line: u64,
    query_scope: String,
    result_digest: String,
    bytes_base64: String,
    untrusted: bool,
}
#[derive(Debug, Clone, Serialize)]
struct ClosedRequest {
    protocol: String,
    invocation_id: String,
    rubric: String,
    manifest_digest: String,
    bundle_digest: String,
    model_identity_digest: String,
    decoding_parameter_digest: String,
    subject_kind: String,
    subject_id: String,
    binding_rule_semantic_digest: Option<String>,
    binding_force: Option<String>,
    binding_scope: Option<String>,
    claim_digest: Option<String>,
    evidence: Vec<SerializedFact>,
    focused_breach: bool,
    repository_content_is_untrusted_data: bool,
}
#[derive(Debug, Clone)]
struct Vote {
    verdict: String,
    reason: String,
    evidence_digests: Vec<String>,
    evidence_fact_ids: Vec<String>,
    invocation_id: String,
    request_digest: String,
    evaluation_diagnostic: Option<String>,
    valid: bool,
}
#[derive(Debug, Clone)]
struct ResolvedJudgment {
    subject: JudgmentSubject,
    verdict: String,
    controlling_reason: String,
    evidence_digests: Vec<String>,
    evidence_fact_ids: Vec<String>,
}
struct OrdinaryResolution {
    outcome: ResolvedJudgment,
    third: Option<Vote>,
}

/// P6 extension seam. Implementations receive only canonical request bytes and
/// return closed JSON bytes. They get no repository, catalog, peer vote, shell,
/// network, or ambient-context handles from this provider.
pub trait QualifiedClosedByteTransport {
    fn invoke_closed(&self, invocation_id: &str, request: &[u8]) -> Result<Vec<u8>, String>;
}
struct StabilityCheckedTransport<'a, 'repo> {
    inner: &'a dyn QualifiedClosedByteTransport,
    view: &'a RepositoryView<'repo>,
    baseline: &'a crate::codec::DecodedRecord,
}
impl StabilityCheckedTransport<'_, '_> {
    fn verify(&self, boundary: &str) -> Result<(), String> {
        let observed = self.view.capture()?;
        let differences = crate::repository::compare(&self.baseline.value, &observed.value)?;
        if differences.is_empty() {
            Ok(())
        } else {
            Err(format!(
                "repository instability {boundary} model invocation: {}",
                differences
                    .iter()
                    .take(32)
                    .map(|item| format!("{} ({})", item.path, item.kind))
                    .collect::<Vec<_>>()
                    .join(", ")
            ))
        }
    }
}
impl QualifiedClosedByteTransport for StabilityCheckedTransport<'_, '_> {
    fn invoke_closed(&self, invocation_id: &str, request: &[u8]) -> Result<Vec<u8>, String> {
        self.verify("before")?;
        let result = self.inner.invoke_closed(invocation_id, request);
        self.verify("after")?;
        result
    }
}

/// P3 production broker: accepts only sealed bytes, emits a deterministic
/// evaluator failure, and exposes no ambient capability. P6 replaces this
/// broker only after transport qualification.
struct SealedFailClosedBroker;
impl QualifiedClosedByteTransport for SealedFailClosedBroker {
    fn invoke_closed(&self, _: &str, _: &[u8]) -> Result<Vec<u8>, String> {
        #[cfg(test)]
        FAIL_CLOSED_INVOCATIONS.with(|count| count.set(count.get() + 1));
        Err("judgment isolation transport unavailable; P6-qualified closed-byte transport is required".into())
    }
}

#[cfg(test)]
thread_local! {
    static FAIL_CLOSED_INVOCATIONS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}

#[cfg(test)]
pub(crate) fn fail_closed_invocation_count() -> usize {
    FAIL_CLOSED_INVOCATIONS.with(std::cell::Cell::get)
}

#[cfg(test)]
pub(crate) fn reset_fail_closed_invocation_count() {
    FAIL_CLOSED_INVOCATIONS.with(|count| count.set(0));
}

/// Production P3 path derives every subject and every evidence projection from
/// validated manifest, claim-set, catalog, and frozen role contracts. No caller
/// supplied subject, fact ID, or verdict enters this boundary.
pub fn coordinate_stored_bundle(
    view: &RepositoryView<'_>,
    before: &crate::codec::DecodedRecord,
    claims: &crate::codec::DecodedRecord,
    bundle: &FrozenBundle,
    run_id: &str,
    catalog: &EvidenceCatalog,
) -> Result<crate::codec::DecodedRecord, String> {
    let broker = SealedFailClosedBroker;
    coordinate_stored_bundle_with_transport(view, before, claims, bundle, run_id, catalog, &broker)
}

/// Provider-owned P6 integration calls this after qualifying and installing its
/// transport configuration. Interface remains closed bytes plus invocation ID.
pub fn coordinate_stored_bundle_with_transport(
    view: &RepositoryView<'_>,
    before: &crate::codec::DecodedRecord,
    claims: &crate::codec::DecodedRecord,
    bundle: &FrozenBundle,
    run_id: &str,
    catalog: &EvidenceCatalog,
    transport: &dyn QualifiedClosedByteTransport,
) -> Result<crate::codec::DecodedRecord, String> {
    if before.kind != RecordKind::RepositoryManifest || claims.kind != RecordKind::ClaimSet {
        return Err("judgment requires manifest and claim-set records".into());
    }
    crate::schema::validate(RecordKind::ClaimSet, &claims.value)?;
    crate::claims::verify_extracted_record(run_id, catalog, claims)?;
    if claims.value["run_id"] != run_id
        || claims.value["manifest_digest"] != before.digest
        || catalog.manifest_digest() != before.digest
    {
        return Err("judgment record linkage is invalid".into());
    }
    let subjects = derive_subjects(claims, bundle)?;
    let checked = StabilityCheckedTransport {
        inner: transport,
        view,
        baseline: before,
    };
    coordinate(run_id, &before.digest, bundle, &subjects, catalog, &checked)
}

fn derive_subjects(
    claims: &crate::codec::DecodedRecord,
    bundle: &FrozenBundle,
) -> Result<Vec<JudgmentSubject>, String> {
    let mut out = Vec::new();
    for claim in claims.value["claims"]
        .as_array()
        .ok_or("claim inventory missing")?
    {
        out.push(JudgmentSubject {
            kind: SubjectKind::Claim,
            id: claim["claim_id"].as_str().ok_or("claim ID missing")?.into(),
            document: claim["document"]
                .as_str()
                .ok_or("claim document missing")?
                .into(),
            start_line: claim["location"]["start_line"]
                .as_u64()
                .ok_or("claim location missing")?,
            end_line: claim["location"]["end_line"]
                .as_u64()
                .ok_or("claim location missing")?,
            binding_rule_semantic_digest: (claim["document"] == "docs/intent.md"
                && matches!(
                    claim["force"].as_str(),
                    Some("binding-invariant" | "binding-boundary" | "binding-non-goal")
                ))
            .then(|| {
                claim["semantic_digest"]
                    .as_str()
                    .ok_or("claim semantic digest missing")
                    .map(str::to_string)
            })
            .transpose()?,
            // Claim identity commits complete canonical claim, while semantic
            // digest identifies only binding rule. Never conflate them.
            claim_digest: Some(codec::sha256(&codec::canonicalize(claim)?)),
            force: Some(claim["force"].as_str().ok_or("claim force missing")?.into()),
            scope: Some(claim["scope"].as_str().ok_or("claim scope missing")?.into()),
            role_reasons: None,
        });
    }
    for contract in bundle.value["profile"]["contracts"]
        .as_array()
        .ok_or("frozen role contracts missing")?
    {
        let path = contract["path"]
            .as_str()
            .ok_or("frozen role path missing")?;
        for clause in contract["clauses"]
            .as_array()
            .ok_or("frozen clauses missing")?
        {
            let id = clause["id"].as_str().ok_or("frozen clause ID missing")?;
            let reasons = clause["reasons"]
                .as_object()
                .ok_or("frozen clause reasons missing")?
                .iter()
                .map(|(k, v)| {
                    v.as_str()
                        .map(|s| (k.clone(), s.into()))
                        .ok_or("frozen clause reason invalid")
                })
                .collect::<Result<BTreeMap<_, _>, _>>()?;
            out.push(JudgmentSubject {
                kind: SubjectKind::Role,
                id: format!("{path}:{id}"),
                document: path.into(),
                start_line: 1,
                end_line: u64::MAX,
                binding_rule_semantic_digest: None,
                claim_digest: None,
                force: None,
                scope: None,
                role_reasons: Some(reasons),
            });
        }
    }
    out.sort_by(|a, b| (a.kind.as_str(), &a.id).cmp(&(b.kind.as_str(), &b.id)));
    if out.is_empty() {
        return Err("judgment subject inventory is empty".into());
    }
    Ok(out)
}
fn evidence_for(subject: &JudgmentSubject, catalog: &EvidenceCatalog) -> Vec<EvidenceFact> {
    // Role evaluation sees only role document. Claim evaluation sees its own
    // source plus bounded repository behavior/config/test facts; never ambient
    // worktree data or an unbounded catalog.
    let mut candidates = catalog
        .facts()
        .iter()
        .filter(|fact| match subject.kind {
            SubjectKind::Role => fact.source_path == subject.document,
            SubjectKind::Claim => {
                (fact.source_path == subject.document
                    && fact.end_line >= subject.start_line
                    && fact.start_line <= subject.end_line)
                    || matches!(
                        fact.query_scope.as_str(),
                        "source-behavior" | "configuration" | "test-behavior"
                    )
            }
        })
        .cloned()
        .collect::<Vec<_>>();
    candidates.sort_by(|a, b| {
        let own_a = a.source_path == subject.document;
        let own_b = b.source_path == subject.document;
        own_b.cmp(&own_a).then_with(|| a.id.cmp(&b.id))
    });
    let mut bytes = 0usize;
    candidates
        .into_iter()
        .filter(|fact| {
            if bytes + fact.bytes.len() > crate::evidence::MAX_PROJECTION_BYTES {
                return false;
            }
            bytes += fact.bytes.len();
            true
        })
        .take(crate::evidence::MAX_PROJECTION_FACTS)
        .collect()
}
fn coordinate(
    run_id: &str,
    manifest: &str,
    bundle: &FrozenBundle,
    subjects: &[JudgmentSubject],
    catalog: &EvidenceCatalog,
    transport: &dyn QualifiedClosedByteTransport,
) -> Result<crate::codec::DecodedRecord, String> {
    let rubric = std::str::from_utf8(&bundle.canonical_bytes)
        .map_err(|_| "stored frozen rubric is not UTF-8")?;
    let (model, decoding) = evaluator_digests(bundle)?;
    let mut claim_votes = Vec::new();
    let mut role_votes = Vec::new();
    let mut adjudications = Vec::new();
    let mut resolved_values = Vec::new();
    for subject in subjects {
        let evidence = evidence_for(subject, catalog);
        let first = invoke(
            transport,
            rubric,
            manifest,
            &bundle.digest,
            &model,
            &decoding,
            subject,
            &evidence,
            false,
            1,
        );
        let second = invoke(
            transport,
            rubric,
            manifest,
            &bundle.digest,
            &model,
            &decoding,
            subject,
            &evidence,
            false,
            2,
        );
        push_vote(&mut claim_votes, &mut role_votes, subject, &first, 1);
        push_vote(&mut claim_votes, &mut role_votes, subject, &second, 2);
        let outcome = if subject.kind == SubjectKind::Claim
            && ((first.valid && first.verdict == "breached")
                || (second.valid && second.verdict == "breached"))
        {
            let breach_ids = [first.clone(), second.clone()]
                .into_iter()
                .filter(|vote| vote.valid && vote.verdict == "breached")
                .flat_map(|vote| vote.evidence_fact_ids)
                .collect::<std::collections::BTreeSet<_>>()
                .into_iter()
                .collect::<Vec<_>>();
            let focused_evidence = catalog.projection_by_ids(&breach_ids).unwrap_or_default();
            let focused = invoke(
                transport,
                rubric,
                manifest,
                &bundle.digest,
                &model,
                &decoding,
                subject,
                &focused_evidence,
                true,
                0,
            );
            adjudications.push(adjudication_value(subject, &focused));
            if !first.valid || !second.valid || !focused.valid {
                // Every valid breach vote still receives focused adjudication,
                // but any invalid required vote keeps final subject outcome at
                // evaluation_error; valid peers cannot launder it.
                evaluation_error(subject, &evidence)
            } else if focused.verdict == "breach_confirmed" {
                resolved_from_vote_as(subject, &focused, "breached", "claim.breached")
            } else if focused.verdict == "unverifiable" {
                resolved_from_vote_as(subject, &focused, "unverifiable", "claim.unverifiable")
            } else if focused.verdict == "breach_not_confirmed" {
                ordinary(
                    subject,
                    transport,
                    rubric,
                    manifest,
                    &bundle.digest,
                    &model,
                    &decoding,
                    &evidence,
                    &first,
                    &second,
                    true,
                    &mut claim_votes,
                    &mut role_votes,
                )
                .outcome
            } else {
                evaluation_error(subject, &evidence)
            }
        } else if !first.valid || !second.valid {
            evaluation_error(subject, &evidence)
        } else {
            let ordinary = ordinary(
                subject,
                transport,
                rubric,
                manifest,
                &bundle.digest,
                &model,
                &decoding,
                &evidence,
                &first,
                &second,
                false,
                &mut claim_votes,
                &mut role_votes,
            );
            if subject.kind == SubjectKind::Claim
                && ordinary
                    .third
                    .as_ref()
                    .is_some_and(|vote| vote.valid && vote.verdict == "breached")
            {
                let third = ordinary.third.as_ref().expect("checked third breach");
                let focused_evidence = catalog
                    .projection_by_ids(&third.evidence_fact_ids)
                    .unwrap_or_default();
                let focused = invoke(
                    transport,
                    rubric,
                    manifest,
                    &bundle.digest,
                    &model,
                    &decoding,
                    subject,
                    &focused_evidence,
                    true,
                    0,
                );
                adjudications.push(adjudication_value(subject, &focused));
                if !focused.valid {
                    evaluation_error(subject, &evidence)
                } else if focused.verdict == "breach_confirmed" {
                    resolved_from_vote_as(subject, &focused, "breached", "claim.breached")
                } else if focused.verdict == "unverifiable" {
                    resolved_from_vote_as(subject, &focused, "unverifiable", "claim.unverifiable")
                } else {
                    evaluation_error(subject, &evidence)
                }
            } else {
                ordinary.outcome
            }
        };
        resolved_values.push(json!({"subject_kind":outcome.subject.kind.as_str(),"subject_id":outcome.subject.id,"verdict":outcome.verdict,"controlling_reason":outcome.controlling_reason,"evidence_fact_ids":outcome.evidence_fact_ids,"evidence_digests":outcome.evidence_digests}));
    }
    codec::encode_record(
        &json!({"schema":"judgment-bundle-v1","run_id":run_id,"manifest_digest":manifest,"bundle_digest":bundle.digest,"model_identity_digest":model,"decoding_parameter_digest":decoding,"claim_votes":claim_votes,"role_votes":role_votes,"focused_breach_adjudications":adjudications,"resolved":resolved_values}),
        RecordKind::JudgmentBundle,
        run_id,
    )
}
#[allow(clippy::too_many_arguments)]
fn ordinary(
    subject: &JudgmentSubject,
    transport: &dyn QualifiedClosedByteTransport,
    rubric: &str,
    manifest: &str,
    bundle: &str,
    model: &str,
    decoding: &str,
    evidence: &[EvidenceFact],
    first: &Vote,
    second: &Vote,
    force_third: bool,
    claims: &mut Vec<Value>,
    roles: &mut Vec<Value>,
) -> OrdinaryResolution {
    if !force_third && compatible(first, second) {
        return OrdinaryResolution {
            outcome: resolved_from_vote(subject, first),
            third: None,
        };
    }
    let third = invoke(
        transport, rubric, manifest, bundle, model, decoding, subject, evidence, false, 3,
    );
    push_vote(claims, roles, subject, &third, 3);
    if !third.valid {
        return OrdinaryResolution {
            outcome: evaluation_error(subject, evidence),
            third: Some(third),
        };
    }
    // After focused non-confirmation, breached initial votes cannot supply
    // ordinary quorum. Third vote alone never resolves a subject.
    let eligible = [first, second, &third]
        .into_iter()
        .filter(|vote| !force_third || vote.verdict != "breached")
        .collect::<Vec<_>>();
    for vote in &eligible {
        if eligible
            .iter()
            .filter(|other| compatible(vote, other))
            .count()
            >= 2
        {
            return OrdinaryResolution {
                outcome: resolved_from_vote(subject, vote),
                third: Some(third),
            };
        }
    }
    OrdinaryResolution {
        outcome: evaluation_error(subject, evidence),
        third: Some(third),
    }
}
#[allow(clippy::too_many_arguments)]
fn invoke(
    transport: &dyn QualifiedClosedByteTransport,
    rubric: &str,
    manifest: &str,
    bundle: &str,
    model: &str,
    decoding: &str,
    subject: &JudgmentSubject,
    evidence: &[EvidenceFact],
    focused: bool,
    ordinal: u8,
) -> Vote {
    let invocation_id=codec::sha256(&codec::canonicalize(&json!({"bundle":bundle,"manifest":manifest,"subject_kind":subject.kind.as_str(),"subject":subject.id,"focused":focused,"ordinal":ordinal})).expect("canonical invocation"));
    let request = ClosedRequest {
        protocol: "documentation-maintenance-isolated-judge-v1".into(),
        invocation_id: invocation_id.clone(),
        rubric: rubric.into(),
        manifest_digest: manifest.into(),
        bundle_digest: bundle.into(),
        model_identity_digest: model.into(),
        decoding_parameter_digest: decoding.into(),
        subject_kind: subject.kind.as_str().into(),
        subject_id: subject.id.clone(),
        binding_rule_semantic_digest: subject.binding_rule_semantic_digest.clone(),
        binding_force: subject.force.clone(),
        binding_scope: subject.scope.clone(),
        claim_digest: subject.claim_digest.clone(),
        evidence: evidence
            .iter()
            .map(|f| SerializedFact {
                id: f.id.clone(),
                source_path: f.source_path.clone(),
                start_line: f.start_line,
                end_line: f.end_line,
                query_scope: f.query_scope.clone(),
                result_digest: f.result_digest.clone(),
                bytes_base64: f.encoded_bytes(),
                untrusted: true,
            })
            .collect(),
        focused_breach: focused,
        repository_content_is_untrusted_data: true,
    };
    let bytes = codec::canonicalize(&serde_json::to_value(request).expect("serialize request"))
        .expect("canonical request");
    let request_digest = codec::sha256(&bytes);
    let output = transport
        .invoke_closed(&invocation_id, &bytes)
        .and_then(|bytes| serde_json::from_slice(&bytes).map_err(|e| e.to_string()))
        .and_then(|v| parse_output(&v, subject, focused, evidence));
    let (verdict, reason, cited_ids, evaluation_diagnostic, valid) = match output {
        Ok((verdict, reason, cited_ids)) => (verdict, reason, cited_ids, None, true),
        Err(error) => (
            "evaluation_error".into(),
            if focused {
                "breach.adjudication.evaluation-error".into()
            } else {
                evaluation_reason(subject).into()
            },
            Vec::new(),
            Some(error.chars().take(4096).collect()),
            false,
        ),
    };
    let cited = evidence
        .iter()
        .filter(|fact| cited_ids.contains(&fact.id))
        .collect::<Vec<_>>();
    Vote {
        verdict,
        reason,
        evidence_digests: cited.iter().map(|f| f.result_digest.clone()).collect(),
        evidence_fact_ids: cited.iter().map(|f| f.id.clone()).collect(),
        invocation_id,
        request_digest,
        evaluation_diagnostic,
        valid,
    }
}
fn parse_output(
    value: &Value,
    subject: &JudgmentSubject,
    focused: bool,
    offered: &[EvidenceFact],
) -> Result<(String, String, Vec<String>), String> {
    let object = value.as_object().ok_or("judge output is not object")?;
    if object.len() != 3 {
        return Err("judge output is not closed".into());
    };
    let v = object
        .get("verdict")
        .and_then(Value::as_str)
        .ok_or("judge verdict invalid")?;
    let r = object
        .get("controlling_reason")
        .and_then(Value::as_str)
        .filter(|x| !x.is_empty() && x.len() <= 128)
        .ok_or("judge reason invalid")?;
    if !tuple_valid(subject, v, r, focused) {
        return Err("judge verdict/reason tuple invalid".into());
    }
    let ids = object
        .get("evidence_fact_ids")
        .and_then(Value::as_array)
        .ok_or("judge cited evidence invalid")?
        .iter()
        .map(|id| {
            id.as_str()
                .map(str::to_string)
                .ok_or("judge cited evidence invalid")
        })
        .collect::<Result<Vec<_>, _>>()?;
    let offered_ids = offered
        .iter()
        .map(|fact| fact.id.as_str())
        .collect::<std::collections::BTreeSet<_>>();
    let cited_ids = ids
        .iter()
        .map(String::as_str)
        .collect::<std::collections::BTreeSet<_>>();
    if ids.is_empty()
        || ids.len() > offered.len()
        || ids.iter().any(|id| !offered_ids.contains(id.as_str()))
        || cited_ids.len() != ids.len()
        || (focused && cited_ids != offered_ids)
    {
        return Err("judge cited evidence is empty, repeated, unavailable, or incomplete for focused adjudication".into());
    }
    Ok((v.into(), r.into(), ids))
}
fn tuple_valid(subject: &JudgmentSubject, verdict: &str, reason: &str, focused: bool) -> bool {
    if focused {
        return matches!(
            (verdict, reason),
            ("breach_confirmed", "breach.binding-rule.confirmed")
                | ("breach_not_confirmed", "breach.binding-rule.not-confirmed")
                | ("unverifiable", "breach.binding-rule.unverifiable")
        );
    }
    match subject.kind {
        SubjectKind::Claim => {
            matches!(
                (verdict, reason),
                ("adhered", "claim.adhered")
                    | ("drifted", "claim.drifted")
                    | ("unverifiable", "claim.unverifiable")
            ) || ((verdict, reason) == ("breached", "claim.breached")
                && subject.document == "docs/intent.md"
                && subject.binding_rule_semantic_digest.is_some())
        }
        SubjectKind::Role => subject
            .role_reasons
            .as_ref()
            .is_some_and(|m| m.get(verdict).is_some_and(|x| x == reason)),
    }
}
fn evaluation_reason(subject: &JudgmentSubject) -> &str {
    match subject.kind {
        SubjectKind::Claim => "claim.evaluation-error",
        SubjectKind::Role => "claim.evaluation-error",
    }
}
fn compatible(a: &Vote, b: &Vote) -> bool {
    a.valid && b.valid && a.verdict == b.verdict && a.reason == b.reason
}
fn resolved_from_vote(subject: &JudgmentSubject, vote: &Vote) -> ResolvedJudgment {
    resolved_from_vote_as(subject, vote, &vote.verdict, &vote.reason)
}
fn resolved_from_vote_as(
    subject: &JudgmentSubject,
    vote: &Vote,
    verdict: &str,
    reason: &str,
) -> ResolvedJudgment {
    ResolvedJudgment {
        subject: subject.clone(),
        verdict: verdict.into(),
        controlling_reason: reason.into(),
        evidence_fact_ids: vote.evidence_fact_ids.clone(),
        evidence_digests: vote.evidence_digests.clone(),
    }
}
fn evaluation_error(subject: &JudgmentSubject, _: &[EvidenceFact]) -> ResolvedJudgment {
    ResolvedJudgment {
        subject: subject.clone(),
        verdict: "evaluation_error".into(),
        controlling_reason: evaluation_reason(subject).into(),
        evidence_fact_ids: Vec::new(),
        evidence_digests: Vec::new(),
    }
}
fn push_vote(
    claims: &mut Vec<Value>,
    roles: &mut Vec<Value>,
    subject: &JudgmentSubject,
    vote: &Vote,
    ordinal: u8,
) {
    let to = if subject.kind == SubjectKind::Claim {
        claims
    } else {
        roles
    };
    to.push(json!({"vote_id":format!("{}:{ordinal}",subject.id),"subject_kind":subject.kind.as_str(),"subject_id":subject.id,"judge_ordinal":ordinal,"verdict":vote.verdict,"controlling_reason":vote.reason,"evidence_digests":vote.evidence_digests,"evidence_fact_ids":vote.evidence_fact_ids,"invocation_id":vote.invocation_id,"request_digest":vote.request_digest,"evaluation_diagnostic":vote.evaluation_diagnostic}));
}
fn adjudication_value(subject: &JudgmentSubject, vote: &Vote) -> Value {
    json!({"adjudication_id":format!("{}:focused",subject.id),"subject_kind":"claim","subject_id":subject.id,"verdict":vote.verdict,"controlling_reason":vote.reason,"evidence_digests":vote.evidence_digests,"evidence_fact_ids":vote.evidence_fact_ids,"invocation_id":vote.invocation_id,"request_digest":vote.request_digest,"evaluation_diagnostic":vote.evaluation_diagnostic,"binding_rule_semantic_digest":subject.binding_rule_semantic_digest,"binding_force":subject.force,"binding_scope":subject.scope,"claim_digest":subject.claim_digest})
}
fn evaluator_digests(bundle: &FrozenBundle) -> Result<(String, String), String> {
    Ok((
        bundle.value["evaluator_identity"]["model_identity_digest"]
            .as_str()
            .ok_or("frozen model identity absent")?
            .into(),
        bundle.value["evaluator_identity"]["decoding_parameter_digest"]
            .as_str()
            .ok_or("frozen decoding identity absent")?
            .into(),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    struct Scripted {
        outputs: RefCell<Vec<Value>>,
        requests: RefCell<Vec<Value>>,
    }
    impl QualifiedClosedByteTransport for Scripted {
        fn invoke_closed(&self, _: &str, b: &[u8]) -> Result<Vec<u8>, String> {
            self.requests
                .borrow_mut()
                .push(serde_json::from_slice(b).unwrap());
            Ok(serde_json::to_vec(&self.outputs.borrow_mut().remove(0)).unwrap())
        }
    }
    #[test]
    fn every_transport_invocation_checks_repository_stability() {
        struct Mutating {
            path: std::path::PathBuf,
        }
        impl QualifiedClosedByteTransport for Mutating {
            fn invoke_closed(&self, _: &str, _: &[u8]) -> Result<Vec<u8>, String> {
                std::fs::write(&self.path, "changed").unwrap();
                Ok(b"{}".to_vec())
            }
        }
        let work = tempfile::tempdir().unwrap();
        let artifacts = tempfile::tempdir().unwrap();
        std::process::Command::new("git")
            .args(["init", "-q"])
            .current_dir(work.path())
            .status()
            .unwrap();
        let source = work.path().join("src.rs");
        std::fs::write(&source, "original").unwrap();
        let roots = crate::boundary::validate_roots(
            &work.path().canonicalize().unwrap(),
            &artifacts.path().canonicalize().unwrap(),
        )
        .unwrap();
        let view = RepositoryView::new(&roots, "run");
        let baseline = view.capture().unwrap();
        let mutating = Mutating { path: source };
        let checked = StabilityCheckedTransport {
            inner: &mutating,
            view: &view,
            baseline: &baseline,
        };
        assert!(checked
            .invoke_closed("invocation", b"{}")
            .unwrap_err()
            .contains("repository instability after model invocation"));
    }

    #[test]
    fn forged_tuple_is_evaluation_error_not_content_verdict() {
        let s = JudgmentSubject {
            kind: SubjectKind::Claim,
            id: "c".into(),
            document: "x".into(),
            start_line: 1,
            end_line: 1,
            binding_rule_semantic_digest: None,
            claim_digest: None,
            force: None,
            scope: None,
            role_reasons: None,
        };
        assert!(!tuple_valid(&s, "adhered", "claim.breached", false));
        assert!(!tuple_valid(
            &s,
            "breach_confirmed",
            "breach.binding-rule.not-confirmed",
            true
        ));
    }
    #[test]
    fn valid_breach_peer_is_focused_even_when_other_initial_vote_is_invalid() {
        let manifest = crate::codec::encode_record(
            &json!({"schema":"repository-manifest-v1","run_id":"run","manifest_kind":"baseline","work_root":"/repo","git_common_dir":"/repo/.git","entries":[],"repository_fingerprint":format!("sha256:{}", "0".repeat(64)),"baseline_digest":null,"overlay_paths":[]}),
            RecordKind::RepositoryManifest,
            "run",
        )
        .unwrap();
        let catalog = EvidenceCatalog::from_manifest(&manifest).unwrap();
        let evidence_id = catalog.facts_for_path("docs/intent.md")[0].id.clone();
        let subject = JudgmentSubject {
            kind: SubjectKind::Claim,
            id: "c".into(),
            document: "docs/intent.md".into(),
            start_line: 1,
            end_line: 1,
            binding_rule_semantic_digest: Some(format!("sha256:{}", "a".repeat(64))),
            claim_digest: Some(format!("sha256:{}", "b".repeat(64))),
            force: Some("binding-invariant".into()),
            scope: Some("repository".into()),
            role_reasons: None,
        };
        let transport = Scripted {
            outputs: RefCell::new(vec![
                json!({}),
                json!({"verdict":"breached","controlling_reason":"claim.breached","evidence_fact_ids":[evidence_id.clone()]}),
                json!({"verdict":"breach_confirmed","controlling_reason":"breach.binding-rule.confirmed","evidence_fact_ids":[evidence_id]}),
            ]),
            requests: RefCell::new(vec![]),
        };
        let bundle = crate::bundle::build_bundle().unwrap();
        let result = coordinate(
            "run",
            &manifest.digest,
            &bundle,
            &[subject],
            &catalog,
            &transport,
        )
        .unwrap();
        assert_eq!(
            result.value["focused_breach_adjudications"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        assert_eq!(result.value["resolved"][0]["verdict"], "evaluation_error");
        assert_eq!(transport.requests.borrow().len(), 3);
    }

    #[test]
    fn closed_transport_sees_no_peer_or_ambient_data() {
        let s = JudgmentSubject {
            kind: SubjectKind::Claim,
            id: "c".into(),
            document: "x".into(),
            start_line: 1,
            end_line: 1,
            binding_rule_semantic_digest: Some(
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(),
            ),
            claim_digest: Some(
                "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb".into(),
            ),
            force: Some("binding-invariant".into()),
            scope: Some("repo".into()),
            role_reasons: None,
        };
        let t = Scripted {
            outputs: RefCell::new(vec![
                json!({"verdict":"adhered","controlling_reason":"claim.adhered"}),
            ]),
            requests: RefCell::new(vec![]),
        };
        let _ = invoke(&t, "{}", "m", "b", "model", "decode", &s, &[], false, 1);
        let r = &t.requests.borrow()[0];
        assert!(r.get("peer_votes").is_none());
        assert!(r.get("worktree").is_none());
    }
}
