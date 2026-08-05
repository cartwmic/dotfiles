use crate::boundary::{
    git, git_command, git_output, BoundaryError, ValidatedRoots, CORE_DOCUMENTS,
};
use crate::codec::{self, DecodedRecord};
use crate::schema::RecordKind;
use base64::Engine;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::Read;
use std::path::Path;

#[cfg(unix)]
use std::os::unix::ffi::OsStrExt;
#[cfg(unix)]
use std::os::unix::fs::{FileTypeExt, MetadataExt, OpenOptionsExt};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ManifestDifference {
    pub path: String,
    pub kind: &'static str,
}

#[derive(Debug, Clone)]
pub struct StagedReplacement {
    pub path: String,
    pub bytes: Vec<u8>,
    pub mode: u32,
}

pub struct RepositoryView<'a> {
    roots: &'a ValidatedRoots,
    run_id: &'a str,
}

impl<'a> RepositoryView<'a> {
    pub fn new(roots: &'a ValidatedRoots, run_id: &'a str) -> Self {
        Self { roots, run_id }
    }

    pub fn capture(&self) -> Result<DecodedRecord, String> {
        let head = head_paths(&self.roots.work_root).map_err(display_boundary)?;
        let index = index_entries(&self.roots.work_root).map_err(display_boundary)?;
        let statuses = status_entries(&self.roots.work_root).map_err(display_boundary)?;
        let paths = complete_paths(&self.roots.work_root, &head, &index, &statuses)
            .map_err(display_boundary)?;
        let mut entries = Vec::with_capacity(paths.len());
        for path in paths {
            let index_entry = index.get(&path);
            let tracked = index_entry.is_some() || head.contains(&path);
            entries.push(inspect_path(
                &self.roots.work_root,
                &path,
                index_entry,
                tracked,
                statuses
                    .get(&path)
                    .map(String::as_str)
                    .unwrap_or(if tracked { "clean" } else { "untracked" }),
            )?);
        }
        let fingerprint = fingerprint(
            "baseline",
            &self.roots.work_root,
            &self.roots.git_common_dir,
            &entries,
            None,
            &[],
        )?;
        let value = json!({
            "schema": "repository-manifest-v1",
            "run_id": self.run_id,
            "manifest_kind": "baseline",
            "work_root": self.roots.work_root.to_string_lossy(),
            "git_common_dir": self.roots.git_common_dir.to_string_lossy(),
            "entries": entries,
            "repository_fingerprint": fingerprint,
            "baseline_digest": null,
            "overlay_paths": [],
        });
        codec::encode_record(&value, RecordKind::RepositoryManifest, self.run_id)
    }

    pub fn capture_stable(&self) -> Result<DecodedRecord, String> {
        let before = self.capture()?;
        let after = self.capture()?;
        let differences = compare(&before.value, &after.value)?;
        if !differences.is_empty() {
            let paths = differences
                .iter()
                .take(32)
                .map(|difference| format!("{} ({})", difference.path, difference.kind))
                .collect::<Vec<_>>()
                .join(", ");
            return Err(format!(
                "repository changed while manifest was captured: {paths}"
            ));
        }
        Ok(after)
    }
}

