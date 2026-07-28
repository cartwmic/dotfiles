//! Command gates: a phase's checkpoint, judged by running the project's checks.
//!
//! Commands are declared per PHASE in `plan.json`, not per repository. What gets
//! validated is a property of the change being made, not of the repository it is
//! made in: a phase that adds persistence and a phase that adds an interface do
//! not need the same checks, and a repository-level list cannot express that.
//! The plan is reviewed and approved, so the commands are reviewed with it.
//!
//! Commands are executed directly - no shell, no word splitting, no expansion -
//! matching the engine's own provider-spawn policy. The argv is author-supplied
//! and deliberately unvalidated beyond its type: the author is the operator, and
//! a fence that must permit `sh` to be useful is not a fence.

use serde::Deserialize;
use serde_json::{json, Value};
use std::io::Read;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use crate::protocol::{Diagnostic, Evidence, GateVerdict};
use crate::util::{contained_join, sha256_hex, truncate_lossy};

/// One entry of a phase's `checkpoint.commands`.
///
/// `plan-ready` has already established the shape, so this deserialises what it
/// accepted. An empty `run` passes that gate deliberately and arrives here, where
/// it fails as a command that cannot be executed - which is where a defect in
/// argv belongs.
#[derive(Debug, Deserialize)]
pub struct CommandSpec {
    pub name: String,
    pub run: Vec<String>,
    #[serde(default)]
    pub working_directory: Option<String>,
}

/// Bytes of captured output retained per command in evidence metadata.
const OUTPUT_SNIPPET_BYTES: usize = 4096;

/// True when `gate_id` runs a phase's checkpoint commands.
///
/// This gate is served by TWO modules: the artifact module validates the cursor
/// document, this one runs the checks. Both contribute to one verdict - the
/// claim must be well-formed and the phase's checks must pass.
pub fn handles(gate_id: &str) -> bool {
    gate_id == "phase-complete"
}

pub struct Outcome {
    pub verdicts: Vec<GateVerdict>,
    pub evidence: Vec<Evidence>,
    pub reason: Option<String>,
}

/// A configuration or spawn problem the provider could not evaluate around.
///
/// This is deliberately distinct from a failing command: an unreachable
/// toolchain is `evaluation_error`, whereas a test suite that ran and failed is
/// an honest gate verdict.
pub struct EvaluationFailure(pub Vec<Diagnostic>);

/// Run the checkpoint commands of the phase currently under verification.
///
/// The phase is the LAST one `implementation.json` claims. That document is a
/// claim - "I have finished this phase" - and this is the half of the gate that
/// decides whether the claim survives contact with the project's own checks.
pub fn evaluate(
    artifact_root: &Path,
    work_root: &Path,
    invocation_deadline: Instant,
    invocation_tag: &str,
) -> Result<Outcome, EvaluationFailure> {
    let (_, cursor) = crate::gates::artifacts::read_document(artifact_root, "implementation.json")
        .map_err(|error| {
            EvaluationFailure(vec![Diagnostic::new("artifact.unreadable", error)])
        })?;
    let (_, plan) = crate::gates::artifacts::read_document(artifact_root, "plan.json")
        .map_err(|error| {
            EvaluationFailure(vec![Diagnostic::new("artifact.unreadable", error)])
        })?;

    // Nothing claimed means nothing to verify. Said plainly here rather than
    // letting a downstream lookup fail with something obscure.
    let Some(phase_id) = crate::gates::implementation::phase_under_verification(&cursor) else {
        return Ok(Outcome {
            verdicts: vec![GateVerdict { gate_id: "phase-complete".to_string(), passed: false }],
            evidence: Vec::new(),
            reason: Some(
                "implementation.json claims no phases, so there is no phase to verify; append \
                 the phase you have finished before requesting phase-complete"
                    .to_string(),
            ),
        });
    };

    let Some(phase) = find_phase(&plan, &phase_id) else {
        return Ok(Outcome {
            verdicts: vec![GateVerdict { gate_id: "phase-complete".to_string(), passed: false }],
            evidence: Vec::new(),
            reason: Some(format!(
                "implementation.json claims phase {phase_id:?}, which the approved plan does not \
                 declare"
            )),
        });
    };

    let checkpoint = phase.get("checkpoint").cloned().unwrap_or(Value::Null);
    let specs: Vec<CommandSpec> = checkpoint
        .get("commands")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| serde_json::from_value(item.clone()).ok())
                .collect()
        })
        .unwrap_or_default();

    // An empty command list is legitimate: a phase may rely entirely on its
    // declared review, or be pure preparation. `plan-ready` allows it and
    // `checkpoint-meaningful` is what judges whether it was the right choice.
    if specs.is_empty() {
        return Ok(Outcome {
            verdicts: vec![GateVerdict { gate_id: "phase-complete".to_string(), passed: true }],
            evidence: vec![Evidence {
                id: format!("{invocation_tag}-checkpoint-{phase_id}"),
                kind: "checkpoint-commands".to_string(),
                locator: crate::util::locator(
                    "checkpoint",
                    &format!("phase {phase_id} declares no commands; nothing was run"),
                ),
                digest: None,
                media_type: Some("text/plain".to_string()),
                metadata: Some(json!({ "phase": phase_id, "commands": 0 })),
            }],
            reason: None,
        });
    }

    let configured = checkpoint.get("timeout_seconds").and_then(Value::as_u64);
    let deadline = crate::util::stage_deadline(configured, invocation_deadline);

    let mut evidence = Vec::new();
    let mut failures = Vec::new();

    for (index, spec) in specs.iter().enumerate() {
        if spec.run.is_empty() {
            return Err(EvaluationFailure(vec![Diagnostic::at(
                "plan.invalid",
                format!(
                    "phase {phase_id} command {:?} declares an empty `run` array; `plan-ready` \
                     does not inspect argv, so this surfaces here",
                    spec.name
                ),
                format!("/phases/{phase_id}/checkpoint/commands/{index}/run"),
            )]));
        }

        let directory = match spec.working_directory.as_deref() {
            Some(relative) => contained_join(work_root, relative).map_err(|error| {
                EvaluationFailure(vec![Diagnostic::at(
                    "plan.invalid",
                    error,
                    format!("/phases/{phase_id}/checkpoint/commands/{index}/working_directory"),
                )])
            })?,
            None => work_root.to_path_buf(),
        };

        let execution = run_command(spec, &directory, deadline)?;
        if !execution.succeeded {
            failures.push(format!("{}: {}", spec.name, execution.summary));
        }
        evidence.push(execution.into_evidence(index, spec, &phase_id, invocation_tag));
    }

    let passed = failures.is_empty();
    Ok(Outcome {
        verdicts: vec![GateVerdict { gate_id: "phase-complete".to_string(), passed }],
        evidence,
        reason: (!passed).then(|| format!("phase {phase_id} checkpoint: {}", failures.join("; "))),
    })
}

