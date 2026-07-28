//! Schema conformance for `plan.json`, plus deterministic referential integrity.
//!
//! Three kinds of check live here, and all three are mechanical:
//!
//! 1. **Shape.** Is the document there, is the field set exactly the expected
//!    one at every level, and does every field carry the right type? Presence
//!    and type only — no character minimums, no entry counts. A one-task phase
//!    is a legitimate plan and a terse `delivers` is the judges' business.
//!
//! 2. **Referential integrity.** Task and phase identifiers must be unique;
//!    `depends_on` must name a task that exists; a dependency must not point
//!    forward into a later phase; and the dependency graph must be acyclic.
//!    None of these are opinions about quality — each is a plan that cannot be
//!    executed as written, decidable without a model.
//!
//! 3. **Element coverage.** Every `element` of the design this plan descends
//!    from must be claimed by at least one phase. This is the plan-side analogue
//!    of the design gate's acceptance-coverage citation: it catches a plan that
//!    silently drops part of the approved design, which no amount of reading the
//!    plan on its own would reveal.
//!
//! Whether the tasks are *sized* correctly, carry enough context, or place
//! checkpoints anywhere useful is not decidable here. That is the
//! `plan-semantic` gate's business. The two layers are complementary; neither
//! substitutes for the other.

use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};

/// The document is a CLOSED schema at every level. An unknown field is rejected
/// rather than ignored, for the same reason it is in `intent.json`: a field no
/// gate reads is a place for work to hide.
const KNOWN_FIELDS: &[&str] = &["revision", "subject_revision", "phases"];

const PHASE_FIELDS: &[&str] = &["id", "goal", "tasks", "checkpoint", "covers"];
const PHASE_REQUIRED_TEXT: &[&str] = &["id", "goal"];

const TASK_FIELDS: &[&str] =
    &["id", "title", "depends_on", "delivers", "context", "done_when"];
const TASK_REQUIRED_TEXT: &[&str] = &["id", "title", "delivers"];
const TASK_REQUIRED_LISTS: &[&str] = &["depends_on", "context", "done_when"];

const CHECKPOINT_FIELDS: &[&str] = &["commands", "timeout_seconds", "review"];
const COMMAND_FIELDS: &[&str] = &["name", "run", "working_directory"];
const REVIEW_FIELDS: &[&str] = &["axes", "context"];

