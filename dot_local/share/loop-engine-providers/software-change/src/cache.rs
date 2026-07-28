//! Replay of semantic judgments for a document that has not changed.
//!
//! Judges are not deterministic, and a rejected attempt costs the author
//! nothing to repeat. Without this, the cheapest way past a semantic gate is to
//! request the same unchanged document again until the sampling falls your way
//! — the verdict becomes a lottery ticket rather than a judgment. Every blind
//! reviewer of this gate raised it.
//!
//! So a judgment is stored under a key covering everything that could
//! legitimately change it: the judged content, the rubrics, the axes selected,
//! and the models. An identical re-request replays the stored verdict instead of
//! resampling. Change the content and the key changes, so a genuine fix is
//! judged afresh — which is the behaviour an honest author wants anyway.
//!
//! What this does NOT do, and the README says so too: it is not a security
//! boundary. The cache sits under `artifact_root`, which the author writes, so
//! an author determined to resample can delete it. That is deliberate — a cache
//! that could block a judgment when it cannot be read would be worse — and it
//! is why the claim here is "an unchanged document gets its previous answer",
//! not "resampling is impossible".
//!
//! This makes the provider stateful, which it otherwise is not. The state is
//! deliberately disposable: it lives beside the run's own artifacts, a miss is
//! always safe, and any read or write failure degrades to judging normally.

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::path::{Path, PathBuf};

use crate::util::sha256_hex;

/// Directory under `artifact_root` holding replayable judgments.
const CACHE_DIR: &str = ".judgments";

/// Field carried by every judged document and read by no rubric. Excluded from
/// the key: see `canonical_document`.
const UNJUDGED_FIELD: &str = "revision";

#[derive(Debug, Serialize, Deserialize)]
pub struct CachedAxis {
    pub axis: String,
    pub passed: bool,
    pub reason: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CachedJudgment {
    pub passed: bool,
    pub consensus_reason: String,
    pub axes: Vec<CachedAxis>,
    /// Recorded for auditing, never used to decide a hit.
    pub judged_at_unix: u64,
}

/// The part of a document a judgment actually depends on.
///
/// Keying on raw bytes would make the cache trivially avoidable: re-indenting
/// the file, or reordering its keys, produces different bytes and an identical
/// document, and the judges would be rolled again for an edit no judge could
/// see. So keys are sorted and whitespace is dropped before hashing. Array order
/// is preserved — the order of `acceptance` entries is content, not formatting.
///
/// `revision` is removed for the same reason from the other direction: no rubric
/// reads it, so bumping it alone changes nothing a judge would look at, and
/// bumping it alongside a real edit changes the key through that edit anyway.
/// Leaving it in would have handed the author a one-character resample button.
pub fn canonical_document(document: &Value) -> Vec<u8> {
    let mut canonical = ordered(document);
    if let Some(fields) = canonical.as_object_mut() {
        fields.remove(UNJUDGED_FIELD);
    }
    serde_json::to_vec(&canonical).unwrap_or_else(|_| canonical.to_string().into_bytes())
}

/// The same value with every object's keys in a fixed order.
fn ordered(value: &Value) -> Value {
    match value {
        Value::Object(fields) => {
            let mut names: Vec<&String> = fields.keys().collect();
            names.sort();
            let mut sorted = Map::new();
            for name in names {
                if let Some(field) = fields.get(name) {
                    sorted.insert(name.clone(), ordered(field));
                }
            }
            Value::Object(sorted)
        }
        Value::Array(items) => Value::Array(items.iter().map(ordered).collect()),
        other => other.clone(),
    }
}

/// Identity of a judgment: anything that could change the answer.
///
/// Models are included because a stronger model is a different judge, not the
/// same judge in a better mood. The rubric hash is included so that improving a
/// rubric re-opens documents that passed under the old one.
///
/// `context` is the upstream document a subject is judged AGAINST, when it has
/// one — `design.json` is judged against `intent.json`. It belongs in the key
/// because it is an input to the judgment: a design that passed against one
/// intent has not been judged against a different one. Without it, editing
/// `intent.json` in place — tightening a constraint, adding a non-goal, changing
/// the outcome, all without bumping its `revision` — would leave an unchanged
/// design replaying a verdict that was never made about the intent now on disk.
/// Subjects with no context (intent itself) hash the empty string, so their keys
/// are unaffected.
pub fn key(
    gate_id: &str,
    document: &Value,
    context: Option<&Value>,
    rubrics_hash: &str,
    axis_ids: &[&str],
    axis_model: &str,
    consensus_model: &str,
) -> String {
    let context_digest = match context {
        Some(context) => sha256_hex(&canonical_document(context)),
        None => String::new(),
    };
    let material = format!(
        "{gate_id}\n{}\n{context_digest}\n{rubrics_hash}\n{}\n{axis_model}\n{consensus_model}",
        sha256_hex(&canonical_document(document)),
        axis_ids.join(",")
    );
    sha256_hex(material.as_bytes()).replace("sha256:", "")
}

fn path_for(artifact_root: &Path, key: &str) -> PathBuf {
    artifact_root.join(CACHE_DIR).join(format!("{key}.json"))
}

/// A stored judgment for this exact key, if one is readable.
///
/// Every failure — missing file, unreadable directory, corrupt or partially
/// written JSON — is a miss. A cache that cannot be read must never be able to
/// block a judgment.
pub fn load(artifact_root: &Path, key: &str) -> Option<CachedJudgment> {
    let raw = std::fs::read(path_for(artifact_root, key)).ok()?;
    serde_json::from_slice(&raw).ok()
}

/// Store a judgment, best effort.
///
/// Written to a temporary file and renamed, so a crash mid-write leaves either
/// the old entry or none — never a truncated one that would be read back as a
/// verdict. Returns whether it was stored, for diagnostics only; a failure to
/// store is not a failure to judge.
pub fn store(artifact_root: &Path, key: &str, judgment: &CachedJudgment) -> bool {
    let path = path_for(artifact_root, key);
    let Some(parent) = path.parent() else {
        return false;
    };
    if std::fs::create_dir_all(parent).is_err() {
        return false;
    }
    let Ok(encoded) = serde_json::to_vec_pretty(judgment) else {
        return false;
    };
    let temporary = path.with_extension("json.tmp");
    if std::fs::write(&temporary, encoded).is_err() {
        return false;
    }
    std::fs::rename(&temporary, &path).is_ok()
}

pub fn now_unix() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn doc() -> Value {
        json!({ "revision": "1", "problem": "p", "acceptance": ["a", "b"] })
    }

