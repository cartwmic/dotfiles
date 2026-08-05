//! Manifest-bound, untrusted repository evidence.  Catalog owns every fact ID.
//!
//! Facts retain exact bytes (never lossy UTF-8); judge projections are obtained
//! only from this catalog, never accepted from callers.
use crate::{codec, repository::RepositoryView, schema::RecordKind};
use base64::Engine;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::Read;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::path::{Component, Path};

pub const MAX_FACT_BYTES: usize = 65_536;
pub const MAX_PROJECTION_FACTS: usize = 128;
pub const MAX_PROJECTION_BYTES: usize = 262_144;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EvidenceFact {
    pub id: String,
    pub manifest_digest: String,
    pub source_path: String,
    pub start_line: u64,
    pub end_line: u64,
    pub query_scope: String,
    pub result_digest: String,
    pub bytes: Vec<u8>,
    pub untrusted: bool,
}

impl EvidenceFact {
    pub fn utf8_text(&self) -> Option<&str> {
        std::str::from_utf8(&self.bytes).ok()
    }
    pub fn encoded_bytes(&self) -> String {
        base64::engine::general_purpose::STANDARD.encode(&self.bytes)
    }
}

#[derive(Debug, Clone)]
pub struct EvidenceCatalog {
    manifest_digest: String,
    entries: BTreeMap<String, Value>,
    facts: Vec<EvidenceFact>,
    fact_index: BTreeMap<String, usize>,
}

impl EvidenceCatalog {
    pub fn from_manifest(manifest: &crate::codec::DecodedRecord) -> Result<Self, String> {
        if manifest.kind != RecordKind::RepositoryManifest {
            return Err("evidence catalog requires repository-manifest-v1".into());
        }
        crate::schema::validate(RecordKind::RepositoryManifest, &manifest.value)?;
        let canonical = codec::canonicalize(&manifest.value)?;
        if canonical != manifest.canonical || codec::sha256(&canonical) != manifest.digest {
            return Err(
                "evidence catalog manifest carrier is not canonical or digest-valid".into(),
            );
        }
        let entries = manifest.value["entries"]
            .as_array()
            .ok_or("validated manifest entries are missing")?;
        let mut catalog = Self {
            manifest_digest: manifest.digest.clone(),
            entries: entries
                .iter()
                .map(|entry| {
                    Ok((
                        entry["path"]
                            .as_str()
                            .ok_or("manifest entry path is invalid")?
                            .to_string(),
                        entry.clone(),
                    ))
                })
                .collect::<Result<_, String>>()?,
            facts: Vec::new(),
            fact_index: BTreeMap::new(),
        };
        let paths = catalog.entries.keys().cloned().collect::<Vec<_>>();
        for path in paths {
            if catalog.entries[&path]["kind"] != "regular" {
                continue;
            }
            let bytes = catalog.manifest_bytes(&path)?;
            catalog.add_file_facts(&path, &bytes)?;
        }
        for path in ["README.md", "AGENTS.md", "docs/intent.md"] {
            if catalog
                .entries
                .get(path)
                .is_none_or(|entry| entry["kind"] != "regular")
            {
                catalog.push_fact(path, 1, 1, "document-absence", Vec::new())?;
            }
        }
        Ok(catalog)
    }

    pub fn manifest_digest(&self) -> &str {
        &self.manifest_digest
    }
    pub fn facts(&self) -> &[EvidenceFact] {
        &self.facts
    }
    pub fn facts_for_path(&self, path: &str) -> Vec<&EvidenceFact> {
        self.facts
            .iter()
            .filter(|fact| fact.source_path == path)
            .collect()
    }
    pub fn fact(&self, id: &str) -> Option<&EvidenceFact> {
        self.fact_index
            .get(id)
            .and_then(|index| self.facts.get(*index))
    }
    /// Exact manifest bytes for deterministic parsers. This does not expose a
    /// worktree read and preserves invalid UTF-8 for callers that must reject it.
    pub fn bytes_for_path(&self, path: &str) -> Result<Vec<u8>, String> {
        self.manifest_bytes(path)
    }