pub fn staged_overlay(
    baseline: &DecodedRecord,
    replacements: &[StagedReplacement],
) -> Result<DecodedRecord, String> {
    if baseline.kind != RecordKind::RepositoryManifest {
        return Err("staged overlay requires a repository-manifest-v1 baseline".to_string());
    }
    if baseline.value["manifest_kind"] != "baseline"
        || !baseline.value["baseline_digest"].is_null()
        || !baseline.value["overlay_paths"]
            .as_array()
            .is_some_and(Vec::is_empty)
    {
        return Err(
            "staged overlay requires a pristine baseline manifest with no baseline digest or overlay paths"
                .to_string(),
        );
    }
    let run_id = baseline.value["run_id"]
        .as_str()
        .expect("validated manifest run_id");
    let mut by_path = BTreeMap::new();
    for replacement in replacements {
        if !CORE_DOCUMENTS.contains(&replacement.path.as_str()) {
            return Err(format!(
                "staged overlay target is not a core document: {}",
                replacement.path
            ));
        }
        if replacement.mode > 0o7777 {
            return Err(format!(
                "staged overlay mode is out of range for {}",
                replacement.path
            ));
        }
        if by_path
            .insert(replacement.path.clone(), replacement)
            .is_some()
        {
            return Err(format!(
                "duplicate staged overlay target: {}",
                replacement.path
            ));
        }
    }
    if by_path.len() > 3 {
        return Err("staged overlay has more than three core-document targets".to_string());
    }

    let mut entries: BTreeMap<String, Value> = baseline.value["entries"]
        .as_array()
        .expect("validated manifest entries")
        .iter()
        .map(|entry| (entry["path"].as_str().unwrap().to_string(), entry.clone()))
        .collect();
    for (path, replacement) in &by_path {
        let digest = codec::sha256(&replacement.bytes);
        let tracked = entries
            .get(path)
            .and_then(|entry| entry["tracked"].as_bool())
            .unwrap_or(false);
        entries.insert(
            path.clone(),
            json!({
                "path": path,
                "kind": "regular",
                "tracked": tracked,
                "git_status": "staged-overlay",
                "core_document": true,
                "identity": {
                    "kind": "regular",
                    "mode": replacement.mode,
                    "size": replacement.bytes.len(),
                    "sha256": digest,
                    "content_base64": base64::engine::general_purpose::STANDARD.encode(&replacement.bytes),
                }
            }),
        );
    }
    let entries: Vec<Value> = entries.into_values().collect();
    let overlay_paths: Vec<Value> = by_path
        .keys()
        .map(|path| Value::String(path.clone()))
        .collect();
    let work_root = baseline.value["work_root"].as_str().unwrap();
    let git_common_dir = baseline.value["git_common_dir"].as_str().unwrap();
    let fingerprint = fingerprint(
        "staged",
        Path::new(work_root),
        Path::new(git_common_dir),
        &entries,
        Some(&baseline.digest),
        &overlay_paths,
    )?;
    let value = json!({
        "schema": "repository-manifest-v1",
        "run_id": run_id,
        "manifest_kind": "staged",
        "work_root": work_root,
        "git_common_dir": git_common_dir,
        "entries": entries,
        "repository_fingerprint": fingerprint,
        "baseline_digest": baseline.digest,
        "overlay_paths": overlay_paths,
    });
    codec::encode_record(&value, RecordKind::RepositoryManifest, run_id)
}

pub fn compare(expected: &Value, actual: &Value) -> Result<Vec<ManifestDifference>, String> {
    for value in [expected, actual] {
        if value.get("schema").and_then(Value::as_str) != Some("repository-manifest-v1") {
            return Err("manifest comparison requires repository-manifest-v1 values".to_string());
        }
    }
    let expected = entries_by_path(expected)?;
    let actual = entries_by_path(actual)?;
    let paths: BTreeSet<&str> = expected
        .keys()
        .chain(actual.keys())
        .map(String::as_str)
        .collect();
    let mut differences = Vec::new();
    for path in paths {
        let kind = match (expected.get(path), actual.get(path)) {
            (None, Some(_)) => Some("added"),
            (Some(_), None) => Some("removed"),
            (Some(left), Some(right)) if left == right => None,
            (Some(left), Some(right)) if left["kind"] != right["kind"] => Some("type-changed"),
            (Some(left), Some(right)) if left["identity"]["mode"] != right["identity"]["mode"] => {
                Some("mode-changed")
            }
            (Some(left), Some(right))
                if left["identity"]["kind"] == "regular"
                    && left["identity"]["sha256"] != right["identity"]["sha256"] =>
            {
                Some("bytes-changed")
            }
            (Some(left), Some(right))
                if left["identity"]["kind"] == "symlink"
                    && left["identity"]["target_sha256"] != right["identity"]["target_sha256"] =>
            {
                Some("target-changed")
            }
            (Some(left), Some(_right))
                if matches!(
                    left["identity"]["kind"].as_str(),
                    Some("character-device" | "block-device")
                ) =>
            {
                Some("device-changed")
            }
            _ => Some("status-changed"),
        };
        if let Some(kind) = kind {
            differences.push(ManifestDifference {
                path: path.to_string(),
                kind,
            });
        }
    }
    Ok(differences)
}

