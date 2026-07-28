//! Artifact gates: review and hand-off decisions read from JSON documents
//! beneath the run's immutable `artifact_root` input.
//!
//! Each gate answers one question — does the document for this step exist, does
//! it point at the revision it claims to descend from, and (for reviews) does
//! its verdict match the event being requested?

use serde::Deserialize;
use serde_json::json;
use std::path::Path;

use crate::protocol::{Evidence, GateVerdict};
use crate::util::{contained_join, file_uri, sha256_hex};

#[derive(Debug, Deserialize, Default)]
struct ArtifactDoc {
    #[serde(default)]
    revision: String,
    /// design.json → the intent revision it was derived from.
    #[serde(default)]
    intent_revision: String,
    /// implementation.json → the plan revision it was derived from.
    #[serde(default)]
    plan_revision: String,
    /// plan.json and every review → the revision of the document under review.
    #[serde(default)]
    subject_revision: String,
    /// Reviews only: `approved` or `changes_requested`.
    #[serde(default)]
    verdict: String,
    /// The final review only: the commit the reviewer actually read.
    #[serde(default)]
    subject_commit: String,
}

/// What a gate must find on disk, and how it must link to its predecessor.
struct Rule {
    /// Document the gate reads and attaches as evidence.
    path: &'static str,
    /// Evidence kind recorded for that document.
    kind: &'static str,
    /// Document whose `revision` the subject must reference, if any.
    parent: Option<&'static str>,
    /// Field on the subject holding that parent revision.
    link_field: LinkField,
    /// Verdict the document must carry, for review gates.
    expected_verdict: Option<&'static str>,
    /// Template conformance applied on top of the generic checks.
    template: Template,
    /// Whether the document must name the commit its author reviewed.
    ///
    /// Only the final review does. Every other review names a document
    /// revision, which is enough because documents do not change underneath a
    /// reviewer without their revision changing. Code does.
    reviews_a_commit: bool,
}

#[derive(Clone, Copy, PartialEq)]
#[allow(clippy::enum_variant_names)]
enum Template {
    None,
    Intent,
    Design,
    Plan,
    /// The phase cursor. Checked in two modes: mid-flight a partial phase list
    /// is correct, but the gate leaving `implement` requires the whole plan.
    ImplementationCursor { require_complete: bool },
}

#[derive(Clone, Copy)]
enum LinkField {
    None,
    IntentRevision,
    PlanRevision,
    SubjectRevision,
}

fn rule_for(gate_id: &str) -> Option<Rule> {
    let rule = match gate_id {
        "intent-ready" => Rule {
            path: "intent.json",
            kind: "intent-document",
            parent: None,
            link_field: LinkField::None,
            expected_verdict: None,
            template: Template::Intent,
            reviews_a_commit: false,
        },
        "design-ready" => Rule {
            path: "design.json",
            kind: "design-document",
            parent: Some("intent.json"),
            link_field: LinkField::IntentRevision,
            expected_verdict: None,
            template: Template::Design,
            reviews_a_commit: false,
        },
        "plan-ready" => Rule {
            path: "plan.json",
            kind: "plan-document",
            parent: Some("design.json"),
            link_field: LinkField::SubjectRevision,
            expected_verdict: None,
            template: Template::Plan,
            reviews_a_commit: false,
        },
        // Verifying one phase reads the same cursor, but a partial list is
        // exactly what it should find.
        "phase-complete" => Rule {
            path: "implementation.json",
            kind: "implementation-cursor",
            parent: Some("plan.json"),
            link_field: LinkField::PlanRevision,
            expected_verdict: None,
            template: Template::ImplementationCursor { require_complete: false },
            reviews_a_commit: false,
        },
        "implementation-ready" => Rule {
            path: "implementation.json",
            kind: "implementation-cursor",
            parent: Some("plan.json"),
            link_field: LinkField::PlanRevision,
            expected_verdict: None,
            template: Template::ImplementationCursor { require_complete: true },
            reviews_a_commit: false,
        },
        "implementation-review-approved" | "implementation-review-changes-requested" => Rule {
            path: "reviews/implementation-review.json",
            kind: "implementation-review",
            parent: Some("implementation.json"),
            link_field: LinkField::SubjectRevision,
            expected_verdict: Some(verdict_for(gate_id)),
            template: Template::None,
            reviews_a_commit: true,
        },
        _ => return None,
    };
    Some(rule)
}

