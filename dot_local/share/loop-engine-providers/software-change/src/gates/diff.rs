//! What the code actually says, extracted from git.
//!
//! Every gate before this one judges a document the author wrote. These two
//! judge the work itself, and the reason is the same reason a self-report was
//! rejected: an author summarising their own change is the least reliable
//! witness available, and the diff is sitting right there.
//!
//! Three properties are deliberate.
//!
//! **The working tree counts.** `git diff <base>` compares the base commit
//! against the tree as it stands, so uncommitted work is included. A gate that
//! only saw commits would pass a phase whose work exists only in the author's
//! editor, or fail one whose work is real but unstaged. Neither is honest.
//!
//! **Untracked files are shown in full.** New files are usually the substance of
//! a phase, and until they are added git will not mention them at all. Adding
//! them would mutate the repository, which a gate must never do, so each is
//! rendered with `git diff --no-index` against `/dev/null` -- read-only, and
//! produces a real patch.
//!
//! **Nothing is truncated.** A cap would silently drop hunks, and the dropped
//! one is exactly as likely as any other to be the one that mattered. Uncapped,
//! an oversized diff overruns the judge and surfaces as `evaluation_error` --
//! visible, and pointing at the real problem, which is a phase too large to
//! review. The measured size is recorded as evidence so the failure, when it
//! comes, is not a surprise.

use serde_json::{json, Map, Value};
use std::path::Path;
use std::process::Command;

use crate::gates::semantic::{DiffScope, Material, Prepared, Subject};
use crate::protocol::{Diagnostic, Evidence, GateVerdict};
use crate::util::{locator, sha256_hex};

/// Assembly could not proceed, and the reason is the author's document rather
/// than a broken environment.
pub struct Refused {
    pub reason: String,
    pub evidence: Vec<Evidence>,
}

/// Assembly could not proceed because the provider could not do its job.
pub struct Unavailable(pub Vec<Diagnostic>);

/// A phase that declares no review, which is legitimate and passes.
///
/// Boxed because the judged variant is far larger than the skipped one, and this
/// value is returned by every diff gate whether or not it judges.
pub enum Assembly {
    Judge(Box<Prepared>),
    NoReview { reason: String },
}

pub fn refusal(gate_id: &str, refused: Refused) -> crate::gates::semantic::Outcome {
    crate::gates::semantic::Outcome {
        verdict: GateVerdict { gate_id: gate_id.to_string(), passed: false },
        evidence: refused.evidence,
        reason: Some(refused.reason),
    }
}

/// Build the material for a diff subject.
///
/// Returns `Err(Ok(Refused))` when the author's documents make the judgment
/// impossible, and `Err(Err(Unavailable))` when the environment does.
#[allow(clippy::type_complexity)]
pub fn prepare(
    subject: &'static Subject,
    artifact_root: &Path,
    work_root: &Path,
    invocation_tag: &str,
) -> Result<Assembly, Result<Refused, Unavailable>> {
    let Material::Diff { scope, context_name } = subject.material else {
        return Err(Err(Unavailable(vec![Diagnostic::new(
            "provider.defect",
            format!("subject {} is not a diff subject", subject.gate_id),
        )])));
    };

    let cursor = read(artifact_root, "implementation.json")?;
    let context = read(artifact_root, context_name)?;

    match scope {
        DiffScope::Phase => {
            let plan = read(artifact_root, "plan.json")?;
            phase_material(
                context_name,
                &context,
                &cursor,
                &plan,
                artifact_root,
                work_root,
                invocation_tag,
            )
        }
        DiffScope::Cumulative => cumulative_material(
            context_name,
            &context,
            &cursor,
            work_root,
            invocation_tag,
        ),
    }
}

