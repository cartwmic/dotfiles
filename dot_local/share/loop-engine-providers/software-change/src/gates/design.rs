//! Schema conformance for `design.json`, plus deterministic acceptance coverage.
//!
//! Two kinds of check live here, and both are mechanical:
//!
//! 1. **Shape.** Is the document there, is the field set exactly the expected
//!    one, and does every field carry the right type? Presence and type only —
//!    no length minimums, no entry counts. Length is not a proxy for substance.
//!
//! 2. **Coverage citation.** Does `coverage` name every acceptance statement of
//!    the intent this design descends from, verbatim, and nothing else? This is
//!    a set comparison over strings, so it is decidable without a model, and a
//!    dropped acceptance criterion is caught before a single judge is spawned.
//!
//! Citation coverage is emphatically **not** entailment. That a design cites an
//! acceptance line says nothing about whether the named element could deliver
//! it. Entailment is the `acceptance-covered` axis of the `design-semantic`
//! gate. The two layers are complementary; neither substitutes for the other.

use serde_json::Value;

/// The document is a CLOSED schema, for the same reason `intent.json` is: an
/// unknown field is content no gate looks at, and a task list sitting beside the
/// design in an `implementation_steps` array would pass every judge unseen.
const KNOWN_FIELDS: &[&str] = &[
    "revision",
    "intent_revision",
    "approach",
    "elements",
    "decisions",
    "coverage",
    "risks",
];

const REQUIRED_TEXT: &[&str] = &["intent_revision", "approach"];
const REQUIRED_LISTS: &[&str] = &["elements", "risks"];

const DECISION_FIELDS: &[&str] = &["decision", "rationale", "rejected"];
const DECISION_REQUIRED_TEXT: &[&str] = &["decision", "rationale"];
const COVERAGE_FIELDS: &[&str] = &["acceptance", "delivered_by"];

/// Returns one reason per violation; empty means the document conforms.
///
/// `intent` is the parsed `intent.json` this design descends from. When it is
/// absent — unreadable, or not yet written — the coverage comparison is skipped
/// and the artifact gate's revision-linkage check reports the real problem.
pub fn check(document: &Value, intent: Option<&Value>) -> Vec<String> {
    let mut reasons = Vec::new();

    let Some(object) = document.as_object() else {
        reasons.push("design.json must be a JSON object".to_string());
        return reasons;
    };

    for key in object.keys() {
        if !KNOWN_FIELDS.contains(&key.as_str()) {
            reasons.push(format!(
                "design.json has unknown field `{key}`; allowed fields are {}",
                KNOWN_FIELDS.join(", ")
            ));
        }
    }

    // `revision` is checked for emptiness because downstream gates compare it
    // literally to detect superseded documents. Mechanical, not a judgment.
    match document.get("revision") {
        None | Some(Value::Null) => {
            reasons.push("design.json is missing required field `revision`".to_string())
        }
        Some(Value::String(text)) if text.trim().is_empty() => {
            reasons.push("design.json field `revision` must not be empty".to_string())
        }
        Some(Value::String(_)) => {}
        Some(_) => reasons.push("design.json field `revision` must be a string".to_string()),
    }

    for field in REQUIRED_TEXT {
        check_text(document.get(field), &format!("`{field}`"), field, &mut reasons);
    }

    for field in REQUIRED_LISTS {
        match document.get(field) {
            None | Some(Value::Null) => {
                reasons.push(format!("design.json is missing required field `{field}`"))
            }
            Some(value) => check_string_array(value, field, &mut reasons),
        }
    }

    check_decisions(document.get("decisions"), &mut reasons);
    let cited = check_coverage(document.get("coverage"), &mut reasons);

    if let Some(intent) = intent {
        check_coverage_matches_intent(cited.as_deref(), intent, &mut reasons);
    }

    reasons
}

fn check_text(value: Option<&Value>, label: &str, field: &str, reasons: &mut Vec<String>) {
    match value {
        None | Some(Value::Null) => {
            reasons.push(format!("design.json is missing required field {label}"))
        }
        Some(Value::String(text)) if text.trim().is_empty() => {
            reasons.push(format!("design.json field {label} must not be empty"))
        }
        Some(Value::String(_)) => {}
        Some(_) => reasons.push(format!("design.json field {label} must be a string")),
        // `field` is kept in the signature so nested labels stay readable.
    }
    let _ = field;
}

fn check_string_array(value: &Value, field: &str, reasons: &mut Vec<String>) {
    let Some(items) = value.as_array() else {
        reasons.push(format!("design.json field `{field}` must be an array of strings"));
        return;
    };
    for (index, item) in items.iter().enumerate() {
        match item {
            Value::String(text) if text.trim().is_empty() => {
                reasons.push(format!("design.json `{field}[{index}]` must not be empty"))
            }
            Value::String(_) => {}
            _ => reasons.push(format!("design.json `{field}[{index}]` must be a string")),
        }
    }
}