    /// Produces catalog-owned projection.  Duplicate paths or facts do not
    /// widen input; projection stays bounded and exact manifest bytes remain
    /// available by requesting chunks in separate invocations.
    pub fn projection(&self, requested_paths: &[String]) -> Result<Vec<EvidenceFact>, String> {
        let mut ids = Vec::new();
        for path in requested_paths {
            let path_facts = self.facts_for_path(path);
            if path_facts.is_empty() {
                return Err(format!(
                    "requested evidence path is absent or non-regular: {path}"
                ));
            }
            ids.extend(path_facts.into_iter().map(|fact| fact.id.clone()));
        }
        self.projection_by_ids(&ids)
    }

    pub fn projection_by_ids(&self, requested_ids: &[String]) -> Result<Vec<EvidenceFact>, String> {
        if requested_ids.len() > MAX_PROJECTION_FACTS {
            return Err("judge evidence request exceeds fact limit".into());
        }
        let mut seen = BTreeSet::new();
        let mut bytes = 0usize;
        let mut projected = Vec::new();
        for id in requested_ids {
            if !seen.insert(id) {
                return Err("judge evidence request has duplicate fact identity".into());
            }
            let fact = self
                .fact(id)
                .ok_or_else(|| format!("requested evidence fact is not catalog-owned: {id}"))?;
            bytes = bytes
                .checked_add(fact.bytes.len())
                .ok_or("judge evidence projection overflow")?;
            if bytes > MAX_PROJECTION_BYTES {
                return Err("judge evidence projection exceeds byte limit".into());
            }
            projected.push(fact.clone());
        }
        Ok(projected)
    }