/// Returns one reason per violation; empty means the document conforms.
///
/// `design` is the parsed `design.json` this plan descends from. When it is
/// absent — unreadable, or not yet written — the element-coverage comparison is
/// skipped and the artifact gate's revision-linkage check reports the real
/// problem.
pub fn check(document: &Value, design: Option<&Value>) -> Vec<String> {
    let mut reasons = Vec::new();

    if !document.is_object() {
        reasons.push("plan.json must be a JSON object".to_string());
        return reasons;
    }

    // `revision` and `subject_revision` are checked for emptiness, unlike every
    // other text field, because gates compare them literally to detect
    // superseded documents. An empty value would make that linkage silently
    // meaningless. Mechanical requirement, not a quality judgment.
    for field in ["revision", "subject_revision"] {
        check_text(document.get(field), &format!("field `{field}`"), &mut reasons);
    }

    if let Some(object) = document.as_object() {
        for key in object.keys() {
            if !KNOWN_FIELDS.contains(&key.as_str()) {
                reasons.push(format!(
                    "plan.json has unknown field `{key}`; allowed fields are {}",
                    KNOWN_FIELDS.join(", ")
                ));
            }
        }
    }

    let phases = match document.get("phases").filter(|value| !value.is_null()) {
        None => {
            reasons.push("plan.json is missing required field `phases`".to_string());
            return reasons;
        }
        Some(value) => match value.as_array() {
            Some(items) => items,
            None => {
                reasons.push("plan.json field `phases` must be an array of objects".to_string());
                return reasons;
            }
        },
    };

    // Phase order is meaningful: it is the order the driver executes them in,
    // and `depends_on` may not point forward. An unordered collection could not
    // express that, so an object keyed by phase id is deliberately not the shape.
    let mut phase_ids: Vec<String> = Vec::new();
    // task id -> index of the phase declaring it, for the forward-reference check
    let mut task_phase: BTreeMap<String, usize> = BTreeMap::new();
    let mut task_order: Vec<String> = Vec::new();
    let mut dependencies: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut covered: Vec<String> = Vec::new();
    let mut shape_ok = true;

    for (index, phase) in phases.iter().enumerate() {
        let Some(object) = phase.as_object() else {
            reasons.push(format!("plan.json `phases[{index}]` must be an object"));
            shape_ok = false;
            continue;
        };

        for key in object.keys() {
            if !PHASE_FIELDS.contains(&key.as_str()) {
                reasons.push(format!(
                    "plan.json `phases[{index}]` has unknown field `{key}`; allowed fields are {}",
                    PHASE_FIELDS.join(", ")
                ));
                shape_ok = false;
            }
        }

        for field in PHASE_REQUIRED_TEXT {
            let before = reasons.len();
            check_text(
                object.get(*field),
                &format!("`phases[{index}].{field}`"),
                &mut reasons,
            );
            shape_ok &= reasons.len() == before;
        }

        if let Some(Value::String(id)) = object.get("id") {
            let id = id.trim().to_string();
            if phase_ids.contains(&id) {
                reasons.push(format!("plan.json declares phase id {id:?} more than once"));
            }
            phase_ids.push(id);
        }

        if let Some(covers) = object.get("covers").filter(|value| !value.is_null()) {
            let before = reasons.len();
            check_string_array(covers, &format!("phases[{index}].covers"), &mut reasons);
            if reasons.len() == before {
                covered.extend(
                    covers
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter_map(Value::as_str)
                        .map(|text| text.trim().to_string()),
                );
            } else {
                shape_ok = false;
            }
        }

        shape_ok &= check_tasks(
            object.get("tasks"),
            index,
            &mut task_phase,
            &mut task_order,
            &mut dependencies,
            &mut reasons,
        );

        shape_ok &= check_checkpoint(object.get("checkpoint"), index, &mut reasons);
    }

    // Comparing dependencies against a malformed task set would bury the real
    // shape error under a wall of derived noise.
    if shape_ok {
        check_dependencies(&task_phase, &task_order, &dependencies, &mut reasons);
        if let Some(design) = design {
            check_covers_matches_design(&covered, design, &mut reasons);
        }
    }

    reasons
}

fn check_tasks(
    value: Option<&Value>,
    phase_index: usize,
    task_phase: &mut BTreeMap<String, usize>,
    task_order: &mut Vec<String>,
    dependencies: &mut BTreeMap<String, Vec<String>>,
    reasons: &mut Vec<String>,
) -> bool {
    let Some(value) = value.filter(|value| !value.is_null()) else {
        reasons.push(format!(
            "plan.json `phases[{phase_index}]` is missing required field `tasks`"
        ));
        return false;
    };
    let Some(items) = value.as_array() else {
        reasons.push(format!(
            "plan.json `phases[{phase_index}].tasks` must be an array of objects"
        ));
        return false;
    };

    let mut ok = true;
    for (index, task) in items.iter().enumerate() {
        let label = format!("phases[{phase_index}].tasks[{index}]");
        let Some(object) = task.as_object() else {
            reasons.push(format!("plan.json `{label}` must be an object"));
            ok = false;
            continue;
        };

        for key in object.keys() {
            if !TASK_FIELDS.contains(&key.as_str()) {
                reasons.push(format!(
                    "plan.json `{label}` has unknown field `{key}`; allowed fields are {}",
                    TASK_FIELDS.join(", ")
                ));
                ok = false;
            }
        }

        for field in TASK_REQUIRED_TEXT {
            let before = reasons.len();
            check_text(object.get(*field), &format!("`{label}.{field}`"), reasons);
            ok &= reasons.len() == before;
        }

        for field in TASK_REQUIRED_LISTS {
            match object.get(*field).filter(|value| !value.is_null()) {
                None => {
                    reasons.push(format!(
                        "plan.json `{label}` is missing required field `{field}`"
                    ));
                    ok = false;
                }
                Some(value) => {
                    let before = reasons.len();
                    check_string_array(value, &format!("{label}.{field}"), reasons);
                    ok &= reasons.len() == before;
                }
            }
        }

        // An empty `depends_on` is legitimate and common — the first task of a
        // plan depends on nothing. An empty `context` or `done_when` is likewise
        // shape-valid; whether either is *sufficient* is the judges' business.
        if let Some(Value::String(id)) = object.get("id") {
            let id = id.trim().to_string();
            if task_phase.contains_key(&id) {
                reasons.push(format!("plan.json declares task id {id:?} more than once"));
                ok = false;
            } else {
                task_phase.insert(id.clone(), phase_index);
                task_order.push(id.clone());
            }
            let declared: Vec<String> = object
                .get("depends_on")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .map(|text| text.trim().to_string())
                .collect();
            dependencies.insert(id, declared);
        }
    }
    ok
}