fn verdict_for(gate_id: &str) -> &'static str {
    if gate_id.ends_with("-approved") {
        "approved"
    } else {
        "changes_requested"
    }
}

/// True when `gate_id` is served by this module rather than by command gates.
pub fn handles(gate_id: &str) -> bool {
    rule_for(gate_id).is_some()
}

/// Read a document beneath `artifact_root` as raw bytes and parsed JSON.
///
/// Exposed so the semantic gate judges byte-for-byte the same document this
/// module validated, rather than re-deriving a path and risking a different
/// one. Bytes are returned alongside the value because evidence digests must
/// cover the file as written, not a re-serialization of it.
pub fn read_document(
    artifact_root: &Path,
    relative: &str,
) -> Result<(Vec<u8>, serde_json::Value), String> {
    let path = contained_join(artifact_root, relative)?;
    let bytes =
        std::fs::read(&path).map_err(|error| format!("cannot read {relative}: {error}"))?;
    let value = serde_json::from_slice(&bytes)
        .map_err(|error| format!("{relative} is not valid JSON: {error}"))?;
    Ok((bytes, value))
}

pub struct Outcome {
    pub verdict: GateVerdict,
    pub evidence: Vec<Evidence>,
    /// Human-readable reason the gate failed, for the journal-visible note.
    pub reason: Option<String>,
}