    /// Reads only an active manifest regular entry and never follows links.
    pub fn checked_read(&self, work_root: &Path, path: &str) -> Result<Vec<u8>, String> {
        let entry = self.regular_entry(path)?;
        let manifest_bytes = self.manifest_bytes(path)?;
        if entry["git_status"] == "staged-overlay" {
            return Ok(manifest_bytes);
        }
        safe_relative(path)?;
        let disk_path = work_root.join(path);
        let before = fs::symlink_metadata(&disk_path)
            .map_err(|error| format!("read manifest evidence {path}: {error}"))?;
        if !before.is_file() || before.file_type().is_symlink() {
            return Err(format!("manifest evidence identity changed at {path}"));
        }
        if entry["identity"]["mode"].as_u64() != Some((before.permissions().mode() & 0o7777) as u64)
        {
            return Err(format!("manifest evidence mode changed at {path}"));
        }
        let mut options = OpenOptions::new();
        options.read(true).custom_flags(libc::O_NOFOLLOW);
        let mut file = options
            .open(&disk_path)
            .map_err(|error| format!("open manifest evidence {path}: {error}"))?;
        let opened = file
            .metadata()
            .map_err(|error| format!("stat manifest evidence {path}: {error}"))?;
        if !same_file(&before, &opened) || !opened.is_file() {
            return Err(format!(
                "manifest evidence identity changed before read at {path}"
            ));
        }
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)
            .map_err(|error| format!("read manifest evidence {path}: {error}"))?;
        let after = file
            .metadata()
            .map_err(|error| format!("stat manifest evidence {path}: {error}"))?;
        if !same_file(&opened, &after)
            || codec::sha256(&bytes) != entry["identity"]["sha256"].as_str().unwrap_or_default()
            || bytes != manifest_bytes
        {
            return Err(format!("manifest evidence bytes changed at {path}"));
        }
        Ok(bytes)
    }

    fn add_file_facts(&mut self, path: &str, bytes: &[u8]) -> Result<(), String> {
        // Byte chunks retain every manifest byte. Boundaries prefer line breaks
        // when text exists but do not depend on UTF-8 validity.
        let scope = classify(path, bytes);
        let mut offset = 0usize;
        let mut line = 1u64;
        while offset < bytes.len().max(1) {
            let end_limit = (offset + MAX_FACT_BYTES).min(bytes.len());
            let end = if end_limit < bytes.len() {
                bytes[offset..end_limit]
                    .iter()
                    .rposition(|byte| *byte == b'\n')
                    .map(|i| offset + i + 1)
                    .filter(|end| *end > offset)
                    .unwrap_or(end_limit)
            } else {
                end_limit
            };
            let slice = &bytes[offset..end];
            let lines = u64::try_from(slice.iter().filter(|byte| **byte == b'\n').count())
                .expect("line count fits u64");
            // A terminal newline starts next (empty) line but that line has no
            // retained bytes. Citations must never extend past slice bytes.
            let end_line = if slice.ends_with(b"\n") {
                line + lines.saturating_sub(1)
            } else {
                line + lines
            };
            self.push_fact(path, line, end_line.max(line), &scope, slice.to_vec())?;
            if offset == bytes.len() {
                break;
            }
            line += lines;
            offset = end;
        }
        // Commands are static syntax evidence, never execution. Emit exact
        // source line bytes under explicit scope so a command claim can cite it.
        if let Ok(text) = std::str::from_utf8(bytes) {
            // JSON command support exists only after parsing its configured
            // `scripts` object; text containment alone never establishes it.
            let json_commands = static_json_commands(path, text);
            for (index, raw) in text.lines().enumerate() {
                if static_command_line(path, raw)
                    || json_commands
                        .iter()
                        .any(|command| raw.trim_start().starts_with(&format!("\"{command}\"")))
                {
                    let number = u64::try_from(index + 1).expect("line index fits u64");
                    self.push_fact(
                        path,
                        number,
                        number,
                        "static-command-support",
                        raw.as_bytes().to_vec(),
                    )?;
                }
            }
        }
        Ok(())
    }

    fn regular_entry(&self, path: &str) -> Result<&Value, String> {
        let entry = self
            .entries
            .get(path)
            .ok_or_else(|| format!("path is not in active manifest: {path}"))?;
        if entry["kind"] != "regular" || entry["identity"]["kind"] != "regular" {
            return Err(format!("manifest path is not a regular file: {path}"));
        }
        Ok(entry)
    }
    fn manifest_bytes(&self, path: &str) -> Result<Vec<u8>, String> {
        let entry = self.regular_entry(path)?;
        let encoded = entry["identity"]["content_base64"]
            .as_str()
            .ok_or_else(|| format!("manifest regular bytes missing at {path}"))?;
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(encoded)
            .map_err(|error| format!("manifest regular bytes invalid at {path}: {error}"))?;
        if codec::sha256(&bytes) != entry["identity"]["sha256"].as_str().unwrap_or_default()
            || entry["identity"]["size"].as_u64() != u64::try_from(bytes.len()).ok()
        {
            return Err(format!(
                "manifest regular bytes digest or size mismatch at {path}"
            ));
        }
        Ok(bytes)
    }
    fn push_fact(
        &mut self,
        source_path: &str,
        start_line: u64,
        end_line: u64,
        query_scope: &str,
        bytes: Vec<u8>,
    ) -> Result<(), String> {
        let result_digest = codec::sha256(&bytes);
        let id = codec::sha256(&codec::canonicalize(
            &json!({"manifest_digest":self.manifest_digest,"source_path":source_path,"start_line":start_line,"end_line":end_line,"query_scope":query_scope,"result_digest":result_digest}),
        )?);
        if self.fact_index.contains_key(&id) {
            return Ok(());
        }
        let index = self.facts.len();
        self.fact_index.insert(id.clone(), index);
        self.facts.push(EvidenceFact {
            id,
            manifest_digest: self.manifest_digest.clone(),
            source_path: source_path.into(),
            start_line,
            end_line,
            query_scope: query_scope.into(),
            result_digest,
            bytes,
            untrusted: true,
        });
        Ok(())
    }
}

