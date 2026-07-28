//! Language-local DTOs for loop-engine provider protocol v1.
//!
//! Normative contract: `docs/provider-protocol-v1.md` and `docs/graph-projection.md`
//! in the loop-engine repository. Nothing here imports engine crates; the wire
//! shapes are reproduced from the frozen spec.

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const PROTOCOL_MAJOR: u32 = 1;
pub const PROVIDER_VERSION: &str = concat!("software-change/", env!("CARGO_PKG_VERSION"));

/// `provider_request_json_bytes` (D008).
pub const REQUEST_LIMIT_BYTES: usize = 4 * 1024 * 1024;
/// `provider_result_stdout_bytes` (D008).
pub const RESULT_LIMIT_BYTES: usize = 1024 * 1024;

// ---------------------------------------------------------------- envelopes

#[derive(Debug, Deserialize)]
pub struct RequestEnvelope {
    pub protocol_major: u32,
    pub role: String,
    pub invocation_id: String,
    pub registration: Registration,
    #[serde(default)]
    pub payload: Value,
}

/// Immutable resolved registration. Only `timeout_seconds` shapes behaviour
/// today; the rest is retained because the protocol guarantees it and it is
/// useful when diagnosing a run from a trace file.
#[derive(Debug, Deserialize)]
pub struct Registration {
    #[allow(dead_code)]
    pub registration_id: String,
    #[allow(dead_code)]
    pub config_revision: u64,
    #[allow(dead_code)]
    pub executable: String,
    #[allow(dead_code)]
    #[serde(default)]
    pub argv: Vec<String>,
    #[allow(dead_code)]
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

#[derive(Debug, Serialize)]
pub struct Diagnostic {
    pub code: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
}

impl Diagnostic {
    pub fn new(code: &str, message: impl Into<String>) -> Self {
        Self { code: code.to_string(), message: message.into(), path: None }
    }

    pub fn at(code: &str, message: impl Into<String>, path: impl Into<String>) -> Self {
        Self { code: code.to_string(), message: message.into(), path: Some(path.into()) }
    }
}

// -------------------------------------------------------------- graph wire

// Graph objects are built directly as JSON in `graph.rs`: the wire shape uses
// `final`, a Rust keyword, and the graph is emitted but never deserialized here.

// ------------------------------------------------------------ run snapshot

#[derive(Debug, Deserialize, Default)]
pub struct CanonicalTransition {
    #[serde(default)]
    pub gate_ids: Vec<String>,
}

#[derive(Debug, Deserialize, Default)]
pub struct CanonicalGraph {
    #[serde(default)]
    pub live_guidance_supported: bool,
    #[serde(default)]
    pub transitions: Vec<CanonicalTransition>,
    /// States as frozen at run creation, carrying the guidance text this run was
    /// created under. Read to detect that the provider was rebuilt with
    /// different judge rubrics than the ones published to the author.
    #[serde(default)]
    pub states: Vec<CanonicalState>,
}

#[derive(Debug, Default, Deserialize)]
pub struct CanonicalState {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub static_guidance: CanonicalGuidance,
}

#[derive(Debug, Default, Deserialize)]
pub struct CanonicalGuidance {
    #[serde(default)]
    pub text: String,
}

#[derive(Debug, Deserialize, Default)]
pub struct RunSnapshot {
    #[serde(default)]
    pub current_state: String,
    #[serde(default)]
    pub inputs: serde_json::Map<String, Value>,
    /// Present on gate and guidance snapshots; compatibility judgments read the
    /// stored graph from the `check_compatibility` payload instead.
    #[serde(default)]
    pub stored_graph: CanonicalGraph,
}

// ---------------------------------------------------------------- evidence

#[derive(Debug, Serialize, Deserialize)]
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
}

#[derive(Debug, Serialize)]
pub struct GateVerdict {
    pub gate_id: String,
    pub passed: bool,
}

// ----------------------------------------------------------- result makers

pub fn description(graph: Value) -> Value {
    serde_json::json!({ "kind": "description", "graph": graph })
}

pub fn accepted(values: Value) -> Value {
    serde_json::json!({ "kind": "accepted", "values": values })
}

pub fn rejected(diagnostics: Vec<Diagnostic>) -> Value {
    serde_json::json!({ "kind": "rejected", "diagnostics": diagnostics })
}

pub fn verdicts(verdicts: Vec<GateVerdict>, evidence: Vec<Evidence>) -> Value {
    serde_json::json!({ "kind": "verdicts", "verdicts": verdicts, "evidence": evidence })
}

pub fn incompatible(diagnostics: Vec<Diagnostic>) -> Value {
    serde_json::json!({ "kind": "incompatible", "diagnostics": diagnostics })
}

pub fn evaluation_error(diagnostics: Vec<Diagnostic>) -> Value {
    serde_json::json!({ "kind": "evaluation_error", "diagnostics": diagnostics })
}

pub fn guidance(text: impl Into<String>) -> Value {
    serde_json::json!({ "kind": "guidance", "text": text.into() })
}

pub fn findings(capabilities: Vec<Value>) -> Value {
    serde_json::json!({ "kind": "findings", "capabilities": capabilities })
}

pub fn finding(capability: &str, status: &str, diagnostics: Vec<Diagnostic>) -> Value {
    serde_json::json!({
        "capability": capability,
        "status": status,
        "diagnostics": diagnostics,
    })
}
