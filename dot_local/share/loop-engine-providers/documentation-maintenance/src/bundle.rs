//! Canonical frozen contract bundle and stored-graph decoding.

use crate::{
    codec, doctrine,
    policy::{DocumentContractRegistry, PolicyCase},
    schema::RecordKind,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

pub const BUNDLE_VERSION: &str = "documentation-audit-bundle-v1";
pub const MACHINE_BUNDLE_MAX_BYTES: usize = 184_320;
pub const AUDIT_GUIDANCE_MAX_BYTES: usize = 184_320;
pub const OTHER_GUIDANCE_TOTAL_MAX_BYTES: usize = 49_152;
pub const GRAPH_MAX_BYTES: usize = 458_752;
pub const SNAPSHOT_ENVELOPE_MAX_BYTES: usize = 524_288;
pub const GUIDANCE_FIELD_MAX_BYTES: usize = 262_144;
pub const METADATA_MAX_DEPTH: usize = 12;

#[derive(Debug, Clone)]
pub struct FrozenBundle {
    pub(crate) value: Value,
    pub(crate) canonical_bytes: Vec<u8>,
    pub(crate) digest: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BundleDecodeError {
    Unsupported(String),
    Execution(String),
}

impl std::fmt::Display for BundleDecodeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unsupported(s) | Self::Execution(s) => f.write_str(s),
        }
    }
}

pub fn build_bundle() -> Result<FrozenBundle, String> {
    let contracts = DocumentContractRegistry::repository_core()
        .resolve_profile("repository-core")?
        .contracts;
    let schemas = RecordKind::ALL
        .into_iter()
        .map(|kind| {
            serde_json::from_str::<Value>(kind.schema_text())
                .map(|schema| (kind.name().to_string(), schema))
                .map_err(|error| format!("embedded schema {}: {error}", kind.name()))
        })
        .collect::<Result<Map<String, Value>, _>>()?;
    let mut value = json!({
        "schema":BUNDLE_VERSION,
        "profile":{"id":"repository-core","contracts":contracts},
        "reason_registry":reason_registry(),
        "claim_policy":claim_policy(),
        "judgment_policy":judgment_policy(),
        "doctrine":compact_doctrine_contract()?,

        "recovery_policy":recovery_policy(),
        "evaluator_identity":evaluator_identity(),
        "record_schemas":schemas,
        "budgets":{
            "machine_bundle_bytes":MACHINE_BUNDLE_MAX_BYTES,
            "audit_static_guidance_bytes":AUDIT_GUIDANCE_MAX_BYTES,
            "other_static_guidance_total_bytes":OTHER_GUIDANCE_TOTAL_MAX_BYTES,
            "metadata_depth":METADATA_MAX_DEPTH,
            "canonical_graph_bytes":GRAPH_MAX_BYTES,
            "individual_guidance_bytes":GUIDANCE_FIELD_MAX_BYTES,
            "snapshot_envelope_bytes":SNAPSHOT_ENVELOPE_MAX_BYTES
        },
        "compatibility":{"unsupported_stored_bundle":"incompatible","supported_bundle_execution_failure":"evaluation_error","criteria_source":"snapshot.stored_graph.metadata.documentation_audit_bundle_v1"}
    });
    let digests = section_digests(&value)?;
    value
        .as_object_mut()
        .expect("bundle object")
        .insert("section_digests".into(), digests);
    validate_bundle_contract(&value)?;
    let canonical_bytes = codec::canonicalize(&value)?;
    if canonical_bytes.len() > MACHINE_BUNDLE_MAX_BYTES {
        return Err(format!(
            "canonical bundle is {} bytes, exceeds {MACHINE_BUNDLE_MAX_BYTES}",
            canonical_bytes.len()
        ));
    }
    let digest = codec::sha256(&canonical_bytes);
    Ok(FrozenBundle {
        value,
        canonical_bytes,
        digest,
    })
}

pub fn validate_frozen_bundle(bundle: &FrozenBundle) -> Result<(), String> {
    validate_bundle_contract(&bundle.value)?;
    let canonical = codec::canonicalize(&bundle.value)?;
    if canonical.len() > MACHINE_BUNDLE_MAX_BYTES
        || canonical != bundle.canonical_bytes
        || codec::sha256(&canonical) != bundle.digest
    {
        return Err(
            "frozen bundle carrier does not match validated canonical contract bytes".into(),
        );
    }
    Ok(())
}

pub fn decode_stored_bundle(stored_graph: &Value) -> Result<FrozenBundle, BundleDecodeError> {
    let metadata = stored_graph
        .get("metadata")
        .and_then(Value::as_object)
        .ok_or_else(|| {
            BundleDecodeError::Unsupported(
                "stored graph has no documentation audit metadata".into(),
            )
        })?;
    let value = metadata
        .get("documentation_audit_bundle_v1")
        .cloned()
        .ok_or_else(|| {
            BundleDecodeError::Unsupported(
                "stored graph has no documentation_audit_bundle_v1".into(),
            )
        })?;
    let version = value
        .get("schema")
        .and_then(Value::as_str)
        .unwrap_or("missing");
    if version != BUNDLE_VERSION {
        return Err(BundleDecodeError::Unsupported(format!(
            "unsupported stored documentation audit bundle {version:?}"
        )));
    }
    if metadata_depth(&Value::Object(metadata.clone())) > METADATA_MAX_DEPTH {
        return Err(BundleDecodeError::Execution(format!(
            "supported stored graph metadata exceeds depth {METADATA_MAX_DEPTH}"
        )));
    }
    let canonical_bytes = codec::canonicalize(&value).map_err(BundleDecodeError::Execution)?;
    if canonical_bytes.len() > MACHINE_BUNDLE_MAX_BYTES {
        return Err(BundleDecodeError::Execution(
            "supported stored bundle exceeds frozen machine budget".into(),
        ));
    }
    let digest = codec::sha256(&canonical_bytes);
    let expected = metadata
        .get("documentation_audit_bundle_digest")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            BundleDecodeError::Execution("supported stored bundle has no digest carrier".into())
        })?;
    if expected != digest {
        return Err(BundleDecodeError::Execution(
            "stored bundle digest does not match stored bytes".into(),
        ));
    }
    validate_bundle_contract(&value).map_err(BundleDecodeError::Execution)?;
    Ok(FrozenBundle {
        value,
        canonical_bytes,
        digest,
    })
}

const DIGESTED_SECTIONS: [&str; 10] = [
    "profile",
    "reason_registry",
    "claim_policy",
    "judgment_policy",
    "doctrine",
    "recovery_policy",
    "evaluator_identity",
    "record_schemas",
    "budgets",
    "compatibility",
];

fn compact_doctrine_contract() -> Result<Value, String> {
    let mut clauses = serde_json::to_value(doctrine::doctrine_clauses())
        .map_err(|error| format!("encode doctrine clauses: {error}"))?;
    for clause in clauses
        .as_array_mut()
        .ok_or("encoded doctrine clauses are not an array")?
    {
        let examples = clause["examples"]
            .as_array_mut()
            .ok_or("encoded doctrine examples are not an array")?;
        for example in examples {
            let object = example
                .as_object()
                .ok_or("encoded doctrine case is not an object")?;
            *example = json!([
                object["class"],
                object["input"],
                object["expected_outcome"],
                object
                    .get("normalized_verdict")
                    .cloned()
                    .unwrap_or(Value::Null),
                object["affected_subject"],
                object["deciding_evidence"],
                object["controlling_reason"]
            ]);
        }
    }
    Ok(json!({
        "packs": doctrine::doctrine_packs(),
        "case_tuple_fields": ["class","input","accepted_mapping","normalized_verdict","affected_subject","deciding_evidence","controlling_reason"],
        "clauses": clauses
    }))
}

