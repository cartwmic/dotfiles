use sha2::{Digest, Sha256};
use std::path::{Component, Path, PathBuf};

pub fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("sha256:{:x}", hasher.finalize())
}

/// Short stable tag derived from the invocation ID.
///
/// Evidence IDs must be unique across the whole run, not merely within one
/// invocation: a `changes-requested` loop re-enters a state and re-evaluates the
/// same gate, and a gate ID alone would collide with the record already stored
/// (`provider.evidence.malformed`). Hashing keeps the ID well inside
/// `identifier_utf8_bytes` regardless of how long the invocation ID is.
pub fn invocation_tag(invocation_id: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(invocation_id.as_bytes());
    format!("{:x}", hasher.finalize())[..16].to_string()
}

/// Percent-encode a filesystem path into a `file://` URI.
///
/// Locators are opaque to the engine — it never parses or dereferences them —
/// but a well-formed URI keeps evidence useful to a human auditor.
pub fn file_uri(path: &Path) -> String {
    const UNRESERVED: &[u8] = b"-._~/";
    let mut uri = String::from("file://");
    for byte in path.to_string_lossy().as_bytes() {
        if byte.is_ascii_alphanumeric() || UNRESERVED.contains(byte) {
            uri.push(*byte as char);
        } else {
            uri.push_str(&format!("%{byte:02X}"));
        }
    }
    uri
}

/// Join `relative` beneath `root`, rejecting anything that escapes the root.
///
/// Lexical containment is checked before touching the filesystem so that a
/// traversal attempt fails even when the target does not exist. Symlinks are
/// resolved afterwards when both paths exist.
pub fn contained_join(root: &Path, relative: &str) -> Result<PathBuf, String> {
    let candidate = Path::new(relative);
    if candidate.is_absolute() {
        return Err(format!("path {relative} must be relative to the root"));
    }
    for component in candidate.components() {
        match component {
            Component::Normal(_) | Component::CurDir => {}
            Component::ParentDir => {
                return Err(format!("path {relative} escapes the root"));
            }
            Component::RootDir | Component::Prefix(_) => {
                return Err(format!("path {relative} must be relative to the root"));
            }
        }
    }

    let joined = root.join(candidate);
    if let (Ok(real_root), Ok(real_joined)) = (root.canonicalize(), joined.canonicalize()) {
        if !real_joined.starts_with(&real_root) {
            return Err(format!("path {relative} resolves outside the root"));
        }
        return Ok(real_joined);
    }
    Ok(joined)
}

/// `evidence_locator_utf8_bytes` (D008).
pub const LOCATOR_LIMIT_BYTES: usize = 8192;
const ELLIPSIS_BYTES: usize = '…'.len_utf8();

/// Build an evidence locator carrying human-readable context.
///
/// The engine preserves `locator` and `digest` on provider evidence but drops
/// `metadata`, so anything a driving agent must be able to read back through
/// `run evidence list` has to travel in the locator. Locators are opaque to the
/// engine — it never parses or dereferences them — so this is a legitimate
/// channel rather than a smuggled format.
pub fn locator(prefix: &str, detail: &str) -> String {
    let flattened: String = detail
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect();
    let combined = format!("{prefix}:{}", flattened.trim());
    if combined.len() <= LOCATOR_LIMIT_BYTES {
        return combined;
    }
    // '…' is three UTF-8 bytes; reserve them so the result stays within bound.
    let mut end = LOCATOR_LIMIT_BYTES - ELLIPSIS_BYTES;
    while end > 0 && !combined.is_char_boundary(end) {
        end -= 1;
    }
    format!("{}…", &combined[..end])
}

/// Truncate on a UTF-8 boundary so bounded diagnostics never emit invalid text.
pub fn truncate_lossy(bytes: &[u8], limit: usize) -> String {
    if bytes.len() <= limit {
        return String::from_utf8_lossy(bytes).into_owned();
    }
    let mut end = limit;
    while end > 0 && !bytes.is_char_boundary_at(end) {
        end -= 1;
    }
    let mut text = String::from_utf8_lossy(&bytes[..end]).into_owned();
    text.push_str("\n… output truncated …");
    text
}

