//! Schema conformance for `intent.json`.
//!
//! This check answers exactly two questions: is the document there, and does it
//! have the right shape? Presence and type only.
//!
//! It deliberately does **not** judge quality. No character minimums, no entry
//! counts, no lexical heuristics. Length is not a proxy for substance, and a
//! count is not a proxy for a real scope fence. Semantic judgment belongs to the
//! `intent-semantic` gate, which asks language models to evaluate named axes.
//! Deterministic schema checks and semantic judgment are complementary layers;
//! neither can substitute for the other.

use serde_json::Value;

/// Fields the schema requires, and the type each must carry.
const REQUIRED_TEXT: &[&str] = &["problem", "outcome"];
const REQUIRED_LISTS: &[&str] = &["acceptance", "non_goals"];
const OPTIONAL_LISTS: &[&str] = &["constraints"];

/// The document is a CLOSED schema. An unknown field is rejected rather than
/// ignored, because no judge looks at one: an `implementation_plan` array sitting
/// beside the intent would put a plan inside the intent document with nothing in
/// the gate able to see it. Rejecting unknown fields is a structural rule, not a
/// judgment about substance.
const KNOWN_FIELDS: &[&str] = &[
    "revision",
    "problem",
    "outcome",
    "acceptance",
    "non_goals",
    "constraints",
];

/// Returns one reason per violation; empty means the document conforms.
pub fn check(document: &Value) -> Vec<String> {
    let mut reasons = Vec::new();

    if !document.is_object() {
        reasons.push("intent.json must be a JSON object".to_string());
        return reasons;
    }

    // `revision` is checked for emptiness, unlike every other field, because
    // downstream gates compare it literally to detect superseded documents. An
    // empty revision would make that linkage silently meaningless. This is a
    // mechanical requirement, not a quality judgment.
    match document.get("revision") {
        None | Some(Value::Null) => {
            reasons.push("intent.json is missing required field `revision`".to_string());
        }
        Some(Value::String(text)) if text.trim().is_empty() => {
            reasons.push("intent.json field `revision` must not be empty".to_string());
        }
        Some(Value::String(_)) => {}
        Some(_) => reasons.push("intent.json field `revision` must be a string".to_string()),
    }

    if let Some(object) = document.as_object() {
        for key in object.keys() {
            if !KNOWN_FIELDS.contains(&key.as_str()) {
                reasons.push(format!(
                    "intent.json has unknown field `{key}`; allowed fields are {}",
                    KNOWN_FIELDS.join(", ")
                ));
            }
        }
    }

    for field in REQUIRED_TEXT {
        match document.get(field) {
            None | Some(Value::Null) => {
                reasons.push(format!("intent.json is missing required field `{field}`"));
            }
            // Blank is rejected for the same reason an absent field is: there is
            // nothing there to judge. This is emptiness, not brevity — no
            // opinion is being expressed about how long the text should be.
            Some(Value::String(text)) if text.trim().is_empty() => {
                reasons.push(format!("intent.json field `{field}` must not be empty"));
            }
            Some(Value::String(_)) => {}
            Some(_) => reasons.push(format!("intent.json field `{field}` must be a string")),
        }
    }

    for field in REQUIRED_LISTS {
        match document.get(field) {
            None | Some(Value::Null) => {
                reasons.push(format!("intent.json is missing required field `{field}`"));
            }
            Some(value) => check_string_array(value, field, &mut reasons),
        }
    }

    for field in OPTIONAL_LISTS {
        if let Some(value) = document.get(field) {
            if !value.is_null() {
                check_string_array(value, field, &mut reasons);
            }
        }
    }

    reasons
}

fn check_string_array(value: &Value, field: &str, reasons: &mut Vec<String>) {
    let Some(items) = value.as_array() else {
        reasons.push(format!("intent.json field `{field}` must be an array of strings"));
        return;
    };
    for (index, item) in items.iter().enumerate() {
        match item {
            Value::String(text) if text.trim().is_empty() => {
                reasons.push(format!("intent.json `{field}[{index}]` must not be empty"));
            }
            Value::String(_) => {}
            _ => reasons.push(format!("intent.json `{field}[{index}]` must be a string")),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::check;
    use serde_json::json;

    fn conforming() -> serde_json::Value {
        json!({
            "revision": "1",
            "problem": "p",
            "outcome": "o",
            "acceptance": ["a"],
            "non_goals": ["n"]
        })
    }

    #[test]
    fn a_conforming_document_passes() {
        assert!(check(&conforming()).is_empty());
    }

    /// The schema layer must not second-guess quality: a terse document is the
    /// semantic judge's business, not the schema's.
    #[test]
    fn short_values_and_single_entries_are_accepted() {
        let doc = json!({
            "revision": "1",
            "problem": "x",
            "outcome": "y",
            "acceptance": ["z"],
            "non_goals": ["n"]
        });
        assert!(check(&doc).is_empty());
    }

    #[test]
    fn missing_required_fields_are_reported_together() {
        let doc = json!({ "revision": "1" });
        let reasons = check(&doc);
        assert_eq!(reasons.len(), 4);
        for field in ["problem", "outcome", "acceptance", "non_goals"] {
            assert!(reasons.iter().any(|r| r.contains(field)));
        }
    }

    #[test]
    fn an_empty_revision_is_rejected_because_linkage_depends_on_it() {
        let mut doc = conforming();
        doc["revision"] = json!("   ");
        assert!(!check(&doc).is_empty());
    }

    #[test]
    fn optional_constraints_are_validated_only_when_present() {
        let mut doc = conforming();
        assert!(check(&doc).is_empty());
        doc["constraints"] = json!(["a real limit"]);
        assert!(check(&doc).is_empty());
        doc["constraints"] = json!("not an array");
        assert!(!check(&doc).is_empty());
    }

    /// A plan smuggled in beside the intent must not pass unseen.
    #[test]
    fn unknown_fields_are_rejected_rather_than_ignored() {
        let mut doc = conforming();
        doc["implementation_plan"] = json!(["Use Redis", "Refactor batch.rs"]);
        let reasons = check(&doc);
        assert_eq!(reasons.len(), 1);
        assert!(reasons[0].contains("implementation_plan"));
    }

    #[test]
    fn blank_values_are_rejected_as_emptiness_not_brevity() {
        let mut doc = conforming();
        doc["outcome"] = json!("   ");
        doc["non_goals"] = json!(["  "]);
        assert_eq!(check(&doc).len(), 2);
    }

    #[test]
    fn wrong_types_are_reported_rather_than_panicking() {
        let doc = json!({
            "revision": 1,
            "problem": 42,
            "outcome": ["not a string"],
            "acceptance": "not an array",
            "non_goals": [7]
        });
        assert_eq!(check(&doc).len(), 5);
    }
}