fn check_checkpoint(value: Option<&Value>, phase_index: usize, reasons: &mut Vec<String>) -> bool {
    let label = format!("phases[{phase_index}].checkpoint");
    let Some(value) = value.filter(|value| !value.is_null()) else {
        reasons.push(format!(
            "plan.json `phases[{phase_index}]` is missing required field `checkpoint`"
        ));
        return false;
    };
    let Some(object) = value.as_object() else {
        reasons.push(format!("plan.json `{label}` must be an object"));
        return false;
    };

    let mut ok = true;
    for key in object.keys() {
        if !CHECKPOINT_FIELDS.contains(&key.as_str()) {
            reasons.push(format!(
                "plan.json `{label}` has unknown field `{key}`; allowed fields are {}",
                CHECKPOINT_FIELDS.join(", ")
            ));
            ok = false;
        }
    }

    // `commands` is required but may be empty: a phase whose completeness is
    // judged only semantically is a legitimate choice, and so is one judged only
    // mechanically.
    match object.get("commands").filter(|value| !value.is_null()) {
        None => {
            reasons.push(format!("plan.json `{label}` is missing required field `commands`"));
            ok = false;
        }
        Some(commands) => ok &= check_commands(commands, &label, reasons),
    }

    if let Some(timeout) = object.get("timeout_seconds").filter(|value| !value.is_null()) {
        if !timeout.is_u64() {
            reasons.push(format!(
                "plan.json `{label}.timeout_seconds` must be a non-negative integer"
            ));
            ok = false;
        }
    }

    if let Some(review) = object.get("review").filter(|value| !value.is_null()) {
        ok &= check_review(review, &label, reasons);
    }

    ok
}

/// The argv itself is deliberately not inspected beyond its type.
///
/// An empty `run` array passes here and fails when the checkpoint executes. That
/// is the same trust boundary the provider has always had — the author supplies
/// argv, the author is the operator — and an allowlist that must permit `sh`
/// to be useful is not a fence.
fn check_commands(value: &Value, parent: &str, reasons: &mut Vec<String>) -> bool {
    let Some(items) = value.as_array() else {
        reasons.push(format!("plan.json `{parent}.commands` must be an array of objects"));
        return false;
    };

    let mut ok = true;
    let mut names: Vec<String> = Vec::new();
    for (index, item) in items.iter().enumerate() {
        let label = format!("{parent}.commands[{index}]");
        let Some(object) = item.as_object() else {
            reasons.push(format!("plan.json `{label}` must be an object"));
            ok = false;
            continue;
        };
        for key in object.keys() {
            if !COMMAND_FIELDS.contains(&key.as_str()) {
                reasons.push(format!(
                    "plan.json `{label}` has unknown field `{key}`; allowed fields are {}",
                    COMMAND_FIELDS.join(", ")
                ));
                ok = false;
            }
        }

        let before = reasons.len();
        check_text(object.get("name"), &format!("`{label}.name`"), reasons);
        ok &= reasons.len() == before;

        // Names are how a failure is reported back to the author, so two
        // commands answering to the same name in one checkpoint would make the
        // diagnosis ambiguous.
        if let Some(Value::String(name)) = object.get("name") {
            let name = name.trim().to_string();
            if names.contains(&name) {
                reasons.push(format!(
                    "plan.json `{parent}` declares command name {name:?} more than once"
                ));
                ok = false;
            }
            names.push(name);
        }

        match object.get("run").filter(|value| !value.is_null()) {
            None => {
                reasons.push(format!("plan.json `{label}` is missing required field `run`"));
                ok = false;
            }
            Some(run) => {
                if run.as_array().is_none() {
                    reasons.push(format!(
                        "plan.json `{label}.run` must be an array of strings"
                    ));
                    ok = false;
                } else {
                    let before = reasons.len();
                    check_string_array(run, &format!("{label}.run"), reasons);
                    ok &= reasons.len() == before;
                }
            }
        }

        if let Some(directory) = object.get("working_directory").filter(|v| !v.is_null()) {
            let before = reasons.len();
            check_text(Some(directory), &format!("`{label}.working_directory`"), reasons);
            ok &= reasons.len() == before;
        }
    }
    ok
}