/// The commit the work tree currently sits on, for staleness comparisons.
///
/// `None` when git cannot answer -- an empty repository, or no git at all. The
/// caller treats that as "nothing to compare" rather than as a mismatch: a
/// missing fact is not evidence of drift.
pub fn head_commit(work_root: &Path) -> Option<String> {
    let output = Command::new("git")
        .args(["-C", &work_root.to_string_lossy(), "rev-parse", "HEAD"])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&output.stdout).trim().to_string();
    (!text.is_empty()).then_some(text)
}

// --------------------------------------------------------------- assembly

#[allow(clippy::too_many_arguments)]
fn phase_material(
    context_name: &str,
    context: &Value,
    cursor: &Value,
    plan: &Value,
    artifact_root: &Path,
    work_root: &Path,
    invocation_tag: &str,
) -> Result<Assembly, Result<Refused, Unavailable>> {
    let Some(phase_id) = crate::gates::implementation::phase_under_verification(cursor) else {
        return Err(Ok(Refused {
            reason: "implementation.json claims no phases, so there is no phase to review"
                .to_string(),
            evidence: Vec::new(),
        }));
    };

    let Some(phase) = find_phase(plan, &phase_id) else {
        return Err(Ok(Refused {
            reason: format!(
                "implementation.json claims phase {phase_id:?}, which the approved plan does not \
                 declare"
            ),
            evidence: Vec::new(),
        }));
    };

    let ids = crate::gates::implementation::plan_phase_ids(plan);
    let is_final = ids.last().map(String::as_str) == Some(phase_id.as_str());

    let mut axes = declared_axes(&phase);
    // The final phase gets `design-faithful` whether or not the plan asked for
    // it. Per-phase reviews only ever see one phase against its own tasks, so
    // nothing in the loop would otherwise ask whether the whole change built the
    // design -- and the last phase is the only point at which the whole change
    // exists. Left to the author, this is the axis that gets forgotten, and the
    // forgetting is invisible.
    if is_final && !axes.iter().any(|axis| axis == "design-faithful") {
        axes.push("design-faithful".to_string());
    }

    if axes.is_empty() {
        return Ok(Assembly::NoReview {
            reason: format!("phase {phase_id} declares no review axes; nothing was judged"),
        });
    }

    // Measured from the boundary recorded for the phase before this one. Absent
    // when the author did not record commits, in which case the range widens to
    // everything since the change began -- noisier, never wrong, and the judges
    // are told so explicitly rather than left to infer it from the volume.
    let incremental = crate::gates::implementation::diff_base_for(cursor, &phase_id);
    let base = match incremental.clone().or_else(|| base_commit(cursor)) {
        Some(base) => base,
        None => {
            return Err(Ok(Refused {
                reason: "implementation.json carries no usable `base_commit`, so the phase diff \
                         has nothing to be measured from"
                    .to_string(),
                evidence: Vec::new(),
            }))
        }
    };

    let extracted = extract(work_root, &base)?;

    let mut text = String::new();
    text.push_str(&format!(
        "{context_name} -- CONTEXT ONLY, NOT UNDER REVIEW. The accepted design this change is \
         building. Do not judge it.\n\n{}\n\n",
        pretty(context)
    ));
    // The plan may name further documents this phase's review needs. Loaded
    // here so an author can, for example, put the intent in front of a phase
    // that implements an acceptance line directly.
    let mut extra = Map::new();
    for (name, loaded) in extra_context(&phase, context_name, artifact_root) {
        match loaded {
            Ok(document) => {
                text.push_str(&format!(
                    "{name} -- CONTEXT ONLY, NOT UNDER REVIEW. Named by this phase's review. Do \
                     not judge it.\n\n{}\n\n",
                    pretty(&document)
                ));
                extra.insert(name, document);
            }
            Err(error) => text.push_str(&format!(
                "{name} -- NAMED BY THIS PHASE'S REVIEW BUT NOT AVAILABLE: {error}. Judge only \
                 what you can see, and say plainly if the missing document is what your ruling \
                 would have turned on.\n\n"
            )),
        }
    }
    text.push_str(&format!(
        "THE PHASE UNDER REVIEW -- phase {phase_id} of the approved plan, with its tasks:\n\n{}\n\n",
        pretty(&phase)
    ));
    if incremental.is_none() {
        text.push_str(
            "NOTE ON THE RANGE: no commit boundary was recorded for the phase before this one, \
             so the diff below covers EVERYTHING done since this change began, not this phase \
             alone. Work belonging to earlier phases of the same plan therefore appears here as \
             a property of how the diff was taken. Do not treat it as work done outside the \
             plan.\n\n",
        );
    }
    text.push_str(&extracted.render());

    Ok(Assembly::Judge(Box::new(Prepared {
        digest_bytes: text.as_bytes().to_vec(),
        subject_value: json!({ "phase": phase, "diff": extracted.body() }),
        // Extra context joins the key: a phase judged against one version of a
        // referenced document has not been judged against another.
        context_value: Some(json!({ context_name: context, "extra": Value::Object(extra) })),
        axis_override: Some(axes),
        evidence: vec![extracted.evidence(
            invocation_tag,
            "phase-diff",
            &format!("phase {phase_id} / {base}..worktree"),
        )],
        text,
    })))
}

