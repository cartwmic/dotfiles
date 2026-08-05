use crate::codec::{self, DecodedRecord};
use crate::schema::RecordKind;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashSet;
use std::ffi::{CStr, CString};
use std::fs::{self, File};
use std::io::{Read, Write};
use std::os::fd::{AsRawFd, FromRawFd, RawFd};
use std::os::unix::ffi::OsStrExt;
use std::path::{Component, Path, PathBuf};
use std::str::FromStr;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

const OWNER_FILE: &str = ".documentation-maintenance-run.json";

// Linked records form a schema-bounded graph (authority manifests have at most
// 32 slots and revision ledgers at most 3 accepted records), but predecessor
// chains span records and therefore need explicit process-resource bounds.
// Depth 256 keeps recursive stack use bounded while allowing long histories;
// 4,096 distinct records accommodates wide authority graphs; and 65,536
// candidate path reads permits substantial long-lived stores without allowing
// digest lookup to scan quadratically without limit.
const MAX_ACTIVE_LINK_DEPTH: usize = 256;
const MAX_DISTINCT_LINK_RECORDS: usize = 4_096;
const MAX_LINK_CANDIDATE_READS: usize = 65_536;

static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RecordCategory {
    Audits,
    Revisions,
    Approvals,
    Verification,
}

impl RecordCategory {
    fn directory(self) -> &'static str {
        match self {
            Self::Audits => "audits",
            Self::Revisions => "revisions",
            Self::Approvals => "approvals",
            Self::Verification => "verification",
        }
    }
}