    fn dir(name: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!("sc-cache-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).unwrap();
        path
    }

    fn judgment(passed: bool) -> CachedJudgment {
        CachedJudgment {
            passed,
            consensus_reason: "because".to_string(),
            axes: vec![CachedAxis {
                axis: "scope-fenced".to_string(),
                passed,
                reason: "r".to_string(),
            }],
            judged_at_unix: now_unix(),
        }
    }

    #[test]
    fn a_stored_judgment_is_replayed() {
        let root = dir("roundtrip");
        let k = key("intent-semantic", &doc(), None, "rub", &["a"], "m", "c");
        assert!(load(&root, &k).is_none());
        assert!(store(&root, &k, &judgment(false)));
        let replayed = load(&root, &k).expect("stored judgment must be readable");
        assert!(!replayed.passed);
        assert_eq!(replayed.axes[0].axis, "scope-fenced");
    }

    /// The point of the whole module: an edited document is judged afresh.
    #[test]
    fn changing_the_document_changes_the_key() {
        let mut edited = doc();
        edited["problem"] = json!("a different problem");
        let a = key("intent-semantic", &doc(), None, "rub", &["a"], "m", "c");
        let b = key("intent-semantic", &edited, None, "rub", &["a"], "m", "c");
        assert_ne!(a, b);
    }

    /// Reformatting is not editing. Key order and whitespace are invisible to a
    /// judge, so they must be invisible to the key as well.
    #[test]
    fn reordering_keys_does_not_change_the_key() {
        let one = json!({ "revision": "1", "problem": "p", "acceptance": ["a", "b"] });
        let other = json!({ "acceptance": ["a", "b"], "problem": "p", "revision": "1" });
        assert_eq!(
            key("intent-semantic", &one, None, "rub", &["a"], "m", "c"),
            key("intent-semantic", &other, None, "rub", &["a"], "m", "c")
        );
    }

    /// The order of `acceptance` entries is content, not formatting.
    #[test]
    fn reordering_a_list_does_change_the_key() {
        let one = json!({ "acceptance": ["a", "b"] });
        let other = json!({ "acceptance": ["b", "a"] });
        assert_ne!(
            key("intent-semantic", &one, None, "rub", &["a"], "m", "c"),
            key("intent-semantic", &other, None, "rub", &["a"], "m", "c")
        );
    }

    /// Bumping `revision` and changing nothing else IS the resample move. No
    /// rubric reads the field, so it must not be able to mint a fresh key.
    #[test]
    fn bumping_revision_alone_does_not_change_the_key() {
        let mut bumped = doc();
        bumped["revision"] = json!("2");
        assert_eq!(
            key("intent-semantic", &doc(), None, "rub", &["a"], "m", "c"),
            key("intent-semantic", &bumped, None, "rub", &["a"], "m", "c")
        );
    }

    /// A real edit is still judged afresh when `revision` moves with it.
    #[test]
    fn a_revision_bump_carrying_a_real_edit_changes_the_key() {
        let mut edited = doc();
        edited["revision"] = json!("2");
        edited["problem"] = json!("a different problem");
        assert_ne!(
            key("intent-semantic", &doc(), None, "rub", &["a"], "m", "c"),
            key("intent-semantic", &edited, None, "rub", &["a"], "m", "c")
        );
    }

    /// Improving a rubric must re-open documents that passed under the old one,
    /// and a different model is a different judge.
    #[test]
    fn rubrics_axes_models_and_gate_all_participate_in_the_key() {
        let d = doc();
        let base = key("intent-semantic", &d, None, "rub", &["a"], "m", "c");
        assert_ne!(base, key("intent-semantic", &d, None, "rub2", &["a"], "m", "c"));
        assert_ne!(base, key("intent-semantic", &d, None, "rub", &["a", "b"], "m", "c"));
        assert_ne!(base, key("intent-semantic", &d, None, "rub", &["a"], "m2", "c"));
        assert_ne!(base, key("intent-semantic", &d, None, "rub", &["a"], "m", "c2"));
        assert_ne!(base, key("design-semantic", &d, None, "rub", &["a"], "m", "c"));
    }

    /// A design is judged AGAINST an intent. Replaying a verdict reached against
    /// a different intent would answer a question nobody asked: an intent edited
    /// in place — a tightened constraint, an added non-goal — leaves the design
    /// byte-identical, so without the context in the key the stale pass returns.
    #[test]
    fn the_context_document_participates_in_the_key() {
        let design = json!({ "revision": "1", "approach": "a", "elements": ["e"] });
        let intent = json!({ "revision": "1", "outcome": "o", "constraints": [] });
        let tightened = json!({ "revision": "1", "outcome": "o", "constraints": ["must stay offline"] });

        let base = key("design-semantic", &design, Some(&intent), "rub", &["a"], "m", "c");
        assert_ne!(
            base,
            key("design-semantic", &design, Some(&tightened), "rub", &["a"], "m", "c"),
            "an edited intent must re-open the design"
        );
        // The context is canonicalised like the document: reformatting it, or
        // bumping only its revision, is not a re-judgement.
        let reformatted = json!({ "constraints": [], "revision": "7", "outcome": "o" });
        assert_eq!(
            base,
            key("design-semantic", &design, Some(&reformatted), "rub", &["a"], "m", "c")
        );
        // A subject with no context is unaffected by any of this.
        assert_ne!(base, key("design-semantic", &design, None, "rub", &["a"], "m", "c"));
    }

    #[test]
    fn a_corrupt_entry_is_a_miss_rather_than_a_verdict() {
        let root = dir("corrupt");
        let k = key("intent-semantic", &doc(), None, "rub", &["a"], "m", "c");
        std::fs::create_dir_all(root.join(CACHE_DIR)).unwrap();
        std::fs::write(root.join(CACHE_DIR).join(format!("{k}.json")), b"{ truncated").unwrap();
        assert!(load(&root, &k).is_none());
    }

    #[test]
    fn an_unwritable_cache_does_not_fail_the_judgment() {
        let missing = PathBuf::from("/nonexistent/root/for/this/test");
        let k = key("intent-semantic", &doc(), None, "rub", &["a"], "m", "c");
        assert!(!store(&missing, &k, &judgment(true)));
        assert!(load(&missing, &k).is_none());
    }
}
