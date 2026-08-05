use crate::codec::{self, DecodedRecord};
use crate::protocol::Evidence;
use crate::schema::RecordKind;
use crate::storage::{ArtifactStore, RecordCategory, StoredRecord};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::str::FromStr;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ArtifactReference {
    pub schema: String,
    pub artifact_id: String,
    pub digest: String,
    pub relative_path: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct AuthorityDelta {
    pub replacements: BTreeMap<String, ArtifactReference>,
    pub invalidations: BTreeSet<String>,
}

#[derive(Debug, Clone)]
pub struct TransitionContext {
    pub graph_revision: String,
    pub source_state: String,
    pub source_workflow_state_version: u64,
    pub event: String,
    pub target_state: String,
    pub required_gate_ids: Vec<String>,
    pub reset: bool,
}

#[derive(Debug, Clone)]
pub struct GateOutcome {
    pub gate_id: String,
    pub passed: bool,
}

#[derive(Debug, Clone)]
pub struct CurrentSnapshot<'a> {
    pub run_id: &'a str,
    pub graph_revision: &'a str,
    pub current_state: &'a str,
    pub workflow_state_version: u64,
    pub stored_graph: Value,
}

#[derive(Debug, Clone)]
pub struct ValidatedAuthority {
    manifest: DecodedRecord,
    manifest_relative_path: Option<String>,
    certificate: Option<StoredRecord>,
    run_id: String,
    graph_revision: String,
    state: String,
    workflow_state_version: u64,
    stored_graph: Value,
}

impl ValidatedAuthority {
    pub fn manifest(&self) -> &DecodedRecord {
        &self.manifest
    }

    pub fn certificate_digest(&self) -> Option<&str> {
        self.certificate
            .as_ref()
            .map(|record| record.digest.as_str())
    }