fn section_digests(value: &Value) -> Result<Value, String> {
    let mut digests = Map::new();
    for key in DIGESTED_SECTIONS {
        let section = value
            .get(key)
            .ok_or_else(|| format!("bundle missing digest subject {key}"))?;
        digests.insert(
            key.into(),
            Value::String(codec::sha256(&codec::canonicalize(section)?)),
        );
    }
    Ok(Value::Object(digests))
}

fn validate_bundle_contract(value: &Value) -> Result<(), String> {
    let object = value
        .as_object()
        .ok_or("supported bundle must be an object")?;
    let expected_keys: BTreeSet<&str> = [
        "schema",
        "profile",
        "reason_registry",
        "claim_policy",
        "judgment_policy",
        "doctrine",
        "recovery_policy",
        "evaluator_identity",
        "record_schemas",
        "budgets",
        "compatibility",
        "section_digests",
    ]
    .into_iter()
    .collect();
    let actual_keys = object.keys().map(String::as_str).collect::<BTreeSet<_>>();
    if actual_keys != expected_keys {
        return Err("supported bundle has missing or unknown top-level fields".into());
    }
    let profile = value
        .get("profile")
        .and_then(Value::as_object)
        .ok_or("supported bundle profile is invalid")?;
    if profile.keys().map(String::as_str).collect::<BTreeSet<_>>()
        != ["id", "contracts"].into_iter().collect()
        || profile.get("id").and_then(Value::as_str) != Some("repository-core")
    {
        return Err("supported bundle profile is not closed repository-core-v1".into());
    }
    let contracts = profile
        .get("contracts")
        .and_then(Value::as_array)
        .ok_or("supported bundle contracts are invalid")?;
    if contracts.len() != 3 {
        return Err("supported bundle must carry exactly repository-core contracts".into());
    }
    let mut contract_paths = BTreeSet::new();
    for contract in contracts {
        let decoded: crate::policy::DocumentContract = serde_json::from_value(contract.clone())
            .map_err(|error| format!("closed document contract violation: {error}"))?;
        contract_paths.insert((decoded.id, decoded.path));
    }
    if contract_paths
        != [
            ("repository-intent-v1".into(), "docs/intent.md".into()),
            ("agent-instructions-v1".into(), "AGENTS.md".into()),
            ("root-readme-v1".into(), "README.md".into()),
        ]
        .into_iter()
        .collect()
    {
        return Err("supported bundle repository-core contract identities are invalid".into());
    }
    validate_supported_section_shapes(value)?;
    validate_doctrine_shapes(value)?;
    let carried = value
        .get("section_digests")
        .ok_or("supported bundle has no section digests")?;
    let recomputed = section_digests(value)?;
    if carried != &recomputed {
        return Err("supported bundle subordinate section digest mismatch".into());
    }
    validate_evaluator_identity(
        value
            .get("evaluator_identity")
            .ok_or("missing evaluator identity")?,
    )?;
    validate_reason_registry(value)?;
    validate_policy_case_shapes(value)?;
    Ok(())
}