fn check_decisions(value: Option<&Value>, reasons: &mut Vec<String>) {
    let Some(value) = value.filter(|value| !value.is_null()) else {
        reasons.push("design.json is missing required field `decisions`".to_string());
        return;
    };
    let Some(items) = value.as_array() else {
        reasons.push("design.json field `decisions` must be an array of objects".to_string());
        return;
    };
    for (index, item) in items.iter().enumerate() {
        let Some(object) = item.as_object() else {
            reasons.push(format!("design.json `decisions[{index}]` must be an object"));
            continue;
        };
        for key in object.keys() {
            if !DECISION_FIELDS.contains(&key.as_str()) {
                reasons.push(format!(
                    "design.json `decisions[{index}]` has unknown field `{key}`; allowed fields are {}",
                    DECISION_FIELDS.join(", ")
                ));
            }
        }
        for field in DECISION_REQUIRED_TEXT {
            check_text(
                object.get(*field),
                &format!("`decisions[{index}].{field}`"),
                field,
                reasons,
            );
        }
        // `rejected` is optional: a decision with no live alternative is a real
        // thing. Whether the omission is honest is the judges' business.
        if let Some(rejected) = object.get("rejected").filter(|value| !value.is_null()) {
            check_string_array(rejected, &format!("decisions[{index}].rejected"), reasons);
        }
    }
}

/// Validates the shape of `coverage` and returns the acceptance lines it cites.
fn check_coverage(value: Option<&Value>, reasons: &mut Vec<String>) -> Option<Vec<String>> {
    let Some(value) = value.filter(|value| !value.is_null()) else {
        reasons.push("design.json is missing required field `coverage`".to_string());
        return None;
    };
    let Some(items) = value.as_array() else {
        reasons.push("design.json field `coverage` must be an array of objects".to_string());
        return None;
    };

    let mut cited = Vec::new();
    let mut shape_ok = true;
    for (index, item) in items.iter().enumerate() {
        let Some(object) = item.as_object() else {
            reasons.push(format!("design.json `coverage[{index}]` must be an object"));
            shape_ok = false;
            continue;
        };
        for key in object.keys() {
            if !COVERAGE_FIELDS.contains(&key.as_str()) {
                reasons.push(format!(
                    "design.json `coverage[{index}]` has unknown field `{key}`; allowed fields are {}",
                    COVERAGE_FIELDS.join(", ")
                ));
                shape_ok = false;
            }
        }
        for field in COVERAGE_FIELDS {
            let before = reasons.len();
            check_text(
                object.get(*field),
                &format!("`coverage[{index}].{field}`"),
                field,
                reasons,
            );
            if reasons.len() != before {
                shape_ok = false;
            }
        }
        if let Some(Value::String(text)) = object.get("acceptance") {
            cited.push(text.trim().to_string());
        }
    }

    // Comparing a malformed coverage list against the intent would bury the real
    // shape error under a wall of set-difference noise.
    shape_ok.then_some(cited)
}