fn entries_by_path(value: &Value) -> Result<BTreeMap<String, &Value>, String> {
    value["entries"]
        .as_array()
        .ok_or_else(|| "manifest entries is not an array".to_string())?
        .iter()
        .map(|entry| {
            entry["path"]
                .as_str()
                .map(|path| (path.to_string(), entry))
                .ok_or_else(|| "manifest entry path is not a string".to_string())
        })
        .collect()
}

#[derive(Debug, Clone)]
struct IndexEntry {
    mode: String,
    object_id: String,
}

fn complete_paths(
    work_root: &Path,
    head: &BTreeSet<String>,
    index: &BTreeMap<String, IndexEntry>,
    statuses: &BTreeMap<String, String>,
) -> Result<Vec<String>, BoundaryError> {
    let output = git(
        work_root,
        &["ls-files", "-z", "--others", "--exclude-standard"],
    )?;
    let mut paths = head.clone();
    paths.extend(index.keys().cloned());
    paths.extend(statuses.keys().cloned());
    for raw in output
        .stdout
        .split(|byte| *byte == 0)
        .filter(|raw| !raw.is_empty())
    {
        let path = std::str::from_utf8(raw).map_err(|_| BoundaryError {
            code: "input.repository.non-utf8-path",
            message: "repository contains a non-UTF-8 path".to_string(),
            path: String::from_utf8_lossy(raw).into_owned(),
        })?;
        if path == ".git" || path.starts_with(".git/") {
            continue;
        }
        paths.insert(path.to_string());
    }
    collect_special_paths(work_root, work_root, &mut paths)?;
    Ok(paths.into_iter().collect())
}

fn collect_special_paths(
    work_root: &Path,
    directory: &Path,
    paths: &mut BTreeSet<String>,
) -> Result<(), BoundaryError> {
    let entries = fs::read_dir(directory).map_err(|error| BoundaryError {
        code: "input.repository.inspect",
        message: error.to_string(),
        path: directory.display().to_string(),
    })?;
    for entry in entries {
        let entry = entry.map_err(|error| BoundaryError {
            code: "input.repository.inspect",
            message: error.to_string(),
            path: directory.display().to_string(),
        })?;
        if directory == work_root && entry.file_name() == ".git" {
            continue;
        }
        let path = entry.path();
        let relative_os = path
            .strip_prefix(work_root)
            .expect("walk rooted at work_root");
        let relative = relative_os.to_str().ok_or_else(|| BoundaryError {
            code: "input.repository.non-utf8-path",
            message: "repository contains a non-UTF-8 path".to_string(),
            path: relative_os.to_string_lossy().into_owned(),
        })?;
        if git_ignored(work_root, relative)? {
            continue;
        }
        let metadata = fs::symlink_metadata(&path).map_err(|error| BoundaryError {
            code: "input.repository.inspect",
            message: error.to_string(),
            path: relative.to_string(),
        })?;
        if metadata.is_dir() {
            collect_special_paths(work_root, &path, paths)?;
        } else if !metadata.is_file() && !metadata.file_type().is_symlink() {
            paths.insert(relative.to_string());
        }
    }
    Ok(())
}

fn git_ignored(work_root: &Path, relative: &str) -> Result<bool, BoundaryError> {
    let status = git_command(
        work_root,
        &["check-ignore", "-q", "--no-index", "--", relative],
    )
    .status()
    .map_err(|error| BoundaryError {
        code: "input.git.unavailable",
        message: format!("execute git check-ignore: {error}"),
        path: relative.to_string(),
    })?;
    match status.code() {
        Some(0) => Ok(true),
        Some(1) => Ok(false),
        code => Err(BoundaryError {
            code: "input.repository.ignore-check",
            message: format!("git check-ignore exited with {code:?}"),
            path: relative.to_string(),
        }),
    }
}