fn validate_supported_section_shapes(value: &Value) -> Result<(), String> {
    fn object<'a>(
        value: &'a Value,
        path: &str,
        keys: &[&str],
    ) -> Result<&'a Map<String, Value>, String> {
        let object = value
            .as_object()
            .ok_or_else(|| format!("{path} must be an object"))?;
        if object.keys().map(String::as_str).collect::<BTreeSet<_>>()
            != keys.iter().copied().collect()
        {
            return Err(format!("{path} has missing or unknown fields"));
        }
        Ok(object)
    }
    fn strings(value: &Value, path: &str, nonempty: bool) -> Result<(), String> {
        let values = value
            .as_array()
            .ok_or_else(|| format!("{path} must be an array"))?;
        if nonempty && values.is_empty() {
            return Err(format!("{path} must not be empty"));
        }
        if values
            .iter()
            .any(|value| value.as_str().is_none_or(str::is_empty))
        {
            return Err(format!("{path} entries must be non-empty strings"));
        }
        Ok(())
    }
    fn string_fields(
        object: &Map<String, Value>,
        path: &str,
        fields: &[&str],
    ) -> Result<(), String> {
        for field in fields {
            if object[*field].as_str().is_none_or(str::is_empty) {
                return Err(format!("{path}.{field} must be a non-empty string"));
            }
        }
        Ok(())
    }
    fn validate_schema_closure(value: &Value, name: &str, path: &str) -> Result<(), String> {
        match value {
            Value::Object(object) => {
                let admits_object = object.get("type").is_some_and(|kind| {
                    kind.as_str() == Some("object")
                        || kind.as_array().is_some_and(|kinds| {
                            kinds.iter().any(|kind| kind.as_str() == Some("object"))
                        })
                });
                if admits_object
                    && (object.get("additionalProperties") != Some(&Value::Bool(false))
                        || !object.get("properties").is_some_and(Value::is_object))
                {
                    return Err(format!(
                        "stored record schema {name} has open object schema at {path}"
                    ));
                }
                for (key, child) in object {
                    validate_schema_closure(child, name, &format!("{path}/{key}"))?;
                }
            }
            Value::Array(items) => {
                for (index, child) in items.iter().enumerate() {
                    validate_schema_closure(child, name, &format!("{path}/{index}"))?;
                }
            }
            _ => {}
        }
        Ok(())
    }

    let claim = object(
        &value["claim_policy"],
        "claim_policy",
        &[
            "schema",
            "claim_kinds",
            "source_units",
            "claim_verdicts",
            "role_verdicts",
            "force_defaults",
            "force_rule",
            "material_change",
            "non_material_change",
            "authority_order",
            "authority_rule",
            "anti_laundering",
            "revision_order",
            "primary_reason",
            "application_policy",
        ],
    )?;
    let force_defaults = object(
        &claim["force_defaults"],
        "claim_policy.force_defaults",
        &[
            "purpose",
            "tenet",
            "invariant",
            "boundary",
            "non-goal",
            "aspiration",
        ],
    )?;
    let primary_reason = object(
        &claim["primary_reason"],
        "claim_policy.primary_reason",
        &["rule", "reason", "linked_reason"],
    )?;
    let application_policy = object(
        &claim["application_policy"],
        "claim_policy.application_policy",
        &[
            "approval_criteria",
            "identity_criteria",
            "application_criteria",
            "recovery_criteria",
        ],
    )?;
    if claim["schema"] != "claim-authority-policy-v1" {
        return Err("unsupported claim policy schema".into());
    }
    string_fields(
        claim,
        "claim_policy",
        &[
            "source_units",
            "force_rule",
            "authority_rule",
            "revision_order",
        ],
    )?;
    string_fields(
        force_defaults,
        "claim_policy.force_defaults",
        &[
            "purpose",
            "tenet",
            "invariant",
            "boundary",
            "non-goal",
            "aspiration",
        ],
    )?;
    string_fields(
        primary_reason,
        "claim_policy.primary_reason",
        &["rule", "reason", "linked_reason"],
    )?;
    string_fields(
        application_policy,
        "claim_policy.application_policy",
        &[
            "approval_criteria",
            "identity_criteria",
            "application_criteria",
            "recovery_criteria",
        ],
    )?;
    for field in [
        "claim_kinds",
        "claim_verdicts",
        "role_verdicts",
        "material_change",
        "non_material_change",
        "authority_order",
        "anti_laundering",
    ] {
        strings(&claim[field], &format!("claim_policy.{field}"), true)?;
    }

    let judgment = object(
        &value["judgment_policy"],
        "judgment_policy",
        &[
            "schema",
            "claim_outputs",
            "role_outputs",
            "focused_breach_outputs",
            "blindness",
            "direct_agreement",
            "ordinary_disagreement",
            "breach_rule",
            "breach_return",
            "invalid_output",
            "role_mapping",
            "disposition_priority",
            "stable_reasons",
        ],
    )?;
    let role_mapping = object(
        &judgment["role_mapping"],
        "judgment_policy.role_mapping",
        &["deficient", "unverifiable", "evaluation_error", "satisfied"],
    )?;
    if judgment["schema"] != "judgment-policy-v1" {
        return Err("unsupported judgment policy schema".into());
    }
    string_fields(
        judgment,
        "judgment_policy",
        &[
            "blindness",
            "direct_agreement",
            "ordinary_disagreement",
            "breach_rule",
            "breach_return",
            "invalid_output",
        ],
    )?;
    string_fields(
        role_mapping,
        "judgment_policy.role_mapping",
        &["deficient", "unverifiable", "evaluation_error", "satisfied"],
    )?;
    for field in [
        "claim_outputs",
        "role_outputs",
        "focused_breach_outputs",
        "disposition_priority",
        "stable_reasons",
    ] {
        strings(&judgment[field], &format!("judgment_policy.{field}"), true)?;
    }

    let recovery = object(
        &value["recovery_policy"],
        "recovery_policy",
        &["schema", "evaluation_recovery", "breach_remediation"],
    )?;
    if recovery["schema"] != "recovery-policy-v1" {
        return Err("unsupported recovery policy schema".into());
    }
    for (field, schema) in [
        ("evaluation_recovery", "evaluation-recovery-v1"),
        ("breach_remediation", "breach-remediation-v1"),
    ] {
        let contract = object(
            &recovery[field],
            &format!("recovery_policy.{field}"),
            &["schema", "requires", "semantics", "reasons", "examples"],
        )?;
        if contract["schema"] != schema {
            return Err(format!("unsupported recovery_policy.{field} schema"));
        }
        string_fields(
            contract,
            &format!("recovery_policy.{field}"),
            &["semantics"],
        )?;
        strings(
            &contract["requires"],
            &format!("recovery_policy.{field}.requires"),
            true,
        )?;
        strings(
            &contract["reasons"],
            &format!("recovery_policy.{field}.reasons"),
            true,
        )?;
        let examples = contract["examples"]
            .as_array()
            .ok_or_else(|| format!("recovery_policy.{field}.examples must be an array"))?;
        if examples.is_empty() {
            return Err(format!(
                "recovery_policy.{field}.examples must not be empty"
            ));
        }
        for example in examples {
            serde_json::from_value::<crate::policy::PolicyCase>(example.clone())
                .map_err(|error| format!("closed recovery case violation: {error}"))?;
        }
    }

    let budgets = object(
        &value["budgets"],
        "budgets",
        &[
            "machine_bundle_bytes",
            "audit_static_guidance_bytes",
            "other_static_guidance_total_bytes",
            "metadata_depth",
            "canonical_graph_bytes",
            "individual_guidance_bytes",
            "snapshot_envelope_bytes",
        ],
    )?;
    if budgets.values().any(|value| value.as_u64().is_none()) {
        return Err("budget values must be unsigned integers".into());
    }
    let compatibility = object(
        &value["compatibility"],
        "compatibility",
        &[
            "unsupported_stored_bundle",
            "supported_bundle_execution_failure",
            "criteria_source",
        ],
    )?;
    if compatibility
        .values()
        .any(|value| value.as_str().is_none_or(str::is_empty))
    {
        return Err("compatibility values must be non-empty strings".into());
    }

    let schemas = value["record_schemas"]
        .as_object()
        .ok_or("record_schemas must be an object")?;
    let expected = RecordKind::ALL
        .into_iter()
        .map(RecordKind::name)
        .collect::<BTreeSet<_>>();
    if schemas.keys().map(String::as_str).collect::<BTreeSet<_>>() != expected {
        return Err("record_schemas inventory differs from supported 17-record contract".into());
    }
    for (name, schema) in schemas {
        let schema_object = schema
            .as_object()
            .ok_or_else(|| format!("stored record schema {name} must be an object"))?;
        for required in [
            "$schema",
            "$id",
            "title",
            "type",
            "additionalProperties",
            "properties",
            "required",
        ] {
            if !schema_object.contains_key(required) {
                return Err(format!(
                    "stored record schema {name} lacks required keyword {required}"
                ));
            }
        }
        if schema_object["$schema"] != "https://json-schema.org/draft/2020-12/schema"
            || schema_object["$id"] != format!("urn:documentation-maintenance:{name}")
            || schema_object["title"] != name.as_str()
            || schema_object["additionalProperties"] != false
            || schema_object["type"] != "object"
            || jsonschema::validator_for(schema).is_err()
        {
            return Err(format!(
                "stored record schema {name} is not a closed valid Draft 2020-12 JSON Schema"
            ));
        }
        validate_schema_closure(schema, name, "$")?;
    }
    Ok(())
}

fn validate_doctrine_shapes(value: &Value) -> Result<(), String> {
    let doctrine = value["doctrine"]
        .as_object()
        .ok_or("doctrine contract must be an object")?;
    if doctrine.keys().map(String::as_str).collect::<BTreeSet<_>>()
        != ["packs", "case_tuple_fields", "clauses"]
            .into_iter()
            .collect()
    {
        return Err("doctrine contract has missing or unknown fields".into());
    }
    let packs = doctrine["packs"]
        .as_array()
        .ok_or("doctrine packs must be an array")?;
    if packs.is_empty() {
        return Err("doctrine packs must not be empty".into());
    }
    for pack in packs {
        serde_json::from_value::<crate::doctrine::DoctrinePack>(pack.clone())
            .map_err(|error| format!("closed doctrine pack violation: {error}"))?;
    }
    let clauses = doctrine["clauses"]
        .as_array()
        .ok_or("doctrine clauses must be an array")?;
    if clauses.is_empty() {
        return Err("doctrine clauses must not be empty".into());
    }
    for clause in clauses {
        let mut expanded = clause.clone();
        let examples = expanded["examples"]
            .as_array_mut()
            .ok_or("doctrine examples must be an array")?;
        let mut classes = BTreeSet::new();
        for example in examples {
            if let Some(class) = example
                .as_array()
                .and_then(|tuple| tuple.first())
                .and_then(Value::as_str)
            {
                classes.insert(class.to_string());
            }
            let tuple = example
                .as_array()
                .filter(|tuple| tuple.len() == 7)
                .ok_or("doctrine case must follow exact seven-field tuple encoding")?;
            *example = json!({
                "class":tuple[0],"input":tuple[1],"expected_outcome":tuple[2],
                "normalized_verdict":tuple[3],"affected_subject":tuple[4],
                "deciding_evidence":tuple[5],"controlling_reason":tuple[6]
            });
        }
        if classes
            != ["good", "bad", "borderline", "out-of-scope"]
                .into_iter()
                .map(str::to_string)
                .collect()
        {
            return Err(
                "every doctrine clause requires good, bad, borderline, and out-of-scope cases"
                    .into(),
            );
        }
        serde_json::from_value::<crate::doctrine::DoctrineClause>(expanded)
            .map_err(|error| format!("closed doctrine clause violation: {error}"))?;
    }
    Ok(())
}