/// Every acceptance statement of the intent must be cited verbatim, and nothing
/// may be cited that the intent does not say.
fn check_coverage_matches_intent(cited: Option<&[String]>, intent: &Value, reasons: &mut Vec<String>) {
    let Some(cited) = cited else { return };
    let Some(acceptance) = intent.get("acceptance").and_then(Value::as_array) else {
        // A malformed intent is the intent gate's problem, not this one's.
        return;
    };
    let expected: Vec<String> = acceptance
        .iter()
        .filter_map(Value::as_str)
        .map(|text| text.trim().to_string())
        .collect();
    if expected.len() != acceptance.len() {
        return;
    }

    for line in &expected {
        let hits = cited.iter().filter(|entry| *entry == line).count();
        if hits == 0 {
            reasons.push(format!(
                "design.json `coverage` does not cite intent acceptance line {line:?}"
            ));
        } else if hits > 1 {
            reasons.push(format!(
                "design.json `coverage` cites intent acceptance line {line:?} {hits} times"
            ));
        }
    }
    for entry in cited {
        if !expected.contains(entry) {
            reasons.push(format!(
                "design.json `coverage` cites {entry:?}, which is not an acceptance line of the \
                 intent revision this design references; cite the intent text verbatim"
            ));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::check;
    use serde_json::{json, Value};

    fn intent() -> Value {
        json!({
            "revision": "1",
            "problem": "p",
            "outcome": "o",
            "acceptance": ["A happens", "B happens"],
            "non_goals": ["n"]
        })
    }

    fn conforming() -> Value {
        json!({
            "revision": "1",
            "intent_revision": "1",
            "approach": "one paragraph",
            "elements": ["thing -- does something"],
            "decisions": [{ "decision": "d", "rationale": "r", "rejected": ["alt"] }],
            "coverage": [
                { "acceptance": "A happens", "delivered_by": "thing" },
                { "acceptance": "B happens", "delivered_by": "thing" }
            ],
            "risks": ["something might go wrong"]
        })
    }

    #[test]
    fn a_conforming_document_passes() {
        assert!(check(&conforming(), Some(&intent())).is_empty());
    }

    /// The schema layer must not second-guess quality: terseness, a single
    /// element, or an empty risk list are the judges' business.
    #[test]
    fn terse_documents_and_empty_lists_are_accepted() {
        let mut doc = conforming();
        doc["approach"] = json!("x");
        doc["risks"] = json!([]);
        doc["decisions"] = json!([{ "decision": "d", "rationale": "r" }]);
        assert!(check(&doc, Some(&intent())).is_empty());
    }

    #[test]
    fn missing_required_fields_are_reported_together() {
        let doc = json!({ "revision": "1" });
        let reasons = check(&doc, None);
        assert_eq!(reasons.len(), 6, "{reasons:?}");
        for field in ["intent_revision", "approach", "elements", "decisions", "coverage", "risks"] {
            assert!(reasons.iter().any(|reason| reason.contains(field)), "{field}: {reasons:?}");
        }
    }

    /// A plan smuggled in beside the design must not pass unseen.
    #[test]
    fn unknown_fields_are_rejected_rather_than_ignored() {
        let mut doc = conforming();
        doc["implementation_steps"] = json!(["step one"]);
        let reasons = check(&doc, Some(&intent()));
        assert_eq!(reasons.len(), 1);
        assert!(reasons[0].contains("implementation_steps"));
    }

    #[test]
    fn a_dropped_acceptance_line_is_caught_without_a_model_call() {
        let mut doc = conforming();
        doc["coverage"] = json!([{ "acceptance": "A happens", "delivered_by": "thing" }]);
        let reasons = check(&doc, Some(&intent()));
        assert_eq!(reasons.len(), 1, "{reasons:?}");
        assert!(reasons[0].contains("B happens"));
    }

    /// Paraphrase is the common way a criterion is quietly softened.
    #[test]
    fn a_paraphrased_citation_is_rejected_as_uncovered_and_extra() {
        let mut doc = conforming();
        doc["coverage"] = json!([
            { "acceptance": "A happens", "delivered_by": "thing" },
            { "acceptance": "B mostly happens", "delivered_by": "thing" }
        ]);
        let reasons = check(&doc, Some(&intent()));
        assert_eq!(reasons.len(), 2, "{reasons:?}");
        assert!(reasons.iter().any(|reason| reason.contains("does not cite")));
        assert!(reasons.iter().any(|reason| reason.contains("verbatim")));
    }

    #[test]
    fn citing_the_same_line_twice_is_rejected() {
        let mut doc = conforming();
        doc["coverage"] = json!([
            { "acceptance": "A happens", "delivered_by": "thing" },
            { "acceptance": "A happens", "delivered_by": "other" },
            { "acceptance": "B happens", "delivered_by": "thing" }
        ]);
        let reasons = check(&doc, Some(&intent()));
        assert_eq!(reasons.len(), 1, "{reasons:?}");
        assert!(reasons[0].contains("2 times"));
    }

    /// Surrounding whitespace is not a defect worth an attempt.
    #[test]
    fn citations_match_after_trimming() {
        let mut doc = conforming();
        doc["coverage"] = json!([
            { "acceptance": "  A happens  ", "delivered_by": "thing" },
            { "acceptance": "B happens", "delivered_by": "thing" }
        ]);
        assert!(check(&doc, Some(&intent())).is_empty());
    }

    #[test]
    fn a_malformed_coverage_entry_suppresses_the_set_comparison() {
        let mut doc = conforming();
        doc["coverage"] = json!([{ "acceptance": 7, "delivered_by": "thing" }]);
        let reasons = check(&doc, Some(&intent()));
        // One shape error, and no set-difference noise on top of it.
        assert_eq!(reasons.len(), 1, "{reasons:?}");
        assert!(reasons[0].contains("coverage[0].acceptance"));
    }

    #[test]
    fn decision_entries_are_validated_field_by_field() {
        let mut doc = conforming();
        doc["decisions"] = json!([
            { "decision": "d" },
            { "decision": "d", "rationale": "r", "why": "not a field" },
            { "decision": "d", "rationale": "r", "rejected": [4] }
        ]);
        let reasons = check(&doc, Some(&intent()));
        assert_eq!(reasons.len(), 3, "{reasons:?}");
        assert!(reasons.iter().any(|reason| reason.contains("decisions[0].rationale")));
        assert!(reasons.iter().any(|reason| reason.contains("`why`")));
        assert!(reasons.iter().any(|reason| reason.contains("decisions[2].rejected[0]")));
    }

    #[test]
    fn coverage_is_not_compared_when_the_intent_is_unavailable() {
        let mut doc = conforming();
        doc["coverage"] = json!([{ "acceptance": "unrelated", "delivered_by": "thing" }]);
        assert!(check(&doc, None).is_empty());
    }
}