fn cumulative_material(
    context_name: &str,
    context: &Value,
    cursor: &Value,
    work_root: &Path,
    invocation_tag: &str,
) -> Result<Assembly, Result<Refused, Unavailable>> {
    let Some(base) = base_commit(cursor) else {
        return Err(Ok(Refused {
            reason: "implementation.json carries no usable `base_commit`, so the change has \
                     nothing to be measured from"
                .to_string(),
            evidence: Vec::new(),
        }));
    };

    let extracted = extract(work_root, &base)?;

    let mut text = String::new();
    text.push_str(&format!(
        "{context_name} -- CONTEXT ONLY, NOT UNDER REVIEW. The accepted intent this change was \
         started for. Do not judge it.\n\n{}\n\n",
        pretty(context)
    ));
    text.push_str(
        "THE CHANGE UNDER REVIEW is the whole diff below: everything done since this change \
         began.\n\n",
    );
    text.push_str(&extracted.render());

    Ok(Assembly::Judge(Box::new(Prepared {
        digest_bytes: text.as_bytes().to_vec(),
        subject_value: json!({ "diff": extracted.body() }),
        context_value: Some(context.clone()),
        axis_override: None,
        evidence: vec![extracted.evidence(
            invocation_tag,
            "change-diff",
            &format!("cumulative / {base}..worktree"),
        )],
        text,
    })))
}

// ------------------------------------------------------------- extraction

struct Extracted {
    stat: String,
    patch: String,
    untracked: Vec<(String, String)>,
}

impl Extracted {
    /// Everything the judges are shown about the code.
    fn render(&self) -> String {
        let mut out = String::new();
        out.push_str("--- FILES CHANGED ---\n\n");
        out.push_str(if self.stat.trim().is_empty() {
            "(no tracked file differs)\n"
        } else {
            &self.stat
        });
        out.push_str("\n\n--- THE DIFF ---\n\n");
        out.push_str(if self.patch.trim().is_empty() {
            "(no tracked change)\n"
        } else {
            &self.patch
        });
        if !self.untracked.is_empty() {
            out.push_str(
                "\n\n--- UNTRACKED FILES ---\n\nThese files are not tracked by git, so they do \
                 not appear in the diff above. Their full contents are shown as patches against \
                 an empty file. They are part of the change; judge them as such.\n\n",
            );
            for (path, patch) in &self.untracked {
                out.push_str(&format!("[untracked] {path}\n{patch}\n"));
            }
        }
        out
    }

    /// The part that identifies the code, for the replay key. Deliberately
    /// excludes `--stat`, which is derived from the patch.
    fn body(&self) -> String {
        let mut out = self.patch.clone();
        for (path, patch) in &self.untracked {
            out.push_str(path);
            out.push('\n');
            out.push_str(patch);
        }
        out
    }