#[derive(Debug, Clone)]
pub struct StoredRecord {
    pub relative_path: String,
    pub digest: String,
    pub decoded: DecodedRecord,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct OwnershipMarker {
    format: String,
    run_id: String,
}

#[derive(Debug, Clone)]
pub struct ArtifactStore {
    root: PathBuf,
    root_dir: Arc<File>,
    run_id: String,
}

impl ArtifactStore {
    pub fn open(root: &Path, run_id: &str) -> Result<Self, String> {
        validate_component(run_id, "run_id")?;
        // Pin supplied root before any pathname inspection. Every later
        // operation is relative to this descriptor, so renames or symlink
        // swaps of supplied path cannot redirect store operations.
        let root_dir = open_directory_path(root).map_err(|error| {
            format!(
                "open artifact_root {} without symlinks: {error}",
                root.display()
            )
        })?;
        let canonical = fs::canonicalize(root).map_err(|error| {
            format!(
                "artifact_root {} cannot be canonicalized: {error}",
                root.display()
            )
        })?;
        if canonical.as_os_str() != root.as_os_str() {
            return Err(format!(
                "artifact_root must use its canonical path: supplied {}, canonical {}",
                root.display(),
                canonical.display()
            ));
        }
        match open_file_at(root_dir.as_raw_fd(), OWNER_FILE) {
            Ok(file) => {
                if !file
                    .metadata()
                    .map_err(|error| format!("inspect artifact ownership marker: {error}"))?
                    .is_file()
                {
                    return Err("artifact ownership marker is not a regular file".to_string());
                }
                let bytes = read_bounded(file, 16 * 1024, "artifact ownership marker")?;
                let marker: OwnershipMarker = serde_json::from_slice(&bytes)
                    .map_err(|error| format!("invalid artifact ownership marker: {error}"))?;
                if marker.format != "documentation-maintenance-run-v1" {
                    return Err("unsupported artifact ownership marker".to_string());
                }
                if marker.run_id != run_id {
                    return Err(format!(
                        "artifact_root {} belongs to run {:?}, not {:?}",
                        canonical.display(),
                        marker.run_id,
                        run_id
                    ));
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                if !directory_names(root_dir.as_raw_fd(), None)
                    .map_err(|error| {
                        format!("inspect artifact_root {}: {error}", canonical.display())
                    })?
                    .is_empty()
                {
                    return Err(format!(
                        "unowned artifact_root must be empty before run {:?} claims it: {}",
                        run_id,
                        canonical.display()
                    ));
                }
                let marker = OwnershipMarker {
                    format: "documentation-maintenance-run-v1".to_string(),
                    run_id: run_id.to_string(),
                };
                let value = serde_json::to_value(&marker)
                    .map_err(|error| format!("encode ownership marker: {error}"))?;
                let bytes = codec::canonicalize(&value)?;
                atomic_create_at(&root_dir, OWNER_FILE, &bytes).map_err(|error| {
                    format!(
                        "atomically claim artifact_root {}: {error}",
                        canonical.display()
                    )
                })?;
            }
            Err(error) => return Err(format!("open artifact ownership marker: {error}")),
        }

        Ok(Self {
            root: canonical,
            root_dir: Arc::new(root_dir),
            run_id: run_id.to_string(),
        })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn run_id(&self) -> &str {
        &self.run_id
    }

    pub fn store(
        &self,
        category: RecordCategory,
        invocation_id: &str,
        kind: RecordKind,
        value: &Value,
    ) -> Result<StoredRecord, String> {
        validate_component(invocation_id, "invocation_id")?;
        let decoded = codec::encode_record(value, kind, &self.run_id)?;
        let components = ["provider", category.directory(), invocation_id];
        let parent = open_or_create_directory_chain(&self.root_dir, &components)?;
        let file_name = format!("{}.json", kind.name());
        atomic_create_at(&parent, &file_name, &decoded.canonical)
            .map_err(|error| format!("persist immutable provider record {file_name}: {error}"))?;
        let relative_path = format!(
            "provider/{}/{invocation_id}/{file_name}",
            category.directory()
        );
        Ok(StoredRecord {
            relative_path,
            digest: decoded.digest.clone(),
            decoded,
        })
    }

    pub fn load(
        &self,
        relative_path: &str,
        kind: RecordKind,
        expected_digest: &str,
    ) -> Result<StoredRecord, String> {
        codec::validate_digest(expected_digest)?;
        let mut verification = LinkVerification::default();
        self.load_with_links(relative_path, kind, expected_digest, &mut verification)
    }

    fn load_with_links(
        &self,
        relative_path: &str,
        kind: RecordKind,
        expected_digest: &str,
        verification: &mut LinkVerification,
    ) -> Result<StoredRecord, String> {
        let key = (kind, expected_digest.to_string());
        // Reserve recursion and distinct-record budget before reading or
        // decoding this record. A limit failure therefore cannot add another
        // bounded read to an already exhausted traversal.
        let started = verification.begin_record(&key)?;
        let stored = match self.read_record(relative_path, kind) {
            Ok(stored) => stored,
            Err(error) => {
                if started {
                    verification.finish_record(&key, false);
                }
                return Err(error);
            }
        };
        if stored.digest != expected_digest {
            if started {
                verification.finish_record(&key, false);
            }
            return Err(format!(
                "provider record digest mismatch at {}: expected {}, computed {}",
                stored.relative_path, expected_digest, stored.digest
            ));
        }
        if !started {
            return Ok(stored);
        }

        let result = self.verify_record_links(&stored.decoded, verification);
        verification.finish_record(&key, result.is_ok());
        result?;
        Ok(stored)
    }

    fn read_record(&self, relative_path: &str, kind: RecordKind) -> Result<StoredRecord, String> {
        let (relative_path, bytes) = self.read_record_bytes(relative_path, kind)?;
        self.decode_record_bytes(relative_path, bytes, kind)
    }

    fn read_record_bytes(
        &self,
        relative_path: &str,
        kind: RecordKind,
    ) -> Result<(String, Vec<u8>), String> {
        let relative = safe_relative(relative_path)?;
        validate_provider_record_path(&relative, kind)?;
        let components = relative
            .components()
            .map(|component| match component {
                Component::Normal(value) => value
                    .to_str()
                    .ok_or_else(|| "provider record path is not UTF-8".to_string()),
                _ => Err("provider record path is not clean and relative".to_string()),
            })
            .collect::<Result<Vec<_>, _>>()?;
        let parent = open_directory_chain(&self.root_dir, &components[..3])
            .map_err(|error| format!("open provider record parent {relative_path}: {error}"))?;
        let file = open_file_at(parent.as_raw_fd(), components[3])
            .map_err(|error| format!("open provider record {relative_path}: {error}"))?;
        let metadata = file
            .metadata()
            .map_err(|error| format!("inspect provider record {relative_path}: {error}"))?;
        if !metadata.is_file() {
            return Err(format!(
                "provider record is not a regular file: {relative_path}"
            ));
        }
        let bytes = read_bounded(file, codec::MAX_RECORD_BYTES, "provider record")
            .map_err(|error| format!("read provider record {relative_path}: {error}"))?;
        Ok((relative.to_string_lossy().into_owned(), bytes))
    }

    fn decode_record_bytes(
        &self,
        relative_path: String,
        bytes: Vec<u8>,
        kind: RecordKind,
    ) -> Result<StoredRecord, String> {
        let decoded = codec::decode_record(&bytes, kind, &self.run_id)
            .map_err(|error| format!("invalid provider record {relative_path}: {error}"))?;
        if decoded.canonical != bytes {
            return Err(format!(
                "stored provider record is not RFC 8785 canonical: {relative_path}"
            ));
        }
        Ok(StoredRecord {
            relative_path,
            digest: decoded.digest.clone(),
            decoded,
        })
    }

    fn verify_record_links(
        &self,
        record: &DecodedRecord,
        verification: &mut LinkVerification,
    ) -> Result<(), String> {
        let value = &record.value;
        // Closed provider-record link table. Digest fields not named here are
        // raw draft/content/model/parameters/evidence identities and must not
        // be resolved as provider records merely because their names end in
        // `_digest` or `_digests`.
        match record.kind {
            RecordKind::RepositoryManifest => {
                self.verify_optional_link(
                    value,
                    "baseline_digest",
                    RecordKind::RepositoryManifest,
                    verification,
                )?;
            }
            RecordKind::ClaimSet | RecordKind::RoleAxisJudgment | RecordKind::JudgmentBundle => {
                self.verify_link(
                    value,
                    "manifest_digest",
                    RecordKind::RepositoryManifest,
                    verification,
                )?;
            }
            RecordKind::AuditReport => {
                self.verify_link(
                    value,
                    "manifest_digest",
                    RecordKind::RepositoryManifest,
                    verification,
                )?;
                self.verify_link(
                    value,
                    "claim_set_digest",
                    RecordKind::ClaimSet,
                    verification,
                )?;
                self.verify_link(
                    value,
                    "judgment_bundle_digest",
                    RecordKind::JudgmentBundle,
                    verification,
                )?;
            }
            RecordKind::RevisionRequest => {
                self.verify_link(
                    value,
                    "audit_report_digest",
                    RecordKind::AuditReport,
                    verification,
                )?;
            }
            RecordKind::RevisionRecord => {
                self.verify_link(
                    value,
                    "request_digest",
                    RecordKind::RevisionRequest,
                    verification,
                )?;
                self.verify_optional_link(
                    value,
                    "predecessor_digest",
                    RecordKind::RevisionRecord,
                    verification,
                )?;
            }
            RecordKind::RevisionLedger => {
                self.verify_link(
                    value,
                    "baseline_manifest_digest",
                    RecordKind::RepositoryManifest,
                    verification,
                )?;
                self.verify_optional_link(
                    value,
                    "predecessor_digest",
                    RecordKind::RevisionLedger,
                    verification,
                )?;
                for accepted in value["accepted"]
                    .as_array()
                    .expect("schema checked accepted")
                {
                    self.verify_link(
                        accepted,
                        "revision_record_digest",
                        RecordKind::RevisionRecord,
                        verification,
                    )?;
                }
            }
            RecordKind::OwnerAttestation => {
                self.verify_link(
                    value,
                    "manifest_digest",
                    RecordKind::RepositoryManifest,
                    verification,
                )?;
            }
            RecordKind::ApprovedBundle => {
                self.verify_link(
                    value,
                    "staged_manifest_digest",
                    RecordKind::RepositoryManifest,
                    verification,
                )?;
                self.verify_link(
                    value,
                    "clean_audit_report_digest",
                    RecordKind::AuditReport,
                    verification,
                )?;
                self.verify_link(
                    value,
                    "owner_attestation_digest",
                    RecordKind::OwnerAttestation,
                    verification,
                )?;
                self.verify_link(
                    value,
                    "baseline_manifest_digest",
                    RecordKind::RepositoryManifest,
                    verification,
                )?;
            }
            RecordKind::ApplicationVerification => {
                self.verify_link(
                    value,
                    "approved_bundle_digest",
                    RecordKind::ApprovedBundle,
                    verification,
                )?;
                self.verify_link(
                    value,
                    "observed_manifest_digest",
                    RecordKind::RepositoryManifest,
                    verification,
                )?;
            }
            RecordKind::AuthorityManifest => {
                if let Some(predecessor) = value["predecessor_root_digest"].as_str() {
                    if predecessor != synthetic_empty_authority_digest(&self.run_id)? {
                        self.resolve_digest(
                            RecordKind::AuthorityManifest,
                            predecessor,
                            verification,
                        )?;
                    }
                }
                for (slot, artifact) in value["slots"].as_object().expect("schema checked slots") {
                    let schema = artifact["schema"]
                        .as_str()
                        .expect("schema checked slot schema");
                    let kind = RecordKind::from_str(schema)
                        .map_err(|error| format!("invalid authority slot {slot}: {error}"))?;
                    let relative_path = artifact["relative_path"]
                        .as_str()
                        .expect("schema checked slot path");
                    let digest = artifact["digest"]
                        .as_str()
                        .expect("schema checked slot digest");
                    self.load_with_links(relative_path, kind, digest, verification)
                        .map_err(|error| format!("invalid authority slot {slot}: {error}"))?;
                }
            }
            RecordKind::TransitionCertificate => {
                let predecessor_root = value["predecessor_root_digest"]
                    .as_str()
                    .expect("schema checked predecessor root");
                if predecessor_root != synthetic_empty_authority_digest(&self.run_id)? {
                    self.resolve_digest(
                        RecordKind::AuthorityManifest,
                        predecessor_root,
                        verification,
                    )?;
                }
                self.resolve_digest(
                    RecordKind::AuthorityManifest,
                    value["successor_root_digest"]
                        .as_str()
                        .expect("schema checked successor root"),
                    verification,
                )?;
                self.verify_optional_link(
                    value,
                    "predecessor_certificate_digest",
                    RecordKind::TransitionCertificate,
                    verification,
                )?;
            }
            RecordKind::BreachRemediation => {
                self.verify_link(
                    value,
                    "prior_breach_digest",
                    RecordKind::AuditReport,
                    verification,
                )?;
                self.verify_link(
                    value,
                    "old_manifest_digest",
                    RecordKind::RepositoryManifest,
                    verification,
                )?;
                self.verify_link(
                    value,
                    "new_manifest_digest",
                    RecordKind::RepositoryManifest,
                    verification,
                )?;
            }
            // These kinds contain only raw content, model, evaluation-key,
            // fixture, parameter, or evidence digests.
            RecordKind::IntentSemanticDiff
            | RecordKind::EvaluationRecovery
            | RecordKind::CalibrationReport => {}
        }
        Ok(())
    }

    fn verify_link(
        &self,
        value: &Value,
        field: &str,
        kind: RecordKind,
        verification: &mut LinkVerification,
    ) -> Result<(), String> {
        let digest = value[field]
            .as_str()
            .ok_or_else(|| format!("provider-record link {field} is not a digest string"))?;
        self.resolve_digest(kind, digest, verification)
            .map_err(|error| format!("invalid provider-record link {field}: {error}"))
    }

    fn verify_optional_link(
        &self,
        value: &Value,
        field: &str,
        kind: RecordKind,
        verification: &mut LinkVerification,
    ) -> Result<(), String> {
        match value[field].as_str() {
            Some(digest) => self
                .resolve_digest(kind, digest, verification)
                .map_err(|error| format!("invalid provider-record link {field}: {error}")),
            None if value[field].is_null() => Ok(()),
            None => Err(format!(
                "optional provider-record link {field} is neither digest nor null"
            )),
        }
    }

    fn resolve_digest(
        &self,
        kind: RecordKind,
        digest: &str,
        verification: &mut LinkVerification,
    ) -> Result<(), String> {
        codec::validate_digest(digest)?;
        let key = (kind, digest.to_string());
        if !verification.preflight_record(&key)? {
            return Ok(());
        }

        let (searched, matching) = self.matching_candidate_paths(kind, digest, verification)?;
        let Some(relative_path) = matching.first() else {
            return Err(format!(
                "no {} record has digest {digest}; searched {searched} candidate path(s)",
                kind.name()
            ));
        };
        self.load_with_links(relative_path, kind, digest, verification)?;
        Ok(())
    }

    fn matching_candidate_paths(
        &self,
        kind: RecordKind,
        expected_digest: &str,
        verification: &mut LinkVerification,
    ) -> Result<(usize, Vec<String>), String> {
        let provider = match open_directory_at(self.root_dir.as_raw_fd(), "provider") {
            Ok(directory) => directory,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Ok((0, Vec::new()))
            }
            Err(error) => return Err(format!("open provider record root: {error}")),
        };

        let mut searched = 0usize;
        let mut paths = Vec::new();
        for category in ["audits", "revisions", "approvals", "verification"] {
            let category_dir = match open_directory_at(provider.as_raw_fd(), category) {
                Ok(directory) => directory,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
                Err(error) => return Err(format!("open provider category {category}: {error}")),
            };
            let remaining = verification.remaining_candidate_reads();
            let mut names = directory_names(category_dir.as_raw_fd(), Some(remaining))
                .map_err(|error| format!("read provider category {category}: {error}"))?;
            names.sort();
            for name in names {
                // Count every invocation path inspection, including a missing
                // file of the requested kind, so sparse stores are bounded too.
                verification.note_candidate_read()?;
                validate_component(&name, "stored invocation_id")?;
                let invocation =
                    open_directory_at(category_dir.as_raw_fd(), &name).map_err(|error| {
                        format!("open provider invocation {category}/{name}: {error}")
                    })?;
                let file_name = format!("{}.json", kind.name());
                match open_file_at(invocation.as_raw_fd(), &file_name) {
                    Ok(file) => {
                        if !file
                            .metadata()
                            .map_err(|error| {
                                format!("inspect provider candidate {category}/{name}: {error}")
                            })?
                            .is_file()
                        {
                            return Err(format!(
                                "provider candidate is not a regular file: {category}/{name}/{file_name}"
                            ));
                        }
                        searched += 1;
                        // Hash bytes from descriptor opened relative to pinned
                        // invocation directory. Oversized records cannot match a
                        // valid provider-record digest and do not poison lookup.
                        let Some(bytes) = read_bounded_candidate(
                            file,
                            codec::MAX_RECORD_BYTES,
                            "provider candidate",
                        )?
                        else {
                            continue;
                        };
                        if codec::sha256(&bytes) == expected_digest {
                            let relative_path = format!("provider/{category}/{name}/{file_name}");
                            // Only a digest match pays schema/canonical decoding.
                            self.decode_record_bytes(relative_path.clone(), bytes, kind)?;
                            paths.push(relative_path);
                        }
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                    Err(error) => {
                        return Err(format!(
                            "open provider candidate {category}/{name}/{file_name}: {error}"
                        ))
                    }
                }
            }
        }
        paths.sort();
        Ok((searched, paths))
    }
}

#[derive(Default)]
struct LinkVerification {
    active: HashSet<(RecordKind, String)>,
    verified: HashSet<(RecordKind, String)>,
    active_depth: usize,
    distinct_records: usize,
    candidate_reads: usize,
}

impl LinkVerification {
    /// Checks whether one record may start verification. `Ok(false)` means the
    /// record was already verified. No lookup or record read should happen for
    /// a new record before this check succeeds.
    fn preflight_record(&self, key: &(RecordKind, String)) -> Result<bool, String> {
        if self.verified.contains(key) {
            return Ok(false);
        }
        if self.active.contains(key) {
            return Err(format!(
                "provider record link cycle detected at {} ({})",
                key.0.name(),
                key.1
            ));
        }
        if self.active_depth >= MAX_ACTIVE_LINK_DEPTH {
            return Err(format!(
                "provider-record link active-depth limit exceeded: maximum {MAX_ACTIVE_LINK_DEPTH} active records"
            ));
        }
        if self.distinct_records >= MAX_DISTINCT_LINK_RECORDS {
            return Err(format!(
                "provider-record link distinct-record limit exceeded: maximum {MAX_DISTINCT_LINK_RECORDS} verified/active records"
            ));
        }
        Ok(true)
    }

    /// Starts verification for one distinct record. `Ok(false)` means the
    /// record was already verified; all limits are checked before mutation.
    fn begin_record(&mut self, key: &(RecordKind, String)) -> Result<bool, String> {
        if !self.preflight_record(key)? {
            return Ok(false);
        }

        let inserted = self.active.insert(key.clone());
        debug_assert!(inserted);
        self.active_depth += 1;
        self.distinct_records += 1;
        Ok(true)
    }

    fn finish_record(&mut self, key: &(RecordKind, String), succeeded: bool) {
        let removed = self.active.remove(key);
        debug_assert!(removed);
        if removed {
            self.active_depth -= 1;
        }
        if succeeded {
            self.verified.insert(key.clone());
        }
    }

    fn remaining_candidate_reads(&self) -> usize {
        MAX_LINK_CANDIDATE_READS.saturating_sub(self.candidate_reads)
    }

    fn note_candidate_read(&mut self) -> Result<(), String> {
        if self.candidate_reads >= MAX_LINK_CANDIDATE_READS {
            return Err(candidate_read_limit_error());
        }
        self.candidate_reads += 1;
        Ok(())
    }
}

fn candidate_read_limit_error() -> String {
    format!(
        "provider-record candidate-read limit exceeded: maximum {MAX_LINK_CANDIDATE_READS} candidate path reads per load"
    )
}

fn synthetic_empty_authority_digest(run_id: &str) -> Result<String, String> {
    let empty = serde_json::json!({
        "schema":"authority-manifest-v1",
        "run_id":run_id,
        "predecessor_root_digest":null,
        "slots":{},
    });
    Ok(codec::encode_record(&empty, RecordKind::AuthorityManifest, run_id)?.digest)
}

fn validate_component(value: &str, label: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
        || value == "."
        || value == ".."
    {
        return Err(format!("{label} is not a safe path component: {value:?}"));
    }
    Ok(())
}

fn safe_relative(value: &str) -> Result<PathBuf, String> {
    let path = Path::new(value);
    if path.is_absolute()
        || path
            .components()
            .any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err(format!(
            "record path must be a clean relative path: {value:?}"
        ));
    }
    Ok(path.to_path_buf())
}

fn validate_provider_record_path(path: &Path, kind: RecordKind) -> Result<(), String> {
    let components = path
        .components()
        .map(|component| match component {
            Component::Normal(value) => value
                .to_str()
                .ok_or_else(|| format!("provider record path is not UTF-8: {}", path.display())),
            _ => Err(format!(
                "provider record path is not clean and relative: {}",
                path.display()
            )),
        })
        .collect::<Result<Vec<_>, _>>()?;
    if components.len() != 4
        || components[0] != "provider"
        || !matches!(
            components[1],
            "audits" | "revisions" | "approvals" | "verification"
        )
        || components[3] != format!("{}.json", kind.name())
    {
        return Err(format!(
            "provider record path must be provider/{{audits,revisions,approvals,verification}}/<invocation>/{}.json: {}",
            kind.name(),
            path.display()
        ));
    }
    validate_component(components[2], "stored invocation_id")
}

fn c_name(name: &str) -> Result<CString, String> {
    CString::new(name.as_bytes()).map_err(|_| format!("path component contains NUL: {name:?}"))
}

fn open_directory_path(path: &Path) -> Result<File, String> {
    if !path.is_absolute() {
        return Err(format!(
            "directory path is not absolute: {}",
            path.display()
        ));
    }
    let slash = c_name("/")?;
    // SAFETY: slash is NUL-terminated and flags require no variadic mode.
    let root_fd = unsafe {
        libc::open(
            slash.as_ptr(),
            libc::O_RDONLY | libc::O_CLOEXEC | libc::O_DIRECTORY | libc::O_NOFOLLOW,
        )
    };
    if root_fd < 0 {
        return Err(std::io::Error::last_os_error().to_string());
    }
    // SAFETY: successful open returns a new owned descriptor.
    let mut current = unsafe { File::from_raw_fd(root_fd) };
    for component in path.components() {
        match component {
            Component::RootDir => {}
            Component::Normal(name) => {
                current = open_directory_at_bytes(current.as_raw_fd(), name.as_bytes())
                    .map_err(|error| format!("open directory component {name:?}: {error}"))?;
            }
            _ => {
                return Err(format!(
                    "directory path is not canonical: {}",
                    path.display()
                ))
            }
        }
    }
    Ok(current)
}

fn open_directory_at(parent: RawFd, name: &str) -> std::io::Result<File> {
    open_directory_at_bytes(parent, name.as_bytes())
}

fn open_directory_at_bytes(parent: RawFd, name: &[u8]) -> std::io::Result<File> {
    let name = CString::new(name)
        .map_err(|_| std::io::Error::new(std::io::ErrorKind::InvalidInput, "NUL in path"))?;
    // SAFETY: name is NUL-terminated, parent is borrowed, and no mode argument is required.
    let fd = unsafe {
        libc::openat(
            parent,
            name.as_ptr(),
            libc::O_RDONLY | libc::O_CLOEXEC | libc::O_DIRECTORY | libc::O_NOFOLLOW,
        )
    };
    if fd < 0 {
        Err(std::io::Error::last_os_error())
    } else {
        // SAFETY: successful openat returns a new owned descriptor.
        Ok(unsafe { File::from_raw_fd(fd) })
    }
}

fn open_file_at(parent: RawFd, name: &str) -> std::io::Result<File> {
    let name = CString::new(name.as_bytes())
        .map_err(|_| std::io::Error::new(std::io::ErrorKind::InvalidInput, "NUL in path"))?;
    // SAFETY: name is NUL-terminated, parent is borrowed, and no mode argument is required.
    let fd = unsafe {
        libc::openat(
            parent,
            name.as_ptr(),
            libc::O_RDONLY | libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK,
        )
    };
    if fd < 0 {
        Err(std::io::Error::last_os_error())
    } else {
        // SAFETY: successful openat returns a new owned descriptor.
        Ok(unsafe { File::from_raw_fd(fd) })
    }
}

fn open_directory_chain(root: &File, components: &[&str]) -> Result<File, String> {
    let mut current = root
        .try_clone()
        .map_err(|error| format!("duplicate artifact_root descriptor: {error}"))?;
    for component in components {
        current = open_directory_at(current.as_raw_fd(), component)
            .map_err(|error| format!("open artifact directory component {component:?}: {error}"))?;
    }
    Ok(current)
}

fn open_or_create_directory_chain(root: &File, components: &[&str]) -> Result<File, String> {
    let mut current = root
        .try_clone()
        .map_err(|error| format!("duplicate artifact_root descriptor: {error}"))?;
    for component in components {
        validate_component(component, "artifact directory component")?;
        match open_directory_at(current.as_raw_fd(), component) {
            Ok(next) => current = next,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                let name = c_name(component)?;
                // SAFETY: name is NUL-terminated and current descriptor is a pinned directory.
                let result = unsafe { libc::mkdirat(current.as_raw_fd(), name.as_ptr(), 0o700) };
                if result < 0 {
                    let create_error = std::io::Error::last_os_error();
                    if create_error.kind() != std::io::ErrorKind::AlreadyExists {
                        return Err(format!(
                            "create artifact directory component {component:?}: {create_error}"
                        ));
                    }
                }
                if result == 0 {
                    current.sync_all().map_err(|error| {
                        format!(
                            "sync parent after creating artifact directory component {component:?}: {error}"
                        )
                    })?;
                }
                current = open_directory_at(current.as_raw_fd(), component).map_err(|error| {
                    format!("open created artifact directory component {component:?}: {error}")
                })?;
            }
            Err(error) => {
                return Err(format!(
                    "open artifact directory component {component:?}: {error}"
                ))
            }
        }
    }
    Ok(current)
}

fn read_bounded(file: File, limit: usize, label: &str) -> Result<Vec<u8>, String> {
    read_bounded_candidate(file, limit, label)?
        .ok_or_else(|| format!("{label} exceeds {limit} byte limit"))
}

fn read_bounded_candidate(
    file: File,
    limit: usize,
    label: &str,
) -> Result<Option<Vec<u8>>, String> {
    let mut bytes = Vec::new();
    file.take((limit + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|error| format!("read {label}: {error}"))?;
    if bytes.len() > limit {
        Ok(None)
    } else {
        Ok(Some(bytes))
    }
}

fn atomic_create_at(parent: &File, name: &str, bytes: &[u8]) -> Result<(), String> {
    let name = c_name(name)?;
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let temp_name = format!(
        ".{}.tmp-{}-{sequence}",
        name.to_string_lossy(),
        std::process::id()
    );
    let temp = c_name(&temp_name)?;
    let parent_fd = parent.as_raw_fd();
    let result = (|| {
        // SAFETY: names are NUL-terminated; O_CREAT supplies mode; parent is pinned.
        let fd = unsafe {
            libc::openat(
                parent_fd,
                temp.as_ptr(),
                libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL | libc::O_CLOEXEC | libc::O_NOFOLLOW,
                0o600,
            )
        };
        if fd < 0 {
            return Err(format!(
                "create same-directory temporary file: {}",
                std::io::Error::last_os_error()
            ));
        }
        // SAFETY: successful openat returns a new owned descriptor.
        let mut file = unsafe { File::from_raw_fd(fd) };
        file.write_all(bytes)
            .and_then(|()| file.sync_all())
            .map_err(|error| format!("write and sync temporary file: {error}"))?;
        drop(file);

        // linkat installs create-only in the same pinned directory. No path
        // resolution can leave artifact_root, and an existing record survives.
        // SAFETY: both names are NUL-terminated and descriptors remain open.
        if unsafe { libc::linkat(parent_fd, temp.as_ptr(), parent_fd, name.as_ptr(), 0) } < 0 {
            return Err(format!(
                "install without replacement: {}",
                std::io::Error::last_os_error()
            ));
        }
        parent
            .sync_all()
            .map_err(|error| format!("sync parent after install: {error}"))?;
        // SAFETY: temp is NUL-terminated and parent is pinned.
        if unsafe { libc::unlinkat(parent_fd, temp.as_ptr(), 0) } < 0 {
            return Err(format!(
                "remove installed temporary link: {}",
                std::io::Error::last_os_error()
            ));
        }
        parent
            .sync_all()
            .map_err(|error| format!("sync parent after temporary cleanup: {error}"))?;
        Ok(())
    })();
    if result.is_err() {
        // SAFETY: best-effort cleanup of a name in the pinned parent.
        unsafe {
            libc::unlinkat(parent_fd, temp.as_ptr(), 0);
        }
    }
    result
}

fn directory_names(directory: RawFd, max_entries: Option<usize>) -> Result<Vec<String>, String> {
    // fdopendir owns its descriptor, so duplicate the pinned directory first.
    // SAFETY: fcntl does not consume the borrowed descriptor.
    let duplicate = unsafe { libc::fcntl(directory, libc::F_DUPFD_CLOEXEC, 0) };
    if duplicate < 0 {
        return Err(format!(
            "duplicate directory descriptor: {}",
            std::io::Error::last_os_error()
        ));
    }
    // SAFETY: duplicate is an owned directory descriptor.
    let stream = unsafe { libc::fdopendir(duplicate) };
    if stream.is_null() {
        let error = std::io::Error::last_os_error();
        // SAFETY: fdopendir failed and did not take ownership.
        unsafe { libc::close(duplicate) };
        return Err(format!("open directory stream: {error}"));
    }

    let mut names = Vec::new();
    loop {
        set_errno(0);
        // SAFETY: stream remains valid until closed below.
        let entry = unsafe { libc::readdir(stream) };
        if entry.is_null() {
            let error = current_errno();
            // SAFETY: stream is valid and closes its duplicated descriptor.
            unsafe { libc::closedir(stream) };
            if error == 0 {
                return Ok(names);
            }
            return Err(std::io::Error::from_raw_os_error(error).to_string());
        }
        // SAFETY: readdir returns a dirent whose d_name is NUL-terminated.
        let name = match unsafe { CStr::from_ptr((*entry).d_name.as_ptr()) }.to_str() {
            Ok(name) => name,
            Err(_) => {
                // SAFETY: stream is valid and closes its duplicated descriptor.
                unsafe { libc::closedir(stream) };
                return Err("directory entry name is not UTF-8".to_string());
            }
        };
        if name != "." && name != ".." {
            if max_entries == Some(names.len()) {
                // SAFETY: stream is valid and closes its duplicated descriptor.
                unsafe { libc::closedir(stream) };
                return Err(candidate_read_limit_error());
            }
            names.push(name.to_string());
        }
    }
}

#[cfg(target_os = "macos")]
fn errno_location() -> *mut libc::c_int {
    // SAFETY: libc exposes thread-local errno through __error on macOS.
    unsafe { libc::__error() }
}

#[cfg(target_os = "linux")]
fn errno_location() -> *mut libc::c_int {
    // SAFETY: libc exposes thread-local errno through __errno_location on Linux.
    unsafe { libc::__errno_location() }
}

fn set_errno(value: libc::c_int) {
    // SAFETY: errno_location returns this thread's valid errno pointer.
    unsafe { *errno_location() = value }
}

fn current_errno() -> libc::c_int {
    // SAFETY: errno_location returns this thread's valid errno pointer.
    unsafe { *errno_location() }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::os::unix::fs::symlink;
    use tempfile::tempdir;

    fn manifest(run_id: &str) -> Value {
        json!({
            "schema":"repository-manifest-v1", "run_id":run_id,
            "manifest_kind":"baseline", "work_root":"/repo", "git_common_dir":"/repo/.git",
            "entries":[], "repository_fingerprint":format!("sha256:{}", "0".repeat(64)),
            "baseline_digest":null, "overlay_paths":[]
        })
    }

    fn claim(run_id: &str, manifest_digest: &str) -> Value {
        json!({
            "schema":"claim-set-v1", "run_id":run_id,
            "manifest_digest":manifest_digest, "claims":[]
        })
    }

    fn judgment_bundle(run_id: &str, manifest_digest: &str) -> Value {
        let mut value: Value = serde_json::from_str(include_str!(
            "../fixtures/records/valid/judgment-bundle-v1.json"
        ))
        .unwrap();
        value["run_id"] = Value::String(run_id.to_string());
        value["manifest_digest"] = Value::String(manifest_digest.to_string());
        value
    }

    fn audit_report(
        run_id: &str,
        manifest_digest: &str,
        claim_digest: &str,
        judgment_digest: &str,
    ) -> Value {
        let mut value: Value = serde_json::from_str(include_str!(
            "../fixtures/records/valid/audit-report-v1.json"
        ))
        .unwrap();
        value["run_id"] = Value::String(run_id.to_string());
        value["manifest_digest"] = Value::String(manifest_digest.to_string());
        value["claim_set_digest"] = Value::String(claim_digest.to_string());
        value["judgment_bundle_digest"] = Value::String(judgment_digest.to_string());
        value
    }

    #[test]
    fn claims_empty_root_and_never_overwrites_records() {
        let temp = tempdir().unwrap();
        let root = fs::canonicalize(temp.path()).unwrap();
        let store = ArtifactStore::open(&root, "run-1").unwrap();
        let manifest = store
            .store(
                RecordCategory::Audits,
                "manifest",
                RecordKind::RepositoryManifest,
                &manifest("run-1"),
            )
            .unwrap();
        let claim = claim("run-1", &manifest.digest);
        let first = store
            .store(
                RecordCategory::Audits,
                "inv-1",
                RecordKind::ClaimSet,
                &claim,
            )
            .unwrap();
        assert!(store
            .store(
                RecordCategory::Audits,
                "inv-1",
                RecordKind::ClaimSet,
                &claim
            )
            .is_err());
        let invocation_dir = root.join("provider/audits/inv-1");
        assert!(fs::read_dir(&invocation_dir).unwrap().all(|entry| !entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .contains(".tmp-")));
        let loaded = store
            .load(&first.relative_path, RecordKind::ClaimSet, &first.digest)
            .unwrap();
        assert_eq!(loaded.decoded.value, claim);
        assert!(ArtifactStore::open(&root, "run-2").is_err());
    }

    #[test]
    fn rejects_nonempty_unowned_root_and_tampered_record() {
        let temp = tempdir().unwrap();
        fs::write(temp.path().join("foreign"), b"x").unwrap();
        let root = fs::canonicalize(temp.path()).unwrap();
        assert!(ArtifactStore::open(&root, "run-1").is_err());

        let temp = tempdir().unwrap();
        let root = fs::canonicalize(temp.path()).unwrap();
        let store = ArtifactStore::open(&root, "run-1").unwrap();
        let saved = store
            .store(
                RecordCategory::Audits,
                "inv-1",
                RecordKind::ClaimSet,
                &claim("run-1", &format!("sha256:{}", "0".repeat(64))),
            )
            .unwrap();
        fs::write(root.join(&saved.relative_path), b"{}").unwrap();
        assert!(store
            .load(&saved.relative_path, RecordKind::ClaimSet, &saved.digest)
            .is_err());
    }

    #[test]
    fn audit_report_load_resolves_and_verifies_pathless_provider_links() {
        let temp = tempdir().unwrap();
        let root = fs::canonicalize(temp.path()).unwrap();
        let store = ArtifactStore::open(&root, "run-1").unwrap();
        let manifest = store
            .store(
                RecordCategory::Audits,
                "manifest",
                RecordKind::RepositoryManifest,
                &manifest("run-1"),
            )
            .unwrap();
        let claim = store
            .store(
                RecordCategory::Audits,
                "claim",
                RecordKind::ClaimSet,
                &claim("run-1", &manifest.digest),
            )
            .unwrap();
        let judgment = store
            .store(
                RecordCategory::Verification,
                "judgment",
                RecordKind::JudgmentBundle,
                &judgment_bundle("run-1", &manifest.digest),
            )
            .unwrap();
        let audit = store
            .store(
                RecordCategory::Approvals,
                "audit",
                RecordKind::AuditReport,
                &audit_report("run-1", &manifest.digest, &claim.digest, &judgment.digest),
            )
            .unwrap();

        let loaded = store
            .load(&audit.relative_path, RecordKind::AuditReport, &audit.digest)
            .unwrap();
        assert_eq!(loaded.digest, audit.digest);
    }

    #[test]
    fn audit_report_load_rejects_missing_and_tampered_linked_records() {
        let temp = tempdir().unwrap();
        let root = fs::canonicalize(temp.path()).unwrap();
        let store = ArtifactStore::open(&root, "run-1").unwrap();
        let manifest = store
            .store(
                RecordCategory::Audits,
                "manifest",
                RecordKind::RepositoryManifest,
                &manifest("run-1"),
            )
            .unwrap();
        let judgment = store
            .store(
                RecordCategory::Audits,
                "judgment",
                RecordKind::JudgmentBundle,
                &judgment_bundle("run-1", &manifest.digest),
            )
            .unwrap();
        let missing_digest = format!("sha256:{}", "f".repeat(64));
        let missing = store
            .store(
                RecordCategory::Audits,
                "missing-audit",
                RecordKind::AuditReport,
                &audit_report("run-1", &manifest.digest, &missing_digest, &judgment.digest),
            )
            .unwrap();
        let error = store
            .load(
                &missing.relative_path,
                RecordKind::AuditReport,
                &missing.digest,
            )
            .unwrap_err();
        assert!(error.contains("claim_set_digest"), "{error}");
        assert!(error.contains("no claim-set-v1 record"), "{error}");

        let stored_claim = store
            .store(
                RecordCategory::Audits,
                "claim",
                RecordKind::ClaimSet,
                &claim("run-1", &manifest.digest),
            )
            .unwrap();
        let audit = store
            .store(
                RecordCategory::Audits,
                "tampered-audit",
                RecordKind::AuditReport,
                &audit_report(
                    "run-1",
                    &manifest.digest,
                    &stored_claim.digest,
                    &judgment.digest,
                ),
            )
            .unwrap();
        let mut tampered = claim("run-1", &manifest.digest);
        tampered["claims"] = json!([{
            "claim_id":"tampered", "document":"README.md",
            "location":{"path":"README.md","start_line":1,"end_line":1},
            "ordinal":0, "proposition":"tampered", "force":"descriptive",
            "evidence_digests":[], "reason_id":"tampered"
        }]);
        let bytes = codec::encode_record(&tampered, RecordKind::ClaimSet, "run-1")
            .unwrap()
            .canonical;
        fs::write(root.join(&stored_claim.relative_path), bytes).unwrap();
        let error = store
            .load(&audit.relative_path, RecordKind::AuditReport, &audit.digest)
            .unwrap_err();
        assert!(error.contains("claim_set_digest"), "{error}");
        assert!(error.contains("no claim-set-v1 record"), "{error}");

        fs::write(root.join(&stored_claim.relative_path), b"{}").unwrap();
        let error = store
            .load(&audit.relative_path, RecordKind::AuditReport, &audit.digest)
            .unwrap_err();
        assert!(error.contains("claim_set_digest"), "{error}");
        assert!(error.contains("no claim-set-v1 record"), "{error}");
    }

    #[test]
    fn digest_resolution_ignores_unrelated_corrupt_same_kind_candidate() {
        let temp = tempdir().unwrap();
        let root = fs::canonicalize(temp.path()).unwrap();
        let store = ArtifactStore::open(&root, "run-1").unwrap();
        let corrupt = store
            .store(
                RecordCategory::Audits,
                "a-corrupt",
                RecordKind::RepositoryManifest,
                &manifest("run-1"),
            )
            .unwrap();
        let expected = store
            .store(
                RecordCategory::Audits,
                "z-expected",
                RecordKind::RepositoryManifest,
                &manifest("run-1"),
            )
            .unwrap();
        fs::write(root.join(corrupt.relative_path), b"not-json").unwrap();
        let linked = store
            .store(
                RecordCategory::Audits,
                "claim",
                RecordKind::ClaimSet,
                &claim("run-1", &expected.digest),
            )
            .unwrap();

        let loaded = store
            .load(&linked.relative_path, RecordKind::ClaimSet, &linked.digest)
            .unwrap();
        assert_eq!(loaded.digest, linked.digest);
    }

    #[test]
    fn pinned_root_operations_reject_static_symlink_components_and_records() {
        let temp = tempdir().unwrap();
        let outside = tempdir().unwrap();
        let root = fs::canonicalize(temp.path()).unwrap();
        let store = ArtifactStore::open(&root, "run-1").unwrap();
        symlink(outside.path(), root.join("provider")).unwrap();
        assert!(store
            .store(
                RecordCategory::Audits,
                "escape",
                RecordKind::RepositoryManifest,
                &manifest("run-1"),
            )
            .is_err());
        assert!(fs::read_dir(outside.path()).unwrap().next().is_none());

        fs::remove_file(root.join("provider")).unwrap();
        let saved = store
            .store(
                RecordCategory::Audits,
                "record-link",
                RecordKind::RepositoryManifest,
                &manifest("run-1"),
            )
            .unwrap();
        let outside_record = outside.path().join("record.json");
        fs::write(&outside_record, &saved.decoded.canonical).unwrap();
        fs::remove_file(root.join(&saved.relative_path)).unwrap();
        symlink(&outside_record, root.join(&saved.relative_path)).unwrap();
        assert!(store
            .load(
                &saved.relative_path,
                RecordKind::RepositoryManifest,
                &saved.digest,
            )
            .is_err());

        let marker_root = tempdir().unwrap();
        let marker_root = fs::canonicalize(marker_root.path()).unwrap();
        symlink(&outside_record, marker_root.join(OWNER_FILE)).unwrap();
        assert!(ArtifactStore::open(&marker_root, "run-1").is_err());
    }

    #[test]
    fn pinned_root_survives_path_replacement_without_writing_replacement() {
        let parent = tempdir().unwrap();
        let outside = tempdir().unwrap();
        let root = parent.path().join("artifacts");
        fs::create_dir(&root).unwrap();
        let root = fs::canonicalize(root).unwrap();
        let pinned = parent.path().join("pinned-artifacts");
        let store = ArtifactStore::open(&root, "run-1").unwrap();

        fs::rename(&root, &pinned).unwrap();
        symlink(outside.path(), &root).unwrap();
        let saved = store
            .store(
                RecordCategory::Audits,
                "after-replacement",
                RecordKind::RepositoryManifest,
                &manifest("run-1"),
            )
            .unwrap();

        assert!(pinned.join(saved.relative_path).is_file());
        assert!(fs::read_dir(outside.path()).unwrap().next().is_none());
    }

    #[test]
    fn digest_resolution_fails_closed_on_symlink_invocation_ancestor() {
        let temp = tempdir().unwrap();
        let outside = tempdir().unwrap();
        let root = fs::canonicalize(temp.path()).unwrap();
        let store = ArtifactStore::open(&root, "run-1").unwrap();
        let expected = store
            .store(
                RecordCategory::Audits,
                "z-expected",
                RecordKind::RepositoryManifest,
                &manifest("run-1"),
            )
            .unwrap();
        symlink(outside.path(), root.join("provider/audits/a-escape")).unwrap();
        let linked = store
            .store(
                RecordCategory::Audits,
                "claim",
                RecordKind::ClaimSet,
                &claim("run-1", &expected.digest),
            )
            .unwrap();

        let error = store
            .load(&linked.relative_path, RecordKind::ClaimSet, &linked.digest)
            .unwrap_err();
        assert!(error.contains("a-escape"), "{error}");
        assert!(error.contains("provider invocation"), "{error}");
    }

    #[test]
    fn link_verification_rejects_cycle_and_depth_over_limit() {
        let mut verification = LinkVerification::default();
        let first = (RecordKind::RevisionRecord, "sha256:first".to_string());
        assert!(verification.begin_record(&first).unwrap());
        let cycle = verification.begin_record(&first).unwrap_err();
        assert!(cycle.contains("link cycle detected"), "{cycle}");

        for index in 1..MAX_ACTIVE_LINK_DEPTH {
            let key = (RecordKind::RevisionRecord, format!("sha256:depth-{index}"));
            assert!(verification.begin_record(&key).unwrap());
        }
        assert_eq!(verification.active_depth, MAX_ACTIVE_LINK_DEPTH);
        let over_limit = (
            RecordKind::RevisionRecord,
            "sha256:depth-over-limit".to_string(),
        );
        let error = verification.begin_record(&over_limit).unwrap_err();
        assert!(error.contains("active-depth limit exceeded"), "{error}");
        assert!(
            error.contains(&MAX_ACTIVE_LINK_DEPTH.to_string()),
            "{error}"
        );
    }

    #[test]
    fn link_verification_rejects_distinct_records_over_limit() {
        let mut verification = LinkVerification::default();
        for index in 0..MAX_DISTINCT_LINK_RECORDS {
            let key = (
                RecordKind::RepositoryManifest,
                format!("sha256:record-{index}"),
            );
            assert!(verification.begin_record(&key).unwrap());
            verification.finish_record(&key, true);
        }
        assert_eq!(verification.distinct_records, MAX_DISTINCT_LINK_RECORDS);
        let over_limit = (
            RecordKind::RepositoryManifest,
            "sha256:record-over-limit".to_string(),
        );
        let error = verification.begin_record(&over_limit).unwrap_err();
        assert!(error.contains("distinct-record limit exceeded"), "{error}");
        assert!(
            error.contains(&MAX_DISTINCT_LINK_RECORDS.to_string()),
            "{error}"
        );
    }

    #[test]
    fn link_verification_rejects_candidate_reads_over_limit() {
        let mut verification = LinkVerification {
            candidate_reads: MAX_LINK_CANDIDATE_READS - 1,
            ..LinkVerification::default()
        };
        verification.note_candidate_read().unwrap();
        assert_eq!(verification.candidate_reads, MAX_LINK_CANDIDATE_READS);
        let error = verification.note_candidate_read().unwrap_err();
        assert!(error.contains("candidate-read limit exceeded"), "{error}");
        assert!(
            error.contains(&MAX_LINK_CANDIDATE_READS.to_string()),
            "{error}"
        );
    }

    #[test]
    fn digest_lookup_applies_remaining_candidate_read_budget() {
        let temp = tempdir().unwrap();
        let root = fs::canonicalize(temp.path()).unwrap();
        let store = ArtifactStore::open(&root, "run-1").unwrap();
        for invocation in ["candidate-1", "candidate-2"] {
            store
                .store(
                    RecordCategory::Audits,
                    invocation,
                    RecordKind::RepositoryManifest,
                    &manifest("run-1"),
                )
                .unwrap();
        }

        let mut verification = LinkVerification {
            candidate_reads: MAX_LINK_CANDIDATE_READS - 1,
            ..LinkVerification::default()
        };
        let missing_digest = format!("sha256:{}", "f".repeat(64));
        let error = store
            .matching_candidate_paths(
                RecordKind::RepositoryManifest,
                &missing_digest,
                &mut verification,
            )
            .unwrap_err();
        assert!(error.contains("candidate-read limit exceeded"), "{error}");
        assert!(
            error.contains(&MAX_LINK_CANDIDATE_READS.to_string()),
            "{error}"
        );
    }
}