fn check_review(value: &Value, parent: &str, reasons: &mut Vec<String>) -> bool {
    let label = format!("{parent}.review");
    let Some(object) = value.as_object() else {
        reasons.push(format!("plan.json `{label}` must be an object"));
        return false;
    };

    let mut ok = true;
    for key in object.keys() {
        if !REVIEW_FIELDS.contains(&key.as_str()) {
            reasons.push(format!(
                "plan.json `{label}` has unknown field `{key}`; allowed fields are {}",
                REVIEW_FIELDS.join(", ")
            ));
            ok = false;
        }
    }

    match object.get("axes").filter(|value| !value.is_null()) {
        None => {
            reasons.push(format!("plan.json `{label}` is missing required field `axes`"));
            ok = false;
        }
        Some(axes) => {
            let before = reasons.len();
            check_string_array(axes, &format!("{label}.axes"), reasons);
            ok &= reasons.len() == before;
            if reasons.len() == before {
                check_axis_names(axes, &label, reasons);
                ok &= reasons.len() == before;
            }
        }
    }

    if let Some(context) = object.get("context").filter(|value| !value.is_null()) {
        let before = reasons.len();
        check_string_array(context, &format!("{label}.context"), reasons);
        ok &= reasons.len() == before;
    }

    ok
}

/// Every declared axis must be one this build actually implements.
///
/// Checked deterministically, here, rather than left to fail at execution. A
/// plan naming an axis that does not exist would otherwise pass review, be
/// approved, and then break the phase loop halfway through the change -- with a
/// diagnosis about provider internals rather than about the plan. The
/// vocabulary is a property of the binary, so this is decidable now.
fn check_axis_names(axes: &Value, label: &str, reasons: &mut Vec<String>) {
    let available = crate::gates::semantic::checkpoint_subject().axis_ids();
    let Some(items) = axes.as_array() else { return };
    for (index, item) in items.iter().enumerate() {
        let Some(name) = item.as_str().map(str::trim) else { continue };
        if !available.contains(&name) {
            reasons.push(format!(
                "plan.json `{label}.axes[{index}]` names {name:?}, which this provider does not \
                 implement; available checkpoint axes are {}",
                available.join(", ")
            ));
        }
    }
}

/// A dependency that names nothing, points forward, or closes a cycle describes
/// a plan that cannot be executed in the order it declares.
fn check_dependencies(
    task_phase: &BTreeMap<String, usize>,
    task_order: &[String],
    dependencies: &BTreeMap<String, Vec<String>>,
    reasons: &mut Vec<String>,
) {
    for task in task_order {
        let Some(declared) = dependencies.get(task) else { continue };
        let Some(phase) = task_phase.get(task) else { continue };
        for dependency in declared {
            if dependency == task {
                reasons.push(format!("plan.json task {task:?} depends on itself"));
                continue;
            }
            match task_phase.get(dependency) {
                None => reasons.push(format!(
                    "plan.json task {task:?} depends on {dependency:?}, which no phase declares"
                )),
                // Equal phase is allowed: within a phase, `depends_on` is what
                // tells a driver which tasks may run in parallel and which may
                // not. Only a dependency on a LATER phase is unexecutable.
                Some(other) if other > phase => reasons.push(format!(
                    "plan.json task {task:?} depends on {dependency:?}, which a later phase \
                     declares; a phase may only depend on work already complete"
                )),
                Some(_) => {}
            }
        }
    }

    if let Some(cycle) = find_cycle(task_order, dependencies) {
        reasons.push(format!(
            "plan.json dependency cycle: {}",
            cycle.join(" -> ")
        ));
    }
}

