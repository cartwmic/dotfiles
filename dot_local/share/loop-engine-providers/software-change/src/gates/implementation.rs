//! Schema conformance for `implementation.json`, the phase cursor.
//!
//! This document is unlike the three before it. Intent, design and plan are
//! authored prose, revised through review cycles, and judged. This one is a
//! cursor: append-only, never reviewed, and read by the engine-facing gates to
//! answer three questions and nothing else — which phase is current, whether
//! every phase is done, and what commit a phase's diff should be measured from.
//!
//! Append-only holds WITHIN A PLAN REVISION. The `revise-plan` edge means a run
//! can return to `plan`, revise it, and come forward to a cursor whose
//! `plan_revision` no longer matches. That cursor may be re-pointed: bump its
//! own `revision` and set `plan_revision` to the new plan. The phase list is
//! NOT rewritten, and the prefix rule below is what makes that safe — a revised
//! plan that reorders, renames or drops an already-claimed phase fails the
//! prefix check, so only the part of the plan that has not been done yet can
//! actually be revised. Retroactively changing a verified phase is refused.
//!
//! Known limit: the prefix rule compares phase IDENTIFIERS. A revised plan that
//! keeps an id and rewrites that phase's tasks passes it, leaving a completed
//! phase verified against tasks that no longer exist. Closing that needs a
//! per-phase verification marker keyed on the phase's task content.
//!
//! Two kinds of check live here, both mechanical:
//!
//! 1. **Shape.** Presence and type, closed field set, non-empty identifiers.
//!
//! 2. **Agreement with the plan.** The claimed phases must be a PREFIX of the
//!    approved plan's phases, in the plan's order. A prefix is the right shape
//!    because the document grows one entry at a time: at any moment mid-flight
//!    it names the phases done so far and no others. Leaving the run requires
//!    that prefix to be the whole list, which is the `require_complete` mode.
//!
//! Nothing here judges the work. `phase-complete` verifies the last claimed
//! phase by running its checkpoint; this module only decides whether the claim
//! is well-formed and consistent with the plan it descends from.

use serde_json::Value;

/// Closed field set, for the same reason as every other document: a field no
/// gate reads is a place for work to hide.
const KNOWN_FIELDS: &[&str] = &["revision", "plan_revision", "base_commit", "phases"];
const PHASE_FIELDS: &[&str] = &["id", "commit"];

/// Returns one reason per violation; empty means the document conforms.
///
/// `plan` is the parsed `plan.json` this cursor descends from. When it is absent
/// the phase comparison is skipped and the artifact gate's revision-linkage
/// check reports the real problem.
///
/// `require_complete` is set by the gate leaving `implement`: mid-flight a
/// partial list is correct, but a run cannot move to review having verified only
/// some of the plan.
pub fn check(document: &Value, plan: Option<&Value>, require_complete: bool) -> Vec<String> {
    let mut reasons = Vec::new();

    if !document.is_object() {
        reasons.push("implementation.json must be a JSON object".to_string());
        return reasons;
    }

    // `revision` and `plan_revision` are compared literally by gates to detect
    // superseded documents; `base_commit` is what a diff is measured from. An
    // empty value in any of them makes a mechanical check silently meaningless.
    for field in ["revision", "plan_revision", "base_commit"] {
        check_text(document.get(field), &format!("field `{field}`"), &mut reasons);
    }

    if let Some(object) = document.as_object() {
        for key in object.keys() {
            if !KNOWN_FIELDS.contains(&key.as_str()) {
                reasons.push(format!(
                    "implementation.json has unknown field `{key}`; allowed fields are {}",
                    KNOWN_FIELDS.join(", ")
                ));
            }
        }
    }

    let entries = match document.get("phases").filter(|value| !value.is_null()) {
        None => {
            reasons.push(
                "implementation.json is missing required field `phases`; write it as an empty \
                 array before starting the first phase"
                    .to_string(),
            );
            return reasons;
        }
        Some(value) => match value.as_array() {
            Some(items) => items,
            None => {
                reasons
                    .push("implementation.json field `phases` must be an array of objects".to_string());
                return reasons;
            }
        },
    };

    let mut claimed: Vec<String> = Vec::new();
    let mut shape_ok = true;
    for (index, entry) in entries.iter().enumerate() {
        let label = format!("phases[{index}]");
        let Some(object) = entry.as_object() else {
            reasons.push(format!("implementation.json `{label}` must be an object"));
            shape_ok = false;
            continue;
        };
        for key in object.keys() {
            if !PHASE_FIELDS.contains(&key.as_str()) {
                reasons.push(format!(
                    "implementation.json `{label}` has unknown field `{key}`; allowed fields are {}",
                    PHASE_FIELDS.join(", ")
                ));
                shape_ok = false;
            }
        }
        let before = reasons.len();
        check_text(object.get("id"), &format!("`{label}.id`"), &mut reasons);
        shape_ok &= reasons.len() == before;

        // `commit` is optional: the loop works without committing, at the cost
        // of every phase being reviewed against everything accumulated rather
        // than against its own work.
        if let Some(commit) = object.get("commit").filter(|value| !value.is_null()) {
            let before = reasons.len();
            check_text(Some(commit), &format!("`{label}.commit`"), &mut reasons);
            shape_ok &= reasons.len() == before;
        }

        if let Some(Value::String(id)) = object.get("id") {
            let id = id.trim().to_string();
            if claimed.contains(&id) {
                reasons.push(format!(
                    "implementation.json claims phase {id:?} more than once"
                ));
                shape_ok = false;
            }
            claimed.push(id);
        }
    }

    if shape_ok {
        if let Some(plan) = plan {
            check_against_plan(&claimed, plan, require_complete, &mut reasons);
        }
    }

    reasons
}

