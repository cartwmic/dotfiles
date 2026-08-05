use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

#[cfg(unix)]
use std::ffi::CString;
#[cfg(unix)]
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
#[cfg(unix)]
use std::os::unix::ffi::OsStrExt;

pub const CORE_DOCUMENTS: [&str; 3] = ["README.md", "AGENTS.md", "docs/intent.md"];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidatedRoots {
    pub work_root: PathBuf,
    pub artifact_root: PathBuf,
    pub git_common_dir: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BoundaryError {
    pub code: &'static str,
    pub message: String,
    pub path: String,
}

impl std::fmt::Display for BoundaryError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            formatter,
            "{} at {}: {}",
            self.code, self.path, self.message
        )
    }
}

pub fn validate_roots(
    work_root: &Path,
    artifact_root: &Path,
) -> Result<ValidatedRoots, BoundaryError> {
    let work = canonical_exact(work_root, "work_root")?;
    let artifact = canonical_exact(artifact_root, "artifact_root")?;
    if work.starts_with(&artifact) || artifact.starts_with(&work) {
        return Err(BoundaryError {
            code: "input.roots.overlap",
            message: "work_root and artifact_root must be disjoint".to_string(),
            path: format!("{} <-> {}", work.display(), artifact.display()),
        });
    }

    let bare = git(&work, &["rev-parse", "--is-bare-repository"])?;
    if text(&bare) != "false" {
        return Err(BoundaryError {
            code: "input.work-root.not-worktree",
            message: "work_root must be a non-bare Git worktree".to_string(),
            path: work.display().to_string(),
        });
    }
    let top = git(&work, &["rev-parse", "--show-toplevel"])?;
    let top = PathBuf::from(text(&top));
    let top = fs::canonicalize(&top).map_err(|error| BoundaryError {
        code: "input.work-root.git-root",
        message: format!("canonicalize Git top level: {error}"),
        path: top.display().to_string(),
    })?;
    if top != work {
        return Err(BoundaryError {
            code: "input.work-root.not-top-level",
            message: format!("work_root must equal Git top level {}", top.display()),
            path: work.display().to_string(),
        });
    }
    let common = git(
        &work,
        &["rev-parse", "--path-format=absolute", "--git-common-dir"],
    )?;
    let common_input = PathBuf::from(text(&common));
    let common = fs::canonicalize(&common_input).map_err(|error| BoundaryError {
        code: "input.work-root.git-common-dir",
        message: format!("canonicalize Git common directory: {error}"),
        path: common_input.display().to_string(),
    })?;
    if artifact.starts_with(&common) || common.starts_with(&artifact) {
        return Err(BoundaryError {
            code: "input.artifact-root.git-overlap",
            message: "artifact_root must not overlap Git administrative storage".to_string(),
            path: artifact.display().to_string(),
        });
    }

    validate_core_documents(&work)?;
    Ok(ValidatedRoots {
        work_root: work,
        artifact_root: artifact,
        git_common_dir: common,
    })
}

fn canonical_exact(path: &Path, label: &'static str) -> Result<PathBuf, BoundaryError> {
    if !path.is_absolute() {
        return Err(BoundaryError {
            code: "input.root.relative",
            message: format!("{label} must be absolute"),
            path: path.display().to_string(),
        });
    }
    let canonical = fs::canonicalize(path).map_err(|error| BoundaryError {
        code: "input.root.missing",
        message: format!("{label} must name an existing directory: {error}"),
        path: path.display().to_string(),
    })?;
    if canonical.as_os_str() != path.as_os_str() {
        return Err(BoundaryError {
            code: "input.root.noncanonical",
            message: format!("{label} must use canonical path {}", canonical.display()),
            path: path.display().to_string(),
        });
    }
    if !canonical.is_dir() {
        return Err(BoundaryError {
            code: "input.root.not-directory",
            message: format!("{label} is not a directory"),
            path: canonical.display().to_string(),
        });
    }
    Ok(canonical)
}