fn head_paths(work_root: &Path) -> Result<BTreeSet<String>, BoundaryError> {
    let verify = git_output(work_root, &["rev-parse", "--verify", "-q", "HEAD"])?;
    if !verify.status.success() {
        return Ok(BTreeSet::new());
    }
    let output = git(work_root, &["ls-tree", "-r", "-z", "--name-only", "HEAD"])?;
    output
        .stdout
        .split(|byte| *byte == 0)
        .filter(|raw| !raw.is_empty())
        .map(|raw| {
            std::str::from_utf8(raw)
                .map(str::to_string)
                .map_err(|_| BoundaryError {
                    code: "input.repository.non-utf8-path",
                    message: "HEAD tree contains a non-UTF-8 path".to_string(),
                    path: String::from_utf8_lossy(raw).into_owned(),
                })
        })
        .collect()
}

fn index_entries(work_root: &Path) -> Result<BTreeMap<String, IndexEntry>, BoundaryError> {
    let output = git(work_root, &["ls-files", "--stage", "-z"])?;
    let mut entries = BTreeMap::new();
    for raw in output
        .stdout
        .split(|byte| *byte == 0)
        .filter(|raw| !raw.is_empty())
    {
        let Some(tab) = raw.iter().position(|byte| *byte == b'\t') else {
            continue;
        };
        let header = std::str::from_utf8(&raw[..tab]).map_err(|_| BoundaryError {
            code: "input.repository.invalid-index",
            message: "Git index emitted invalid UTF-8 metadata".to_string(),
            path: work_root.display().to_string(),
        })?;
        let path = std::str::from_utf8(&raw[tab + 1..]).map_err(|_| BoundaryError {
            code: "input.repository.non-utf8-path",
            message: "Git index contains a non-UTF-8 path".to_string(),
            path: String::from_utf8_lossy(&raw[tab + 1..]).into_owned(),
        })?;
        let fields: Vec<&str> = header.split(' ').collect();
        if fields.len() != 3 {
            return Err(BoundaryError {
                code: "input.repository.invalid-index",
                message: "Git index emitted malformed stage metadata".to_string(),
                path: path.to_string(),
            });
        }
        if fields[2] != "0" {
            return Err(BoundaryError {
                code: "input.repository.conflicted-index",
                message: format!(
                    "conflicted index path is not fully modeled (encountered stage {})",
                    fields[2]
                ),
                path: path.to_string(),
            });
        }
        entries.insert(
            path.to_string(),
            IndexEntry {
                mode: fields[0].to_string(),
                object_id: fields[1].to_string(),
            },
        );
    }
    Ok(entries)
}

fn status_entries(work_root: &Path) -> Result<BTreeMap<String, String>, BoundaryError> {
    let output = git(
        work_root,
        &[
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignored=no",
        ],
    )?;
    let records: Vec<&[u8]> = output.stdout.split(|byte| *byte == 0).collect();
    let mut statuses = BTreeMap::new();
    let mut index = 0;
    while index < records.len() {
        let raw = records[index];
        index += 1;
        if raw.is_empty() {
            continue;
        }
        if raw.len() < 4 || raw[2] != b' ' {
            continue;
        }
        let status = String::from_utf8_lossy(&raw[..2]).into_owned();
        let path_raw = &raw[3..];
        let path = std::str::from_utf8(path_raw).map_err(|_| BoundaryError {
            code: "input.repository.non-utf8-path",
            message: "Git status contains a non-UTF-8 path".to_string(),
            path: String::from_utf8_lossy(path_raw).into_owned(),
        })?;
        statuses.insert(path.to_string(), status.clone());
        if status.bytes().any(|byte| matches!(byte, b'R' | b'C')) && index < records.len() {
            let source_raw = records[index];
            index += 1;
            let source = std::str::from_utf8(source_raw).map_err(|_| BoundaryError {
                code: "input.repository.non-utf8-path",
                message: "Git status contains a non-UTF-8 rename source".to_string(),
                path: String::from_utf8_lossy(source_raw).into_owned(),
            })?;
            statuses.insert(source.to_string(), format!("{status}:source"));
        }
    }
    Ok(statuses)
}

