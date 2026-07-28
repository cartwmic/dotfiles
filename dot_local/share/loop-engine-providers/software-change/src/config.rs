//! The repository-level workflow configuration file.
//!
//! `.loop-workflow.toml` lives at `work_root` and is read fresh on every gate
//! invocation. It is deliberately *not* a run input: a run input is frozen at
//! `run create`, whereas validation commands and judge models are properties of
//! the repository being worked in and may legitimately be corrected mid-run.
//!
//! Consequence worth knowing: two attempts at the same gate in the same run can
//! be judged under different configuration. Every gate that reads this file
//! records what it actually used in its evidence, so the journal still explains
//! any given verdict.

use serde::Deserialize;
use std::path::{Path, PathBuf};

use crate::protocol::Diagnostic;

pub const CONFIG_FILE: &str = ".loop-workflow.toml";

// Unknown keys are rejected throughout. A silently ignored key is the worst
// possible failure here: a misspelled `axes` or a `model` written under the
// wrong table leaves the gate running with defaults the author did not choose,
// and nothing in the run explains why. Better to refuse to start.
#[derive(Debug, Deserialize, Default)]
#[serde(deny_unknown_fields)]
pub struct WorkflowConfig {
    /// Present for forward compatibility; nothing dispatches on it yet.
    #[allow(dead_code)]
    #[serde(default)]
    pub schema_version: u32,
    /// Absent when this repository does not use semantic judgment.
    ///
    /// This is now the only table. Validation commands used to live here too,
    /// and moved into the plan: what gets validated is a property of the change
    /// being made, not of the repository it is made in.
    #[serde(default)]
    pub judge: Option<JudgeConfig>,
}



/// Configuration for the non-deterministic judge gates.
///
/// `model` is the only required key. Everything else has a defensible default
/// so that a repository opting in writes three lines, not thirty.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct JudgeConfig {
    /// Model pattern handed to the judge CLI, e.g. `claude-bridge/claude-sonnet-5`.
    pub model: String,
    /// Model for the deciding judge. Defaults to `model`.
    #[serde(default)]
    pub consensus_model: Option<String>,
    /// argv of the judge CLI. `run[0]` is the executable; never shelled out.
    #[serde(default = "default_judge_command")]
    pub command: Vec<String>,
    /// Extension files to load explicitly.
    ///
    /// Judges run with extension *discovery* disabled so that no ambient
    /// extension — memory, MCP, telemetry — can reach a judgment. Providers
    /// that arrive via an extension must therefore be named here. A leading
    /// `~/` is expanded.
    #[serde(default)]
    pub extensions: Vec<String>,
    /// Subset of the built-in `intent.json` axes to run. Defaults to all.
    #[serde(default)]
    pub axes: Option<Vec<String>>,
    /// Subset of the built-in `design.json` axes to run. Defaults to all.
    ///
    /// Kept separate from `axes` rather than shared: the axis vocabularies are
    /// disjoint, so one list would make every entry ambiguous about which
    /// document it selects, and a typo would silently disable a whole subject.
    #[serde(default)]
    pub design_axes: Option<Vec<String>>,
    /// Subset of the built-in `plan.json` axes to run. Defaults to all.
    #[serde(default)]
    pub plan_axes: Option<Vec<String>>,
    /// Subset of the final cumulative-diff axes to run. Defaults to all.
    ///
    /// There is deliberately no key for the PER-PHASE checkpoint axes. Those are
    /// declared by the plan, phase by phase, because which phases are worth
    /// judging and on what is a property of the change rather than of the
    /// repository. A key here would look like it worked and do nothing.
    #[serde(default)]
    pub implementation_axes: Option<Vec<String>>,
    /// Thinking level passed through to the judge CLI.
    #[serde(default)]
    pub thinking: Option<String>,
    /// Wall-clock budget for the whole judgment, capped by the engine's
    /// provider timeout regardless of what is written here.
    #[serde(default)]
    pub timeout_seconds: Option<u64>,
    /// How many axis judges may be in flight at once. Defaults to 3.
    ///
    /// Raise it only if your judge CLI is a thin API client. A CLI that starts
    /// another agent process behind it saturates well before the axis count,
    /// and the symptom is every judge timing out at once rather than the run
    /// merely being slow.
    #[serde(default)]
    pub max_parallel_axes: Option<usize>,
}

fn default_judge_command() -> Vec<String> {
    vec!["pi".to_string()]
}

