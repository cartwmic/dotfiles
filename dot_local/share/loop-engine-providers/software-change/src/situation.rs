//! Where the run actually stands, rendered for `live_guidance`.
//!
//! Static guidance is frozen into the stored graph at run creation, before any
//! document exists. It can state the contract — what to write, what the gates
//! check, what the judges are told — and it must stay correct for a run that
//! arrives at a state for the first time and for one that comes back to it on
//! a revision edge. It cannot tell those two apart.
//!
//! This can. The engine does not report which state a run came from, and the
//! provider never sees the journal, so "where did I come from" is not
//! answerable. It is also the wrong question. What matters is not the path but
//! the condition it leaves behind: whether documents exist BELOW the one this
//! state authors, and whether they still point at the version above them.
//!
//! That is answerable from `artifact_root` alone, deterministically, and it
//! survives a return taken twice. So the situation reported here is derived
//! from the documents on disk, never from run history.

use std::path::Path;

use serde_json::Value;

/// One document in the chain, and the field it uses to name its parent.
///
/// The chain is the whole invalidation story: each document carries the parent
/// revision it was written against, and its deterministic gate refuses it when
/// that no longer matches what the parent says. Revising anything high in the
/// chain therefore refuses everything below it until each is re-pointed — which
/// means re-read, and re-judged.
struct Link {
    /// File name under `artifact_root`.
    file: &'static str,
    /// Field naming the revision of the document above. `None` for the root.
    parent_field: Option<&'static str>,
    /// What that document is called in prose.
    label: &'static str,
}

const CHAIN: &[Link] = &[
    Link { file: "intent.json", parent_field: None, label: "the intent" },
    Link { file: "design.json", parent_field: Some("intent_revision"), label: "the design" },
    Link { file: "plan.json", parent_field: Some("subject_revision"), label: "the plan" },
    Link {
        file: "implementation.json",
        parent_field: Some("plan_revision"),
        label: "the phase cursor",
    },
];

/// Index into `CHAIN` of the document a state authors.
fn authored_by(state: &str) -> Option<usize> {
    match state {
        "explore" => Some(0),
        "design" => Some(1),
        "plan" => Some(2),
        "implement" => Some(3),
        _ => None,
    }
}

fn revision_of(document: &Value) -> &str {
    document.get("revision").and_then(Value::as_str).unwrap_or("")
}