fn inspect_path(
    work_root: &Path,
    relative: &str,
    index: Option<&IndexEntry>,
    tracked: bool,
    status: &str,
) -> Result<Value, String> {
    let core = CORE_DOCUMENTS.contains(&relative);
    if index.is_some_and(|entry| entry.mode == "160000") {
        return Ok(json!({
            "path":relative, "kind":"gitlink", "tracked":true, "git_status":status,
            "core_document":core, "identity":{"kind":"gitlink","object_id":index.unwrap().object_id}
        }));
    }
    let path = work_root.join(relative);
    let metadata = match fs::symlink_metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok(json!({
                "path":relative, "kind":"absent", "tracked":tracked, "git_status":status,
                "core_document":core, "identity":{"kind":"absent"}
            }))
        }
        Err(error) => return Err(format!("inspect repository path {relative}: {error}")),
    };
    let file_type = metadata.file_type();
    let mode = unix_mode(&metadata);
    let (kind, identity) = if file_type.is_dir() {
        // Git tracks files, symlinks, and gitlinks, never directories. A path
        // retained from HEAD or the index can therefore become a directory in
        // the worktree when its tracked entry is removed and descendants are
        // added beneath the same name. Keep the old tracked path as explicit
        // absence; complete_paths records each non-ignored descendant
        // separately. Directories themselves remain outside the manifest.
        ("absent", json!({"kind":"absent"}))
    } else if file_type.is_file() {
        let bytes = read_regular_stable(&path, &metadata)?;
        (
            "regular",
            json!({"kind":"regular","mode":mode,"size":bytes.len(),"sha256":codec::sha256(&bytes),"content_base64":base64::engine::general_purpose::STANDARD.encode(bytes)}),
        )
    } else if file_type.is_symlink() {
        let target = fs::read_link(&path)
            .map_err(|error| format!("read symlink target {relative}: {error}"))?;
        #[cfg(unix)]
        let bytes = target.as_os_str().as_bytes();
        #[cfg(not(unix))]
        let bytes = target.to_string_lossy().as_bytes();
        (
            "symlink",
            json!({"kind":"symlink","mode":mode,"target_sha256":codec::sha256(bytes),"target_base64":base64::engine::general_purpose::STANDARD.encode(bytes)}),
        )
    } else if is_fifo(&file_type) {
        ("fifo", json!({"kind":"fifo","mode":mode}))
    } else if is_socket(&file_type) {
        ("socket", json!({"kind":"socket","mode":mode}))
    } else if is_char_device(&file_type) {
        let (major, minor) = device_identity(&metadata);
        (
            "character-device",
            json!({"kind":"character-device","mode":mode,"device_major":major,"device_minor":minor}),
        )
    } else if is_block_device(&file_type) {
        let (major, minor) = device_identity(&metadata);
        (
            "block-device",
            json!({"kind":"block-device","mode":mode,"device_major":major,"device_minor":minor}),
        )
    } else {
        return Err(format!("unsupported repository path type: {relative}"));
    };
    Ok(json!({
        "path":relative, "kind":kind, "tracked":tracked, "git_status":status,
        "core_document":core, "identity":identity
    }))
}

fn read_regular_stable(path: &Path, before: &fs::Metadata) -> Result<Vec<u8>, String> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    options.custom_flags(libc::O_NOFOLLOW);
    let mut file = options
        .open(path)
        .map_err(|error| format!("open regular file {}: {error}", path.display()))?;
    let opened = file
        .metadata()
        .map_err(|error| format!("stat open file {}: {error}", path.display()))?;
    if !same_file(before, &opened) || !opened.is_file() {
        return Err(format!(
            "repository path changed before read: {}",
            path.display()
        ));
    }
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)
        .map_err(|error| format!("read regular file {}: {error}", path.display()))?;
    let after = file
        .metadata()
        .map_err(|error| format!("stat read file {}: {error}", path.display()))?;
    if !same_file(&opened, &after) {
        return Err(format!(
            "repository path changed during read: {}",
            path.display()
        ));
    }
    Ok(bytes)
}