fn validate_core_documents(work_root: &Path) -> Result<(), BoundaryError> {
    for relative in CORE_DOCUMENTS {
        validate_core_document_no_follow(work_root, relative)?;
    }

    let staged = git(work_root, &["ls-files", "--stage", "-z"])?;
    for record in staged
        .stdout
        .split(|byte| *byte == 0)
        .filter(|record| !record.is_empty())
    {
        let Some(tab) = record.iter().position(|byte| *byte == b'\t') else {
            continue;
        };
        let header = &record[..tab];
        let path = std::str::from_utf8(&record[tab + 1..]).map_err(|_| BoundaryError {
            code: "input.repository.non-utf8-path",
            message: "Git index contains a non-UTF-8 path".to_string(),
            path: String::from_utf8_lossy(&record[tab + 1..]).into_owned(),
        })?;
        let mode = header
            .split(|byte| *byte == b' ')
            .next()
            .unwrap_or_default();
        if mode == b"160000"
            && CORE_DOCUMENTS
                .iter()
                .any(|core| *core == path || core.starts_with(&format!("{path}/")))
        {
            return Err(BoundaryError {
                code: "input.core-document.submodule",
                message: "core document is resident in a Git submodule".to_string(),
                path: path.to_string(),
            });
        }
    }
    Ok(())
}

