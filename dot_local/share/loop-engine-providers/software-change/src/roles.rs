//! Five-role dispatcher.
//!
//! Each role may return only the `result.kind` values the protocol permits for
//! it; returning anything else is `provider.protocol.malformed` at the engine.
//! Transport-level problems (unsupported major, bad envelope) are signalled by
//! returning `Err` here, never by a role-specific result.

use serde_json::{json, Value};
use std::path::PathBuf;

use crate::gates::{artifacts, commands, design, diff, intent, plan, semantic};
use crate::graph;
use crate::protocol::*;

pub fn handle(request: RequestEnvelope) -> Result<ResultEnvelope, String> {
    if request.protocol_major != PROTOCOL_MAJOR {
        return Err(format!("unsupported protocol_major {}", request.protocol_major));
    }
    if request.invocation_id.is_empty() {
        return Err("missing invocation_id".to_string());
    }

    let result = match request.role.as_str() {
        "describe" => description(graph::workflow_graph()),
        "validate_inputs" => validate_inputs(&request.payload),
        "evaluate_gates" => evaluate_gates(
            &request.payload,
            request.registration.timeout_seconds,
            &crate::util::invocation_tag(&request.invocation_id),
        ),
        "live_guidance" => live_guidance(&request.payload),
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

// ------------------------------------------------------------ validate_inputs

/// Value-only validation. Topology never appears here — the engine already has
/// the declarations from `describe`.
fn validate_inputs(payload: &Value) -> Value {
    let declarations = payload
        .get("declarations")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let candidates = payload.get("candidate_values").cloned().unwrap_or(json!({}));

    let mut diagnostics = Vec::new();
    for declaration in &declarations {
        let Some(id) = declaration.get("id").and_then(Value::as_str) else {
            continue;
        };
        let required = declaration.get("required").and_then(Value::as_bool).unwrap_or(false);
        let kind = declaration.get("kind").and_then(Value::as_str).unwrap_or("string");
        let path = format!("/candidate_values/{id}");
        let value = candidates.get(id);

        let Some(value) = value else {
            if required {
                diagnostics.push(Diagnostic::at(
                    "input.required",
                    format!("required input {id} is missing"),
                    path,
                ));
            }
            continue;
        };

        let Some(text) = value.as_str() else {
            diagnostics.push(Diagnostic::at(
                "input.type",
                format!("input {id} must be a string"),
                path,
            ));
            continue;
        };

        if text.trim().is_empty() {
            diagnostics.push(Diagnostic::at(
                "input.empty",
                format!("input {id} must not be empty"),
                path,
            ));
            continue;
        }

        // Both roots are dereferenced by gates from an arbitrary working
        // directory, so a relative path would silently resolve differently
        // per invocation.
        if kind == "path" {
            if !PathBuf::from(text).is_absolute() {
                diagnostics.push(Diagnostic::at(
                    "input.path.relative",
                    format!("input {id} must be an absolute path"),
                    path,
                ));
                continue;
            }
            if !PathBuf::from(text).is_dir() {
                diagnostics.push(Diagnostic::at(
                    "input.path.missing",
                    format!("input {id} must name an existing directory"),
                    path,
                ));
            }
        }
    }

    if diagnostics.is_empty() {
        accepted(candidates)
    } else {
        rejected(diagnostics)
    }
}

// ------------------------------------------------------------- evaluate_gates

fn evaluate_gates(payload: &Value, provider_timeout_seconds: u64, invocation_tag: &str) -> Value {
    let snapshot: RunSnapshot = payload
        .get("snapshot")
        .and_then(|value| serde_json::from_value(value.clone()).ok())
        .unwrap_or_default();

    let required: Vec<String> = payload
        .get("required_gate_ids")
        .and_then(Value::as_array)
        .map(|ids| ids.iter().filter_map(Value::as_str).map(str::to_string).collect())
        .unwrap_or_default();

    // A stored graph naming gates this build dropped must be reported as
    // incompatible, not silently failed.
    let unsupported: Vec<&String> = required
        .iter()
        .filter(|id| !graph::is_supported_gate(id))
        .collect();
    if !unsupported.is_empty() {
        let names: Vec<&str> = unsupported.iter().map(|id| id.as_str()).collect();
        return incompatible(vec![Diagnostic::new(
            "compatibility.unsupported",
            format!("stored graph requires unsupported gates: {}", names.join(", ")),
        )]);
    }

    let artifact_root = snapshot.inputs.get("artifact_root").and_then(Value::as_str);
    let work_root = snapshot.inputs.get("work_root").and_then(Value::as_str);

    // One clock for the whole invocation. Several stages may run here -- a
    // phase's checkpoint commands and then its diff judgment -- and each one
    // deriving its own budget from the registration timeout is how the sum
    // overruns it.
    let invocation_deadline = crate::util::invocation_deadline(provider_timeout_seconds);

    let mut verdicts_out = Vec::new();
    let mut evidence_out = Vec::new();
    let mut reasons = Vec::new();

    let runs_commands = required.iter().any(|id| commands::handles(id));

    if runs_commands {
        let (Some(work_root), Some(artifact_root)) = (work_root, artifact_root) else {
            return evaluation_error(vec![Diagnostic::new(
                "input.missing",
                "run inputs work_root and artifact_root are both required to run a phase \
                 checkpoint: the commands come from the plan, and they run against the work",
            )]);
        };
        match commands::evaluate(
            std::path::Path::new(artifact_root),
            std::path::Path::new(work_root),
            invocation_deadline,
            invocation_tag,
        ) {
            Ok(outcome) => {
                verdicts_out.extend(outcome.verdicts);
                evidence_out.extend(outcome.evidence);
                if let Some(reason) = outcome.reason {
                    reasons.push(reason);
                }
            }
            Err(commands::EvaluationFailure(diagnostics)) => {
                return evaluation_error(diagnostics);
            }
        }
    }

    for gate_id in required.iter().filter(|id| artifacts::handles(id)) {
        let Some(artifact_root) = artifact_root else {
            return evaluation_error(vec![Diagnostic::new(
                "input.missing",
                "run input artifact_root is required to evaluate artifact gates",
            )]);
        };
        let outcome = artifacts::evaluate(
            gate_id,
            std::path::Path::new(artifact_root),
            work_root.map(std::path::Path::new),
            invocation_tag,
        );
        verdicts_out.push(outcome.verdict);
        evidence_out.extend(outcome.evidence);
        if let Some(reason) = outcome.reason {
            reasons.push(reason);
        }
    }

/// Read a document subject's material and its schema violations.
///
/// The schema check is matched EXHAUSTIVELY on purpose. A catch-all here would
/// run the intent schema over a document that is not an intent, and the
/// resulting violations would suppress judgment with a diagnosis about entirely
/// the wrong fields.
fn prepare_document(
    subject: &'static semantic::Subject,
    artifact_root: &std::path::Path,
) -> Result<(semantic::Prepared, Vec<String>), String> {
    let name = subject.document_name().ok_or("subject reviews no document")?;
    let (bytes, document) = artifacts::read_document(artifact_root, name)?;

    // The upstream document is context for the judges and, for the design
    // schema, the source of the acceptance lines that must be cited. Absent
    // means the linkage check reports it instead.
    let context = subject
        .context_name()
        .and_then(|name| artifacts::read_document(artifact_root, name).ok())
        .map(|(_, value)| value);

    let violations = match subject.gate_id {
        "intent-semantic" => intent::check(&document),
        "design-semantic" => design::check(&document, context.as_ref()),
        "plan-semantic" => plan::check(&document, context.as_ref()),
        other => {
            return Err(format!(
                "semantic subject {other} has no schema check wired; this is a provider build \
                 defect, not a document problem"
            ))
        }
    };

    Ok((semantic::document_material(subject, &document, &bytes, context.as_ref()), violations))
}

    // Semantic judgment, LAST. Everything above it is deterministic and cheap;
    // this is the only part that spends model calls, and a transition whose
    // deterministic half has already failed cannot complete no matter what a
    // judge says.
    //
    // So when anything above failed, judgment is WITHHELD rather than bought.
    // The provider already took this position for schema violations -- "a
    // document that fails its schema is not worth spending model calls on" --
    // and a phase whose own checkpoint commands just failed is the same case.
    // Measured before this: a failing checkpoint still spent three axis judges
    // and a decider on the diff it had already refused.
    //
    // The withheld verdict is a FAIL carrying "not judged", never a pass: no
    // judge ruled, so no claim in the author's favour is honest, and the
    // transition was failing anyway.
    let blocking: Vec<String> = verdicts_out
        .iter()
        .filter(|verdict| !verdict.passed)
        .map(|verdict| verdict.gate_id.clone())
        .collect();

    for gate_id in required.iter().filter(|id| semantic::handles(id)) {
        let subject = match semantic::subject_for(gate_id) {
            Some(subject) => subject,
            None => continue,
        };
        let Some(artifact_root) = artifact_root else {
            return evaluation_error(vec![Diagnostic::new(
                "input.missing",
                format!("run input artifact_root is required to evaluate the {gate_id} gate"),
            )]);
        };
        let artifact_root = std::path::Path::new(artifact_root);

        if !blocking.is_empty() {
            verdicts_out.push(GateVerdict { gate_id: gate_id.clone(), passed: false });
            reasons.push(format!(
                "not judged: {} must pass before {} is judged, and no model call was spent on a \
                 transition that cannot complete",
                blocking.join(", "),
                subject.label()
            ));
            continue;
        }

        // Guidance for the current state exactly as frozen at run creation.
        // Empty when the stored graph predates rubric publication, which reads
        // as "nothing to compare" rather than as drift.
        let stored_guidance = snapshot
            .stored_graph
            .states
            .iter()
            .find(|state| state.id == snapshot.current_state)
            .map(|state| state.static_guidance.text.as_str())
            .unwrap_or("");

        // Two material kinds, assembled differently and judged identically.
        let (prepared, violations) = match subject.material {
            semantic::Material::Document { .. } => {
                match prepare_document(subject, artifact_root) {
                    Ok(pair) => pair,
                    // An unreadable or unparseable document is a gate failure,
                    // not an evaluation error: nothing is broken except the
                    // document, and the schema gate in the same invocation
                    // reports the detail.
                    Err(reason) => {
                        verdicts_out
                            .push(GateVerdict { gate_id: gate_id.clone(), passed: false });
                        reasons.push(format!("not judged: {reason}"));
                        continue;
                    }
                }
            }
            semantic::Material::Diff { .. } => {
                let Some(work_root) = work_root else {
                    return evaluation_error(vec![Diagnostic::new(
                        "input.missing",
                        format!(
                            "run input work_root is required to evaluate the {gate_id} gate: it \
                             judges the actual diff, which lives in the repository"
                        ),
                    )]);
                };
                match diff::prepare(
                    subject,
                    artifact_root,
                    std::path::Path::new(work_root),
                    invocation_tag,
                ) {
                    // No schema applies to a diff: there is nothing the
                    // author could have mis-shaped.
                    Ok(diff::Assembly::Judge(prepared)) => (*prepared, Vec::new()),
                    // A phase that declares no review passes. Whether declaring
                    // none was the right call is what `checkpoint-meaningful`
                    // judged when the plan was approved; re-litigating it here
                    // would overrule a decision that already had its gate.
                    Ok(diff::Assembly::NoReview { reason }) => {
                        verdicts_out
                            .push(GateVerdict { gate_id: gate_id.clone(), passed: true });
                        evidence_out.push(Evidence {
                            id: format!("{invocation_tag}-{gate_id}-skipped"),
                            kind: "checkpoint-judgment".to_string(),
                            locator: crate::util::locator("review", &reason),
                            digest: None,
                            media_type: Some("text/plain".to_string()),
                            metadata: Some(json!({ "gate_id": gate_id, "judged": false })),
                        });
                        continue;
                    }
                    Err(Ok(refused)) => {
                        let outcome = diff::refusal(gate_id, refused);
                        verdicts_out.push(outcome.verdict);
                        evidence_out.extend(outcome.evidence);
                        if let Some(reason) = outcome.reason {
                            reasons.push(reason);
                        }
                        continue;
                    }
                    Err(Err(diff::Unavailable(diagnostics))) => {
                        return evaluation_error(diagnostics)
                    }
                }
            }
        };

        match semantic::evaluate(
            subject,
            prepared,
            &violations,
            artifact_root,
            work_root.map(std::path::Path::new),
            stored_guidance,
            invocation_deadline,
            invocation_tag,
        ) {
            Ok(outcome) => {
                verdicts_out.push(outcome.verdict);
                evidence_out.extend(outcome.evidence);
                if let Some(reason) = outcome.reason {
                    reasons.push(reason);
                }
            }
            Err(semantic::EvaluationFailure(diagnostics)) => {
                return evaluation_error(diagnostics);
            }
        }
    }

    // The engine requires exactly one verdict per requested gate ID, in no
    // particular order. Restore request order and prove the set is exact.
    //
    // A gate may be served by MORE THAN ONE module -- `phase-complete` is judged
    // both by the artifact module, which validates the cursor, and by the
    // command module, which runs the phase's checks. Every contribution must
    // hold, so they are ANDed. Taking the first would silently discard the
    // other, and the half that got discarded would be whichever module happened
    // to run second: a cursor claiming phases in the wrong order passed because
    // its commands were green.
    let mut ordered = Vec::with_capacity(required.len());
    for gate_id in &required {
        let contributions: Vec<bool> = verdicts_out
            .iter()
            .filter(|verdict| &verdict.gate_id == gate_id)
            .map(|verdict| verdict.passed)
            .collect();
        if contributions.is_empty() {
            return evaluation_error(vec![Diagnostic::new(
                "gate.unevaluated",
                format!("gate {gate_id} produced no verdict"),
            )]);
        }
        ordered.push(GateVerdict {
            gate_id: gate_id.clone(),
            passed: contributions.into_iter().all(|passed| passed),
        });
    }

    // Explain the rejection. The reason text rides in the locator because the
    // engine drops provider evidence `metadata`; without this a driving agent
    // would see only `gate.failed` with no way to learn why through the CLI.
    if !reasons.is_empty() {
        let summary = reasons.join(" | ");
        evidence_out.push(Evidence {
            id: format!("{invocation_tag}-diagnosis"),
            kind: "gate-diagnosis".to_string(),
            locator: crate::util::locator("diagnosis", &summary),
            digest: None,
            media_type: Some("text/plain".to_string()),
            metadata: Some(json!({ "reasons": reasons, "gate_ids": required })),
        });
    }

    verdicts(ordered, evidence_out)
}

// -------------------------------------------------------------- live_guidance

fn live_guidance(payload: &Value) -> Value {
    let snapshot: RunSnapshot = payload
        .get("snapshot")
        .and_then(|value| serde_json::from_value(value.clone()).ok())
        .unwrap_or_default();

    let Some(text) = graph::live_guidance_for(&snapshot.current_state) else {
        return guidance(format!(
            "State {:?} is not recognized by this provider build. Use the stored static guidance from `run show`.",
            snapshot.current_state
        ));
    };

    // Static guidance is frozen at run creation, before any document exists, so
    // it states the contract and nothing situational. Two things it can never
    // say get appended here.
    //
    // 1. Which phase is current. `implement` runs a self-loop over a phase list
    //    that did not exist when the graph was stored.
    //
    // 2. Whether this state is being visited or REVISITED. The revision edges
    //    mean any authoring state can be re-entered from below, and an author
    //    revising a document with judged work beneath it is in a materially
    //    different position from one writing it for the first time. The engine
    //    does not report the previous state, but the documents on disk answer
    //    the question that actually matters.
    let Some(artifact_root) = snapshot.inputs.get("artifact_root").and_then(Value::as_str) else {
        return guidance(text);
    };
    let artifact_root = std::path::Path::new(artifact_root);

    let mut out = text.to_string();
    out.push_str(&crate::situation::live_situation(
        &snapshot.current_state,
        artifact_root,
    ));
    if snapshot.current_state == "implement" {
        out.push_str(&crate::gates::implementation::live_cursor(artifact_root));
    }
    guidance(out)
}

// --------------------------------------------------------- check_compatibility

/// Findings are non-latching observations. Incompatibility reported here is a
/// completed operation at the engine, not a rejection.
fn check_compatibility(payload: &Value) -> Value {
    let stored: CanonicalGraph = payload
        .get("stored_graph")
        .and_then(|value| serde_json::from_value(value.clone()).ok())
        .unwrap_or_default();

    let requested: Vec<String> = payload
        .get("capabilities")
        .and_then(Value::as_array)
        .map(|values| values.iter().filter_map(Value::as_str).map(str::to_string).collect())
        .unwrap_or_else(|| {
            vec!["evaluate_gates".to_string(), "live_guidance".to_string()]
        });

    let capabilities = requested
        .into_iter()
        .map(|capability| match capability.as_str() {
            "evaluate_gates" => {
                let mut missing: Vec<String> = stored
                    .transitions
                    .iter()
                    .flat_map(|transition| transition.gate_ids.iter())
                    .filter(|gate_id| !graph::is_supported_gate(gate_id))
                    .cloned()
                    .collect();
                missing.sort();
                missing.dedup();

                if missing.is_empty() {
                    finding(&capability, "compatible", vec![])
                } else {
                    finding(
                        &capability,
                        "incompatible",
                        vec![Diagnostic::new(
                            "gate.removed",
                            format!(
                                "stored graph requires gates this build no longer implements: {}",
                                missing.join(", ")
                            ),
                        )],
                    )
                }
            }
            "live_guidance" => {
                if stored.live_guidance_supported {
                    finding(&capability, "compatible", vec![])
                } else {
                    finding(
                        &capability,
                        "incompatible",
                        vec![Diagnostic::new(
                            "compatibility.unsupported",
                            "stored graph declares live guidance unsupported",
                        )],
                    )
                }
            }
            other => finding(
                other,
                "unknown",
                vec![Diagnostic::new(
                    "compatibility.unknown",
                    format!("capability {other} is not evaluated by this provider"),
                )],
            ),
        })
        .collect();

    findings(capabilities)
}

#[cfg(test)]
mod verdict_tests {
    use super::*;

    fn snapshot(artifact_root: &str, work_root: &str, gates: &[&str]) -> Value {
        json!({
            "snapshot": {
                "current_state": "implement",
                "inputs": { "artifact_root": artifact_root, "work_root": work_root },
                "stored_graph": { "states": [], "transitions": [], "live_guidance_supported": true }
            },
            "required_gate_ids": gates,
        })
    }

    /// `phase-complete` is judged by two modules: the artifact module validates
    /// the cursor, the command module runs the phase's checks. Both must hold.
    ///
    /// Regression: the ordering loop used to take the FIRST verdict for a gate
    /// id, so a cursor claiming phases in the wrong order passed on the strength
    /// of its commands being green. Whichever module ran second was discarded.
    #[test]
    fn a_gate_served_by_two_modules_fails_when_either_half_fails() {
        let root = std::env::temp_dir().join(format!("sc-roles-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();
        std::fs::write(
            root.join("plan.json"),
            json!({
                "revision": "1",
                "phases": [
                    { "id": "P1", "checkpoint": { "commands": [] } },
                    { "id": "P2", "checkpoint": { "commands": [{ "name": "ok", "run": ["/usr/bin/true"] }] } }
                ]
            })
            .to_string(),
        )
        .unwrap();
        // Claims P2 first, which the plan does not allow. Its commands pass.
        std::fs::write(
            root.join("implementation.json"),
            json!({
                "revision": "1",
                "plan_revision": "1",
                "base_commit": "irrelevant",
                "phases": [{ "id": "P2" }]
            })
            .to_string(),
        )
        .unwrap();

        let path = root.to_string_lossy().to_string();
        let result = evaluate_gates(&snapshot(&path, &path, &["phase-complete"]), 600, "tag");
        let verdicts = result["verdicts"].as_array().expect("verdicts");
        assert_eq!(verdicts.len(), 1);
        assert_eq!(
            verdicts[0]["passed"], false,
            "the cursor half must not be discarded because the command half passed"
        );
    }
}
