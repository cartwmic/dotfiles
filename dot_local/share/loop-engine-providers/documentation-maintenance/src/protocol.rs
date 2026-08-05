use crate::authority::{self, CurrentSnapshot};
use crate::boundary;
use crate::storage::ArtifactStore;
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
        "describe" => description(),
        "validate_inputs" => validate_inputs(&request.payload),
        "evaluate_gates" => evaluate_gates(&request.payload),
        "live_guidance" => incompatible(vec![Diagnostic::new(
            "compatibility.phase-unavailable",
            "live guidance policy is outside implemented phase P1",
        )]),
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

fn description() -> Value {
    json!({
        "kind":"description",
        "graph":{
            "initial_state":"audit",
            "states":[{
                "id":"audit",
                "final":false,
                "static_guidance":{
                    "kind":"text",
                    "text":"Protocol/run-boundary phase is active. Assessment gates and frozen policy are intentionally unavailable in phase P1."
                }
            }],
            "transitions":[],
            "input_declarations":[
                {"id":"work_root","kind":"path","required":true},
                {"id":"artifact_root","kind":"path","required":true}
            ],
            "live_guidance_supported":false,
            "metadata":{"documentation_maintenance_provider_phase":"P1"}
        }
    })
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

fn evaluate_gates(payload: &Value) -> Value {
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
    if let Err(error) = authority::validate_selected_authority(&store, &current, &selected) {
        return evaluation_error(vec![Diagnostic::at(
            "authority.invalid",
            error,
            "/selected_evidence",
        )]);
    }
    incompatible(vec![Diagnostic::new(
        "compatibility.phase-unavailable",
        "assessment gate policy is outside implemented phase P1; no gate verdict was produced",
    )])
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
    let capabilities: Vec<Value> = requested
        .into_iter()
        .map(|capability| match capability {
            "protocol-v1" | "run-boundary" => json!({"capability":capability,"status":"compatible","diagnostics":[]}),
            "evaluate_gates" | "live_guidance" => json!({
                "capability":capability,"status":"incompatible",
                "diagnostics":[{"code":"compatibility.phase-unavailable","message":"capability is outside implemented phase P1"}]
            }),
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
    fn describe_is_p1_only_and_input_validation_reaches_dispatch() {
        let request = RequestEnvelope {
            protocol_major: 1,
            role: "describe".into(),
            invocation_id: "inv".into(),
            registration: registration(),
            payload: json!({}),
        };
        let response = handle(request).unwrap();
        assert_eq!(response.result["kind"], "description");
        assert!(response.result["graph"]["transitions"]
            .as_array()
            .unwrap()
            .is_empty());

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