/// Live text for a state that authors a document: whether anything downstream
/// exists, and exactly what a revision here would refuse.
///
/// Returns an empty string for states with nothing to report, so the caller can
/// append unconditionally.
pub fn live_situation(state: &str, artifact_root: &Path) -> String {
    let Some(index) = authored_by(state) else {
        return String::new();
    };

    let read = |name: &str| {
        crate::gates::artifacts::read_document(artifact_root, name).map(|(_, value)| value)
    };
    let documents: Vec<Option<Value>> =
        CHAIN.iter().map(|link| read(link.file).ok()).collect();

    let subject = &CHAIN[index];
    let downstream: Vec<usize> = ((index + 1)..CHAIN.len())
        .filter(|position| documents[*position].is_some())
        .collect();

    let mut out = String::from("\n\n--- WHERE THIS RUN STANDS ---\n\n");

    if downstream.is_empty() {
        out.push_str(&format!(
            "Nothing downstream of {} exists yet, so this is the first pass through this \
             state. Write {} and request the gate; nothing is waiting on a revision here.\n",
            subject.label, subject.file
        ));
        return out;
    }

    // Something below this state exists, which means the run has been further
    // along than it is now. Say so plainly, then price the edit.
    out.push_str(&format!(
        "Documents BELOW {} already exist, so the run has been further along than this. \
         You are revising, not authoring from nothing.\n\n",
        subject.file
    ));

    for position in &downstream {
        let document = documents[*position].as_ref().expect("filtered on Some");
        let link = &CHAIN[*position];
        let revision = revision_of(document);
        let claimed = link
            .parent_field
            .and_then(|field| document.get(field))
            .and_then(Value::as_str)
            .unwrap_or("");
        let parent = documents[position - 1].as_ref().map(revision_of).unwrap_or("");

        let state_note = if parent.is_empty() {
            "its parent is not readable, so the link cannot be checked".to_string()
        } else if claimed == parent {
            format!(
                "names {} revision {parent:?} -- currently in agreement",
                CHAIN[position - 1].file
            )
        } else {
            format!(
                "names {} revision {claimed:?}, but that file is now revision {parent:?} -- \
                 ALREADY STALE, and its gate will refuse it until it is re-pointed",
                CHAIN[position - 1].file
            )
        };

        out.push_str(&format!(
            "  {} (revision {revision:?}) {state_note}\n",
            link.file
        ));
    }

    out.push_str(&format!(
        "\nWhat an edit here costs. Raising the `revision` of {} makes every document listed \
         here stale: each carries the parent revision it was written against, and its \
         deterministic gate refuses it until that value is re-pointed at the new one. \
         Re-pointing means re-reading, and passing the gate again means being judged again. \
         The cascade runs the whole way down, in order, and there is no edge that skips a \
         state on the way back.\n",
        subject.file
    ));

    if downstream.contains(&3) {
        let claimed = documents[3]
            .as_ref()
            .and_then(|cursor| cursor.get("phases"))
            .and_then(Value::as_array)
            .map(Vec::len)
            .unwrap_or(0);
        out.push_str(&format!(
            "\nVerified work sits downstream: the phase cursor claims {claimed} phase(s). A \
             revised plan may reorder, rename or drop only phases that have NOT been claimed. \
             Touch a claimed one and the cursor's prefix check refuses it, because a phase that \
             has been verified cannot be changed under it.\n"
        ));
    }

    out.push_str(
        "\nIf that price is not worth paying, the alternative is to work within the document \
         as it was accepted. If it is, make the edit deliberately and expect to walk the whole \
         chain forward again.\n",
    );

    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write(root: &Path, name: &str, body: &str) {
        std::fs::write(root.join(name), body).expect("write fixture");
    }

    fn temp(tag: &str) -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!("sc-situation-{tag}"));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).expect("create fixture root");
        path
    }

    #[test]
    fn a_cold_state_is_reported_as_a_first_pass() {
        let root = temp("cold");
        write(&root, "intent.json", r#"{"revision":"1"}"#);

        let text = live_situation("explore", &root);
        assert!(text.contains("first pass"), "{text}");
        assert!(!text.contains("You are revising"), "{text}");
    }

    #[test]
    fn a_return_names_every_downstream_document() {
        let root = temp("return");
        write(&root, "intent.json", r#"{"revision":"2"}"#);
        write(&root, "design.json", r#"{"revision":"3","intent_revision":"2"}"#);
        write(&root, "plan.json", r#"{"revision":"4","subject_revision":"3"}"#);

        let text = live_situation("explore", &root);
        assert!(text.contains("You are revising"), "{text}");
        assert!(text.contains("design.json"), "{text}");
        assert!(text.contains("plan.json"), "{text}");
        assert!(text.contains("in agreement"), "{text}");
    }

    #[test]
    fn an_already_stale_link_is_called_out() {
        let root = temp("stale");
        write(&root, "intent.json", r#"{"revision":"3"}"#);
        write(&root, "design.json", r#"{"revision":"3","intent_revision":"2"}"#);

        let text = live_situation("explore", &root);
        assert!(text.contains("ALREADY STALE"), "{text}");
        assert!(text.contains("\"2\""), "{text}");
        assert!(text.contains("\"3\""), "{text}");
    }

    #[test]
    fn verified_phases_are_priced_when_the_cursor_exists() {
        let root = temp("cursor");
        write(&root, "intent.json", r#"{"revision":"1"}"#);
        write(&root, "design.json", r#"{"revision":"1","intent_revision":"1"}"#);
        write(&root, "plan.json", r#"{"revision":"1","subject_revision":"1"}"#);
        write(
            &root,
            "implementation.json",
            r#"{"revision":"1","plan_revision":"1","base_commit":"abc","phases":[{"id":"P1"},{"id":"P2"}]}"#,
        );

        let text = live_situation("plan", &root);
        assert!(text.contains("claims 2 phase(s)"), "{text}");
        assert!(text.contains("prefix check"), "{text}");
    }

    #[test]
    fn a_state_that_authors_nothing_reports_nothing() {
        let root = temp("none");
        assert!(live_situation("implementation-review", &root).is_empty());
        assert!(live_situation("end", &root).is_empty());
    }
}