    fn evidence(&self, invocation_tag: &str, kind: &str, range: &str) -> Evidence {
        let body = self.body();
        let bytes = body.len();
        Evidence {
            id: format!("{invocation_tag}-{kind}"),
            kind: kind.to_string(),
            // Size rides in the locator because the engine drops evidence
            // metadata, and "how big was the thing the judge was asked to read"
            // is the first question anyone asks when a judgment times out.
            locator: locator(
                "diff",
                &format!(
                    "{range} / {bytes} bytes / {} untracked file(s)",
                    self.untracked.len()
                ),
            ),
            digest: Some(sha256_hex(body.as_bytes())),
            media_type: Some("text/x-diff".to_string()),
            metadata: Some(json!({
                "range": range,
                "bytes": bytes,
                "untracked_files": self.untracked.len(),
            })),
        }
    }
}

fn extract(work_root: &Path, base: &str) -> Result<Extracted, Result<Refused, Unavailable>> {
    let root = work_root.to_string_lossy().to_string();

    // Verified first so a bad `base_commit` is reported as what it is -- a wrong
    // value in the author's cursor -- instead of surfacing as an opaque git
    // error inside a diff that never ran.
    let verified = git(&root, &["rev-parse", "--verify", &format!("{base}^{{commit}}")])?;
    if !verified.ok {
        return Err(Ok(Refused {
            reason: format!(
                "implementation.json names commit {base:?}, which does not exist in this \
                 repository; a diff cannot be measured from it"
            ),
            evidence: Vec::new(),
        }));
    }

    let stat = require(git(&root, &["diff", "--stat", base, "--"])?, "git diff --stat")?;
    let patch = require(git(&root, &["diff", base, "--"])?, "git diff")?;
    let listed = require(
        git(&root, &["ls-files", "--others", "--exclude-standard"])?,
        "git ls-files --others",
    )?;

    let mut untracked = Vec::new();
    for path in listed.lines().map(str::trim).filter(|line| !line.is_empty()) {
        // `--no-index` exits 1 when the files differ, which is the normal case
        // here and not a failure. Only a missing stdout is treated as one.
        let rendered = git(&root, &["diff", "--no-index", "--", "/dev/null", path])?;
        untracked.push((path.to_string(), rendered.stdout));
    }

    Ok(Extracted { stat, patch, untracked })
}

struct GitOutput {
    ok: bool,
    stdout: String,
    stderr: String,
}

fn git(root: &str, args: &[&str]) -> Result<GitOutput, Result<Refused, Unavailable>> {
    let mut command = Command::new("git");
    command.arg("-C").arg(root);
    for arg in args {
        command.arg(arg);
    }
    let output = command.output().map_err(|error| {
        Err(Unavailable(vec![Diagnostic::new(
            "dependency.unavailable",
            format!(
                "cannot run git in {root}: {error}; the checkpoint and final reviews judge the \
                 actual diff, so git is required"
            ),
        )]))
    })?;
    Ok(GitOutput {
        ok: output.status.success(),
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).trim().to_string(),
    })
}

fn require(output: GitOutput, what: &str) -> Result<String, Result<Refused, Unavailable>> {
    if output.ok {
        Ok(output.stdout)
    } else {
        Err(Err(Unavailable(vec![Diagnostic::new(
            "dependency.unavailable",
            format!("{what} failed: {}", output.stderr),
        )])))
    }
}

// ------------------------------------------------------------------ shared

fn read(artifact_root: &Path, name: &str) -> Result<Value, Result<Refused, Unavailable>> {
    crate::gates::artifacts::read_document(artifact_root, name)
        .map(|(_, value)| value)
        // A missing or malformed document is the author's problem, not a broken
        // provider: the schema half of the same transition says exactly what is
        // wrong with it.
        .map_err(|error| Ok(Refused { reason: format!("not judged: {error}"), evidence: Vec::new() }))
}