/// Depth-first search returning the first cycle found, as a readable path.
fn find_cycle(
    task_order: &[String],
    dependencies: &BTreeMap<String, Vec<String>>,
) -> Option<Vec<String>> {
    let mut settled: BTreeSet<&str> = BTreeSet::new();
    let mut stack: Vec<&str> = Vec::new();
    let mut on_stack: BTreeSet<&str> = BTreeSet::new();

    for root in task_order {
        if settled.contains(root.as_str()) {
            continue;
        }
        // Iterative DFS: `visit` marks entry, `None` marks the post-order pop.
        let mut work: Vec<(&str, bool)> = vec![(root.as_str(), false)];
        while let Some((task, expanded)) = work.pop() {
            if expanded {
                stack.pop();
                on_stack.remove(task);
                settled.insert(task);
                continue;
            }
            if settled.contains(task) {
                continue;
            }
            if on_stack.contains(task) {
                let start = stack.iter().position(|entry| *entry == task).unwrap_or(0);
                let mut cycle: Vec<String> =
                    stack[start..].iter().map(|entry| entry.to_string()).collect();
                cycle.push(task.to_string());
                return Some(cycle);
            }
            stack.push(task);
            on_stack.insert(task);
            work.push((task, true));
            if let Some(declared) = dependencies.get(task) {
                for dependency in declared {
                    if !settled.contains(dependency.as_str()) {
                        work.push((dependency.as_str(), false));
                    }
                }
            }
        }
    }
    None
}

/// Every design element must be claimed by some phase, and nothing may be
/// claimed that the design does not contain.
fn check_covers_matches_design(covered: &[String], design: &Value, reasons: &mut Vec<String>) {
    let Some(elements) = design.get("elements").and_then(Value::as_array) else {
        // A malformed design is the design gate's problem, not this one's.
        return;
    };
    let expected: Vec<String> = elements
        .iter()
        .filter_map(Value::as_str)
        .map(|text| text.trim().to_string())
        .collect();
    if expected.len() != elements.len() {
        return;
    }

    for element in &expected {
        if !covered.iter().any(|entry| entry == element) {
            reasons.push(format!(
                "plan.json: no phase `covers` design element {element:?}"
            ));
        }
    }
    for entry in covered {
        if !expected.contains(entry) {
            reasons.push(format!(
                "plan.json `covers` names {entry:?}, which is not an element of the design \
                 revision this plan references; cite the design text verbatim"
            ));
        }
    }
}

fn check_text(value: Option<&Value>, label: &str, reasons: &mut Vec<String>) {
    match value {
        None | Some(Value::Null) => {
            reasons.push(format!("plan.json is missing required {label}"));
        }
        // Blank is rejected for the same reason an absent value is: there is
        // nothing there. This is emptiness, not brevity.
        Some(Value::String(text)) if text.trim().is_empty() => {
            reasons.push(format!("plan.json {label} must not be empty"));
        }
        Some(Value::String(_)) => {}
        Some(_) => reasons.push(format!("plan.json {label} must be a string")),
    }
}