#[cfg(unix)]
fn validate_core_document_no_follow(work_root: &Path, relative: &str) -> Result<(), BoundaryError> {
    let root = CString::new(work_root.as_os_str().as_bytes()).map_err(|error| BoundaryError {
        code: "input.core-document.inspect",
        message: error.to_string(),
        path: relative.to_string(),
    })?;
    let root_fd = unsafe {
        libc::open(
            root.as_ptr(),
            libc::O_RDONLY | libc::O_DIRECTORY | libc::O_CLOEXEC | libc::O_NOFOLLOW,
        )
    };
    if root_fd < 0 {
        return Err(BoundaryError {
            code: "input.core-document.inspect",
            message: std::io::Error::last_os_error().to_string(),
            path: work_root.display().to_string(),
        });
    }
    let mut directory = unsafe { OwnedFd::from_raw_fd(root_fd) };
    let components: Vec<&str> = relative.split('/').collect();
    let mut traversed = String::new();
    for (index, component) in components.iter().enumerate() {
        if !traversed.is_empty() {
            traversed.push('/');
        }
        traversed.push_str(component);
        let component = CString::new(*component).expect("static core path has no NUL");
        let mut stat: libc::stat = unsafe { std::mem::zeroed() };
        let result = unsafe {
            libc::fstatat(
                directory.as_raw_fd(),
                component.as_ptr(),
                &mut stat,
                libc::AT_SYMLINK_NOFOLLOW,
            )
        };
        if result != 0 {
            let error = std::io::Error::last_os_error();
            if error.kind() == std::io::ErrorKind::NotFound {
                return Ok(());
            }
            return Err(BoundaryError {
                code: "input.core-document.inspect",
                message: error.to_string(),
                path: traversed,
            });
        }
        let file_kind = stat.st_mode & libc::S_IFMT;
        if file_kind == libc::S_IFLNK {
            return Err(BoundaryError {
                code: "input.core-document.symlink",
                message: "core documents and every ancestor must not be symbolic links".to_string(),
                path: traversed,
            });
        }
        let is_last = index + 1 == components.len();
        if is_last {
            if file_kind != libc::S_IFREG {
                return Err(BoundaryError {
                    code: "input.core-document.nonregular",
                    message: "an existing core document must be a regular file".to_string(),
                    path: traversed,
                });
            }
        } else {
            if file_kind != libc::S_IFDIR {
                return Err(BoundaryError {
                    code: "input.core-document.nonregular",
                    message: "every core-document ancestor must be a directory".to_string(),
                    path: traversed,
                });
            }
            let next_fd = unsafe {
                libc::openat(
                    directory.as_raw_fd(),
                    component.as_ptr(),
                    libc::O_RDONLY | libc::O_DIRECTORY | libc::O_CLOEXEC | libc::O_NOFOLLOW,
                )
            };
            if next_fd < 0 {
                return Err(BoundaryError {
                    code: "input.core-document.inspect",
                    message: std::io::Error::last_os_error().to_string(),
                    path: traversed,
                });
            }
            directory = unsafe { OwnedFd::from_raw_fd(next_fd) };
        }
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_core_document_no_follow(work_root: &Path, relative: &str) -> Result<(), BoundaryError> {
    let mut path = work_root.to_path_buf();
    for component in relative.split('/') {
        path.push(component);
        match fs::symlink_metadata(&path) {
            Ok(metadata) if metadata.file_type().is_symlink() => {
                return Err(BoundaryError {
                    code: "input.core-document.symlink",
                    message: "core documents and every ancestor must not be symbolic links"
                        .to_string(),
                    path: path
                        .strip_prefix(work_root)
                        .unwrap()
                        .to_string_lossy()
                        .into_owned(),
                });
            }
            Ok(_) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
            Err(error) => {
                return Err(BoundaryError {
                    code: "input.core-document.inspect",
                    message: error.to_string(),
                    path: relative.to_string(),
                });
            }
        }
    }
    if !path.is_file() {
        return Err(BoundaryError {
            code: "input.core-document.nonregular",
            message: "an existing core document must be a regular file".to_string(),
            path: relative.to_string(),
        });
    }
    Ok(())
}

pub(crate) fn git_command(work_root: &Path, args: &[&str]) -> Command {
    let mut command = Command::new("git");
    command
        .arg("--no-optional-locks")
        .args(["-c", "core.fsmonitor=false"])
        .args(["-c", "core.untrackedCache=false"])
        .args(["-c", "core.hooksPath=/dev/null"])
        .args(["-c", "credential.helper="])
        .args(["-c", "diff.external="])
        .args(["-c", "submodule.recurse=false"])
        .arg("-C")
        .arg(work_root)
        .args(args)
        .env("GIT_OPTIONAL_LOCKS", "0")
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_TERMINAL_PROMPT", "0")
        .env_remove("GIT_CONFIG")
        .env_remove("GIT_CONFIG_SYSTEM")
        .env_remove("GIT_CONFIG_PARAMETERS")
        .env_remove("GIT_EXEC_PATH")
        .env_remove("GIT_EXTERNAL_DIFF")
        .env_remove("GIT_DIFF_OPTS")
        .env_remove("GIT_ASKPASS")
        .env_remove("SSH_ASKPASS")
        .env_remove("GIT_SSH")
        .env_remove("GIT_SSH_COMMAND");
    for index in 0..256 {
        command
            .env_remove(format!("GIT_CONFIG_KEY_{index}"))
            .env_remove(format!("GIT_CONFIG_VALUE_{index}"));
    }
    command.env_remove("GIT_CONFIG_COUNT");
    command
}

pub(crate) fn git_output(work_root: &Path, args: &[&str]) -> Result<Output, BoundaryError> {
    git_command(work_root, args)
        .output()
        .map_err(|error| BoundaryError {
            code: "input.git.unavailable",
            message: format!("execute Git: {error}"),
            path: work_root.display().to_string(),
        })
}

pub(crate) fn git(work_root: &Path, args: &[&str]) -> Result<Output, BoundaryError> {
    let output = git_output(work_root, args)?;
    if !output.status.success() {
        return Err(BoundaryError {
            code: "input.work-root.not-git",
            message: format!(
                "git {} failed: {}",
                args.join(" "),
                String::from_utf8_lossy(&output.stderr).trim()
            ),
            path: work_root.display().to_string(),
        });
    }
    Ok(output)
}

fn text(output: &Output) -> String {
    String::from_utf8_lossy(&output.stdout).trim().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    use std::os::unix::fs::symlink;
    use tempfile::tempdir;

    fn init() -> (tempfile::TempDir, tempfile::TempDir, PathBuf, PathBuf) {
        let work = tempdir().unwrap();
        let artifacts = tempdir().unwrap();
        Command::new("git")
            .args(["init", "-q"])
            .current_dir(work.path())
            .status()
            .unwrap();
        let work_path = fs::canonicalize(work.path()).unwrap();
        let artifact_path = fs::canonicalize(artifacts.path()).unwrap();
        (work, artifacts, work_path, artifact_path)
    }

    fn tree(root: &Path) -> BTreeMap<String, Vec<u8>> {
        fn walk(base: &Path, at: &Path, out: &mut BTreeMap<String, Vec<u8>>) {
            for item in fs::read_dir(at).unwrap() {
                let item = item.unwrap();
                if item.file_name() == ".git" {
                    continue;
                }
                let path = item.path();
                let rel = path
                    .strip_prefix(base)
                    .unwrap()
                    .to_string_lossy()
                    .into_owned();
                let metadata = fs::symlink_metadata(&path).unwrap();
                if metadata.is_dir() {
                    walk(base, &path, out);
                } else if metadata.file_type().is_symlink() {
                    out.insert(
                        rel,
                        fs::read_link(path)
                            .unwrap()
                            .to_string_lossy()
                            .as_bytes()
                            .to_vec(),
                    );
                } else {
                    out.insert(rel, fs::read(path).unwrap());
                }
            }
        }
        let mut out = BTreeMap::new();
        walk(root, root, &mut out);
        out
    }

    #[test]
    fn validates_git_boundary_without_mutating_worktree() {
        let (_work, _artifacts, work, artifacts) = init();
        fs::write(work.join("README.md"), b"readme").unwrap();
        let before = tree(&work);
        let validated = validate_roots(&work, &artifacts).unwrap();
        assert_eq!(validated.work_root, work);
        assert_eq!(before, tree(&work));
    }

    #[test]
    fn rejects_core_document_resident_below_gitlink() {
        let (_work, _artifacts, work, artifacts) = init();
        let status = Command::new("git")
            .args([
                "update-index",
                "--add",
                "--cacheinfo",
                "160000,1111111111111111111111111111111111111111,docs",
            ])
            .current_dir(&work)
            .status()
            .unwrap();
        assert!(status.success());
        let error = validate_roots(&work, &artifacts).unwrap_err();
        assert_eq!(error.code, "input.core-document.submodule");
        assert_eq!(error.path, "docs");
    }

    #[test]
    fn rejects_non_git_overlap_noncanonical_and_core_symlink() {
        let non_git = tempdir().unwrap();
        let artifacts = tempdir().unwrap();
        let non_git_path = fs::canonicalize(non_git.path()).unwrap();
        let artifact_path = fs::canonicalize(artifacts.path()).unwrap();
        assert!(validate_roots(&non_git_path, &artifact_path).is_err());

        let (_work, _artifacts, work, artifacts) = init();
        assert!(validate_roots(&work, &work).is_err());
        let noncanonical = work.join(".");
        assert!(validate_roots(&noncanonical, &artifacts).is_err());
        fs::write(work.join("target"), b"x").unwrap();
        symlink("target", work.join("README.md")).unwrap();
        let error = validate_roots(&work, &artifacts).unwrap_err();
        assert_eq!(error.code, "input.core-document.symlink");
        assert_eq!(error.path, "README.md");
    }

    #[test]
    fn rejects_symlink_in_core_document_ancestor_without_reading_outside() {
        let (_work, _artifacts, work, artifacts) = init();
        let outside = tempdir().unwrap();
        fs::write(outside.path().join("intent.md"), b"outside").unwrap();
        symlink(outside.path(), work.join("docs")).unwrap();

        let error = validate_roots(&work, &artifacts).unwrap_err();
        assert_eq!(error.code, "input.core-document.symlink");
        assert_eq!(error.path, "docs");
        assert_eq!(
            fs::read(outside.path().join("intent.md")).unwrap(),
            b"outside"
        );
    }

    #[test]
    fn isolated_git_disables_configured_fsmonitor_helper() {
        let (_work, _artifacts, work, artifacts) = init();
        let marker = work.join("fsmonitor-ran");
        let hook = artifacts.join("malicious-fsmonitor.sh");
        fs::write(
            &hook,
            format!("#!/bin/sh\nprintf invoked > '{}'\n", marker.display()),
        )
        .unwrap();
        let mut permissions = fs::metadata(&hook).unwrap().permissions();
        use std::os::unix::fs::PermissionsExt;
        permissions.set_mode(0o755);
        fs::set_permissions(&hook, permissions).unwrap();
        assert!(Command::new("git")
            .args(["config", "core.fsmonitor", hook.to_str().unwrap()])
            .current_dir(&work)
            .status()
            .unwrap()
            .success());

        validate_roots(&work, &artifacts).unwrap();
        assert!(git(&work, &["status", "--porcelain=v1"]).is_ok());
        assert!(!marker.exists(), "configured fsmonitor helper was invoked");
    }
}