/// Phase identifiers of the plan, in the order the plan declares them.
pub fn plan_phase_ids(plan: &Value) -> Vec<String> {
    plan.get("phases")
        .and_then(Value::as_array)
        .map(|phases| {
            phases
                .iter()
                .filter_map(|phase| phase.get("id").and_then(Value::as_str))
                .map(|id| id.trim().to_string())
                .collect()
        })
        .unwrap_or_default()
}

/// The claimed list must be the plan's phases, in order, truncated at some
/// point — and, when leaving the state, not truncated at all.
fn check_against_plan(
    claimed: &[String],
    plan: &Value,
    require_complete: bool,
    reasons: &mut Vec<String>,
) {
    let expected = plan_phase_ids(plan);
    if expected.is_empty() {
        // A plan with no phases is the plan gate's problem, not this one's.
        return;
    }

    if claimed.len() > expected.len() {
        reasons.push(format!(
            "implementation.json claims {} phases but the plan declares {}",
            claimed.len(),
            expected.len()
        ));
        return;
    }

    for (index, id) in claimed.iter().enumerate() {
        if id != &expected[index] {
            reasons.push(format!(
                "implementation.json claims {id:?} at position {index}, but the plan declares \
                 {:?} there; phases are verified in the plan's order and may not be skipped or \
                 reordered. If the plan was revised through `revise-plan`, this means the \
                 revision changed a phase that was already claimed -- a phase that has been \
                 verified cannot be changed under it. Revise only the phases still outstanding, \
                 or start a new run",
                expected[index]
            ));
            return;
        }
    }

    if require_complete && claimed.len() != expected.len() {
        let missing: Vec<&str> =
            expected[claimed.len()..].iter().map(String::as_str).collect();
        reasons.push(format!(
            "implementation.json has not claimed every phase of the plan; still outstanding: {}",
            missing.join(", ")
        ));
    }
}

/// The phase whose checkpoint `phase-complete` should verify: the last claimed.
///
/// `None` when nothing is claimed yet, which is a gate failure with a clearer
/// message than any downstream lookup would produce.
pub fn phase_under_verification(document: &Value) -> Option<String> {
    document
        .get("phases")
        .and_then(Value::as_array)?
        .last()?
        .get("id")
        .and_then(Value::as_str)
        .map(|id| id.trim().to_string())
}