fn validate_policy_case_shapes(value: &Value) -> Result<(), String> {
    fn decode_cases(cases: &Value, subject: &str) -> Result<Vec<PolicyCase>, String> {
        cases
            .as_array()
            .ok_or_else(|| format!("{subject} examples must be an array"))?
            .iter()
            .map(|case| {
                serde_json::from_value::<PolicyCase>(case.clone())
                    .map_err(|error| format!("{subject} case is not closed: {error}"))
            })
            .collect()
    }

    for contract in value["profile"]["contracts"]
        .as_array()
        .ok_or("profile contracts must be an array")?
    {
        decode_cases(&contract["claim_examples"], "claim")?;
        for clause in contract["clauses"]
            .as_array()
            .ok_or("role clauses must be an array")?
        {
            decode_cases(&clause["examples"], "role")?;
        }
    }
    let tuple_fields = value["doctrine"]["case_tuple_fields"]
        .as_array()
        .ok_or("doctrine case tuple fields must be an array")?;
    let expected_tuple_fields = [
        "class",
        "input",
        "accepted_mapping",
        "normalized_verdict",
        "affected_subject",
        "deciding_evidence",
        "controlling_reason",
    ];
    if tuple_fields
        .iter()
        .map(Value::as_str)
        .collect::<Option<Vec<_>>>()
        .as_deref()
        != Some(expected_tuple_fields.as_slice())
    {
        return Err("doctrine case tuple field contract is unsupported".into());
    }
    for clause in value["doctrine"]["clauses"]
        .as_array()
        .ok_or("doctrine clauses must be an array")?
    {
        let id = clause["id"]
            .as_str()
            .ok_or("doctrine clause requires an id")?;
        for case in clause["examples"]
            .as_array()
            .ok_or("doctrine examples must be an array")?
        {
            let tuple = case
                .as_array()
                .filter(|tuple| tuple.len() == 7)
                .ok_or("doctrine case must follow exact seven-field tuple encoding")?;
            for (index, field) in tuple.iter().enumerate() {
                if index == 3 {
                    if !field.is_string() {
                        return Err("doctrine normalized verdict must be a string".into());
                    }
                } else if field.as_str().is_none_or(str::is_empty) {
                    return Err("doctrine case tuple strings must be non-empty".into());
                }
            }
            let normalized = tuple[3].as_str().expect("checked normalized verdict");
            let expected_reason = format!("doctrine.{}.{normalized}", id.to_ascii_lowercase());
            if tuple[6] != expected_reason {
                return Err(format!(
                    "doctrine case normalized verdict and reason disagree for {id}"
                ));
            }
        }
    }
    Ok(())
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ModelSpec {
    provider: String,
    model: String,
    model_id: String,
    role: String,
    source: String,
    provenance: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DecodingParameters {
    temperature: f64,
    top_p: f64,
    max_output_tokens: u64,
    reasoning_effort: String,
    seed: Option<u64>,
    stop: Vec<String>,
    response_format: String,
    tool_choice: String,
    parallel_tool_calls: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct EvaluatorIdentity {
    schema: String,
    production_judge: ModelSpec,
    focused_adjudicator: ModelSpec,
    decoding_parameters: DecodingParameters,
    model_identity_digest: String,
    decoding_parameter_digest: String,
    qualification_status: String,
    qualification_tuple_fields: Vec<String>,
    production_use_gate: String,
    invalidation: String,
}

fn validate_evaluator_identity(value: &Value) -> Result<(), String> {
    let identity: EvaluatorIdentity = serde_json::from_value(value.clone())
        .map_err(|error| format!("closed evaluator identity violation: {error}"))?;
    if identity.schema != "evaluator-identity-v1" {
        return Err("unsupported evaluator identity schema".into());
    }
    let models = json!({
        "production_judge": identity.production_judge,
        "focused_adjudicator": identity.focused_adjudicator,
    });
    let model_digest = codec::sha256(&codec::canonicalize(&models)?);
    let parameters = serde_json::to_value(&identity.decoding_parameters)
        .map_err(|error| format!("encode decoding identity: {error}"))?;
    let parameter_digest = codec::sha256(&codec::canonicalize(&parameters)?);
    if identity.model_identity_digest != model_digest
        || identity.decoding_parameter_digest != parameter_digest
    {
        return Err("supported evaluator subordinate identity digest mismatch".into());
    }
    if identity.qualification_status != "unqualified_until_calibration"
        || identity.qualification_tuple_fields
            != [
                "bundle_digest",
                "model_identity_digest",
                "decoding_parameter_digest",
                "fixture_digest",
            ]
        || identity.production_use_gate != "P6 qualification is mandatory before any production judgment or focused adjudication"
    {
        return Err("evaluator qualification status or tuple fields are invalid".into());
    }
    if identity.invalidation.is_empty()
        || identity.production_judge.provider.is_empty()
        || identity.production_judge.model.is_empty()
        || identity.production_judge.model_id.is_empty()
        || identity.production_judge.role.is_empty()
        || identity.production_judge.source != "provider-compiled-phase-p2-identity"
        || identity.production_judge.provenance != "Implementation-selected closed identity; no prior owner selection or qualification is claimed."
        || identity.focused_adjudicator.provider.is_empty()
        || identity.focused_adjudicator.model.is_empty()
        || identity.focused_adjudicator.model_id.is_empty()
        || identity.focused_adjudicator.role.is_empty()
        || identity.focused_adjudicator.source != "provider-compiled-phase-p2-identity"
        || identity.focused_adjudicator.provenance != "Implementation-selected closed identity; no prior owner selection or qualification is claimed."
        || identity.decoding_parameters.temperature != 0.0
        || identity.decoding_parameters.top_p != 1.0
        || identity.decoding_parameters.max_output_tokens == 0
        || identity.decoding_parameters.reasoning_effort.is_empty()
        || identity.decoding_parameters.seed.is_some()
        || !identity.decoding_parameters.stop.is_empty()
        || identity.decoding_parameters.response_format != "closed-json-schema"
        || identity.decoding_parameters.tool_choice != "none"
        || identity.decoding_parameters.parallel_tool_calls
    {
        return Err("evaluator identity contains unsupported model or decoding values".into());
    }
    Ok(())
}

fn validate_reason_registry(value: &Value) -> Result<(), String> {
    let registry = value
        .get("reason_registry")
        .and_then(Value::as_array)
        .ok_or("reason registry must be an array")?;
    let registered = registry
        .iter()
        .map(|v| v.as_str().ok_or("reason registry entry must be string"))
        .collect::<Result<BTreeSet<_>, _>>()?;
    if registered.len() != registry.len() {
        return Err("reason registry entries must be unique".into());
    }
    for clause in value["doctrine"]["clauses"]
        .as_array()
        .ok_or("doctrine clauses must be an array")?
    {
        for case in clause["examples"]
            .as_array()
            .ok_or("doctrine examples must be an array")?
        {
            let reason = case
                .as_array()
                .and_then(|tuple| tuple.get(6))
                .and_then(Value::as_str)
                .ok_or("doctrine tuple controlling reason must be a string")?;
            if !registered.contains(reason) {
                return Err(format!("unknown doctrine case reason {reason}"));
            }
        }
    }
    fn inspect(value: &Value, registered: &BTreeSet<&str>) -> Result<(), String> {
        match value {
            Value::Object(map) => {
                for (key, child) in map {
                    if matches!(
                        key.as_str(),
                        "controlling_reason" | "reason" | "linked_reason"
                    ) {
                        let reason = child.as_str().ok_or("emitted reason must be string")?;
                        if !registered.contains(reason) {
                            return Err(format!("unknown emitted reason {reason}"));
                        }
                    }
                    if key == "reasons" || key == "stable_reasons" || key == "reason_ids" {
                        match child {
                            Value::Array(array) => {
                                for reason in array {
                                    let reason = reason.as_str().ok_or("reason must be string")?;
                                    if !registered.contains(reason) {
                                        return Err(format!("unknown emitted reason {reason}"));
                                    }
                                }
                            }
                            Value::Object(reasons) => {
                                for reason in reasons.values() {
                                    let reason = reason.as_str().ok_or("reason must be string")?;
                                    if !registered.contains(reason) {
                                        return Err(format!("unknown emitted reason {reason}"));
                                    }
                                }
                            }
                            _ => return Err("reasons must be array or object".into()),
                        }
                    }
                    inspect(child, registered)?;
                }
            }
            Value::Array(items) => {
                for item in items {
                    inspect(item, registered)?;
                }
            }
            _ => {}
        }
        Ok(())
    }
    for section in [
        "profile",
        "claim_policy",
        "judgment_policy",
        "doctrine",
        "recovery_policy",
    ] {
        inspect(
            value.get(section).ok_or("reason-bearing section missing")?,
            &registered,
        )?;
    }
    Ok(())
}

fn reason_registry() -> Vec<String> {
    let mut reasons = BTreeSet::new();
    if let Ok(profile) =
        DocumentContractRegistry::repository_core().resolve_profile("repository-core")
    {
        for contract in profile.contracts {
            reasons.extend(contract.reason_ids);
        }
    }
    for clause in doctrine::doctrine_clauses() {
        reasons.extend(clause.reasons);
    }
    for reason in [
        "claim.extracted.action-changing",
        "authority.binding-rule.weakened",
        "authority.binding-rule.deleted-or-relabelled",
        "authority.lower-source-cannot-establish-binding",
        "authority.aspiration-guarantee-laundering",
        "claim.adhered",
        "claim.drifted",
        "claim.breached",
        "claim.unverifiable",
        "claim.evaluation-error",
        "breach.binding-rule.confirmed",
        "breach.binding-rule.not-confirmed",
        "breach.binding-rule.unverifiable",
        "breach.adjudication.evaluation-error",
        "judgment.third.match",
        "judgment.incompatible",
        "recovery.evaluation.accepted",
        "recovery.evaluation.identity-mismatch",
        "recovery.evaluation.key-changed",
        "recovery.evaluation.inspection-missing",
        "recovery.evaluation.cause-missing",
        "recovery.evaluation.retry-condition-missing",
        "recovery.evaluation.authorization-missing",
        "recovery.evaluation.resampling-refused",
        "recovery.breach.accepted",
        "recovery.breach.identity-mismatch",
        "recovery.breach.identical-fingerprint",
        "recovery.breach.documentation-only",
        "recovery.breach.irrelevant-change",
        "recovery.breach.rule-weakened",
        "recovery.breach.reassessment-missing",
        "recovery.breach.still-confirmed",
    ] {
        reasons.insert(reason.to_string());
    }
    reasons.into_iter().collect()
}

fn claim_policy() -> Value {
    json!({
        "schema":"claim-authority-policy-v1",
        "claim_kinds":["identity","capability","prerequisite","limitation","command","path","permission","safety-boundary","binding-rule","expected-outcome","role-obligation","doctrine-proposal"],
        "source_units":"Deterministic Markdown blocks; action-changing propositions split semantically and identified by document/range/ordinal/proposition digest.",
        "claim_verdicts":["adhered","drifted","breached","unverifiable","evaluation_error"],
        "role_verdicts":["satisfied","deficient","unverifiable","evaluation_error"],
        "force_defaults":{"purpose":"descriptive-identity","tenet":"defeasible","invariant":"binding","boundary":"binding","non-goal":"binding","aspiration":"non-binding"},
        "force_rule":"Headings supply default force; exceptions must be explicit. Tenet deviations are drifted unless a documented competing trade-off supports adhered with tenet.tradeoff.accepted. Binding violations are breached. Missing evidence is unverifiable. Borderline is input class only and resolves to a closed verdict with deciding evidence. Doctrine out-of-scope is inapplicable and emits no claim verdict.",
        "material_change":["creation","meaning change","force change","scope change","rationale change","operational-effect change","breach-evidence change","governance change","classification change","binding-rule removal or weakening","tenet abandonment or force reduction"],
        "non_material_change":["semantic-neutral formatting","link repair without semantic change"],
        "authority_order":["docs/intent.md","AGENTS.md","README.md"],
        "authority_rule":"docs/intent.md is authoritative over AGENTS.md over README.md. Source, configuration, tests, lower-authority prose, and repository layout are evidence only and cannot establish, weaken, narrow, delete, relabel, or opportunistically remap binding intent.",
        "anti_laundering":["existing binding intent cannot be weakened, narrowed, deleted, or relabelled to excuse repository drift","existing aspiration cannot be presented as current guarantee","new binding intent cannot begin violated and remains aspiration until external remediation","mapping changes are material intent amendments","unverifiable action-changing claims are removed or narrowed to evidenced scope without unsupported replacement facts"],
        "revision_order":"Intent first; changed higher-authority bytes invalidate every dependent accepted draft or candidate.",
        "primary_reason":{"rule":"One repository fact yields one primary finding and stable reason; other effects are linked consequences, never duplicate remediation findings.","reason":"finding.one-fact.primary","linked_reason":"finding.linked-consequence"},
        "application_policy":{"approval_criteria":"Apply requires selected approved-bundle-v1 and selected nonrevoked owner-attestation-v1 for final-staged-bundle.","identity_criteria":"Approved owner_attestation_digest equals selected attestation digest; staged_manifest_digest equals attestation manifest_digest and proposed_digest; targets match exactly by path, digest, mode, and order.","application_criteria":"Application verification binds selected approved-bundle digest, reports exact true, and carries no mismatches. Provider never repairs caller worktree.","recovery_criteria":"Missing, revoked, stale, or inconsistent approval and any byte, mode, target, or non-target mismatch block completion and require gated restart at a new baseline."}
    })
}

fn judgment_policy() -> Value {
    let mut stable_reasons = vec![
        "claim.adhered".to_string(),
        "claim.drifted".to_string(),
        "claim.breached".to_string(),
        "claim.unverifiable".to_string(),
        "claim.evaluation-error".to_string(),
        "breach.binding-rule.confirmed".to_string(),
        "breach.binding-rule.not-confirmed".to_string(),
        "breach.binding-rule.unverifiable".to_string(),
        "breach.adjudication.evaluation-error".to_string(),
        "judgment.third.match".to_string(),
        "judgment.incompatible".to_string(),
        "finding.one-fact.primary".to_string(),
        "finding.linked-consequence".to_string(),
        "tenet.tradeoff.accepted".to_string(),
    ];
    for contract in DocumentContractRegistry::repository_core()
        .resolve_profile("repository-core")
        .expect("compiled repository-core profile resolves")
        .contracts
    {
        for clause in contract.clauses {
            stable_reasons.extend([
                clause.reasons.satisfied,
                clause.reasons.deficient,
                clause.reasons.unverifiable,
                clause.reasons.out_of_scope,
            ]);
        }
    }
    stable_reasons.sort();
    stable_reasons.dedup();
    json!({
        "schema":"judgment-policy-v1",
        "claim_outputs":["adhered","drifted","breached","unverifiable","evaluation_error"],
        "role_outputs":["satisfied","deficient","unverifiable","evaluation_error"],
        "focused_breach_outputs":["breach_confirmed","breach_not_confirmed","unverifiable","evaluation_error"],
        "blindness":"Every subject gets two independent blind schema-valid judgments; judges see neither peers nor ambient context.",
        "direct_agreement":"Matching verdict and controlling reason resolve directly.",
        "ordinary_disagreement":"Disputed non-breach results invoke blind third judgment and resolve only when two valid outputs match verdict and controlling reason.",
        "breach_rule":"Any breach vote bypasses ordinary majority and invokes focused blind adjudication over exact binding rule, claim, cited evidence, and active manifest.",
        "breach_return":"breach_confirmed resolves breach; breach_not_confirmed returns to ordinary resolution only when compatible; incompatible, invalid, or unresolved prescribed results become evaluation_error.",
        "invalid_output":"Schema-invalid, unknown-reason, incompatible, or missing required output is evaluation_error, never content verdict.",
        "role_mapping":{"deficient":"revision_required","unverifiable":"revision_required","evaluation_error":"evaluation_error","satisfied":"non-blocking"},
        "disposition_priority":["evaluation_error","breach_confirmed","revision_required","clean"],
        "stable_reasons":stable_reasons
    })
}

fn recovery_case(class: &str, input: &str, outcome: &str, reason: &str, evidence: &str) -> Value {
    json!({"class":class,"input":input,"expected_outcome":outcome,"affected_subject":"recovery","deciding_evidence":evidence,"controlling_reason":reason})
}
fn recovery_policy() -> Value {
    json!({
        "schema":"recovery-policy-v1",
        "evaluation_recovery":{
            "schema":"evaluation-recovery-v1",
            "requires":["failed invocation or audit-report identity","unchanged evaluation key","inspected journal or report evidence identity","diagnosed cause","exactly one of non-empty changed retry condition or non-empty explicit transient-failure rationale","caller retry authorization"],
            "semantics":"Exactly one retry alternative is present: changed_retry_condition XOR transient_failure_rationale. Caller-attested procedural evidence is not proof inspection occurred. Unchanged semantic key replays existing result and cannot be resampled. Protocol evaluate_gates evaluation_error commits no transition or provider evidence and retry requires inline recovery record.",
            "reasons":["recovery.evaluation.accepted","recovery.evaluation.identity-mismatch","recovery.evaluation.key-changed","recovery.evaluation.inspection-missing","recovery.evaluation.cause-missing","recovery.evaluation.retry-condition-missing","recovery.evaluation.authorization-missing","recovery.evaluation.resampling-refused"],
            "examples":[
                recovery_case("good","Recovery binds failed identity and unchanged key, cites inspected report, diagnoses schema timeout, records corrected service condition, and carries caller authorization.","accepted","recovery.evaluation.accepted","all required identities and changed retry condition are present"),
                recovery_case("bad","Recovery names a different failed invocation than the committed evaluation error.","refused","recovery.evaluation.identity-mismatch","failed invocation or audit-report identity is not exact"),
                recovery_case("bad","Recovery changes the manifest, subject, bundle, model, decoding, or evidence identity in the evaluation key.","refused","recovery.evaluation.key-changed","retry cannot substitute a different semantic evaluation key"),
                recovery_case("bad","Recovery carries no inspected journal or report evidence digest.","refused","recovery.evaluation.inspection-missing","caller assertion is not proof that cited evaluator evidence was inspected"),
                recovery_case("bad","Recovery leaves diagnosed cause empty or absent.","refused","recovery.evaluation.cause-missing","retry requires a non-empty diagnosis tied to inspected evidence"),
                recovery_case("bad","Recovery supplies neither changed retry condition nor transient-failure rationale.","refused","recovery.evaluation.retry-condition-missing","exactly one non-empty retry alternative is required"),
                recovery_case("bad","Recovery is otherwise complete but caller retry authorization is missing or false.","refused","recovery.evaluation.authorization-missing","provider cannot authorize its own retry"),
                recovery_case("bad","Caller asks for another sample under identical key without cause or changed condition.","refused","recovery.evaluation.resampling-refused","unchanged-key resampling would bypass deterministic replay"),
                recovery_case("borderline","Transient provider outage is attested with unchanged key and authorization but no changed filesystem fact.","accepted","recovery.evaluation.accepted","explicit transient-failure rationale is permitted instead of changed condition"),
                recovery_case("out-of-scope","Content disagreement is presented as evaluator recovery.","refused","recovery.evaluation.cause-missing","semantic content disagreement follows judgment/adjudication, not recovery")
            ]
        },
        "breach_remediation":{
            "schema":"breach-remediation-v1",
            "requires":["prior breach identity","exact binding-rule semantic identity, force, and binding scope","cited breach evidence","old manifest","new manifest","at least one relevant changed non-core path","unchanged/unweakened prior rule","reassessment scope fixed to whole-repository","reassessment manifest bound to new manifest","reassessment rule identity equal to exact prior rule"],
            "semantics":"Binding scope and whole-repository reassessment are explicit record fields. Identical fingerprint, documentation-only change, weakened or remapped rule, mismatched reassessment binding, and residual confirmed breach are refused. Drafting, approval, application, and completion remain blocked until new whole-repository audit no longer confirms breach.",
            "reasons":["recovery.breach.accepted","recovery.breach.identity-mismatch","recovery.breach.identical-fingerprint","recovery.breach.documentation-only","recovery.breach.irrelevant-change","recovery.breach.rule-weakened","recovery.breach.reassessment-missing","recovery.breach.still-confirmed"],
            "examples":[
                recovery_case("good","Prior inner-to-outer breach is bound; source dependency changes outside core documents; rule is byte-semantically unweakened; new complete manifest is queued for whole audit.","accepted","recovery.breach.accepted","relevant non-core remediation and exact-rule reassessment are bound"),
                recovery_case("bad","Remediation record names a different prior breach, binding rule, force, scope, or evidence identity.","refused","recovery.breach.identity-mismatch","prior breach and exact binding authority must remain identical"),
                recovery_case("bad","Old and new repository fingerprints are identical.","refused","recovery.breach.identical-fingerprint","unchanged repository cannot establish external remediation"),
                recovery_case("bad","Only README, AGENTS, or docs/intent bytes changed.","refused","recovery.breach.documentation-only","documentation cannot remediate confirmed repository breach"),
                recovery_case("bad","Changed non-core paths have no established relation to cited breach evidence.","refused","recovery.breach.irrelevant-change","a path change alone is not remediation evidence"),
                recovery_case("bad","Intent wording is weakened so existing dependency no longer appears forbidden.","refused","recovery.breach.rule-weakened","documentation cannot remediate implementation breach"),
                recovery_case("bad","Reassessment is limited to changed paths or is not bound to new manifest and exact prior rule.","refused","recovery.breach.reassessment-missing","whole-repository reassessment identity is mandatory"),
                recovery_case("bad","Whole-repository reassessment still confirms the exact prior breach.","refused","recovery.breach.still-confirmed","drafting and completion remain blocked while breach persists"),
                recovery_case("borderline","Non-core file changed but relevance to cited breach is not established.","refused","recovery.breach.irrelevant-change","path change alone does not prove remediation relevance"),
                recovery_case("out-of-scope","README typo is offered as binding-breach remediation.","refused","recovery.breach.documentation-only","core-document-only change is outside breach remediation")
            ]
        }
    })
}

fn evaluator_identity() -> Value {
    let models = json!({
        "production_judge":{"provider":"openai-codex","model":"gpt-5.6-sol","model_id":"openai-codex/gpt-5.6-sol","role":"blind-claim-and-role-judge","source":"provider-compiled-phase-p2-identity","provenance":"Implementation-selected closed identity; no prior owner selection or qualification is claimed."},
        "focused_adjudicator":{"provider":"openai-codex","model":"gpt-5.6-sol","model_id":"openai-codex/gpt-5.6-sol","role":"blind-focused-breach-adjudicator","source":"provider-compiled-phase-p2-identity","provenance":"Implementation-selected closed identity; no prior owner selection or qualification is claimed."}
    });
    let parameters = json!({"temperature":0.0,"top_p":1.0,"max_output_tokens":16384,"reasoning_effort":"high","seed":null,"stop":[],"response_format":"closed-json-schema","tool_choice":"none","parallel_tool_calls":false});
    let model_identity_digest = codec::sha256(
        &codec::canonicalize(&models).expect("compiled evaluator model identity is canonical"),
    );
    let decoding_parameter_digest = codec::sha256(
        &codec::canonicalize(&parameters)
            .expect("compiled evaluator decoding parameters are canonical"),
    );
    json!({
        "schema":"evaluator-identity-v1",
        "production_judge":models["production_judge"],
        "focused_adjudicator":models["focused_adjudicator"],
        "decoding_parameters":parameters,
        "model_identity_digest":model_identity_digest,
        "decoding_parameter_digest":decoding_parameter_digest,
        "qualification_status":"unqualified_until_calibration",
        "qualification_tuple_fields":["bundle_digest","model_identity_digest","decoding_parameter_digest","fixture_digest"],
        "production_use_gate":"P6 qualification is mandatory before any production judgment or focused adjudication",
        "invalidation":"Any model, decoding parameter, criterion, example, mapping, or schema byte change creates a new unqualified tuple."
    })
}

pub fn human_contract(bundle: &FrozenBundle) -> Result<String, String> {
    let exact = String::from_utf8(bundle.canonical_bytes.clone()).map_err(|e| e.to_string())?;
    Ok(format!("DOCUMENTATION AUDIT CONTRACT {BUNDLE_VERSION}\nCanonical bundle digest: {}\nThe canonical JSON below is the complete exact human-readable machine contract. Judgment criteria are its stored strings; do not paraphrase them.\n\n{exact}",bundle.digest))
}

pub fn metadata_depth(value: &Value) -> usize {
    match value {
        Value::Object(map) => 1 + map.values().map(metadata_depth).max().unwrap_or(0),
        Value::Array(values) => values.iter().map(metadata_depth).max().unwrap_or(0),
        _ => 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bundle_is_complete_canonical_bounded_and_digest_stable() {
        let a = build_bundle().unwrap();
        let b = build_bundle().unwrap();
        assert_eq!(a.canonical_bytes, b.canonical_bytes);
        assert_eq!(a.digest, b.digest);
        assert_eq!(
            a.digest,
            "sha256:f303acba7c284a997b36c2973434ca4468dd2708064e870ff6ccda96d63a68be"
        );
        assert!(a.canonical_bytes.len() <= MACHINE_BUNDLE_MAX_BYTES);
        assert!(metadata_depth(&a.value) <= METADATA_MAX_DEPTH);
        let human = human_contract(&a).unwrap();
        assert!(human.len() <= AUDIT_GUIDANCE_MAX_BYTES);
        assert!(human.contains(&a.digest));
        for k in [
            "claim_policy",
            "judgment_policy",
            "doctrine",
            "recovery_policy",
            "evaluator_identity",
            "record_schemas",
        ] {
            assert!(a.value.get(k).is_some());
        }
    }
    #[test]
    fn model_identity_is_explicit_unqualified_and_changes_qualification_identity() {
        let a = build_bundle().unwrap();
        assert_eq!(
            a.value["evaluator_identity"]["qualification_status"],
            "unqualified_until_calibration"
        );
        assert_eq!(
            a.value["evaluator_identity"]["production_judge"]["source"],
            "provider-compiled-phase-p2-identity"
        );
        assert!(
            a.value["evaluator_identity"]["production_judge"]["provenance"]
                .as_str()
                .unwrap()
                .contains("no prior owner selection")
        );
        assert!(a.value["evaluator_identity"]["production_use_gate"]
            .as_str()
            .unwrap()
            .contains("P6 qualification is mandatory"));
        let mut changed = a.value.clone();
        if let Some(value) =
            changed.pointer_mut("/evaluator_identity/decoding_parameters/temperature")
        {
            *value = json!(0.1);
        }
        assert_ne!(
            codec::sha256(&codec::canonicalize(&changed).unwrap()),
            a.digest
        );
    }
    #[test]
    fn stored_decoder_distinguishes_unsupported_from_supported_corruption() {
        let b = build_bundle().unwrap();
        let graph = json!({"metadata":{"documentation_audit_bundle_v1":b.value,"documentation_audit_bundle_digest":b.digest}});
        assert!(decode_stored_bundle(&graph).is_ok());
        let unsupported = json!({"metadata":{"documentation_audit_bundle_v1":{"schema":"v2"}}});
        assert!(matches!(
            decode_stored_bundle(&unsupported),
            Err(BundleDecodeError::Unsupported(_))
        ));
        let mut corrupt = graph;
        corrupt["metadata"]["documentation_audit_bundle_digest"] =
            json!("sha256:0000000000000000000000000000000000000000000000000000000000000000");
        assert!(matches!(
            decode_stored_bundle(&corrupt),
            Err(BundleDecodeError::Execution(_))
        ));
    }
    #[test]
    fn supported_run_frozen_criteria_do_not_depend_on_current_compiled_values() {
        let mut value = build_bundle().unwrap().value;
        value["profile"]["contracts"][0]["clauses"][0]["obligation"] =
            json!("Earlier supported run-frozen RI1 obligation bytes.");
        value["section_digests"] = section_digests(&value).unwrap();
        let digest = codec::sha256(&codec::canonicalize(&value).unwrap());
        let stored = json!({"metadata":{
            "documentation_audit_bundle_v1":value,
            "documentation_audit_bundle_digest":digest
        }});
        let decoded = decode_stored_bundle(&stored).unwrap();
        assert_eq!(
            decoded.value["profile"]["contracts"][0]["clauses"][0]["obligation"],
            "Earlier supported run-frozen RI1 obligation bytes."
        );
    }

    #[test]
    fn supported_bundle_is_closed_at_every_nested_contract_surface() {
        fn resign(mut value: Value) -> Value {
            value["section_digests"] = section_digests(&value).unwrap();
            let digest = codec::sha256(&codec::canonicalize(&value).unwrap());
            json!({"metadata":{"documentation_audit_bundle_v1":value,"documentation_audit_bundle_digest":digest}})
        }
        let base = build_bundle().unwrap().value;
        type BundleMutation = Box<dyn Fn(&mut Value)>;
        let mutations: Vec<BundleMutation> = vec![
            Box::new(|v| {
                v.as_object_mut()
                    .unwrap()
                    .insert("unknown".into(), json!(true));
            }),
            Box::new(|v| {
                v["profile"]["contracts"][0]
                    .as_object_mut()
                    .unwrap()
                    .insert("unknown".into(), json!(true));
            }),
            Box::new(|v| {
                v["profile"]["contracts"][0]["clauses"][0]["examples"][0]
                    .as_object_mut()
                    .unwrap()
                    .insert("unknown".into(), json!(true));
            }),
            Box::new(|v| {
                v["record_schemas"]["audit-report-v1"] = json!(true);
            }),
            Box::new(|v| {
                v["record_schemas"]["audit-report-v1"] = json!({});
            }),
            Box::new(|v| {
                v["doctrine"]["packs"] = json!([]);
            }),
            Box::new(|v| {
                v["doctrine"]["clauses"] = json!([]);
            }),
            Box::new(|v| {
                v["recovery_policy"]["evaluation_recovery"]["examples"] = json!([]);
            }),
            Box::new(|v| {
                v["recovery_policy"]["breach_remediation"]["examples"] = json!([]);
            }),
            Box::new(|v| {
                v["claim_policy"]["schema"] = json!(false);
            }),
            Box::new(|v| {
                v["claim_policy"]["force_defaults"]["tenet"] = json!(false);
            }),
            Box::new(|v| {
                v["judgment_policy"]["blindness"] = Value::Null;
            }),
            Box::new(|v| {
                v["judgment_policy"]["role_mapping"]["deficient"] = json!(false);
            }),
            Box::new(|v| {
                v["recovery_policy"]["evaluation_recovery"]["schema"] = json!("other-v1");
            }),
            Box::new(|v| {
                v["record_schemas"]["audit-report-v1"]["properties"]["findings"]["items"]
                    ["additionalProperties"] = json!(true);
            }),
            Box::new(|v| {
                v["record_schemas"]["audit-report-v1"]["properties"]["findings"]["items"]["type"] =
                    json!(["object"]);
                v["record_schemas"]["audit-report-v1"]["properties"]["findings"]["items"]
                    ["additionalProperties"] = json!(true);
            }),
            Box::new(|v| {
                v["evaluator_identity"]["production_judge"]
                    .as_object_mut()
                    .unwrap()
                    .insert("unknown".into(), json!(true));
            }),
            Box::new(|v| {
                v["evaluator_identity"]["decoding_parameters"]["temperature"] = json!(0.1);
            }),
            Box::new(|v| {
                v["recovery_policy"]["evaluation_recovery"]
                    .as_object_mut()
                    .unwrap()
                    .insert("unknown".into(), json!(true));
            }),
            Box::new(|v| {
                v["profile"]["contracts"][0]["clauses"][0]["examples"][0]["controlling_reason"] =
                    json!("unknown.reason");
            }),
            Box::new(|v| {
                v["doctrine"]["clauses"][0]["examples"][1][3] = json!("adhered");
            }),
            Box::new(|v| {
                v["doctrine"]["clauses"][0]["examples"][0]
                    .as_array_mut()
                    .unwrap()
                    .pop();
            }),
        ];
        for (index, mutate) in mutations.into_iter().enumerate() {
            let mut value = base.clone();
            mutate(&mut value);
            assert!(
                matches!(
                    decode_stored_bundle(&resign(value)),
                    Err(BundleDecodeError::Execution(_))
                ),
                "mutation {index} was accepted"
            );
        }
        let mut subordinate = base;
        subordinate["section_digests"]["profile"] = json!(format!("sha256:{}", "0".repeat(64)));
        let digest = codec::sha256(&codec::canonicalize(&subordinate).unwrap());
        let graph = json!({"metadata":{"documentation_audit_bundle_v1":subordinate,"documentation_audit_bundle_digest":digest}});
        assert!(matches!(
            decode_stored_bundle(&graph),
            Err(BundleDecodeError::Execution(_))
        ));
    }

    #[test]
    fn unsupported_version_precedes_nested_validation() {
        let deeply_malformed = json!({"metadata":{"documentation_audit_bundle_v1":{"schema":"documentation-audit-bundle-v2","profile":{"unknown":{"nested":{"far":true}}}}}});
        assert!(matches!(
            decode_stored_bundle(&deeply_malformed),
            Err(BundleDecodeError::Unsupported(_))
        ));
    }

    #[test]
    fn recovery_examples_cover_exact_inventory_classes_and_every_reason() {
        let b = build_bundle().unwrap();
        let evaluation = b
            .value
            .pointer("/recovery_policy/evaluation_recovery/examples")
            .unwrap()
            .as_array()
            .unwrap();
        let breach = b
            .value
            .pointer("/recovery_policy/breach_remediation/examples")
            .unwrap()
            .as_array()
            .unwrap();
        assert_eq!(evaluation.len(), 10);
        assert_eq!(breach.len(), 10);
        for cases in [evaluation, breach] {
            let classes = cases
                .iter()
                .map(|case| case["class"].as_str().unwrap())
                .collect::<BTreeSet<_>>();
            assert_eq!(
                classes,
                BTreeSet::from(["good", "bad", "borderline", "out-of-scope"])
            );
        }
        for reason in b.value["recovery_policy"]["evaluation_recovery"]["reasons"]
            .as_array()
            .unwrap()
            .iter()
            .chain(
                b.value["recovery_policy"]["breach_remediation"]["reasons"]
                    .as_array()
                    .unwrap(),
            )
        {
            assert!(
                evaluation
                    .iter()
                    .chain(breach)
                    .any(|case| { case["controlling_reason"].as_str() == reason.as_str() }),
                "missing recovery case for {reason}"
            );
        }
    }

    #[test]
    fn generic_role_reasons_are_absent_and_every_emitted_reason_is_registered() {
        let b = build_bundle().unwrap();
        let registry = b.value["reason_registry"]
            .as_array()
            .unwrap()
            .iter()
            .map(|reason| reason.as_str().unwrap())
            .collect::<BTreeSet<_>>();
        assert!(registry.iter().all(|reason| !matches!(
            *reason,
            "role.satisfied" | "role.deficient" | "role.unverifiable" | "role.evaluation-error"
        )));
        let stable = b.value["judgment_policy"]["stable_reasons"]
            .as_array()
            .unwrap()
            .iter()
            .map(|reason| reason.as_str().unwrap())
            .collect::<BTreeSet<_>>();
        assert!(stable.contains("role.r1.satisfied"));
        assert!(stable.contains("role.ri8.out-of-scope"));
        assert!(stable.iter().all(|reason| registry.contains(reason)));
        validate_reason_registry(&b.value).unwrap();
    }
}
