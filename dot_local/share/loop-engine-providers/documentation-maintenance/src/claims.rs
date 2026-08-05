//! Deterministic Markdown source units, claim identity, force, and authority.
use crate::{codec, evidence::EvidenceCatalog, schema::RecordKind};
use serde_json::json;
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Claim {
    pub claim_id: String,
    pub source_unit_id: String,
    pub semantic_digest: String,
    pub document: String,
    pub start_line: u64,
    pub end_line: u64,
    pub ordinal: u64,
    pub proposition: String,
    pub force: String,
    pub scope: String,
    pub evidence_digests: Vec<String>,
    pub reason_id: String,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthorityFinding {
    pub path: String,
    pub start_line: u64,
    pub end_line: u64,
    pub reason_id: String,
}

pub fn extract_core_claims(
    run_id: &str,
    catalog: &EvidenceCatalog,
) -> Result<crate::codec::DecodedRecord, String> {
    let mut claims = Vec::new();
    for document in ["docs/intent.md", "AGENTS.md", "README.md"] {
        // Parse complete immutable manifest bytes, not independently decoded
        // chunks: a UTF-8 character or Markdown source unit may cross a chunk.
        let Ok(bytes) = catalog.bytes_for_path(document) else {
            continue;
        };
        let text = std::str::from_utf8(&bytes)
            .map_err(|_| format!("core document {document} is not valid UTF-8"))?;
        claims.extend(extract_markdown_claims(
            document,
            text,
            &codec::sha256(&bytes),
        )?);
    }
    claims.sort_by(|a, b| a.claim_id.cmp(&b.claim_id));
    codec::encode_record(
        &json!({"schema":"claim-set-v1","run_id":run_id,"manifest_digest":catalog.manifest_digest(),"claims":claims.iter().map(claim_value).collect::<Vec<_>>() }),
        RecordKind::ClaimSet,
        run_id,
    )
}

/// Proves claim inventory came from exact active manifest bytes rather than a
/// caller-authored schema-valid substitute.
pub fn verify_extracted_record(
    run_id: &str,
    catalog: &EvidenceCatalog,
    record: &crate::codec::DecodedRecord,
) -> Result<(), String> {
    if record.kind != RecordKind::ClaimSet {
        return Err("claim provenance requires claim-set-v1".into());
    }
    let expected = extract_core_claims(run_id, catalog)?;
    if record.digest != expected.digest || record.value != expected.value {
        return Err("claim set does not equal deterministic active-manifest extraction".into());
    }
    Ok(())
}

/// Source units are heading-scoped Markdown blocks. Fenced code is not prose;
/// inserting unrelated blocks cannot renumber a claim in another unit.
pub fn extract_markdown_claims(
    document: &str,
    markdown: &str,
    evidence_digest: &str,
) -> Result<Vec<Claim>, String> {
    let mut claims = Vec::new();
    let mut heading = "document".to_string();
    let mut unit_start = 1u64;
    let mut block = Vec::<(u64, String)>::new();
    let mut in_fence = false;
    let flush = |block: &mut Vec<(u64, String)>,
                 heading: &str,
                 unit_start: u64,
                 claims: &mut Vec<Claim>|
     -> Result<(), String> {
        if block.is_empty() {
            return Ok(());
        }
        let start = block[0].0;
        let end = block.last().expect("nonempty").0;
        let raw = block
            .iter()
            .map(|(_, s)| s.as_str())
            .collect::<Vec<_>>()
            .join(" ");
        let unit = codec::sha256(&codec::canonicalize(
            &json!({"document":document,"heading":normalize(heading),"start_line":unit_start,"block_start":start,"block_end":end}),
        )?);
        let force = force_for(heading, &raw);
        for (ordinal, proposition) in split_propositions(&raw).into_iter().enumerate() {
            if !action_changing(&proposition, heading) {
                continue;
            }
            let proposition = proposition.trim().to_string();
            let normalized = normalize(&proposition);
            let ordinal = u64::try_from(ordinal).expect("ordinal fits");
            let claim_id = codec::sha256(&codec::canonicalize(
                &json!({"document":document,"source_unit_id":unit,"range":[start,end],"ordinal":ordinal,"proposition":normalized}),
            )?);
            let semantic_digest = codec::sha256(&codec::canonicalize(
                &json!({"proposition": normalized, "force": force, "scope": normalize(heading)}),
            )?);
            claims.push(Claim {
                claim_id,
                source_unit_id: unit.clone(),
                semantic_digest,
                document: document.into(),
                start_line: start,
                end_line: end,
                ordinal,
                proposition,
                force: force.clone(),
                scope: heading.to_string(),
                evidence_digests: vec![evidence_digest.into()],
                reason_id: "claim.extracted.action-changing".into(),
            });
        }
        block.clear();
        Ok(())
    };
    for (index, raw) in markdown.lines().enumerate() {
        let line = u64::try_from(index + 1).expect("line fits");
        let trimmed = raw.trim();
        if trimmed.starts_with("```") || trimmed.starts_with("~~~") {
            flush(&mut block, &heading, unit_start, &mut claims)?;
            in_fence = !in_fence;
            continue;
        }
        if in_fence {
            continue;
        }
        if let Some(title) = trimmed
            .strip_prefix('#')
            .map(str::trim)
            .filter(|s| !s.is_empty())
        {
            flush(&mut block, &heading, unit_start, &mut claims)?;
            heading = title.to_ascii_lowercase();
            unit_start = line;
            continue;
        }
        if trimmed.is_empty() || trimmed.starts_with("<!--") {
            flush(&mut block, &heading, unit_start, &mut claims)?;
            continue;
        }
        block.push((
            line,
            trimmed.trim_start_matches(['-', '*', '+', ' ']).to_string(),
        ));
    }
    flush(&mut block, &heading, unit_start, &mut claims)?;
    Ok(claims)
}

/// Intent is only authority. Matching detects exact semantic identity and
/// conservative token-overlap rewrites; no lower source may repair a missing
/// or weaker binding rule.
/// Production record boundary for staged/audit callers. Both decoded claim
/// sets are schema- and manifest-bound before their canonical claim inventory
/// is compared; callers cannot feed an unrelated slice to evade this check.
pub fn anti_laundering_records(
    baseline: &crate::codec::DecodedRecord,
    proposed: &crate::codec::DecodedRecord,
) -> Result<Vec<AuthorityFinding>, String> {
    for record in [baseline, proposed] {
        if record.kind != RecordKind::ClaimSet {
            return Err("authority comparison requires claim-set-v1 records".into());
        }
        crate::schema::validate(RecordKind::ClaimSet, &record.value)?;
        if codec::sha256(&codec::canonicalize(&record.value)?) != record.digest {
            return Err("authority comparison claim-set digest is invalid".into());
        }
    }
    let decode = |record: &crate::codec::DecodedRecord| -> Result<Vec<Claim>, String> {
        record.value["claims"]
            .as_array()
            .ok_or("claim-set claims missing")?
            .iter()
            .map(|v| {
                let location = &v["location"];
                Ok(Claim {
                    claim_id: v["claim_id"].as_str().ok_or("claim id missing")?.into(),
                    source_unit_id: v["source_unit_id"]
                        .as_str()
                        .ok_or("source unit missing")?
                        .into(),
                    semantic_digest: v["semantic_digest"]
                        .as_str()
                        .ok_or("semantic digest missing")?
                        .into(),
                    document: v["document"]
                        .as_str()
                        .ok_or("claim document missing")?
                        .into(),
                    start_line: location["start_line"]
                        .as_u64()
                        .ok_or("claim start missing")?,
                    end_line: location["end_line"].as_u64().ok_or("claim end missing")?,
                    ordinal: v["ordinal"].as_u64().ok_or("claim ordinal missing")?,
                    proposition: v["proposition"]
                        .as_str()
                        .ok_or("claim proposition missing")?
                        .into(),
                    force: v["force"].as_str().ok_or("claim force missing")?.into(),
                    scope: v["scope"].as_str().ok_or("claim scope missing")?.into(),
                    evidence_digests: v["evidence_digests"]
                        .as_array()
                        .ok_or("claim evidence missing")?
                        .iter()
                        .map(|x| {
                            x.as_str()
                                .map(str::to_string)
                                .ok_or("claim evidence invalid")
                        })
                        .collect::<Result<_, _>>()?,
                    reason_id: v["reason_id"]
                        .as_str()
                        .ok_or("claim reason missing")?
                        .into(),
                })
            })
            .collect()
    };
    Ok(anti_laundering(&decode(baseline)?, &decode(proposed)?))
}

/// Manifest-bound staged authority check. Neither inventory may be replaced
/// by caller-authored schema-valid claims.
pub fn verify_anti_laundering_records(
    run_id: &str,
    baseline_catalog: &EvidenceCatalog,
    proposed_catalog: &EvidenceCatalog,
    baseline: &crate::codec::DecodedRecord,
    proposed: &crate::codec::DecodedRecord,
) -> Result<Vec<AuthorityFinding>, String> {
    verify_extracted_record(run_id, baseline_catalog, baseline)?;
    verify_extracted_record(run_id, proposed_catalog, proposed)?;
    anti_laundering_records(baseline, proposed)
}

pub fn anti_laundering(baseline: &[Claim], proposed: &[Claim]) -> Vec<AuthorityFinding> {
    let old = bindings(baseline);
    let new = bindings(proposed);
    let mut findings = Vec::new();
    for prior in old.values() {
        let candidate = new
            .get(&binding_key(prior))
            .or_else(|| new.values().find(|next| related_binding(prior, next)));
        match candidate {
            Some(next)
                if same_or_stronger_force(&prior.force, &next.force)
                    && same_scope_and_rule(prior, next) => {}
            Some(next) => findings.push(finding(next, "authority.binding-rule.weakened")),
            None => findings.push(finding(
                prior,
                "authority.binding-rule.deleted-or-relabelled",
            )),
        }
    }
    findings.extend(current_authority_findings(proposed));
    findings.sort_by(|a, b| {
        (&a.reason_id, &a.path, a.start_line).cmp(&(&b.reason_id, &b.path, b.start_line))
    });
    findings.dedup();
    findings
}

/// Deterministic current-inventory authority violations. Audit consumes this
/// directly, so lower-source and aspiration laundering cannot be dead staged
/// checks when no baseline record is available.
pub fn current_authority_findings(claims: &[Claim]) -> Vec<AuthorityFinding> {
    let mut findings = Vec::new();
    for claim in claims {
        if is_binding(&claim.force) && claim.document != "docs/intent.md" {
            findings.push(finding(
                claim,
                "authority.lower-source-cannot-establish-binding",
            ));
        }
        if claim.force == "aspiration" && binding_like(&claim.proposition) {
            findings.push(finding(claim, "authority.aspiration-guarantee-laundering"));
        }
    }
    findings.sort_by(|a, b| {
        (&a.reason_id, &a.path, a.start_line).cmp(&(&b.reason_id, &b.path, b.start_line))
    });
    findings.dedup();
    findings
}

pub fn claim_value(claim: &Claim) -> serde_json::Value {
    json!({"claim_id":claim.claim_id,"source_unit_id":claim.source_unit_id,"semantic_digest":claim.semantic_digest,"document":claim.document,"location":{"path":claim.document,"start_line":claim.start_line,"end_line":claim.end_line},"ordinal":claim.ordinal,"proposition":claim.proposition,"force":claim.force,"scope":claim.scope,"evidence_digests":claim.evidence_digests,"reason_id":claim.reason_id})
}
pub fn semantic_digest(claim: &Claim) -> String {
    claim.semantic_digest.clone()
}

fn split_propositions(raw: &str) -> Vec<String> {
    let mut result = Vec::new();
    let mut current = String::new();
    let mut tick = false;
    for c in raw.chars() {
        if c == '`' {
            tick = !tick;
        }
        current.push(c);
        if !tick && matches!(c, '.' | ';' | '!' | '?') {
            let value = current.trim().trim_end_matches(['.', ';', '!', '?']).trim();
            if !value.is_empty() {
                result.push(value.into());
            }
            current.clear();
        }
    }
    let value = current.trim();
    if !value.is_empty() {
        result.push(value.into());
    }
    result
}
fn action_changing(proposition: &str, heading: &str) -> bool {
    let lower = proposition.to_ascii_lowercase();
    [
        "must",
        "must not",
        "never",
        "always",
        "required",
        "forbid",
        "should",
        "may",
        "cannot",
        "do not",
        "run `",
        "use `",
        "scope:",
        "rationale:",
        "operational effect:",
        "breach evidence:",
    ]
    .iter()
    .any(|n| lower.contains(n))
        || [
            "purpose",
            "tenet",
            "invariant",
            "boundar",
            "non-goal",
            "non goal",
            "aspiration",
        ]
        .iter()
        .any(|n| heading.contains(n))
}
fn force_for(heading: &str, proposition: &str) -> String {
    let lower = proposition.to_ascii_lowercase();
    for (marker, force) in [
        ("[force: purpose]", "purpose"),
        ("[force: tenet]", "tenet"),
        ("[force: binding-invariant]", "binding-invariant"),
        ("[force: binding-boundary]", "binding-boundary"),
        ("[force: binding-non-goal]", "binding-non-goal"),
        ("[force: aspiration]", "aspiration"),
        ("[force: descriptive]", "descriptive"),
    ] {
        if lower.contains(marker) {
            return force.into();
        }
    }
    if heading.contains("purpose") {
        "purpose"
    } else if heading.contains("tenet") {
        "tenet"
    } else if heading.contains("invariant") {
        "binding-invariant"
    } else if heading.contains("boundar") {
        "binding-boundary"
    } else if heading.contains("non-goal") || heading.contains("non goal") {
        "binding-non-goal"
    } else if heading.contains("aspiration") {
        "aspiration"
    } else {
        "descriptive"
    }
    .into()
}
fn normalize(value: &str) -> String {
    value
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_ascii_lowercase()
}
fn bindings(claims: &[Claim]) -> BTreeMap<String, Claim> {
    claims
        .iter()
        .filter(|c| c.document == "docs/intent.md" && is_binding(&c.force))
        .map(|c| (binding_key(c), c.clone()))
        .collect()
}
fn binding_key(claim: &Claim) -> String {
    normalize(&claim.proposition)
        .split_whitespace()
        .filter(|word| {
            !matches!(
                *word,
                "must"
                    | "not"
                    | "never"
                    | "always"
                    | "required"
                    | "should"
                    | "may"
                    | "cannot"
                    | "do"
                    | "force"
                    | "binding-invariant"
                    | "binding-boundary"
                    | "binding-non-goal"
            )
        })
        .collect::<Vec<_>>()
        .join(" ")
}
fn related_binding(a: &Claim, b: &Claim) -> bool {
    let left_key = binding_key(a);
    let right_key = binding_key(b);
    let left = left_key.split_whitespace().collect::<BTreeSet<_>>();
    let right = right_key.split_whitespace().collect::<BTreeSet<_>>();
    let overlap = left.intersection(&right).count() * 2;
    overlap >= left.len().min(right.len()).max(1)
}
fn is_binding(force: &str) -> bool {
    matches!(
        force,
        "binding-invariant" | "binding-boundary" | "binding-non-goal"
    )
}
fn same_or_stronger_force(old: &str, new: &str) -> bool {
    old == new && is_binding(new)
}
fn same_scope_and_rule(old: &Claim, new: &Claim) -> bool {
    normalize(&old.scope) == normalize(&new.scope)
        && normalize(&old.proposition) == normalize(&new.proposition)
}
fn binding_like(text: &str) -> bool {
    let text = text.to_ascii_lowercase();
    text.contains("must") || text.contains("never") || text.contains("required")
}
fn finding(claim: &Claim, reason: &str) -> AuthorityFinding {
    AuthorityFinding {
        path: claim.document.clone(),
        start_line: claim.start_line,
        end_line: claim.end_line,
        reason_id: reason.into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn source_units_ignore_fences_and_keep_other_units_stable() {
        let a="# Invariants\nMust keep policy inward; must not import adapters.\n```\nMust fake output\n```\n# Aspirations\nMay automate checks.\n";
        let b = "# Intro\nwords\n\n".to_string() + a;
        let first = extract_markdown_claims("docs/intent.md", a, "sha256:aaa").unwrap();
        let second = extract_markdown_claims("docs/intent.md", &b, "sha256:aaa").unwrap();
        assert_eq!(first.len(), 3);
        // Heading-local ordinal stays zero despite an earlier source unit.
        assert_eq!(first[2].ordinal, second[2].ordinal);
        assert_eq!(first[2].force, "aspiration");
    }
    #[test]
    fn authority_rejects_rewrite_scope_and_aspiration_laundering() {
        let d = "sha256:aaa";
        let old = extract_markdown_claims(
            "docs/intent.md",
            "# Boundaries\nMust not import adapters.",
            d,
        )
        .unwrap();
        let new = extract_markdown_claims(
            "docs/intent.md",
            "# Aspirations\nMust not import adapters.",
            d,
        )
        .unwrap();
        let reasons = anti_laundering(&old, &new)
            .into_iter()
            .map(|f| f.reason_id)
            .collect::<BTreeSet<_>>();
        assert!(reasons.contains("authority.binding-rule.deleted-or-relabelled"));
        assert!(reasons.contains("authority.aspiration-guarantee-laundering"));
    }
    #[test]
    fn record_boundary_cannot_compare_unvalidated_claim_slice() {
        let malformed = crate::codec::DecodedRecord {
            kind: RecordKind::ClaimSet,
            value: json!({"schema":"claim-set-v1","run_id":"run","manifest_digest":"not-a-digest","claims":[]}),
            canonical: vec![],
            digest: "sha256:bad".into(),
        };
        assert!(anti_laundering_records(&malformed, &malformed).is_err());
    }
}