/// Commit a phase's diff is measured FROM: the commit recorded for the phase
/// before it, or `base_commit` when it is the first.
///
/// `None` when no boundary is recorded, in which case the caller falls back to
/// the cumulative range and says so.
pub fn diff_base_for(document: &Value, phase_id: &str) -> Option<String> {
    let entries = document.get("phases").and_then(Value::as_array)?;
    let position = entries.iter().position(|entry| {
        entry.get("id").and_then(Value::as_str).map(str::trim) == Some(phase_id)
    })?;
    if position == 0 {
        return document
            .get("base_commit")
            .and_then(Value::as_str)
            .map(|c| c.trim().to_string());
    }
    entries[position - 1]
        .get("commit")
        .and_then(Value::as_str)
        .map(|c| c.trim().to_string())
        .filter(|c| !c.is_empty())
}

/// Everything static guidance cannot say, because it is frozen before any plan
/// exists: which phase is which, what its tasks are, and what its checkpoint
/// will run.
///
/// Deliberately does NOT claim to know where the run is. The provider sees the
/// documents, not the journal, so it cannot tell an accepted phase from a
/// claimed-and-rejected one. Guessing would be worse than saying so: an author
/// told "you are on P3" when they are on P2 will act on it. Instead this states
/// what the cursor says and gives the rule that resolves it.
pub fn live_cursor(artifact_root: &std::path::Path) -> String {
    let read = |name: &str| {
        crate::gates::artifacts::read_document(artifact_root, name).map(|(_, value)| value)
    };

    let Ok(plan) = read("plan.json") else {
        return "\n\n--- CURRENT POSITION ---\n\nplan.json could not be read, so no phase \
                information is available. That is a problem to fix before anything else: the \
                phase loop reads it on every request."
            .to_string();
    };
    let expected = plan_phase_ids(&plan);

    let mut out = String::from("\n\n--- CURRENT POSITION ---\n\n");
    out.push_str(&format!(
        "The approved plan declares {} phase(s): {}.\n\n",
        expected.len(),
        if expected.is_empty() { "(none)".to_string() } else { expected.join(", ") }
    ));

    let cursor = match read("implementation.json") {
        Ok(cursor) => cursor,
        Err(error) => {
            out.push_str(&format!(
                "implementation.json is not readable yet ({error}).\n\nWrite it before doing \
                 any work:\n\n  {{\n    \"revision\": \"1\",\n    \"plan_revision\": \"{}\",\n    \
                 \"base_commit\": \"<the commit this change starts from>\",\n    \"phases\": []\n  }}\n",
                plan.get("revision").and_then(Value::as_str).unwrap_or("1")
            ));
            return out;
        }
    };

    let plan_revision = plan.get("revision").and_then(Value::as_str).unwrap_or("");
    let claimed_revision = cursor.get("plan_revision").and_then(Value::as_str).unwrap_or("");
    if !plan_revision.is_empty() && claimed_revision != plan_revision {
        out.push_str(&format!(
            "WARNING: implementation.json descends from plan revision {claimed_revision:?} but \
             the current plan is revision {plan_revision:?}. Every gate in this state will refuse \
             until they agree.\n\n"
        ));
    }

    let claimed: Vec<String> = cursor
        .get("phases")
        .and_then(Value::as_array)
        .map(|entries| {
            entries
                .iter()
                .filter_map(|entry| entry.get("id").and_then(Value::as_str))
                .map(|id| id.trim().to_string())
                .collect()
        })
        .unwrap_or_default();

    match claimed.last() {
        None => {
            out.push_str(
                "implementation.json claims no phases yet, so nothing is under verification. \
                 Start the first phase: do its work, then append it to `phases` and request \
                 `phase-complete`.\n",
            );
        }
        Some(last) => {
            out.push_str(&format!(
                "implementation.json claims: {}.\n\n`phase-complete` verifies the LAST claim, \
                 which is {last:?}.\n\nThis provider reads your documents, not the run journal, \
                 so it cannot tell you whether {last:?} has already been accepted. `run show` \
                 can. If it has, append the next phase below and work on it; if it has not, fix \
                 {last:?} and request `phase-complete` again WITHOUT touching the list.\n",
                claimed.join(", ")
            ));
        }
    }

    let next = expected.iter().find(|id| !claimed.contains(id));
    for (heading, id) in [("THE PHASE UNDER VERIFICATION", claimed.last()), ("THE NEXT UNCLAIMED PHASE", next)]
    {
        let Some(id) = id else { continue };
        let Some(phase) = find_phase(&plan, id) else { continue };
        out.push_str(&format!("\n--- {heading}: {id} ---\n\n"));
        out.push_str(&describe_phase(&phase, expected.last().map(String::as_str) == Some(id.as_str())));
    }

    if next.is_none() && claimed.len() == expected.len() && !expected.is_empty() {
        out.push_str(
            "\nEvery phase of the plan is claimed. Once the last one is accepted, request \
             `implementation-ready`.\n",
        );
    }
    out
}