/// Evaluate one artifact gate.
///
/// A gate never mutates anything: it reads, judges, and returns. The engine
/// alone decides whether the transition commits.
pub fn evaluate(
    gate_id: &str,
    artifact_root: &Path,
    work_root: Option<&Path>,
    invocation_tag: &str,
) -> Outcome {
    let Some(rule) = rule_for(gate_id) else {
        return fail(gate_id, format!("gate {gate_id} is not an artifact gate"));
    };

    let subject_path = match contained_join(artifact_root, rule.path) {
        Ok(path) => path,
        Err(error) => return fail(gate_id, error),
    };

    let bytes = match std::fs::read(&subject_path) {
        Ok(bytes) => bytes,
        Err(error) => {
            return fail(gate_id, format!("cannot read {}: {error}", rule.path));
        }
    };

    // Parsed twice on purpose: once loosely for the shared revision/verdict
    // fields, once as raw JSON so template conformance can report per-field
    // violations instead of a single opaque deserialization error.
    let raw: serde_json::Value = match serde_json::from_slice(&bytes) {
        Ok(value) => value,
        Err(error) => {
            return fail(gate_id, format!("{} is not valid JSON: {error}", rule.path));
        }
    };
    let subject: ArtifactDoc = serde_json::from_value(raw.clone()).unwrap_or_default();

    if subject.revision.trim().is_empty() {
        return fail(gate_id, format!("{} is missing a non-empty `revision`", rule.path));
    }

    // Linkage is checked BEFORE template conformance because the design
    // template compares its coverage citations against the intent this
    // document references. Reporting a set difference computed against a
    // document the author was not writing against would be noise on top of
    // the real error.
    // Revision linkage: the subject must name the exact revision of the
    // document it descends from. This is what makes a stale review fail
    // instead of silently approving superseded work.
    if let Some(parent_name) = rule.parent {
        let parent_path = match contained_join(artifact_root, parent_name) {
            Ok(path) => path,
            Err(error) => return fail(gate_id, error),
        };
        let parent: ArtifactDoc = match std::fs::read(&parent_path)
            .map_err(|error| format!("cannot read {parent_name}: {error}"))
            .and_then(|raw| {
                serde_json::from_slice(&raw)
                    .map_err(|error| format!("{parent_name} is not valid JSON: {error}"))
            }) {
            Ok(doc) => doc,
            Err(error) => return fail(gate_id, error),
        };

        let claimed: &str = match rule.link_field {
            LinkField::IntentRevision => subject.intent_revision.as_str(),
            LinkField::PlanRevision => subject.plan_revision.as_str(),
            LinkField::SubjectRevision => subject.subject_revision.as_str(),
            LinkField::None => "",
        };

        if claimed.trim().is_empty() {
            return fail(
                gate_id,
                format!("{} does not reference a {parent_name} revision", rule.path),
            );
        }
        if claimed != parent.revision {
            return fail(
                gate_id,
                format!(
                    "{} references {parent_name} revision {claimed} but the current revision is {}",
                    rule.path, parent.revision
                ),
            );
        }
    }

    // Template conformance reports every violation at once; fixing a document
    // one rejected field per attempt would be miserable.
    let violations = match rule.template {
        Template::None => Vec::new(),
        Template::Intent => super::intent::check(&raw),
        // The design template compares its coverage citations against the
        // intent's acceptance list, so the upstream document is read here. An
        // unreadable intent yields `None`: the linkage check below reports that
        // properly instead of this check blaming the design for it.
        Template::Design => {
            let intent = rule
                .parent
                .and_then(|name| read_document(artifact_root, name).ok())
                .map(|(_, value)| value);
            super::design::check(&raw, intent.as_ref())
        }
        // Same shape as the design template, one level down: the plan's
        // `covers` claims are compared against the design's `elements`, so the
        // upstream document is read here.
        Template::Plan => {
            let design = rule
                .parent
                .and_then(|name| read_document(artifact_root, name).ok())
                .map(|(_, value)| value);
            super::plan::check(&raw, design.as_ref())
        }
        // Compared against the plan's phase list, so the plan is read here for
        // the same reason the design is read for a plan.
        Template::ImplementationCursor { require_complete } => {
            let plan = rule
                .parent
                .and_then(|name| read_document(artifact_root, name).ok())
                .map(|(_, value)| value);
            super::implementation::check(&raw, plan.as_ref(), require_complete)
        }
    };
    if !violations.is_empty() {
        return fail(gate_id, violations.join("; "));
    }

    // Verdict agreement: requesting `approved` against a document that says
    // `changes_requested` is a policy failure, not an engine error.
    if let Some(expected) = rule.expected_verdict {
        if subject.verdict != expected {
            return fail(
                gate_id,
                format!(
                    "{} records verdict {:?} but this event requires {expected}",
                    rule.path, subject.verdict
                ),
            );
        }
    }

    let evidence = Evidence {
        id: format!("{invocation_tag}-artifact-{gate_id}"),
        kind: rule.kind.to_string(),
        // Revision is appended because the engine drops evidence metadata, and
        // "which revision did this gate actually accept" is the fact an auditor
        // needs when reading the run back. Locators are opaque to the engine.
        locator: format!("{}#revision={}", file_uri(&subject_path), subject.revision),
        digest: Some(sha256_hex(&bytes)),
        media_type: Some("application/json".to_string()),
        metadata: Some(json!({
            "gate_id": gate_id,
            "artifact_path": rule.path,
            "revision": subject.revision,
        })),
    };

    let mut evidence = vec![evidence];

    // What the reviewer actually read. A document review can link by revision
    // because a document cannot change without its revision changing; a code
    // review cannot, because the tree moves underneath it silently.
    //
    // Recorded, not enforced, for the same reason rubric drift is: refusing
    // would strand a finished change over a commit that may be a rebase, a
    // merge, or an unrelated file landing after the reviewer was satisfied. What
    // the reader needs is to know the review was written against a different
    // tree, and now the journal says so.
    if rule.reviews_a_commit {
        let claimed = subject.subject_commit.trim();
        let head = work_root.and_then(super::diff::head_commit);
        match (claimed, head.as_deref()) {
            // Required, unlike the drift it enables. A review with no
            // `subject_commit` states nothing about what was read, so there is
            // nothing to detect drift against and the whole mechanism is
            // decorative. Costing the author one line is the cheaper half of
            // that trade.
            ("", _) => {
                return fail(
                    gate_id,
                    format!(
                        "{} is missing a non-empty `subject_commit`; a code review must name the \
                         commit it read, because the tree moves under a reviewer without any \
                         revision changing",
                        rule.path
                    ),
                )
            }
            // Git could not answer -- an empty repository, or none at all. A
            // missing fact is not evidence of drift.
            (_, None) => {}
            (claimed, Some(head)) if claimed != head => {
                evidence.push(Evidence {
                    id: format!("{invocation_tag}-review-commit-drift"),
                    kind: "review-commit-drift".to_string(),
                    locator: crate::util::locator(
                        "review:drift",
                        &format!(
                            "{} was written against commit {claimed}, and the repository is now \
                             at {head}; the tree moved after the review was recorded. The verdict \
                             stands, and the semantic judgment on this same transition read the \
                             CURRENT tree rather than the reviewed one.",
                            rule.path
                        ),
                    ),
                    digest: None,
                    media_type: Some("text/plain".to_string()),
                    metadata: Some(json!({
                        "reviewed_commit": claimed,
                        "head_commit": head,
                    })),
                });
            }
            _ => {}
        }
    }

    Outcome {
        verdict: GateVerdict { gate_id: gate_id.to_string(), passed: true },
        evidence,
        reason: None,
    }
}