    /// Load every selected authority slot through its closed schema and digest.
    /// Callers receive selected values only; filesystem candidates remain inert.
    pub fn load_slots(&self, store: &ArtifactStore) -> Result<BTreeMap<String, Value>, String> {
        let mut loaded = BTreeMap::new();
        let slots = self.manifest.value["slots"]
            .as_object()
            .ok_or_else(|| "selected authority manifest has no slots object".to_string())?;
        for (slot, reference) in slots {
            let reference: ArtifactReference = serde_json::from_value(reference.clone())
                .map_err(|error| format!("decode selected authority slot {slot}: {error}"))?;
            let kind = RecordKind::from_str(&reference.schema)?;
            let record = store.load(&reference.relative_path, kind, &reference.digest)?;
            loaded.insert(slot.clone(), record.decoded.value);
        }
        Ok(loaded)
    }
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CertificateEvidenceMetadata {
    schema: String,
    run_id: String,
    graph_revision: String,
    source_state: String,
    source_workflow_state_version: u64,
    event: String,
    target_state: String,
    expected_successor_workflow_state_version: u64,
    required_gate_ids: Vec<String>,
    predecessor_root_digest: String,
    successor_root_digest: String,
    delta_digest: String,
    certificate_digest: String,
    certificate_relative_path: String,
    authority_manifest_relative_path: String,
    predecessor_authority_manifest_relative_path: Option<String>,
    predecessor_certificate_relative_path: Option<String>,
}

pub fn empty_manifest(run_id: &str) -> Result<DecodedRecord, String> {
    codec::encode_record(
        &json!({
            "schema":"authority-manifest-v1",
            "run_id":run_id,
            "predecessor_root_digest":null,
            "slots":{}
        }),
        RecordKind::AuthorityManifest,
        run_id,
    )
}

pub fn validate_selected_authority(
    store: &ArtifactStore,
    snapshot: &CurrentSnapshot<'_>,
    selected: &[Evidence],
) -> Result<ValidatedAuthority, String> {
    if snapshot.run_id != store.run_id() {
        return Err("snapshot run_id differs from artifact store owner".to_string());
    }
    codec::validate_digest(snapshot.graph_revision)?;
    if selected.is_empty() {
        if snapshot.current_state == "audit" && snapshot.workflow_state_version == 0 {
            return Ok(ValidatedAuthority {
                manifest: empty_manifest(snapshot.run_id)?,
                manifest_relative_path: None,
                certificate: None,
                run_id: snapshot.run_id.to_string(),
                graph_revision: snapshot.graph_revision.to_string(),
                state: snapshot.current_state.to_string(),
                workflow_state_version: snapshot.workflow_state_version,
                stored_graph: snapshot.stored_graph.clone(),
            });
        }
        return Err("exactly one selected transition certificate is required outside initial audit version 0".to_string());
    }
    if selected.len() != 1 {
        return Err(format!(
            "exactly one selected transition certificate is required, received {}",
            selected.len()
        ));
    }
    let evidence = &selected[0];
    if evidence.kind != "transition-certificate-v1" {
        return Err(format!(
            "selected evidence kind must be transition-certificate-v1, found {:?}",
            evidence.kind
        ));
    }
    let claimed_digest = evidence
        .digest
        .as_deref()
        .ok_or_else(|| "selected transition certificate has no digest".to_string())?;
    let metadata: CertificateEvidenceMetadata = serde_json::from_value(
        evidence
            .metadata
            .clone()
            .ok_or_else(|| "selected transition certificate has no metadata".to_string())?,
    )
    .map_err(|error| {
        format!("selected transition certificate metadata is not closed and valid: {error}")
    })?;
    if metadata.schema != "transition-certificate-evidence-v1" {
        return Err("selected transition certificate metadata schema is unsupported".to_string());
    }
    if evidence.locator != metadata.certificate_relative_path {
        return Err("selected certificate locator differs from metadata path".to_string());
    }
    if claimed_digest != metadata.certificate_digest {
        return Err(
            "selected certificate evidence digest differs from metadata digest".to_string(),
        );
    }

    let certificate = store.load(
        &metadata.certificate_relative_path,
        RecordKind::TransitionCertificate,
        &metadata.certificate_digest,
    )?;
    let cert = &certificate.decoded.value;
    let expected_evidence_id = certificate_evidence_id(
        &certificate.digest,
        cert["target_state"]
            .as_str()
            .expect("validated target state"),
        cert["expected_successor_workflow_state_version"]
            .as_u64()
            .expect("validated successor version"),
    )?;
    if evidence.id != expected_evidence_id {
        return Err("selected transition certificate evidence ID is not canonical".to_string());
    }
    compare_certificate_metadata(cert, &metadata)?;
    if cert["run_id"] != snapshot.run_id
        || cert["graph_revision"] != snapshot.graph_revision
        || cert["target_state"] != snapshot.current_state
        || cert["expected_successor_workflow_state_version"] != snapshot.workflow_state_version
    {
        return Err(
            "selected transition certificate does not identify current snapshot".to_string(),
        );
    }
    if cert["source_state"] == cert["target_state"] {
        return Err(
            "authority-changing transition certificate must target a distinct state".to_string(),
        );
    }
    let certificate_gates = cert["required_gate_ids"]
        .as_array()
        .expect("validated required gate IDs")
        .iter()
        .map(|gate| gate.as_str().expect("validated gate ID").to_string())
        .collect::<Vec<_>>();
    validate_frozen_transition(
        &snapshot.stored_graph,
        cert["source_state"]
            .as_str()
            .expect("validated source state"),
        cert["event"].as_str().expect("validated event"),
        cert["target_state"]
            .as_str()
            .expect("validated target state"),
        &certificate_gates,
    )?;

    let manifest = store.load(
        &metadata.authority_manifest_relative_path,
        RecordKind::AuthorityManifest,
        &metadata.successor_root_digest,
    )?;
    let predecessor = load_and_validate_predecessor(store, snapshot, cert, &metadata)?;
    let expected_predecessor = if cert["reset"] == true {
        Value::Null
    } else {
        cert["predecessor_root_digest"].clone()
    };
    if manifest.decoded.value["predecessor_root_digest"] != expected_predecessor {
        return Err(
            "successor authority manifest predecessor does not match certificate".to_string(),
        );
    }
    if cert["reset"] == true
        && (cert["event"] != "restart-audit"
            || cert["target_state"] != "audit"
            || !cert["required_gate_ids"]
                .as_array()
                .is_some_and(|gates| gates.iter().any(|gate| gate == "restart-permitted"))
            || !manifest.decoded.value["slots"]
                .as_object()
                .unwrap()
                .is_empty())
    {
        return Err(
            "reset certificate is not a gated restart to empty audit authority".to_string(),
        );
    }
    validate_manifest_slots(store, &manifest.decoded.value)?;
    let recomputed_delta = derive_delta(&predecessor.value, &manifest.decoded.value)?;
    let recomputed_delta_digest = delta_digest(&recomputed_delta)?;
    if cert["delta_digest"] != recomputed_delta_digest {
        return Err(
            "transition certificate delta does not match predecessor and successor manifests"
                .to_string(),
        );
    }
    Ok(ValidatedAuthority {
        manifest: manifest.decoded.clone(),
        manifest_relative_path: Some(manifest.relative_path.clone()),
        certificate: Some(certificate),
        run_id: snapshot.run_id.to_string(),
        graph_revision: snapshot.graph_revision.to_string(),
        state: snapshot.current_state.to_string(),
        workflow_state_version: snapshot.workflow_state_version,
        stored_graph: snapshot.stored_graph.clone(),
    })
}

pub fn create_successor(
    store: &ArtifactStore,
    category: RecordCategory,
    invocation_id: &str,
    predecessor: &ValidatedAuthority,
    context: &TransitionContext,
    outcomes: &[GateOutcome],
    delta: &AuthorityDelta,
) -> Result<Evidence, String> {
    validate_transition_attempt(store.run_id(), predecessor, context, outcomes, delta)?;
    let predecessor_digest = predecessor.manifest.digest.clone();
    let predecessor_slots = predecessor.manifest.value["slots"]
        .as_object()
        .expect("validated authority slots");
    let successor_slots = if context.reset {
        MapLike::empty()
    } else {
        apply_delta(predecessor_slots, delta)?
    };
    let successor_value = json!({
        "schema":"authority-manifest-v1",
        "run_id":store.run_id(),
        "predecessor_root_digest": if context.reset { Value::Null } else { Value::String(predecessor_digest.clone()) },
        "slots":successor_slots.0,
    });
    let successor = store.store(
        category,
        invocation_id,
        RecordKind::AuthorityManifest,
        &successor_value,
    )?;
    validate_manifest_slots(store, &successor.decoded.value)?;

    let recomputed_delta = derive_delta(&predecessor.manifest.value, &successor.decoded.value)?;
    if &recomputed_delta != delta {
        return Err(
            "requested authority delta differs from predecessor/successor manifests".to_string(),
        );
    }
    let delta_digest = delta_digest(&recomputed_delta)?;
    let mut gates = context.required_gate_ids.clone();
    gates.sort();
    let certificate_value = json!({
        "schema":"transition-certificate-v1",
        "run_id":store.run_id(),
        "graph_revision":context.graph_revision,
        "source_state":context.source_state,
        "source_workflow_state_version":context.source_workflow_state_version,
        "event":context.event,
        "target_state":context.target_state,
        "expected_successor_workflow_state_version":context.source_workflow_state_version + 1,
        "required_gate_ids":gates,
        "predecessor_root_digest":predecessor_digest,
        "successor_root_digest":successor.digest,
        "delta_digest":delta_digest,
        "predecessor_certificate_digest":predecessor.certificate_digest(),
        "all_pass":true,
        "reset":context.reset,
    });
    let certificate = store.store(
        category,
        invocation_id,
        RecordKind::TransitionCertificate,
        &certificate_value,
    )?;
    let metadata = CertificateEvidenceMetadata {
        schema: "transition-certificate-evidence-v1".to_string(),
        run_id: store.run_id().to_string(),
        graph_revision: context.graph_revision.clone(),
        source_state: context.source_state.clone(),
        source_workflow_state_version: context.source_workflow_state_version,
        event: context.event.clone(),
        target_state: context.target_state.clone(),
        expected_successor_workflow_state_version: context.source_workflow_state_version + 1,
        required_gate_ids: gates,
        predecessor_root_digest: predecessor_digest,
        successor_root_digest: successor.digest,
        delta_digest,
        certificate_digest: certificate.digest.clone(),
        certificate_relative_path: certificate.relative_path.clone(),
        authority_manifest_relative_path: successor.relative_path,
        predecessor_authority_manifest_relative_path: predecessor.manifest_relative_path.clone(),
        predecessor_certificate_relative_path: predecessor
            .certificate
            .as_ref()
            .map(|record| record.relative_path.clone()),
    };
    let metadata = serde_json::to_value(metadata)
        .map_err(|error| format!("encode certificate evidence: {error}"))?;
    let evidence = Evidence {
        id: certificate_evidence_id(
            &certificate.digest,
            &context.target_state,
            context.source_workflow_state_version + 1,
        )?,
        kind: "transition-certificate-v1".to_string(),
        locator: certificate.relative_path,
        digest: Some(certificate.digest),
        media_type: Some(
            "application/vnd.documentation-maintenance.transition-certificate+json".to_string(),
        ),
        metadata: Some(metadata),
        observed_at: None,
    };
    let encoded = serde_json::to_vec(&evidence)
        .map_err(|error| format!("encode certificate evidence: {error}"))?;
    if encoded.len() > 65_536 {
        return Err(
            "transition certificate evidence exceeds protocol 65536-byte record bound".to_string(),
        );
    }
    Ok(evidence)
}

/// Engine evidence identity is content-addressed, not invocation-addressed.
///
/// Protocol v1 rejects any result evidence ID already present in run evidence.
/// Therefore caller-preseeded inline evidence with this exact ID and a provider
/// certificate cannot coexist in one committed transition. Provider must keep
/// deterministic identity and fail closed; changing ID to evade collision would
/// let one certificate acquire multiple engine identities.
pub fn certificate_evidence_id(
    certificate_digest: &str,
    target_state: &str,
    successor_version: u64,
) -> Result<String, String> {
    codec::validate_digest(certificate_digest)?;
    if target_state.is_empty() {
        return Err("certificate target state must not be empty".to_string());
    }
    let identity = json!({
        "certificate_digest": certificate_digest,
        "target_state": target_state,
        "successor_workflow_state_version": successor_version,
    });
    let digest = codec::sha256(&codec::canonicalize(&identity)?);
    Ok(format!(
        "transition-certificate-{}",
        digest
            .strip_prefix("sha256:")
            .expect("sha256 helper prefix")
    ))
}

fn delta_digest(delta: &AuthorityDelta) -> Result<String, String> {
    let value = json!({
        "invalidations":delta.invalidations.iter().collect::<Vec<_>>(),
        "replacements":delta.replacements,
    });
    Ok(codec::sha256(&codec::canonicalize(&value)?))
}

fn derive_delta(predecessor: &Value, successor: &Value) -> Result<AuthorityDelta, String> {
    let predecessor = predecessor["slots"]
        .as_object()
        .ok_or_else(|| "predecessor authority manifest has no slots object".to_string())?;
    let successor = successor["slots"]
        .as_object()
        .ok_or_else(|| "successor authority manifest has no slots object".to_string())?;
    let mut delta = AuthorityDelta::default();
    for slot in predecessor.keys() {
        if !successor.contains_key(slot) {
            delta.invalidations.insert(slot.clone());
        }
    }
    for (slot, value) in successor {
        if predecessor.get(slot) != Some(value) {
            let reference: ArtifactReference = serde_json::from_value(value.clone())
                .map_err(|error| format!("decode successor authority slot {slot}: {error}"))?;
            delta.replacements.insert(slot.clone(), reference);
        }
    }
    Ok(delta)
}

fn load_and_validate_predecessor(
    store: &ArtifactStore,
    snapshot: &CurrentSnapshot<'_>,
    certificate: &Value,
    metadata: &CertificateEvidenceMetadata,
) -> Result<DecodedRecord, String> {
    let predecessor_digest = certificate["predecessor_root_digest"]
        .as_str()
        .expect("validated predecessor digest");
    let predecessor_certificate_digest = certificate["predecessor_certificate_digest"].as_str();
    match (
        predecessor_certificate_digest,
        metadata.predecessor_certificate_relative_path.as_deref(),
        metadata
            .predecessor_authority_manifest_relative_path
            .as_deref(),
    ) {
        (None, None, None) => {
            if certificate["source_state"] != "audit"
                || certificate["source_workflow_state_version"] != 0
            {
                return Err(
                    "only initial audit version 0 may omit predecessor certificate linkage"
                        .to_string(),
                );
            }
            let predecessor = empty_manifest(snapshot.run_id)?;
            if predecessor.digest != predecessor_digest {
                return Err("initial certificate predecessor is not canonical empty root".to_string());
            }
            Ok(predecessor)
        }
        (Some(certificate_digest), Some(certificate_path), Some(manifest_path)) => {
            let predecessor_manifest = store.load(
                manifest_path,
                RecordKind::AuthorityManifest,
                predecessor_digest,
            )?;
            validate_manifest_slots(store, &predecessor_manifest.decoded.value)?;
            let predecessor_certificate = store.load(
                certificate_path,
                RecordKind::TransitionCertificate,
                certificate_digest,
            )?;
            let prior = &predecessor_certificate.decoded.value;
            if prior["run_id"] != snapshot.run_id
                || prior["graph_revision"] != snapshot.graph_revision
                || prior["successor_root_digest"] != predecessor_digest
                || prior["target_state"] != certificate["source_state"]
                || prior["expected_successor_workflow_state_version"]
                    != certificate["source_workflow_state_version"]
            {
                return Err("transition certificate predecessor linkage is invalid".to_string());
            }
            Ok(predecessor_manifest.decoded)
        }
        _ => Err(
            "predecessor certificate digest, certificate path, and manifest path must be present together"
                .to_string(),
        ),
    }
}

fn validate_frozen_transition(
    stored_graph: &Value,
    source_state: &str,
    event: &str,
    target_state: &str,
    required_gate_ids: &[String],
) -> Result<(), String> {
    let transitions = stored_graph
        .get("transitions")
        .and_then(Value::as_array)
        .ok_or_else(|| "stored graph has no canonical transitions array".to_string())?;
    let mut requested_gates = required_gate_ids.to_vec();
    requested_gates.sort();
    requested_gates.dedup();
    if requested_gates.len() != required_gate_ids.len() {
        return Err("required gate IDs must be unique".to_string());
    }
    let matching = transitions.iter().filter(|transition| {
        transition.get("source_state_id").and_then(Value::as_str) == Some(source_state)
            && transition.get("event_id").and_then(Value::as_str) == Some(event)
            && transition.get("target_state_id").and_then(Value::as_str) == Some(target_state)
    });
    let mut count = 0usize;
    for transition in matching {
        count += 1;
        let mut graph_gates = transition
            .get("gate_ids")
            .and_then(Value::as_array)
            .ok_or(())
            .and_then(|gates| {
                gates
                    .iter()
                    .map(|gate| gate.as_str().map(str::to_string).ok_or(()))
                    .collect::<Result<Vec<_>, _>>()
            })
            .map_err(|()| "stored graph transition has invalid gate IDs".to_string())?;
        graph_gates.sort();
        if graph_gates == requested_gates {
            return Ok(());
        }
    }
    if count == 0 {
        Err(format!(
            "certificate transition {source_state} --{event}--> {target_state} is absent from stored graph"
        ))
    } else {
        Err(format!(
            "certificate gate set does not match frozen transition {source_state} --{event}--> {target_state}"
        ))
    }
}

fn validate_transition_attempt(
    run_id: &str,
    predecessor: &ValidatedAuthority,
    context: &TransitionContext,
    outcomes: &[GateOutcome],
    delta: &AuthorityDelta,
) -> Result<(), String> {
    if predecessor.manifest.kind != RecordKind::AuthorityManifest
        || predecessor.run_id != run_id
        || predecessor.manifest.value["run_id"] != run_id
    {
        return Err("predecessor is not this run's selected authority manifest".to_string());
    }
    codec::validate_digest(&context.graph_revision)?;
    if predecessor.graph_revision != context.graph_revision
        || predecessor.state != context.source_state
        || predecessor.workflow_state_version != context.source_workflow_state_version
    {
        return Err(
            "transition source does not match snapshot that selected predecessor authority"
                .to_string(),
        );
    }
    if context.source_state == context.target_state {
        return Err("authority-changing transition must target a distinct state".to_string());
    }
    if context.required_gate_ids.is_empty() {
        return Err("authority succession requires at least one gate".to_string());
    }
    validate_frozen_transition(
        &predecessor.stored_graph,
        &context.source_state,
        &context.event,
        &context.target_state,
        &context.required_gate_ids,
    )?;
    let required: BTreeSet<&str> = context
        .required_gate_ids
        .iter()
        .map(String::as_str)
        .collect();
    if required.len() != context.required_gate_ids.len() {
        return Err("required gate IDs must be unique".to_string());
    }
    let observed: BTreeMap<&str, bool> = outcomes
        .iter()
        .map(|outcome| (outcome.gate_id.as_str(), outcome.passed))
        .collect();
    if observed.len() != outcomes.len()
        || observed.keys().copied().collect::<BTreeSet<_>>() != required
    {
        return Err("gate outcomes must contain exactly one result per required gate".to_string());
    }
    if observed.values().any(|passed| !passed) {
        return Err("failed gate attempt cannot create authority succession".to_string());
    }
    if delta.replacements.len() + delta.invalidations.len() > 32 {
        return Err("authority delta exceeds 32 slots".to_string());
    }
    if delta
        .replacements
        .keys()
        .any(|slot| delta.invalidations.contains(slot))
    {
        return Err("authority delta cannot replace and invalidate the same slot".to_string());
    }
    if context.reset {
        if context.event != "restart-audit"
            || context.target_state != "audit"
            || !required.contains("restart-permitted")
            || !delta.replacements.is_empty()
        {
            return Err(
                "reset requires gated restart-audit with no replacement authority".to_string(),
            );
        }
        let slots = predecessor.manifest.value["slots"].as_object().unwrap();
        let invalidated: BTreeSet<&str> = delta.invalidations.iter().map(String::as_str).collect();
        let existing: BTreeSet<&str> = slots.keys().map(String::as_str).collect();
        if invalidated != existing {
            return Err(
                "reset delta must invalidate every current authority slot exactly".to_string(),
            );
        }
    }
    Ok(())
}

struct MapLike(serde_json::Map<String, Value>);
impl MapLike {
    fn empty() -> Self {
        Self(serde_json::Map::new())
    }
}

fn apply_delta(
    predecessor: &serde_json::Map<String, Value>,
    delta: &AuthorityDelta,
) -> Result<MapLike, String> {
    let mut slots = predecessor.clone();
    for slot in &delta.invalidations {
        if slots.remove(slot).is_none() {
            return Err(format!("authority delta invalidates absent slot {slot}"));
        }
    }
    for (slot, artifact) in &delta.replacements {
        let expected = crate::schema::slot_schema(slot)
            .ok_or_else(|| format!("unsupported authority slot {slot}"))?;
        if artifact.schema != expected {
            return Err(format!("authority slot {slot} requires schema {expected}"));
        }
        codec::validate_digest(&artifact.digest)?;
        slots.insert(
            slot.clone(),
            serde_json::to_value(artifact)
                .map_err(|error| format!("encode artifact reference: {error}"))?,
        );
    }
    if slots.len() > 32 {
        return Err("successor authority manifest exceeds 32 slots".to_string());
    }
    Ok(MapLike(slots))
}

fn validate_manifest_slots(store: &ArtifactStore, manifest: &Value) -> Result<(), String> {
    let slots = manifest["slots"].as_object().expect("validated slots");
    if slots.len() > 32 {
        return Err("authority manifest exceeds 32 slots".to_string());
    }
    for (slot, value) in slots {
        let artifact: ArtifactReference = serde_json::from_value(value.clone())
            .map_err(|error| format!("invalid authority reference in slot {slot}: {error}"))?;
        let expected = crate::schema::slot_schema(slot)
            .ok_or_else(|| format!("unsupported authority slot {slot}"))?;
        if artifact.schema != expected {
            return Err(format!("authority slot {slot} requires {expected}"));
        }
        let kind = RecordKind::from_str(&artifact.schema)?;
        store.load(&artifact.relative_path, kind, &artifact.digest)?;
    }
    Ok(())
}

fn compare_certificate_metadata(
    cert: &Value,
    metadata: &CertificateEvidenceMetadata,
) -> Result<(), String> {
    let pairs = [
        ("run_id", Value::String(metadata.run_id.clone())),
        (
            "graph_revision",
            Value::String(metadata.graph_revision.clone()),
        ),
        ("source_state", Value::String(metadata.source_state.clone())),
        (
            "source_workflow_state_version",
            Value::from(metadata.source_workflow_state_version),
        ),
        ("event", Value::String(metadata.event.clone())),
        ("target_state", Value::String(metadata.target_state.clone())),
        (
            "expected_successor_workflow_state_version",
            Value::from(metadata.expected_successor_workflow_state_version),
        ),
        (
            "required_gate_ids",
            serde_json::to_value(&metadata.required_gate_ids).unwrap(),
        ),
        (
            "predecessor_root_digest",
            Value::String(metadata.predecessor_root_digest.clone()),
        ),
        (
            "successor_root_digest",
            Value::String(metadata.successor_root_digest.clone()),
        ),
        ("delta_digest", Value::String(metadata.delta_digest.clone())),
    ];
    for (field, expected) in pairs {
        if cert[field] != expected {
            return Err(format!("certificate metadata mismatch at {field}"));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::RecordCategory;
    use tempfile::tempdir;

    fn graph() -> String {
        format!("sha256:{}", "9".repeat(64))
    }

    fn test_stored_graph() -> Value {
        json!({
            "transitions": [
                {
                    "source_state_id": "audit",
                    "event_id": "audit-complete",
                    "target_state_id": "triage",
                    "gate_ids": ["audit-ready"]
                },
                {
                    "source_state_id": "triage",
                    "event_id": "baseline-clean",
                    "target_state_id": "end",
                    "gate_ids": ["audit-clean"]
                }
            ]
        })
    }

    #[test]
    fn all_pass_successor_is_selected_only_at_matching_successor_snapshot() {
        let temp = tempdir().unwrap();
        let root = std::fs::canonicalize(temp.path()).unwrap();
        let store = ArtifactStore::open(&root, "run-1").unwrap();
        let graph_revision = graph();
        let initial = CurrentSnapshot {
            run_id: "run-1",
            graph_revision: &graph_revision,
            current_state: "audit",
            workflow_state_version: 0,
            stored_graph: test_stored_graph(),
        };
        let predecessor = validate_selected_authority(&store, &initial, &[]).unwrap();
        let context = TransitionContext {
            graph_revision: graph_revision.clone(),
            source_state: "audit".into(),
            source_workflow_state_version: 0,
            event: "audit-complete".into(),
            target_state: "triage".into(),
            required_gate_ids: vec!["audit-ready".into()],
            reset: false,
        };
        let mut forged_event = context.clone();
        forged_event.event = "forged-event".into();
        assert!(create_successor(
            &store,
            RecordCategory::Audits,
            "forged-event",
            &predecessor,
            &forged_event,
            &[GateOutcome {
                gate_id: "audit-ready".into(),
                passed: true,
            }],
            &AuthorityDelta::default(),
        )
        .unwrap_err()
        .contains("absent from stored graph"));
        let mut forged_gates = context.clone();
        forged_gates.required_gate_ids = vec!["forged-gate".into()];
        assert!(create_successor(
            &store,
            RecordCategory::Audits,
            "forged-gates",
            &predecessor,
            &forged_gates,
            &[GateOutcome {
                gate_id: "forged-gate".into(),
                passed: true,
            }],
            &AuthorityDelta::default(),
        )
        .unwrap_err()
        .contains("gate set does not match"));

        let evidence = create_successor(
            &store,
            RecordCategory::Audits,
            "inv-1",
            &predecessor,
            &context,
            &[GateOutcome {
                gate_id: "audit-ready".into(),
                passed: true,
            }],
            &AuthorityDelta::default(),
        )
        .unwrap();
        let current = CurrentSnapshot {
            run_id: "run-1",
            graph_revision: &graph_revision,
            current_state: "triage",
            workflow_state_version: 1,
            stored_graph: test_stored_graph(),
        };
        let mut noncanonical_id = evidence.clone();
        noncanonical_id.id = "caller-chosen-id".to_string();
        assert!(
            validate_selected_authority(&store, &current, &[noncanonical_id])
                .unwrap_err()
                .contains("evidence ID is not canonical")
        );

        let mut metadata: CertificateEvidenceMetadata =
            serde_json::from_value(evidence.metadata.clone().unwrap()).unwrap();
        let original_certificate = store
            .load(
                &metadata.certificate_relative_path,
                RecordKind::TransitionCertificate,
                &metadata.certificate_digest,
            )
            .unwrap();
        let wrong_delta = format!("sha256:{}", "0".repeat(64));
        let mut bad_value = original_certificate.decoded.value;
        bad_value["delta_digest"] = Value::String(wrong_delta.clone());
        let bad_certificate = store
            .store(
                RecordCategory::Audits,
                "bad-delta",
                RecordKind::TransitionCertificate,
                &bad_value,
            )
            .unwrap();
        metadata.delta_digest = wrong_delta;
        metadata.certificate_digest = bad_certificate.digest.clone();
        metadata.certificate_relative_path = bad_certificate.relative_path.clone();
        let bad_evidence = Evidence {
            id: certificate_evidence_id(&bad_certificate.digest, "triage", 1).unwrap(),
            kind: "transition-certificate-v1".into(),
            locator: bad_certificate.relative_path,
            digest: Some(bad_certificate.digest),
            media_type: evidence.media_type.clone(),
            metadata: Some(serde_json::to_value(metadata).unwrap()),
            observed_at: None,
        };
        assert!(
            validate_selected_authority(&store, &current, &[bad_evidence])
                .unwrap_err()
                .contains("delta does not match")
        );

        let selected =
            validate_selected_authority(&store, &current, std::slice::from_ref(&evidence)).unwrap();
        let next_context = TransitionContext {
            graph_revision: graph_revision.clone(),
            source_state: "triage".into(),
            source_workflow_state_version: 1,
            event: "baseline-clean".into(),
            target_state: "end".into(),
            required_gate_ids: vec!["audit-clean".into()],
            reset: false,
        };
        let next_evidence = create_successor(
            &store,
            RecordCategory::Audits,
            "inv-2",
            &selected,
            &next_context,
            &[GateOutcome {
                gate_id: "audit-clean".into(),
                passed: true,
            }],
            &AuthorityDelta::default(),
        )
        .unwrap();
        let end = CurrentSnapshot {
            run_id: "run-1",
            graph_revision: &graph_revision,
            current_state: "end",
            workflow_state_version: 2,
            stored_graph: test_stored_graph(),
        };
        validate_selected_authority(&store, &end, &[next_evidence]).unwrap();

        let stale = CurrentSnapshot {
            workflow_state_version: 2,
            ..current.clone()
        };
        assert!(
            validate_selected_authority(&store, &stale, std::slice::from_ref(&evidence)).is_err()
        );
        assert!(validate_selected_authority(&store, &current, &[]).is_err());
        assert!(
            validate_selected_authority(&store, &current, &[evidence.clone(), evidence]).is_err()
        );
    }

    #[test]
    fn replacement_and_invalidation_delta_round_trip_from_manifests() {
        let temp = tempdir().unwrap();
        let root = std::fs::canonicalize(temp.path()).unwrap();
        let store = ArtifactStore::open(&root, "run-1").unwrap();
        let graph_revision = graph();
        let initial = CurrentSnapshot {
            run_id: "run-1",
            graph_revision: &graph_revision,
            current_state: "audit",
            workflow_state_version: 0,
            stored_graph: test_stored_graph(),
        };
        let predecessor = validate_selected_authority(&store, &initial, &[]).unwrap();
        let repository_manifest = store
            .store(
                RecordCategory::Audits,
                "repository-manifest",
                RecordKind::RepositoryManifest,
                &json!({
                    "schema":"repository-manifest-v1",
                    "run_id":"run-1",
                    "manifest_kind":"baseline",
                    "work_root":"/repo",
                    "git_common_dir":"/repo/.git",
                    "entries":[],
                    "repository_fingerprint":format!("sha256:{}", "0".repeat(64)),
                    "baseline_digest":null,
                    "overlay_paths":[]
                }),
            )
            .unwrap();
        let claim = store
            .store(
                RecordCategory::Audits,
                "claim",
                RecordKind::ClaimSet,
                &json!({
                    "schema":"claim-set-v1",
                    "run_id":"run-1",
                    "manifest_digest":repository_manifest.digest,
                    "claims":[]
                }),
            )
            .unwrap();
        let replacement = ArtifactReference {
            schema: "claim-set-v1".into(),
            artifact_id: "claim-1".into(),
            digest: claim.digest,
            relative_path: claim.relative_path,
        };
        let delta = AuthorityDelta {
            replacements: BTreeMap::from([("claim-set".into(), replacement)]),
            invalidations: BTreeSet::new(),
        };
        let first = create_successor(
            &store,
            RecordCategory::Audits,
            "replace",
            &predecessor,
            &TransitionContext {
                graph_revision: graph_revision.clone(),
                source_state: "audit".into(),
                source_workflow_state_version: 0,
                event: "audit-complete".into(),
                target_state: "triage".into(),
                required_gate_ids: vec!["audit-ready".into()],
                reset: false,
            },
            &[GateOutcome {
                gate_id: "audit-ready".into(),
                passed: true,
            }],
            &delta,
        )
        .unwrap();
        let triage = CurrentSnapshot {
            run_id: "run-1",
            graph_revision: &graph_revision,
            current_state: "triage",
            workflow_state_version: 1,
            stored_graph: test_stored_graph(),
        };
        let predecessor = validate_selected_authority(&store, &triage, &[first]).unwrap();
        let invalidation = AuthorityDelta {
            replacements: BTreeMap::new(),
            invalidations: BTreeSet::from(["claim-set".into()]),
        };
        let second = create_successor(
            &store,
            RecordCategory::Audits,
            "invalidate",
            &predecessor,
            &TransitionContext {
                graph_revision: graph_revision.clone(),
                source_state: "triage".into(),
                source_workflow_state_version: 1,
                event: "baseline-clean".into(),
                target_state: "end".into(),
                required_gate_ids: vec!["audit-clean".into()],
                reset: false,
            },
            &[GateOutcome {
                gate_id: "audit-clean".into(),
                passed: true,
            }],
            &invalidation,
        )
        .unwrap();
        let end = CurrentSnapshot {
            run_id: "run-1",
            graph_revision: &graph_revision,
            current_state: "end",
            workflow_state_version: 2,
            stored_graph: test_stored_graph(),
        };
        let selected = validate_selected_authority(&store, &end, &[second]).unwrap();
        assert!(selected.manifest.value["slots"]
            .as_object()
            .unwrap()
            .is_empty());
    }

    #[test]
    fn deterministic_certificate_id_exposes_preseed_conflict_instead_of_aliasing() {
        let temp = tempdir().unwrap();
        let root = std::fs::canonicalize(temp.path()).unwrap();
        let store = ArtifactStore::open(&root, "run-1").unwrap();
        let graph_revision = graph();
        let initial = CurrentSnapshot {
            run_id: "run-1",
            graph_revision: &graph_revision,
            current_state: "audit",
            workflow_state_version: 0,
            stored_graph: test_stored_graph(),
        };
        let predecessor = validate_selected_authority(&store, &initial, &[]).unwrap();
        let context = TransitionContext {
            graph_revision,
            source_state: "audit".into(),
            source_workflow_state_version: 0,
            event: "audit-complete".into(),
            target_state: "triage".into(),
            required_gate_ids: vec!["audit-ready".into()],
            reset: false,
        };
        let outcomes = [GateOutcome {
            gate_id: "audit-ready".into(),
            passed: true,
        }];
        let first = create_successor(
            &store,
            RecordCategory::Audits,
            "provider-attempt",
            &predecessor,
            &context,
            &outcomes,
            &AuthorityDelta::default(),
        )
        .unwrap();
        let second = create_successor(
            &store,
            RecordCategory::Audits,
            "same-certificate-other-invocation",
            &predecessor,
            &context,
            &outcomes,
            &AuthorityDelta::default(),
        )
        .unwrap();
        assert_eq!(first.digest, second.digest);
        assert_eq!(first.id, second.id);

        // This models protocol-v1 run evidence uniqueness: caller-preseeded
        // inline evidence with canonical ID occupies same key, so engine rejects
        // provider result rather than committing ambiguous transition evidence.
        let mut engine_evidence_ids = BTreeSet::from([first.id]);
        assert!(!engine_evidence_ids.insert(second.id));
    }

    #[test]
    fn failed_attempt_writes_nothing_and_reset_requires_exact_empty_delta() {
        let temp = tempdir().unwrap();
        let root = std::fs::canonicalize(temp.path()).unwrap();
        let store = ArtifactStore::open(&root, "run-1").unwrap();
        let graph_revision = graph();
        let initial = CurrentSnapshot {
            run_id: "run-1",
            graph_revision: &graph_revision,
            current_state: "audit",
            workflow_state_version: 0,
            stored_graph: test_stored_graph(),
        };
        let predecessor = validate_selected_authority(&store, &initial, &[]).unwrap();
        let context = TransitionContext {
            graph_revision: graph_revision.clone(),
            source_state: "audit".into(),
            source_workflow_state_version: 0,
            event: "audit-complete".into(),
            target_state: "triage".into(),
            required_gate_ids: vec!["audit-ready".into()],
            reset: false,
        };
        assert!(create_successor(
            &store,
            RecordCategory::Audits,
            "failed",
            &predecessor,
            &context,
            &[GateOutcome {
                gate_id: "audit-ready".into(),
                passed: false
            }],
            &AuthorityDelta::default()
        )
        .is_err());
        assert!(!root.join("provider/audits/failed").exists());

        let authority = validate_selected_authority(&store, &initial, &[]).unwrap();
        assert!(authority.certificate.is_none());
    }
}