/// The plan's declaration of one phase, by id.
fn find_phase(plan: &Value, phase_id: &str) -> Option<Value> {
    plan.get("phases")?
        .as_array()?
        .iter()
        .find(|phase| phase.get("id").and_then(Value::as_str).map(str::trim) == Some(phase_id))
        .cloned()
}


struct Execution {
    succeeded: bool,
    summary: String,
    exit_code: Option<i32>,
    timed_out: bool,
    duration_ms: u128,
    output: Vec<u8>,
}

fn run_command(
    spec: &CommandSpec,
    directory: &Path,
    deadline: Instant,
) -> Result<Execution, EvaluationFailure> {
    let started = Instant::now();
    let mut child = Command::new(&spec.run[0])
        .args(&spec.run[1..])
        .current_dir(directory)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| {
            EvaluationFailure(vec![Diagnostic::new(
                "dependency.unavailable",
                format!("cannot spawn {:?} for command {:?}: {error}", spec.run[0], spec.name),
            )])
        })?;

    // Drain both pipes on their own threads: a command that fills a pipe buffer
    // would otherwise block forever and defeat the deadline.
    let mut stdout = child.stdout.take();
    let mut stderr = child.stderr.take();
    let stdout_reader = std::thread::spawn(move || drain(&mut stdout));
    let stderr_reader = std::thread::spawn(move || drain(&mut stderr));

    let mut timed_out = false;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) => {
                if Instant::now() >= deadline {
                    let _ = child.kill();
                    let _ = child.wait();
                    timed_out = true;
                    break None;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(error) => {
                return Err(EvaluationFailure(vec![Diagnostic::new(
                    "dependency.unavailable",
                    format!("cannot wait on command {:?}: {error}", spec.name),
                )]));
            }
        }
    };

    let mut output = stdout_reader.join().unwrap_or_default();
    output.extend(stderr_reader.join().unwrap_or_default());

    let exit_code = status.and_then(|status| status.code());
    let succeeded = !timed_out && exit_code == Some(0);
    let summary = if timed_out {
        "timed out".to_string()
    } else {
        match exit_code {
            Some(0) => "exit 0".to_string(),
            Some(code) => format!("exit {code}"),
            None => "terminated by signal".to_string(),
        }
    };

    Ok(Execution {
        succeeded,
        summary,
        exit_code,
        timed_out,
        duration_ms: started.elapsed().as_millis(),
        output,
    })
}

fn drain(stream: &mut Option<impl Read>) -> Vec<u8> {
    let mut buffer = Vec::new();
    if let Some(stream) = stream.as_mut() {
        let _ = stream.read_to_end(&mut buffer);
    }
    buffer
}

impl Execution {
    fn into_evidence(
        self,
        index: usize,
        spec: &CommandSpec,
        phase_id: &str,
        invocation_tag: &str,
    ) -> Evidence {
        Evidence {
            id: format!("{invocation_tag}-checkpoint-{index}"),
            kind: "checkpoint-command".to_string(),
            // argv and exit status ride in the locator: the engine drops
            // provider evidence metadata, and which command failed is exactly
            // what an operator needs from `run evidence list`.
            locator: crate::util::locator(
                "command",
                &format!("{phase_id} / {} [{}] {}", spec.name, spec.run.join(" "), self.summary),
            ),
            digest: Some(sha256_hex(&self.output)),
            media_type: Some("text/plain".to_string()),
            metadata: Some(json!({
                "phase": phase_id,
                "command_name": spec.name,
                "argv": spec.run,
                "exit_code": self.exit_code,
                "timed_out": self.timed_out,
                "duration_ms": self.duration_ms as u64,
                "succeeded": self.succeeded,
                "output_bytes": self.output.len() as u64,
                "output_snippet": truncate_lossy(&self.output, OUTPUT_SNIPPET_BYTES),
            })),
        }
    }
}
