use crate::codec::{self, DecodedRecord};
use crate::schema::RecordKind;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;

const OWNER_FILE: &str = ".documentation-maintenance-run.json";
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
    run_id: String,
}

impl ArtifactStore {
    pub fn open(root: &Path, run_id: &str) -> Result<Self, String> {
        validate_component(run_id, "run_id")?;
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
        if !canonical.is_dir() {
            return Err(format!(
                "artifact_root is not a directory: {}",
                canonical.display()
            ));
        }

        let marker_path = canonical.join(OWNER_FILE);
        let mut marker_options = OpenOptions::new();
        marker_options.read(true);
        #[cfg(unix)]
        marker_options.custom_flags(libc::O_NOFOLLOW);
        match marker_options.open(&marker_path) {
            Ok(mut file) => {
                let mut bytes = Vec::new();
                file.read_to_end(&mut bytes)
                    .map_err(|error| format!("read artifact ownership marker: {error}"))?;
                let marker: OwnershipMarker = serde_json::from_slice(&bytes).map_err(|error| {
                    format!(
                        "invalid artifact ownership marker {}: {error}",
                        marker_path.display()
                    )
                })?;
                if marker.format != "documentation-maintenance-run-v1" {
                    return Err(format!(
                        "unsupported artifact ownership marker at {}",
                        marker_path.display()
                    ));
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
                let mut entries = fs::read_dir(&canonical).map_err(|read_error| {
                    format!(
                        "inspect artifact_root {}: {read_error}",
                        canonical.display()
                    )
                })?;
                if entries.next().is_some() {
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
                    .map_err(|encode_error| format!("encode ownership marker: {encode_error}"))?;
                let bytes = codec::canonicalize(&value)?;
                atomic_create(&marker_path, &bytes).map_err(|create_error| {
                    format!(
                        "atomically claim artifact_root {}: {create_error}",
                        canonical.display()
                    )
                })?;
            }
            Err(error) => {
                return Err(format!(
                    "open artifact ownership marker {}: {error}",
                    marker_path.display()
                ))
            }
        }

        Ok(Self {
            root: canonical,
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
        let parent = self
            .root
            .join("provider")
            .join(category.directory())
            .join(invocation_id);
        fs::create_dir_all(&parent).map_err(|error| {
            format!(
                "create invocation record directory {}: {error}",
                parent.display()
            )
        })?;
        ensure_canonical_child(&self.root, &parent)?;
        let path = parent.join(format!("{}.json", kind.name()));
        atomic_create(&path, &decoded.canonical).map_err(|error| {
            format!(
                "persist immutable provider record {}: {error}",
                path.display()
            )
        })?;
        let relative_path = path
            .strip_prefix(&self.root)
            .expect("path assembled beneath root")
            .to_string_lossy()
            .into_owned();
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
        let relative = safe_relative(relative_path)?;
        let path = self.root.join(&relative);
        let parent = path
            .parent()
            .ok_or_else(|| "record path has no parent".to_string())?;
        ensure_canonical_child(&self.root, parent)?;
        let mut options = OpenOptions::new();
        options.read(true);
        #[cfg(unix)]
        options.custom_flags(libc::O_NOFOLLOW);
        let file = options
            .open(&path)
            .map_err(|error| format!("open provider record {}: {error}", path.display()))?;
        let mut bytes = Vec::new();
        file.take((codec::MAX_RECORD_BYTES + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|error| format!("read provider record {}: {error}", path.display()))?;
        let decoded = codec::decode_record(&bytes, kind, &self.run_id)?;
        if decoded.canonical != bytes {
            return Err(format!(
                "stored provider record is not RFC 8785 canonical: {}",
                path.display()
            ));
        }
        if decoded.digest != expected_digest {
            return Err(format!(
                "provider record digest mismatch at {}: expected {}, computed {}",
                path.display(),
                expected_digest,
                decoded.digest
            ));
        }
        Ok(StoredRecord {
            relative_path: relative.to_string_lossy().into_owned(),
            digest: decoded.digest.clone(),
            decoded,
        })
    }
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

fn ensure_canonical_child(root: &Path, child: &Path) -> Result<(), String> {
    let canonical = fs::canonicalize(child)
        .map_err(|error| format!("canonicalize artifact path {}: {error}", child.display()))?;
    if !canonical.starts_with(root) {
        return Err(format!(
            "artifact path escapes artifact_root: {} resolves to {}",
            child.display(),
            canonical.display()
        ));
    }
    Ok(())
}

fn atomic_create(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| format!("atomic destination has no parent: {}", path.display()))?;
    let name = path
        .file_name()
        .ok_or_else(|| format!("atomic destination has no file name: {}", path.display()))?
        .to_string_lossy();
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let temp = parent.join(format!(".{name}.tmp-{}-{sequence}", std::process::id()));
    let result = (|| {
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        options.custom_flags(libc::O_NOFOLLOW);
        let mut file = options
            .open(&temp)
            .map_err(|error| format!("create same-directory temporary file: {error}"))?;
        file.write_all(bytes)
            .and_then(|_| file.sync_all())
            .map_err(|error| format!("write and sync temporary file: {error}"))?;
        drop(file);

        // Same-directory hard-link installation is atomic and create-only: an
        // existing destination returns AlreadyExists and is never replaced.
        fs::hard_link(&temp, path)
            .map_err(|error| format!("install without replacement: {error}"))?;
        sync_directory(parent)?;
        fs::remove_file(&temp)
            .map_err(|error| format!("remove installed temporary link: {error}"))?;
        sync_directory(parent)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result
}

fn sync_directory(path: &Path) -> Result<(), String> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|error| format!("sync directory {}: {error}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::tempdir;

    fn claim(run_id: &str) -> Value {
        json!({
            "schema":"claim-set-v1", "run_id":run_id,
            "manifest_digest":format!("sha256:{}", "0".repeat(64)), "claims":[]
        })
    }

    #[test]
    fn claims_empty_root_and_never_overwrites_records() {
        let temp = tempdir().unwrap();
        let root = fs::canonicalize(temp.path()).unwrap();
        let store = ArtifactStore::open(&root, "run-1").unwrap();
        let first = store
            .store(
                RecordCategory::Audits,
                "inv-1",
                RecordKind::ClaimSet,
                &claim("run-1"),
            )
            .unwrap();
        assert!(store
            .store(
                RecordCategory::Audits,
                "inv-1",
                RecordKind::ClaimSet,
                &claim("run-1")
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
        assert_eq!(loaded.decoded.value, claim("run-1"));
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
                &claim("run-1"),
            )
            .unwrap();
        fs::write(root.join(&saved.relative_path), b"{}").unwrap();
        assert!(store
            .load(&saved.relative_path, RecordKind::ClaimSet, &saved.digest)
            .is_err());
    }
}