#[cfg(unix)]
fn same_file(left: &fs::Metadata, right: &fs::Metadata) -> bool {
    left.dev() == right.dev()
        && left.ino() == right.ino()
        && left.len() == right.len()
        && left.mode() == right.mode()
        && left.mtime() == right.mtime()
        && left.mtime_nsec() == right.mtime_nsec()
}
#[cfg(not(unix))]
fn same_file(left: &fs::Metadata, right: &fs::Metadata) -> bool {
    left.len() == right.len() && left.modified().ok() == right.modified().ok()
}

#[cfg(unix)]
fn unix_mode(metadata: &fs::Metadata) -> u32 {
    metadata.mode() & 0o7777
}
#[cfg(not(unix))]
fn unix_mode(_metadata: &fs::Metadata) -> u32 {
    0
}
#[cfg(unix)]
fn is_fifo(file_type: &fs::FileType) -> bool {
    file_type.is_fifo()
}
#[cfg(not(unix))]
fn is_fifo(_file_type: &fs::FileType) -> bool {
    false
}
#[cfg(unix)]
fn is_socket(file_type: &fs::FileType) -> bool {
    file_type.is_socket()
}
#[cfg(not(unix))]
fn is_socket(_file_type: &fs::FileType) -> bool {
    false
}
#[cfg(unix)]
fn is_char_device(file_type: &fs::FileType) -> bool {
    file_type.is_char_device()
}
#[cfg(not(unix))]
fn is_char_device(_file_type: &fs::FileType) -> bool {
    false
}
#[cfg(unix)]
fn is_block_device(file_type: &fs::FileType) -> bool {
    file_type.is_block_device()
}
#[cfg(not(unix))]
fn is_block_device(_file_type: &fs::FileType) -> bool {
    false
}
#[cfg(unix)]
fn device_identity(metadata: &fs::Metadata) -> (u64, u64) {
    let device = metadata.rdev() as libc::dev_t;
    (libc::major(device) as u64, libc::minor(device) as u64)
}
#[cfg(not(unix))]
fn device_identity(_metadata: &fs::Metadata) -> (u64, u64) {
    (0, 0)
}

fn fingerprint(
    kind: &str,
    work_root: &Path,
    git_common_dir: &Path,
    entries: &[Value],
    baseline_digest: Option<&str>,
    overlay_paths: &[Value],
) -> Result<String, String> {
    let payload = json!({
        "manifest_kind":kind,
        "work_root":work_root.to_string_lossy(),
        "git_common_dir":git_common_dir.to_string_lossy(),
        "entries":entries,
        "baseline_digest":baseline_digest,
        "overlay_paths":overlay_paths,
    });
    Ok(codec::sha256(&codec::canonicalize(&payload)?))
}