fn check_string_array(value: &Value, field: &str, reasons: &mut Vec<String>) {
    let Some(items) = value.as_array() else {
        reasons.push(format!("plan.json field `{field}` must be an array of strings"));
        return;
    };
    for (index, item) in items.iter().enumerate() {
        match item {
            Value::String(text) if text.trim().is_empty() => {
                reasons.push(format!("plan.json `{field}[{index}]` must not be empty"));
            }
            Value::String(_) => {}
            _ => reasons.push(format!("plan.json `{field}[{index}]` must be a string")),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::check;
    use serde_json::{json, Value};

    fn design() -> Value {
        json!({
            "revision": "2",
            "elements": ["A resumable transfer surface", "A durable progress record"]
        })
    }

    fn conforming() -> Value {
        json!({
            "revision": "1",
            "subject_revision": "2",
            "phases": [
                {
                    "id": "P1",
                    "goal": "Make progress durable",
                    "covers": ["A durable progress record"],
                    "tasks": [
                        {
                            "id": "T001",
                            "title": "Record progress",
                            "depends_on": [],
                            "delivers": "Progress survives restart",
                            "context": ["design.json"],
                            "done_when": ["A restart resumes where it stopped"]
                        }
                    ],
                    "checkpoint": {
                        "commands": [{ "name": "test", "run": ["cargo", "test"] }]
                    }
                },
                {
                    "id": "P2",
                    "goal": "Expose resumption",
                    "covers": ["A resumable transfer surface"],
                    "tasks": [
                        {
                            "id": "T002",
                            "title": "Resume a transfer",
                            "depends_on": ["T001"],
                            "delivers": "An interrupted transfer continues",
                            "context": ["design.json"],
                            "done_when": ["An interrupted transfer completes"]
                        }
                    ],
                    "checkpoint": {
                        "commands": [],
                        "timeout_seconds": 600,
                        "review": { "axes": ["tasks-actually-done"], "context": ["design.json"] }
                    }
                }
            ]
        })
    }

    #[test]
    fn a_conforming_document_passes() {
        assert_eq!(check(&conforming(), Some(&design())), Vec::<String>::new());
    }

    /// The schema layer must not second-guess sizing: a one-task phase with a
    /// terse `delivers` is the semantic judge's business.
    #[test]
    fn terse_entries_and_empty_command_lists_are_accepted() {
        let doc = json!({
            "revision": "1",
            "subject_revision": "2",
            "phases": [{
                "id": "P1",
                "goal": "g",
                "tasks": [{
                    "id": "T001", "title": "t", "depends_on": [],
                    "delivers": "d", "context": [], "done_when": []
                }],
                "checkpoint": { "commands": [] }
            }]
        });
        assert!(check(&doc, None).is_empty());
    }

    /// Argv is not inspected: an empty `run` fails when it executes, not here.
    #[test]
    fn an_empty_run_array_passes_the_schema() {
        let mut doc = conforming();
        doc["phases"][0]["checkpoint"]["commands"] = json!([{ "name": "noop", "run": [] }]);
        assert!(check(&doc, Some(&design())).is_empty());
    }

    #[test]
    fn missing_required_fields_are_reported_together() {
        let doc = json!({ "revision": "1" });
        let reasons = check(&doc, None);
        assert!(reasons.iter().any(|r| r.contains("subject_revision")));
        assert!(reasons.iter().any(|r| r.contains("phases")));
    }

    #[test]
    fn unknown_fields_are_rejected_at_every_level() {
        let mut doc = conforming();
        doc["phases"][0]["owner"] = json!("someone");
        doc["phases"][0]["tasks"][0]["estimate"] = json!("2d");
        doc["phases"][0]["checkpoint"]["retries"] = json!(3);
        let reasons = check(&doc, Some(&design()));
        assert!(reasons.iter().any(|r| r.contains("owner")));
        assert!(reasons.iter().any(|r| r.contains("estimate")));
        assert!(reasons.iter().any(|r| r.contains("retries")));
    }

    #[test]
    fn duplicate_identifiers_are_rejected() {
        let mut doc = conforming();
        doc["phases"][1]["id"] = json!("P1");
        doc["phases"][1]["tasks"][0]["id"] = json!("T001");
        let reasons = check(&doc, Some(&design()));
        assert!(reasons.iter().any(|r| r.contains("phase id \"P1\"")));
        assert!(reasons.iter().any(|r| r.contains("task id \"T001\"")));
    }

    #[test]
    fn a_dependency_on_an_unknown_task_is_rejected() {
        let mut doc = conforming();
        doc["phases"][1]["tasks"][0]["depends_on"] = json!(["T099"]);
        let reasons = check(&doc, Some(&design()));
        assert!(reasons.iter().any(|r| r.contains("T099") && r.contains("no phase declares")));
    }

    /// A phase cannot depend on work a later phase performs; the driver would
    /// have nothing to run.
    #[test]
    fn a_forward_dependency_across_phases_is_rejected() {
        let mut doc = conforming();
        doc["phases"][0]["tasks"][0]["depends_on"] = json!(["T002"]);
        let reasons = check(&doc, Some(&design()));
        assert!(reasons.iter().any(|r| r.contains("later phase")));
    }

    /// Within one phase a dependency is an ordering hint for a driver deciding
    /// what to parallelise, so it must remain legal.
    #[test]
    fn a_dependency_inside_the_same_phase_is_allowed() {
        let mut doc = conforming();
        doc["phases"][0]["tasks"] = json!([
            { "id": "T001", "title": "a", "depends_on": [], "delivers": "d",
              "context": [], "done_when": [] },
            { "id": "T00b", "title": "b", "depends_on": ["T001"], "delivers": "d",
              "context": [], "done_when": [] }
        ]);
        assert!(check(&doc, Some(&design())).is_empty());
    }

    #[test]
    fn a_dependency_cycle_is_reported_with_its_path() {
        let mut doc = conforming();
        doc["phases"][0]["tasks"] = json!([
            { "id": "T001", "title": "a", "depends_on": ["T00b"], "delivers": "d",
              "context": [], "done_when": [] },
            { "id": "T00b", "title": "b", "depends_on": ["T001"], "delivers": "d",
              "context": [], "done_when": [] }
        ]);
        let reasons = check(&doc, Some(&design()));
        assert!(reasons.iter().any(|r| r.contains("dependency cycle")));
    }

    #[test]
    fn a_task_depending_on_itself_is_rejected() {
        let mut doc = conforming();
        doc["phases"][0]["tasks"][0]["depends_on"] = json!(["T001"]);
        let reasons = check(&doc, Some(&design()));
        assert!(reasons.iter().any(|r| r.contains("depends on itself")));
    }

    #[test]
    fn a_design_element_no_phase_claims_is_reported() {
        let mut doc = conforming();
        doc["phases"][1]["covers"] = json!([]);
        let reasons = check(&doc, Some(&design()));
        assert!(reasons
            .iter()
            .any(|r| r.contains("no phase `covers`") && r.contains("resumable transfer")));
    }

    #[test]
    fn claiming_something_the_design_does_not_contain_is_reported() {
        let mut doc = conforming();
        doc["phases"][0]["covers"] = json!(["A durable progress record", "A caching layer"]);
        let reasons = check(&doc, Some(&design()));
        assert!(reasons.iter().any(|r| r.contains("A caching layer")));
    }

    /// Without the design there is nothing to compare against; the artifact
    /// gate's linkage check reports the real problem.
    #[test]
    fn coverage_is_skipped_when_the_design_is_unavailable() {
        let mut doc = conforming();
        doc["phases"][1]["covers"] = json!([]);
        assert!(check(&doc, None).is_empty());
    }

    #[test]
    fn wrong_types_are_reported_rather_than_panicking() {
        let doc = json!({
            "revision": 1,
            "subject_revision": ["nope"],
            "phases": "not an array"
        });
        assert_eq!(check(&doc, None).len(), 3);
    }

    /// An axis that does not exist would pass review, be approved, and then
    /// break the phase loop halfway through the change -- with a diagnosis about
    /// provider internals rather than about the plan. The vocabulary is a
    /// property of the binary, so it is decidable now.
    #[test]
    fn a_checkpoint_axis_this_build_does_not_implement_is_rejected() {
        let mut doc = conforming();
        doc["phases"][0]["checkpoint"]["review"] = json!({ "axes": ["vibes-good"] });
        let reasons = check(&doc, Some(&design()));
        assert!(
            reasons.iter().any(|reason| reason.contains("vibes-good")),
            "{reasons:?}"
        );
    }

    #[test]
    fn every_axis_named_in_plan_guidance_actually_exists() {
        let available = crate::gates::semantic::checkpoint_subject().axis_ids();
        for axis in ["tasks-actually-done", "no-scope-creep", "design-faithful"] {
            assert!(available.contains(&axis), "{axis} is named in guidance but not implemented");
        }
    }

    #[test]
    fn a_malformed_checkpoint_is_reported() {
        let mut doc = conforming();
        doc["phases"][0]["checkpoint"] = json!({ "commands": [{ "run": ["x"] }] });
        let reasons = check(&doc, Some(&design()));
        assert!(reasons.iter().any(|r| r.contains("name")));
    }

    #[test]
    fn duplicate_command_names_in_one_checkpoint_are_rejected() {
        let mut doc = conforming();
        doc["phases"][0]["checkpoint"]["commands"] = json!([
            { "name": "test", "run": ["a"] },
            { "name": "test", "run": ["b"] }
        ]);
        let reasons = check(&doc, Some(&design()));
        assert!(reasons.iter().any(|r| r.contains("more than once")));
    }
}