fn base_commit(cursor: &Value) -> Option<String> {
    cursor
        .get("base_commit")
        .and_then(Value::as_str)
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn find_phase(plan: &Value, phase_id: &str) -> Option<Value> {
    plan.get("phases")?
        .as_array()?
        .iter()
        .find(|phase| phase.get("id").and_then(Value::as_str).map(str::trim) == Some(phase_id))
        .cloned()
}

/// Axes the plan declares for this phase's checkpoint review.
fn declared_axes(phase: &Value) -> Vec<String> {
    phase
        .get("checkpoint")
        .and_then(|checkpoint| checkpoint.get("review"))
        .and_then(|review| review.get("axes"))
        .and_then(Value::as_array)
        .map(|axes| {
            axes.iter()
                .filter_map(Value::as_str)
                .map(|axis| axis.trim().to_string())
                .filter(|axis| !axis.is_empty())
                .collect()
        })
        .unwrap_or_default()
}

/// Additional documents the phase's review declares as context, minus the one
/// the subject already supplies.
pub fn extra_context_names(phase: &Value, already: &str) -> Vec<String> {
    phase
        .get("checkpoint")
        .and_then(|checkpoint| checkpoint.get("review"))
        .and_then(|review| review.get("context"))
        .and_then(Value::as_array)
        .map(|names| {
            names
                .iter()
                .filter_map(Value::as_str)
                .map(str::trim)
                .filter(|name| !name.is_empty() && *name != already)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default()
}

/// The phase's declared extra context documents, loaded.
///
/// A document that will not load is SKIPPED with a note in the material rather
/// than refusing the gate. The plan named it, the plan was approved, and failing
/// the phase because an optional reference is missing would punish the wrong
/// person -- but silently omitting it would let a judge rule while believing it
/// had seen something it never did.
fn extra_context(
    phase: &Value,
    already: &str,
    artifact_root: &Path,
) -> Vec<(String, Result<Value, String>)> {
    extra_context_names(phase, already)
        .into_iter()
        .map(|name| {
            let loaded = crate::gates::artifacts::read_document(artifact_root, &name)
                .map(|(_, value)| value)
                .map_err(|error| error.to_string());
            (name, loaded)
        })
        .collect()
}

fn pretty(value: &Value) -> String {
    serde_json::to_string_pretty(value).unwrap_or_else(|_| value.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::path::PathBuf;

    /// A real repository, because the whole point of this module is what git
    /// actually reports. A fake would test the fake.
    fn repo(name: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!("sc-diff-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();
        let run = |args: &[&str]| {
            let status = Command::new("git")
                .arg("-C")
                .arg(&root)
                .args(args)
                .output()
                .expect("git must be available for these tests");
            assert!(status.status.success(), "git {args:?}: {:?}", status);
        };
        run(&["init", "-q"]);
        run(&["config", "user.email", "t@example.invalid"]);
        run(&["config", "user.name", "t"]);
        std::fs::write(root.join("kept.txt"), "one\n").unwrap();
        run(&["add", "."]);
        run(&["commit", "-qm", "base"]);
        root
    }

    fn head(root: &Path) -> String {
        head_commit(root).expect("a repository with one commit has a HEAD")
    }

    #[test]
    fn a_tracked_edit_appears_without_being_committed() {
        let root = repo("tracked");
        let base = head(&root);
        std::fs::write(root.join("kept.txt"), "one\ntwo\n").unwrap();

        let extracted = match extract(&root, &base) {
            Ok(extracted) => extracted,
            Err(_) => panic!("extraction must succeed against a real base commit"),
        };
        assert!(extracted.patch.contains("+two"), "{}", extracted.patch);
        assert!(extracted.stat.contains("kept.txt"), "{}", extracted.stat);
    }

    /// New files are usually the substance of a phase, and git will not mention
    /// them until they are added. A gate may not add them, so they are rendered
    /// against an empty file instead.
    #[test]
    fn untracked_files_are_shown_in_full() {
        let root = repo("untracked");
        let base = head(&root);
        std::fs::write(root.join("new.rs"), "fn added() {}\n").unwrap();

        let extracted = extract(&root, &base).ok().expect("extraction");
        assert_eq!(extracted.untracked.len(), 1);
        assert_eq!(extracted.untracked[0].0, "new.rs");
        assert!(extracted.untracked[0].1.contains("fn added"), "{:?}", extracted.untracked[0].1);

        let rendered = extracted.render();
        assert!(rendered.contains("UNTRACKED FILES"));
        assert!(rendered.contains("fn added"));
    }

    /// Files git is told to ignore stay ignored: a gate that pasted `target/`
    /// into a judge prompt would be useless for a single real repository.
    #[test]
    fn ignored_files_stay_out_of_the_material() {
        let root = repo("ignored");
        std::fs::write(root.join(".gitignore"), "noise/\n").unwrap();
        std::fs::create_dir_all(root.join("noise")).unwrap();
        std::fs::write(root.join("noise/big.bin"), "x".repeat(1024)).unwrap();
        let base = head(&root);

        let extracted = extract(&root, &base).ok().expect("extraction");
        let paths: Vec<&str> = extracted.untracked.iter().map(|(p, _)| p.as_str()).collect();
        assert!(!paths.iter().any(|p| p.starts_with("noise/")), "{paths:?}");
    }

    /// A base commit that does not exist is the author's cursor being wrong, not
    /// the provider being broken -- so it must be a gate failure with a reason,
    /// never an evaluation error.
    #[test]
    fn a_base_commit_that_does_not_exist_is_refused_not_errored() {
        let root = repo("badbase");
        match extract(&root, "0000000000000000000000000000000000000000") {
            Err(Ok(refused)) => assert!(refused.reason.contains("does not exist"), "{}", refused.reason),
            Err(Err(_)) => panic!("a bad base commit must not read as a broken environment"),
            Ok(_) => panic!("a bad base commit must not succeed"),
        }
    }

    /// The evidence has to carry the size, because "how big was it" is the first
    /// question anyone asks when a judgment times out.
    #[test]
    fn evidence_records_the_measured_size() {
        let root = repo("size");
        let base = head(&root);
        std::fs::write(root.join("kept.txt"), "one\ntwo\n").unwrap();
        let extracted = extract(&root, &base).ok().expect("extraction");
        let evidence = extracted.evidence("tag", "phase-diff", "P1 / base..worktree");
        assert!(evidence.locator.contains("bytes"), "{}", evidence.locator);
        assert_eq!(evidence.metadata.unwrap()["bytes"], extracted.body().len());
    }

    #[test]
    fn the_final_phase_gets_design_faithful_whether_or_not_the_plan_asked() {
        let with_review = json!({
            "id": "P2",
            "checkpoint": { "commands": [], "review": { "axes": ["tasks-actually-done"] } }
        });
        assert_eq!(declared_axes(&with_review), vec!["tasks-actually-done"]);

        // The append itself lives in `phase_material`; this pins the two inputs
        // it combines so a rename of either is caught here rather than in a run.
        let none = json!({ "id": "P1", "checkpoint": { "commands": [] } });
        assert!(declared_axes(&none).is_empty());
        assert!(crate::gates::semantic::checkpoint_subject()
            .axis_ids()
            .contains(&"design-faithful"));
    }

    #[test]
    fn extra_review_context_excludes_what_the_subject_already_supplies() {
        let phase = json!({
            "checkpoint": {
                "commands": [],
                "review": { "axes": ["tasks-actually-done"], "context": ["design.json", "intent.json"] }
            }
        });
        assert_eq!(extra_context_names(&phase, "design.json"), vec!["intent.json"]);
    }
}