pub fn require_stable_model_phase<T>(
    view: &RepositoryView<'_>,
    before: &crate::codec::DecodedRecord,
    phase: impl FnOnce() -> Result<T, String>,
) -> Result<T, String> {
    let result = phase()?;
    let after = view.capture()?;
    let differences = crate::repository::compare(&before.value, &after.value)?;
    if differences.is_empty() {
        Ok(result)
    } else {
        Err(format!(
            "repository changed during model phase: {}",
            differences
                .iter()
                .take(32)
                .map(|item| format!("{} ({})", item.path, item.kind))
                .collect::<Vec<_>>()
                .join(", ")
        ))
    }
}
fn same_file(left: &fs::Metadata, right: &fs::Metadata) -> bool {
    left.dev() == right.dev()
        && left.ino() == right.ino()
        && left.len() == right.len()
        && left.mode() == right.mode()
        && left.mtime() == right.mtime()
        && left.mtime_nsec() == right.mtime_nsec()
}
fn safe_relative(path: &str) -> Result<(), String> {
    if Path::new(path).is_absolute()
        || Path::new(path)
            .components()
            .any(|component| !matches!(component, Component::Normal(_)))
    {
        Err(format!(
            "manifest evidence path is not clean and relative: {path:?}"
        ))
    } else {
        Ok(())
    }
}
fn classify(path: &str, bytes: &[u8]) -> String {
    let text = std::str::from_utf8(bytes).unwrap_or("");
    if matches!(path, "README.md" | "AGENTS.md" | "docs/intent.md") {
        "document-text".into()
    } else if path.ends_with(".toml")
        || path.ends_with(".json")
        || path.ends_with(".yaml")
        || path.ends_with(".yml")
    {
        "configuration".into()
    } else if path.contains("test") || text.contains("#[test]") {
        "test-behavior".into()
    } else if path.contains("owner") || path.contains("CODEOWNERS") {
        "ownership-boundary".into()
    } else {
        "source-behavior".into()
    }
}
fn static_command_line(path: &str, line: &str) -> bool {
    let trimmed = line.trim();
    (path.ends_with(".toml")
        && (trimmed.starts_with("[tasks.")
            || trimmed.starts_with("run =")
            || trimmed.starts_with("run = ")))
        || trimmed.starts_with("#!")
        || trimmed.starts_with("fn main(")
        || trimmed.starts_with("command ")
}
fn static_json_commands(path: &str, text: &str) -> BTreeSet<String> {
    if !path.ends_with(".json") {
        return BTreeSet::new();
    }
    serde_json::from_str::<Value>(text)
        .ok()
        .and_then(|value| value.get("scripts").and_then(Value::as_object).cloned())
        .map(|scripts| {
            scripts
                .into_iter()
                .filter_map(|(name, command)| {
                    command
                        .as_str()
                        .filter(|value| !value.is_empty())
                        .map(|_| name)
                })
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::boundary::validate_roots;
    use crate::repository::RepositoryView;
    use std::fs;
    use std::process::Command;
    use tempfile::tempdir;
    fn fixture() -> (tempfile::TempDir, crate::boundary::ValidatedRoots) {
        let work = tempdir().unwrap();
        let artifacts = tempdir().unwrap();
        Command::new("git")
            .args(["init", "-q"])
            .current_dir(work.path())
            .status()
            .unwrap();
        fs::write(work.path().join("README.md"), "# Demo\nRun `tool start`.\n").unwrap();
        fs::write(work.path().join("src.rs"), "fn main() {}\n").unwrap();
        let roots = validate_roots(
            &fs::canonicalize(work.path()).unwrap(),
            &fs::canonicalize(artifacts.path()).unwrap(),
        )
        .unwrap();
        (work, roots)
    }
    #[test]
    fn catalog_preserves_binary_and_rejects_forged_projection() {
        let (work, roots) = fixture();
        fs::write(work.path().join("blob"), [0xff; 70_000]).unwrap();
        let manifest = RepositoryView::new(&roots, "run-1").capture().unwrap();
        let catalog = EvidenceCatalog::from_manifest(&manifest).unwrap();
        let blob = catalog.facts_for_path("blob");
        assert!(blob.len() >= 2);
        assert!(blob.iter().all(|f| f.utf8_text().is_none()));
        assert!(catalog
            .projection_by_ids(&["sha256:forged".into()])
            .is_err());
        assert_eq!(
            catalog.checked_read(&roots.work_root, "README.md").unwrap(),
            b"# Demo\nRun `tool start`.\n"
        );
    }
    #[test]
    fn trailing_newline_fact_does_not_cite_empty_next_line() {
        let (work, roots) = fixture();
        fs::write(work.path().join("README.md"), "one\n").unwrap();
        let manifest = RepositoryView::new(&roots, "run-1").capture().unwrap();
        let catalog = EvidenceCatalog::from_manifest(&manifest).unwrap();
        let fact = catalog
            .facts_for_path("README.md")
            .into_iter()
            .next()
            .unwrap();
        assert_eq!((fact.start_line, fact.end_line), (1, 1));
    }
    #[test]
    fn model_phase_stability_rejects_mutation() {
        let (work, roots) = fixture();
        let view = RepositoryView::new(&roots, "run-1");
        let before = view.capture().unwrap();
        assert!(require_stable_model_phase(&view, &before, || {
            fs::write(work.path().join("src.rs"), "changed").unwrap();
            Ok(())
        })
        .is_err());
    }
}