impl JudgeConfig {
    pub fn consensus_model(&self) -> &str {
        self.consensus_model.as_deref().unwrap_or(&self.model)
    }

    /// The configured axis subset for one judged document, if any.
    /// Every subject's key is matched explicitly, and an unrecognised key
    /// PANICS rather than falling through to `axes`.
    ///
    /// A catch-all here is how a new subject silently inherits the intent axis
    /// list: the selection would appear to work, the wrong vocabulary would be
    /// applied, and `select_axes` would reject every entry with a confusing
    /// message about the wrong document. The key comes from a `static Subject`
    /// in this binary, never from user input, so an unknown key is a build
    /// defect and failing loudly at the first test run is the point.
    /// Zero is treated as one: a configured value that would launch nothing
    /// must not deadlock the gate.
    pub fn max_parallel_axes(&self) -> usize {
        self.max_parallel_axes.unwrap_or(3).max(1)
    }

    pub fn axes_for(&self, key: &str) -> Option<&Vec<String>> {
        match key {
            "axes" => self.axes.as_ref(),
            "design_axes" => self.design_axes.as_ref(),
            "plan_axes" => self.plan_axes.as_ref(),
            "implementation_axes" => self.implementation_axes.as_ref(),
            other => panic!("no [judge] key is wired for subject axes_key {other:?}"),
        }
    }

    /// Absolute paths for every configured extension, with `~/` expanded.
    pub fn extension_paths(&self) -> Vec<PathBuf> {
        let home = std::env::var_os("HOME").map(PathBuf::from);
        self.extensions.iter().map(|raw| expand_home(raw, home.as_deref())).collect()
    }
}

fn expand_home(raw: &str, home: Option<&Path>) -> PathBuf {
    match (raw.strip_prefix("~/"), home) {
        (Some(rest), Some(home)) => home.join(rest),
        _ => PathBuf::from(raw),
    }
}

/// Read and parse the configuration file, or explain precisely why not.
pub fn load(work_root: &Path) -> Result<WorkflowConfig, Diagnostic> {
    let path = work_root.join(CONFIG_FILE);
    let raw = std::fs::read_to_string(&path).map_err(|error| {
        Diagnostic::new("config.missing", format!("cannot read {}: {error}", path.display()))
    })?;
    toml::from_str(&raw).map_err(|error| {
        Diagnostic::new("config.invalid", format!("{} is not valid TOML: {error}", path.display()))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(text: &str) -> WorkflowConfig {
        toml::from_str(text).unwrap()
    }

    #[test]
    fn a_misplaced_or_misspelled_key_is_refused_rather_than_ignored() {
        // `axes` under [validation] instead of [judge] — observed in practice.
        assert!(toml::from_str::<WorkflowConfig>(
            "[judge]\nmodel = \"p/m\"\n[validation]\naxes = [\"solution-agnostic\"]\n"
        )
        .is_err());
        assert!(toml::from_str::<WorkflowConfig>("[judge]\nmoddel = \"p/m\"\n").is_err());
    }

    #[test]
    fn judge_is_absent_unless_the_repository_opts_in() {
        let config = parse("schema_version = 1\n");
        assert!(config.judge.is_none());
    }

    #[test]
    fn consensus_model_falls_back_to_the_axis_model() {
        let config = parse("[judge]\nmodel = \"p/m\"\n");
        let judge = config.judge.unwrap();
        assert_eq!(judge.consensus_model(), "p/m");
        assert_eq!(judge.command, vec!["pi".to_string()]);
    }

    #[test]
    fn a_declared_consensus_model_wins() {
        let config = parse("[judge]\nmodel = \"p/m\"\nconsensus_model = \"p/bigger\"\n");
        assert_eq!(config.judge.unwrap().consensus_model(), "p/bigger");
    }

    #[test]
    fn a_leading_tilde_expands_only_when_a_home_is_known() {
        let home = PathBuf::from("/home/example");
        assert_eq!(
            expand_home("~/ext/index.ts", Some(&home)),
            PathBuf::from("/home/example/ext/index.ts")
        );
        assert_eq!(expand_home("/abs/x.ts", Some(&home)), PathBuf::from("/abs/x.ts"));
        // Without a home the literal path is kept: spawning then fails loudly
        // rather than silently judging with a different extension set.
        assert_eq!(expand_home("~/ext/index.ts", None), PathBuf::from("~/ext/index.ts"));
    }
}
