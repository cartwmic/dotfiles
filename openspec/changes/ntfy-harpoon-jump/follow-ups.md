# Follow-ups

**Change:** ntfy-harpoon-jump
**Created:** 2026-07-04 (first out-of-scope routing)

## Queue

| # | Finding | Severity | Origin (review type, round) | Routing reason | Status |
|---|---|---|---|---|---|
| 1 | `termux/sync.sh` idempotence guard detects only its own sentinel-fenced managed block, not an UNMANAGED hand-written `Host remote` ControlMaster stanza already present in the phone `~/.ssh/config`. A user with such a manual block gets a second (managed) block appended; ssh first-match-wins keeps behavior correct but the config carries a redundant stanza. | P3 | code-review rounds 1-4 | Out of scope for the frozen intent: intent idempotence is Constitution IV "no-op when already applied [by this script]"; robustly parsing arbitrary hand-written ssh stanzas from an adb `run-as` toybox shell (grep/sed only, no awk) is disproportionate and was demonstrably defect-prone across 3 fix attempts (each precise-detection heuristic introduced a new false-skip/over-match edge). Surfaced to the user via `termux/README.md`; the sentinel guard fully satisfies the script's own re-run idempotence. | open |

## Waivers

- (none)

## Promotion

- 1 — not-pursued unless a real user hits a manual-block collision; if pursued, a successor change should manage the block via an `Include ~/.ssh/config.d/*` file (idempotent by construction) rather than in-place stanza parsing.