fn fail(gate_id: &str, reason: String) -> Outcome {
    Outcome {
        verdict: GateVerdict { gate_id: gate_id.to_string(), passed: false },
        evidence: Vec::new(),
        reason: Some(reason),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    /// Per-test directory: these tests run in parallel, so a shared fixture path
    /// would let one test delete another's artifacts mid-run.
    fn fixture(name: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!("sc-gate-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(root.join("reviews")).unwrap();
        std::fs::write(root.join("intent.json"), CONFORMING_INTENT.as_bytes()).unwrap();
        root
    }

    /// Downstream gates only read `revision` from intent.json, but it must still
    /// satisfy the intent template for the `intent-ready` gate itself.
    pub(super) const CONFORMING_INTENT: &str = r#"{
      "revision": "1",
      "problem": "Callers of calc have no way to subtract, so every caller reimplements it inconsistently.",
      "outcome": "Callers can subtract two numbers using calc directly.",
      "acceptance": [
        "Subtracting two numbers returns their difference",
        "Existing addition behaviour is unchanged"
      ],
      "non_goals": ["Multiplication or division"]
    }"#;

    /// A design that satisfies the design template against CONFORMING_INTENT.
    /// Coverage must cite both acceptance lines verbatim.
    pub(super) const CONFORMING_DESIGN: &str = r#"{
      "revision": "1",
      "intent_revision": "1",
      "approach": "calc gains a subtraction operation alongside the existing addition.",
      "elements": ["calc -- owns the arithmetic operations callers can ask for"],
      "decisions": [{
        "decision": "Subtraction is a first-class operation rather than negated addition.",
        "rationale": "Callers name the operation they want; expressing it as negation would put the transformation in every caller. Revisit if the operation set grows past what one surface can hold."
      }],
      "coverage": [
        {
          "acceptance": "Subtracting two numbers returns their difference",
          "delivered_by": "calc -- the new subtraction operation"
        },
        {
          "acceptance": "Existing addition behaviour is unchanged",
          "delivered_by": "calc -- addition keeps its current behaviour; subtraction is additive to the surface"
        }
      ],
      "risks": ["Assumes no caller relies on calc rejecting subtraction requests."]
    }"#;

    fn write(root: &Path, name: &str, body: &str) {
        std::fs::write(root.join(name), body).unwrap();
    }

    #[test]
    fn intent_gate_requires_a_revision() {
        let root = fixture("intent");
        assert!(evaluate("intent-ready", &root, None, "tag").verdict.passed);

        write(&root, "intent.json", r#"{"revision":"  "}"#);
        assert!(!evaluate("intent-ready", &root, None, "tag").verdict.passed);
    }

    /// Schema violations are reported together so an author fixes the document
    /// once rather than discovering one missing field per attempt.
    #[test]
    fn intent_gate_reports_every_schema_violation_at_once() {
        let root = fixture("template");
        write(&root, "intent.json", r#"{"revision":"1"}"#);
        let outcome = evaluate("intent-ready", &root, None, "tag");
        assert!(!outcome.verdict.passed);
        let reason = outcome.reason.unwrap();
        for field in ["problem", "outcome", "acceptance", "non_goals"] {
            assert!(reason.contains(field), "expected {field} in: {reason}");
        }
    }

    /// Terseness is the semantic judge's business. The schema layer must accept
    /// a structurally valid but thin document.
    #[test]
    fn intent_gate_accepts_a_thin_but_conforming_document() {
        let root = fixture("thin");
        write(
            &root,
            "intent.json",
            r#"{"revision":"1","problem":"x","outcome":"y","acceptance":["z"],"non_goals":["n"]}"#,
        );
        assert!(evaluate("intent-ready", &root, None, "tag").verdict.passed);
    }

    #[test]
    fn missing_document_fails_rather_than_erroring() {
        let root = fixture("missing");
        let outcome = evaluate("design-ready", &root, None, "tag");
        assert!(!outcome.verdict.passed);
        assert!(outcome.reason.unwrap().contains("design.json"));
    }

    #[test]
    fn stale_revision_linkage_fails() {
        let root = fixture("stale");
        let stale =
            CONFORMING_DESIGN.replace(r#""intent_revision": "1""#, r#""intent_revision": "0""#);
        write(&root, "design.json", &stale);
        let outcome = evaluate("design-ready", &root, None, "tag");
        assert!(!outcome.verdict.passed);
        assert!(outcome.reason.unwrap().contains("revision 0"));

        write(&root, "design.json", CONFORMING_DESIGN);
        let ok = evaluate("design-ready", &root, None, "tag");
        assert!(ok.verdict.passed, "{:?}", ok.reason);
    }

    /// Linkage is reported before coverage: a design written against a
    /// superseded intent must be told THAT, not handed a set difference
    /// computed against a document it was never written against.
    #[test]
    fn stale_linkage_is_reported_before_coverage_differences() {
        let root = fixture("order");
        let stale = CONFORMING_DESIGN
            .replace(r#""intent_revision": "1""#, r#""intent_revision": "0""#)
            .replace("Existing addition behaviour is unchanged", "Something never said");
        write(&root, "design.json", &stale);
        let reason = evaluate("design-ready", &root, None, "tag").reason.unwrap();
        assert!(reason.contains("revision 0"), "{reason}");
        assert!(!reason.contains("coverage"), "{reason}");
    }

    /// The deterministic half of the design gate: a dropped acceptance line is
    /// caught by the artifact gate, before any model call is spent.
    #[test]
    fn design_gate_catches_an_uncited_acceptance_line() {
        let root = fixture("coverage");
        let partial = CONFORMING_DESIGN
            .replace("Existing addition behaviour is unchanged", "Addition still works somehow");
        write(&root, "design.json", &partial);
        let outcome = evaluate("design-ready", &root, None, "tag");
        assert!(!outcome.verdict.passed);
        let reason = outcome.reason.unwrap();
        assert!(reason.contains("Existing addition behaviour is unchanged"), "{reason}");
        assert!(reason.contains("verbatim"), "{reason}");
    }

    /// `implementation-review` is the only review state left, so it is where
    /// verdict agreement is now pinned. Requesting `approved` against a document
    /// that says `changes_requested` is a policy failure, not an engine error.
    #[test]
    fn review_verdict_must_match_the_requested_event() {
        let root = fixture("verdict");
        write(&root, "implementation.json", r#"{"revision":"1","plan_revision":"1"}"#);
        write(
            &root,
            "reviews/implementation-review.json",
            r#"{"revision":"1","subject_revision":"1","subject_commit":"abc","verdict":"changes_requested"}"#,
        );
        assert!(!evaluate("implementation-review-approved", &root, None, "tag").verdict.passed);
        assert!(
            evaluate("implementation-review-changes-requested", &root, None, "tag").verdict.passed
        );
    }

    /// Revision linkage is what makes a stale review fail instead of silently
    /// approving superseded work.
    #[test]
    fn a_review_of_a_superseded_revision_fails() {
        let root = fixture("superseded");
        write(&root, "implementation.json", r#"{"revision":"2","plan_revision":"1"}"#);
        write(
            &root,
            "reviews/implementation-review.json",
            r#"{"revision":"1","subject_revision":"1","subject_commit":"abc","verdict":"approved"}"#,
        );
        assert!(!evaluate("implementation-review-approved", &root, None, "tag").verdict.passed);
    }

    /// Regression: deterministic per-gate evidence IDs collided with the record
    /// already stored whenever a `changes-requested` loop re-entered a state,
    /// which the engine rejects as `provider.evidence.malformed`.
    #[test]
    fn evidence_ids_differ_across_invocations_of_the_same_gate() {
        let root = fixture("evidence-ids");
        let first = evaluate("intent-ready", &root, None, "aaaaaaaaaaaaaaaa").evidence.into_iter().next().unwrap();
        let second = evaluate("intent-ready", &root, None, "bbbbbbbbbbbbbbbb").evidence.into_iter().next().unwrap();
        assert_ne!(first.id, second.id);
        assert!(first.id.len() <= 128, "evidence ID must fit identifier_utf8_bytes");
    }

    #[test]
    fn traversal_out_of_the_artifact_root_is_refused() {
        let root = fixture("traversal");
        assert!(crate::util::contained_join(&root, "../escape.json").is_err());
        assert!(crate::util::contained_join(&root, "/etc/passwd").is_err());
        assert!(crate::util::contained_join(&root, "reviews/ok.json").is_ok());
    }
}

#[cfg(test)]
mod plan_wiring_tests {
    use super::tests::{CONFORMING_DESIGN, CONFORMING_INTENT};
    use super::*;
    use std::path::PathBuf;

    /// Per-test directory, for the same parallelism reason as the sibling suite.
    fn plan_fixture(name: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!("sc-plan-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(root.join("reviews")).unwrap();
        std::fs::write(root.join("intent.json"), CONFORMING_INTENT.as_bytes()).unwrap();
        std::fs::write(root.join("design.json"), CONFORMING_DESIGN.as_bytes()).unwrap();
        root
    }

    fn write(root: &Path, name: &str, body: &str) {
        std::fs::write(root.join(name), body).unwrap();
    }

    /// A plan that conforms to the template and claims every design element.
    fn conforming_plan() -> String {
        r#"{
          "revision": "1",
          "subject_revision": "1",
          "phases": [{
            "id": "P1",
            "goal": "Add the subtraction operation",
            "covers": ["calc -- owns the arithmetic operations callers can ask for"],
            "tasks": [{
              "id": "T001",
              "title": "Add subtraction to calc",
              "depends_on": [],
              "delivers": "calc answers a subtraction request with the difference",
              "context": ["design.json"],
              "done_when": ["Subtracting two numbers returns their difference"]
            }],
            "checkpoint": { "commands": [{ "name": "test", "run": ["cargo", "test"] }] }
          }]
        }"#
        .to_string()
    }

    /// The template must actually be reached through the artifact gate, not just
    /// unit-tested in isolation.
    #[test]
    fn plan_gate_applies_the_plan_template() {
        let root = plan_fixture("template-applied");
        write(&root, "plan.json", &conforming_plan());
        assert!(evaluate("plan-ready", &root, None, "tag").verdict.passed);

        // A plan that drops a design element must fail through the same path.
        let dropped = conforming_plan().replace(
            r#""covers": ["calc -- owns the arithmetic operations callers can ask for"],"#,
            r#""covers": [],"#,
        );
        write(&root, "plan.json", &dropped);
        let outcome = evaluate("plan-ready", &root, None, "tag");
        assert!(!outcome.verdict.passed);
        assert!(outcome.reason.unwrap().contains("no phase `covers`"));
    }

    /// Referential integrity is reported through the gate, not swallowed.
    #[test]
    fn plan_gate_reports_a_dependency_cycle() {
        let root = plan_fixture("cycle");
        let cyclic = conforming_plan().replace(
            r#""depends_on": [],"#,
            r#""depends_on": ["T001"],"#,
        );
        write(&root, "plan.json", &cyclic);
        let outcome = evaluate("plan-ready", &root, None, "tag");
        assert!(!outcome.verdict.passed);
        assert!(outcome.reason.unwrap().contains("depends on itself"));
    }

    /// Linkage still precedes the template: a plan written against a superseded
    /// design must be told that, not handed a coverage set-difference computed
    /// against a document it was never written for.
    #[test]
    fn stale_design_linkage_is_reported_before_coverage() {
        let root = plan_fixture("stale");
        write(&root, "plan.json", &conforming_plan().replace(
            r#""subject_revision": "1","#,
            r#""subject_revision": "0","#,
        ));
        let outcome = evaluate("plan-ready", &root, None, "tag");
        assert!(!outcome.verdict.passed);
        let reason = outcome.reason.unwrap();
        assert!(reason.contains("design.json revision 0"));
        assert!(!reason.contains("covers"));
    }
}

#[cfg(test)]
mod commit_link_tests {
    use super::*;
    use serde_json::json;
    use std::path::PathBuf;

    fn staged(name: &str, review: serde_json::Value) -> PathBuf {
        let root = std::env::temp_dir().join(format!("sc-commit-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(root.join("reviews")).unwrap();
        std::fs::write(
            root.join("plan.json"),
            json!({ "revision": "1", "phases": [{ "id": "P1" }] }).to_string(),
        )
        .unwrap();
        std::fs::write(
            root.join("implementation.json"),
            json!({
                "revision": "1",
                "plan_revision": "1",
                "base_commit": "abc",
                "phases": [{ "id": "P1" }]
            })
            .to_string(),
        )
        .unwrap();
        std::fs::write(root.join("reviews/implementation-review.json"), review.to_string())
            .unwrap();
        root
    }

    /// A review with no `subject_commit` states nothing about what was read, so
    /// there is nothing for drift detection to compare against. Required.
    #[test]
    fn a_final_review_must_name_the_commit_it_read() {
        let root = staged(
            "missing",
            json!({ "revision": "1", "subject_revision": "1", "verdict": "approved" }),
        );
        let outcome = evaluate("implementation-review-approved", &root, None, "tag");
        assert!(!outcome.verdict.passed);
        assert!(outcome.reason.unwrap().contains("subject_commit"));
    }

    /// Only the FINAL review reviews code. A design review linking by revision
    /// is complete, because a document cannot change without its revision
    /// changing.
    #[test]
    fn document_reviews_are_not_asked_for_a_commit() {
        assert!(!rule_for("design-ready").unwrap().reviews_a_commit);
        assert!(!rule_for("plan-ready").unwrap().reviews_a_commit);
        assert!(rule_for("implementation-review-approved").unwrap().reviews_a_commit);
        // The document review states are gone; only the code review remains.
        assert!(rule_for("design-review-approved").is_none());
        assert!(rule_for("plan-review-approved").is_none());
    }

    /// Without a repository there is no HEAD to compare against, and a missing
    /// fact is not evidence of drift: the gate must not invent one.
    #[test]
    fn a_commit_that_cannot_be_compared_is_not_reported_as_drift() {
        let root = staged(
            "nogit",
            json!({
                "revision": "1",
                "subject_revision": "1",
                "subject_commit": "abc123",
                "verdict": "approved"
            }),
        );
        let outcome = evaluate("implementation-review-approved", &root, Some(&root), "tag");
        assert!(outcome.verdict.passed);
        assert!(!outcome.evidence.iter().any(|e| e.kind == "review-commit-drift"));
    }
}