trait CharBoundary {
    fn is_char_boundary_at(&self, index: usize) -> bool;
}

impl CharBoundary for [u8] {
    fn is_char_boundary_at(&self, index: usize) -> bool {
        index == 0 || index == self.len() || (self[index] & 0xC0) != 0x80
    }
}

#[cfg(test)]
mod tests {
    use super::{locator, LOCATOR_LIMIT_BYTES};

    #[test]
    fn locator_carries_detail_and_flattens_control_characters() {
        assert_eq!(locator("diagnosis", "line one\nline two"), "diagnosis:line one line two");
    }

    #[test]
    fn locator_stays_within_the_evidence_bound() {
        let built = locator("command", &"x".repeat(20_000));
        assert!(built.len() <= LOCATOR_LIMIT_BYTES);
        assert!(built.ends_with('…'));
    }
}

// --------------------------------------------------------------- deadlines

/// Seconds held back from the engine's provider budget so this process can
/// still write its result envelope before the engine's SIGTERM lands.
pub const RESULT_MARGIN_SECONDS: u64 = 5;

/// The instant by which everything this invocation does must be finished.
///
/// Computed ONCE per invocation and threaded to every module that waits on
/// something. Previously the command gate and the judge each derived their own
/// budget from the registration timeout, each starting from its own
/// `Instant::now()` -- so a 900s registration could spend 895s running tests and
/// then hand the judge a fresh 895s clock. The engine's SIGTERM landed first,
/// and a provider killed before it can write its envelope reads as broken rather
/// than as slow.
pub fn invocation_deadline(provider_timeout_seconds: u64) -> std::time::Instant {
    std::time::Instant::now()
        + std::time::Duration::from_secs(
            provider_timeout_seconds.saturating_sub(RESULT_MARGIN_SECONDS).max(1),
        )
}

/// A per-stage budget, never allowed past the shared invocation deadline.
///
/// `configured` is what the repository or the plan asked for. It is honoured
/// when it fits and clamped when it does not, so a generous per-stage setting
/// cannot overrun the invocation just because an earlier stage was slow.
pub fn stage_deadline(
    configured: Option<u64>,
    invocation_deadline: std::time::Instant,
) -> std::time::Instant {
    match configured {
        Some(seconds) => (std::time::Instant::now()
            + std::time::Duration::from_secs(seconds.max(1)))
        .min(invocation_deadline),
        None => invocation_deadline,
    }
}

#[cfg(test)]
mod deadline_tests {
    use super::*;
    use std::time::{Duration, Instant};

    fn seconds_until(deadline: Instant) -> u64 {
        deadline.saturating_duration_since(Instant::now()).as_secs()
    }

    #[test]
    fn the_invocation_deadline_reserves_room_to_answer() {
        // A range, not an equality: the margin is exact but the clock moves
        // between computing the deadline and measuring it, so `as_secs`
        // truncation lands on either side. Asserting the exact value made this
        // test fail roughly one run in ten for no reason anyone would want to
        // debug.
        let remaining = seconds_until(invocation_deadline(600));
        assert!((594..=595).contains(&remaining), "{remaining}");
        // A pathologically small registration still yields a usable value
        // rather than a deadline already in the past.
        assert!(invocation_deadline(1) > Instant::now());
    }

    /// The property the split budgets used to violate: two stages in one
    /// invocation cannot between them outlast the invocation.
    #[test]
    fn a_stage_never_outlives_the_invocation_however_generous_its_own_setting() {
        let invocation = Instant::now() + Duration::from_secs(30);
        assert_eq!(stage_deadline(Some(9_000), invocation), invocation);
        assert_eq!(stage_deadline(None, invocation), invocation);
        // A stage asking for less than remains is honoured.
        assert!(stage_deadline(Some(5), invocation) < invocation);
    }

    /// A second stage starting late gets the REMAINING time, not a fresh copy
    /// of its configured budget.
    #[test]
    fn a_late_stage_inherits_what_is_left_rather_than_starting_over() {
        let invocation = Instant::now() + Duration::from_secs(10);
        let late = stage_deadline(Some(600), invocation);
        assert_eq!(late, invocation);
        assert!(seconds_until(late) <= 10);
    }
}