fn display_boundary(error: BoundaryError) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::boundary::validate_roots;
    use std::os::unix::fs::{symlink, PermissionsExt};
    use std::os::unix::net::UnixListener;
    use std::process::Command;
    use tempfile::tempdir;

    fn fixture() -> (tempfile::TempDir, tempfile::TempDir, ValidatedRoots) {
        let work = tempdir().unwrap();
        let artifacts = tempdir().unwrap();
        Command::new("git")
            .args(["init", "-q"])
            .current_dir(work.path())
            .status()
            .unwrap();
        fs::write(work.path().join("tracked.txt"), b"tracked").unwrap();
        fs::create_dir(work.path().join("docs")).unwrap();
        fs::write(work.path().join("docs/intent.md"), b"intent").unwrap();
        Command::new("git")
            .args(["add", "."])
            .current_dir(work.path())
            .status()
            .unwrap();
        fs::write(work.path().join("untracked.txt"), b"untracked").unwrap();
        fs::write(work.path().join("ignored.txt"), b"ignored").unwrap();
        fs::write(work.path().join(".gitignore"), b"ignored.txt\n").unwrap();
        symlink("tracked.txt", work.path().join("link")).unwrap();
        let roots = validate_roots(
            &fs::canonicalize(work.path()).unwrap(),
            &fs::canonicalize(artifacts.path()).unwrap(),
        )
        .unwrap();
        (work, artifacts, roots)
    }

    #[test]
    fn manifest_has_complete_git_set_and_type_identities() {
        let (work, _artifacts, roots) = fixture();
        let fifo = work.path().join("pipe");
        let fifo_c = std::ffi::CString::new(fifo.as_os_str().as_bytes()).unwrap();
        assert_eq!(unsafe { libc::mkfifo(fifo_c.as_ptr(), 0o600) }, 0);
        let _socket = UnixListener::bind(work.path().join("socket")).unwrap();
        let manifest = RepositoryView::new(&roots, "run-1").capture().unwrap();
        let entries = entries_by_path(&manifest.value).unwrap();
        assert!(entries.contains_key("tracked.txt"));
        assert!(entries.contains_key("untracked.txt"));
        assert!(entries.contains_key("docs/intent.md"));
        assert!(!entries.contains_key("ignored.txt"));
        assert!(!entries.keys().any(|path| path.starts_with(".git/")));
        assert_eq!(entries["link"]["kind"], "symlink");
        assert_eq!(entries["pipe"]["kind"], "fifo");
        assert_eq!(entries["socket"]["kind"], "socket");
    }

    #[test]
    fn comparison_orders_added_removed_type_mode_and_byte_changes() {
        let (_work, _artifacts, roots) = fixture();
        let view = RepositoryView::new(&roots, "run-1");
        let before = view.capture().unwrap();
        fs::write(roots.work_root.join("tracked.txt"), b"changed").unwrap();
        fs::remove_file(roots.work_root.join("untracked.txt")).unwrap();
        fs::write(roots.work_root.join("added.txt"), b"added").unwrap();
        fs::remove_file(roots.work_root.join("link")).unwrap();
        fs::write(roots.work_root.join("link"), b"regular now").unwrap();
        let mut permissions = fs::metadata(roots.work_root.join("docs/intent.md"))
            .unwrap()
            .permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(roots.work_root.join("docs/intent.md"), permissions).unwrap();
        let after = view.capture().unwrap();
        let differences = compare(&before.value, &after.value).unwrap();
        assert_eq!(
            differences
                .iter()
                .map(|item| item.path.as_str())
                .collect::<Vec<_>>(),
            vec![
                "added.txt",
                "docs/intent.md",
                "link",
                "tracked.txt",
                "untracked.txt"
            ]
        );
        assert_eq!(
            differences.iter().map(|item| item.kind).collect::<Vec<_>>(),
            vec![
                "added",
                "mode-changed",
                "type-changed",
                "bytes-changed",
                "removed"
            ]
        );
    }

    #[test]
    fn staged_overlay_changes_only_core_targets() {
        let (_work, _artifacts, roots) = fixture();
        let baseline = RepositoryView::new(&roots, "run-1").capture().unwrap();
        let staged = staged_overlay(
            &baseline,
            &[StagedReplacement {
                path: "README.md".to_string(),
                bytes: b"draft".to_vec(),
                mode: 0o644,
            }],
        )
        .unwrap();
        let differences = compare(&baseline.value, &staged.value).unwrap();
        assert_eq!(
            differences,
            vec![ManifestDifference {
                path: "README.md".to_string(),
                kind: "added"
            }]
        );
        assert!(staged_overlay(
            &baseline,
            &[StagedReplacement {
                path: "src/lib.rs".to_string(),
                bytes: vec![],
                mode: 0o644
            }]
        )
        .is_err());
        assert!(staged_overlay(&staged, &[]).is_err());

        let mut tainted = baseline.clone();
        tainted.value["overlay_paths"] = json!(["README.md"]);
        assert!(staged_overlay(&tainted, &[]).is_err());
    }

    fn commit_all(work: &Path) {
        assert!(Command::new("git")
            .args([
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ])
            .current_dir(work)
            .status()
            .unwrap()
            .success());
    }

    #[test]
    fn manifest_unions_head_index_and_both_rename_paths_with_explicit_deletion() {
        let (_work, _artifacts, roots) = fixture();
        commit_all(&roots.work_root);
        assert!(Command::new("git")
            .args(["mv", "tracked.txt", "renamed.txt"])
            .current_dir(&roots.work_root)
            .status()
            .unwrap()
            .success());
        assert!(Command::new("git")
            .args(["rm", "-q", "docs/intent.md"])
            .current_dir(&roots.work_root)
            .status()
            .unwrap()
            .success());

        let manifest = RepositoryView::new(&roots, "run-1").capture().unwrap();
        let entries = entries_by_path(&manifest.value).unwrap();
        assert_eq!(entries["tracked.txt"]["kind"], "absent");
        assert_eq!(entries["tracked.txt"]["tracked"], true);
        assert_eq!(entries["renamed.txt"]["kind"], "regular");
        assert_eq!(entries["docs/intent.md"]["kind"], "absent");
        assert_eq!(entries["docs/intent.md"]["tracked"], true);
    }

    #[test]
    fn tracked_file_replaced_by_directory_is_absent_while_descendants_remain() {
        let (_work, _artifacts, roots) = fixture();
        commit_all(&roots.work_root);
        fs::remove_file(roots.work_root.join("tracked.txt")).unwrap();
        fs::create_dir(roots.work_root.join("tracked.txt")).unwrap();
        fs::write(
            roots.work_root.join("tracked.txt/descendant.txt"),
            b"replacement",
        )
        .unwrap();

        let manifest = RepositoryView::new(&roots, "run-1").capture().unwrap();
        let entries = entries_by_path(&manifest.value).unwrap();
        assert_eq!(entries["tracked.txt"]["kind"], "absent");
        assert_eq!(entries["tracked.txt"]["tracked"], true);
        assert_eq!(entries["tracked.txt/descendant.txt"]["kind"], "regular");
        assert_eq!(entries["tracked.txt/descendant.txt"]["tracked"], false);
    }

    #[test]
    fn conflicted_index_is_rejected_with_its_path() {
        use std::io::Write;
        use std::process::Stdio;

        let (_work, _artifacts, roots) = fixture();
        let mut object_ids = Vec::new();
        for bytes in [b"base".as_slice(), b"ours".as_slice(), b"theirs".as_slice()] {
            let mut child = Command::new("git")
                .args(["hash-object", "-w", "--stdin"])
                .current_dir(&roots.work_root)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .spawn()
                .unwrap();
            child.stdin.as_mut().unwrap().write_all(bytes).unwrap();
            let output = child.wait_with_output().unwrap();
            assert!(output.status.success());
            object_ids.push(String::from_utf8(output.stdout).unwrap().trim().to_string());
        }
        let mut child = Command::new("git")
            .args(["update-index", "--index-info"])
            .current_dir(&roots.work_root)
            .stdin(Stdio::piped())
            .spawn()
            .unwrap();
        let index = format!(
            "0 0000000000000000000000000000000000000000\ttracked.txt\n100644 {} 1\tconflict.txt\n100644 {} 2\tconflict.txt\n100644 {} 3\tconflict.txt\n",
            object_ids[0], object_ids[1], object_ids[2]
        );
        child
            .stdin
            .as_mut()
            .unwrap()
            .write_all(index.as_bytes())
            .unwrap();
        assert!(child.wait().unwrap().success());

        let error = RepositoryView::new(&roots, "run-1").capture().unwrap_err();
        assert!(
            error.contains("input.repository.conflicted-index"),
            "{error}"
        );
        assert!(error.contains("conflict.txt"), "{error}");
    }
}