/// The parts of a phase a worker needs in front of them.
fn describe_phase(phase: &Value, is_final: bool) -> String {
    let mut out = String::new();
    if let Some(goal) = phase.get("goal").and_then(Value::as_str) {
        out.push_str(&format!("goal: {goal}\n\n"));
    }
    if let Some(tasks) = phase.get("tasks").and_then(Value::as_array) {
        out.push_str("tasks:\n");
        for task in tasks {
            let id = task.get("id").and_then(Value::as_str).unwrap_or("?");
            let title = task.get("title").and_then(Value::as_str).unwrap_or("");
            out.push_str(&format!("  - {id}: {title}\n"));
            // `done_when` is a list of conditions, not one sentence: a task can
            // owe several observable outcomes and each is judged on its own.
            for condition in task
                .get("done_when")
                .and_then(Value::as_array)
                .map(|items| items.iter().filter_map(Value::as_str).collect::<Vec<_>>())
                .unwrap_or_default()
            {
                out.push_str(&format!("      done_when: {condition}\n"));
            }
        }
        out.push('\n');
    }

    let checkpoint = phase.get("checkpoint");
    let commands = checkpoint
        .and_then(|value| value.get("commands"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if commands.is_empty() {
        out.push_str("checkpoint commands: none declared\n");
    } else {
        out.push_str("checkpoint commands (these must exit 0):\n");
        for command in &commands {
            let name = command.get("name").and_then(Value::as_str).unwrap_or("?");
            let argv: Vec<&str> = command
                .get("run")
                .and_then(Value::as_array)
                .map(|items| items.iter().filter_map(Value::as_str).collect())
                .unwrap_or_default();
            out.push_str(&format!("  - {name}: {}\n", argv.join(" ")));
        }
    }

    let mut axes: Vec<String> = checkpoint
        .and_then(|value| value.get("review"))
        .and_then(|review| review.get("axes"))
        .and_then(Value::as_array)
        .map(|items| items.iter().filter_map(Value::as_str).map(str::to_string).collect())
        .unwrap_or_default();
    let appended = is_final && !axes.iter().any(|axis| axis == "design-faithful");
    if appended {
        axes.push("design-faithful".to_string());
    }
    if axes.is_empty() {
        out.push_str("checkpoint review: none declared; the diff is not judged for this phase\n");
    } else {
        out.push_str(&format!("checkpoint review axes: {}\n", axes.join(", ")));
        if appended {
            out.push_str(
                "  (`design-faithful` was added by the provider because this is the final \
                 phase, where the whole change exists to be compared against the design)\n",
            );
        }
        out.push_str(
            "  The review judges the actual diff of your work. There is nothing to write.\n",
        );
    }
    out
}

fn find_phase(plan: &Value, phase_id: &str) -> Option<Value> {
    plan.get("phases")?
        .as_array()?
        .iter()
        .find(|phase| phase.get("id").and_then(Value::as_str).map(str::trim) == Some(phase_id))
        .cloned()
}

fn check_text(value: Option<&Value>, label: &str, reasons: &mut Vec<String>) {
    match value {
        None | Some(Value::Null) => {
            reasons.push(format!("implementation.json is missing required {label}"));
        }
        Some(Value::String(text)) if text.trim().is_empty() => {
            reasons.push(format!("implementation.json {label} must not be empty"));
        }
        Some(Value::String(_)) => {}
        Some(_) => reasons.push(format!("implementation.json {label} must be a string")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn plan() -> Value {
        json!({
            "revision": "1",
            "phases": [ { "id": "P1" }, { "id": "P2" }, { "id": "P3" } ]
        })
    }

    fn cursor(phases: Value) -> Value {
        json!({
            "revision": "1",
            "plan_revision": "1",
            "base_commit": "abc123",
            "phases": phases
        })
    }

    fn rich_plan() -> Value {
        json!({
            "revision": "1",
            "phases": [
                {
                    "id": "P1",
                    "goal": "lay the persistence down",
                    "tasks": [{ "id": "T1", "title": "add the table", "done_when": ["migration applies"] }],
                    "checkpoint": {
                        "commands": [{ "name": "unit", "run": ["cargo", "test"] }],
                        "review": { "axes": ["tasks-actually-done"] }
                    }
                },
                {
                    "id": "P2",
                    "goal": "expose it",
                    "tasks": [{ "id": "T2", "title": "add the endpoint", "done_when": ["GET returns 200"] }],
                    "checkpoint": { "commands": [], "review": { "axes": ["no-scope-creep"] } }
                }
            ]
        })
    }

    fn staged(name: &str, cursor: Option<Value>) -> std::path::PathBuf {
        let root = std::env::temp_dir().join(format!("sc-cursor-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();
        std::fs::write(root.join("plan.json"), rich_plan().to_string()).unwrap();
        if let Some(cursor) = cursor {
            std::fs::write(root.join("implementation.json"), cursor.to_string()).unwrap();
        }
        root
    }

    /// Static guidance is frozen before any plan exists, so this is the only
    /// surface that can name a phase. If it stops naming one, the author is left
    /// reading the plan by hand every step.
    #[test]
    fn live_guidance_names_the_phase_and_its_checkpoint() {
        let root = staged("named", Some(cursor(json!([{ "id": "P1", "commit": "c1" }]))));
        let text = live_cursor(&root);
        assert!(text.contains("P1"), "{text}");
        assert!(text.contains("add the table"), "{text}");
        assert!(text.contains("cargo test"), "{text}");
        assert!(text.contains("tasks-actually-done"), "{text}");
        // The next phase is shown too, because the provider cannot tell whether
        // P1 has been accepted and must not guess.
        assert!(text.contains("NEXT UNCLAIMED PHASE"), "{text}");
        assert!(text.contains("add the endpoint"), "{text}");
    }

    /// The automatic final-phase axis has to be visible where the author is
    /// standing, or it reads as an unexplained extra judgment.
    #[test]
    fn live_guidance_shows_the_appended_final_axis() {
        let root = staged(
            "final",
            Some(cursor(json!([{ "id": "P1", "commit": "c1" }, { "id": "P2", "commit": "c2" }]))),
        );
        let text = live_cursor(&root);
        assert!(text.contains("design-faithful"), "{text}");
        assert!(text.contains("added by the provider"), "{text}");
        assert!(text.contains("implementation-ready"), "{text}");
    }

    #[test]
    fn live_guidance_tells_a_fresh_run_what_to_write() {
        let root = staged("fresh", None);
        let text = live_cursor(&root);
        assert!(text.contains("base_commit"), "{text}");
        assert!(text.contains("\"phases\": []"), "{text}");
    }

    /// A cursor pointing at a superseded plan is the failure that would
    /// otherwise present as every gate in the state refusing for no stated
    /// reason.
    #[test]
    fn live_guidance_warns_when_the_cursor_descends_from_another_plan() {
        let mut stale = cursor(json!([]));
        stale["plan_revision"] = json!("0");
        let root = staged("stale", Some(stale));
        let text = live_cursor(&root);
        assert!(text.contains("WARNING"), "{text}");
    }

    #[test]
    fn an_empty_cursor_is_valid_before_the_first_phase() {
        assert_eq!(check(&cursor(json!([])), Some(&plan()), false), Vec::<String>::new());
    }

    #[test]
    fn a_partial_prefix_is_valid_mid_flight() {
        let doc = cursor(json!([{ "id": "P1", "commit": "def" }]));
        assert!(check(&doc, Some(&plan()), false).is_empty());
    }

    /// Mid-flight a partial list is correct; leaving the state it is not.
    #[test]
    fn a_partial_prefix_is_rejected_when_completeness_is_required() {
        let doc = cursor(json!([{ "id": "P1" }]));
        assert!(check(&doc, Some(&plan()), false).is_empty());
        let reasons = check(&doc, Some(&plan()), true);
        assert!(reasons.iter().any(|r| r.contains("P2") && r.contains("P3")));
    }

    #[test]
    fn the_full_list_in_order_satisfies_completeness() {
        let doc = cursor(json!([{ "id": "P1" }, { "id": "P2" }, { "id": "P3" }]));
        assert!(check(&doc, Some(&plan()), true).is_empty());
    }

    #[test]
    fn skipping_a_phase_is_rejected() {
        let doc = cursor(json!([{ "id": "P1" }, { "id": "P3" }]));
        let reasons = check(&doc, Some(&plan()), false);
        assert!(reasons.iter().any(|r| r.contains("position 1")));
    }

    #[test]
    fn reordering_phases_is_rejected() {
        let doc = cursor(json!([{ "id": "P2" }]));
        assert!(!check(&doc, Some(&plan()), false).is_empty());
    }

    #[test]
    fn claiming_a_phase_twice_is_rejected() {
        let doc = cursor(json!([{ "id": "P1" }, { "id": "P1" }]));
        assert!(check(&doc, Some(&plan()), false)
            .iter()
            .any(|r| r.contains("more than once")));
    }

    #[test]
    fn claiming_more_phases_than_the_plan_has_is_rejected() {
        let doc = cursor(json!([
            { "id": "P1" }, { "id": "P2" }, { "id": "P3" }, { "id": "P4" }
        ]));
        assert!(check(&doc, Some(&plan()), false)
            .iter()
            .any(|r| r.contains("claims 4 phases")));
    }

    #[test]
    fn commit_is_optional_but_must_be_a_non_empty_string_when_present() {
        let mut doc = cursor(json!([{ "id": "P1" }]));
        assert!(check(&doc, Some(&plan()), false).is_empty());
        doc["phases"][0]["commit"] = json!("");
        assert!(!check(&doc, Some(&plan()), false).is_empty());
    }

    #[test]
    fn unknown_fields_are_rejected_at_both_levels() {
        let mut doc = cursor(json!([{ "id": "P1" }]));
        doc["notes"] = json!("hello");
        doc["phases"][0]["duration"] = json!(12);
        let reasons = check(&doc, Some(&plan()), false);
        assert!(reasons.iter().any(|r| r.contains("notes")));
        assert!(reasons.iter().any(|r| r.contains("duration")));
    }

    #[test]
    fn a_missing_phases_field_says_to_write_an_empty_array() {
        let doc = json!({ "revision": "1", "plan_revision": "1", "base_commit": "a" });
        let reasons = check(&doc, Some(&plan()), false);
        assert!(reasons.iter().any(|r| r.contains("empty array")));
    }

    #[test]
    fn the_phase_under_verification_is_the_last_claimed() {
        let doc = cursor(json!([{ "id": "P1" }, { "id": "P2" }]));
        assert_eq!(phase_under_verification(&doc).as_deref(), Some("P2"));
        assert_eq!(phase_under_verification(&cursor(json!([]))), None);
    }

    /// The first phase measures from `base_commit`; later phases measure from
    /// the phase before them, which is what keeps a review scoped to one phase.
    #[test]
    fn the_diff_base_is_the_previous_boundary() {
        let doc = cursor(json!([
            { "id": "P1", "commit": "c1" },
            { "id": "P2", "commit": "c2" }
        ]));
        assert_eq!(diff_base_for(&doc, "P1").as_deref(), Some("abc123"));
        assert_eq!(diff_base_for(&doc, "P2").as_deref(), Some("c1"));
    }

    /// Without a recorded boundary there is nothing to diff from; the caller
    /// falls back to the cumulative range rather than guessing.
    #[test]
    fn an_uncommitted_previous_phase_yields_no_base() {
        let doc = cursor(json!([{ "id": "P1" }, { "id": "P2" }]));
        assert_eq!(diff_base_for(&doc, "P1").as_deref(), Some("abc123"));
        assert_eq!(diff_base_for(&doc, "P2"), None);
    }

    #[test]
    fn plan_comparison_is_skipped_when_the_plan_is_unavailable() {
        let doc = cursor(json!([{ "id": "whatever" }]));
        assert!(check(&doc, None, true).is_empty());
    }

    #[test]
    fn wrong_types_are_reported_rather_than_panicking() {
        let doc = json!({
            "revision": 1, "plan_revision": [], "base_commit": {}, "phases": "no"
        });
        assert_eq!(check(&doc, None, false).len(), 4);
    }
}
