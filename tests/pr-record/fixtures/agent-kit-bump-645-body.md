Pin `@cartwmic/agent-kit` to 0.67.1 (package.json and package-lock.json), made by `agent_kit_bump.py 0.67.1` (playbook rule 7c57de5a).

Principles (`~/.local/share/agent-harness/design-principles.md`):

| # | Principle | Result | Evidence |
|---|---|---|---|
| 1 | Composable components | n/a | No component is added or changed; the bump moves one version pin. |
| 2 | Kernel and adapters | n/a | No component is added or changed. |
| 3 | Clean architecture inside each component | n/a | No code layer is added or changed. |
| 4 | YAGNI and KISS | pass | The diff is the two pin files only: package.json and package-lock.json. |
| 5 | Written contracts and invariants | n/a | No contract changes. |
| 6 | Conformance suites | n/a | No adapter changes. |
| 7 | No cross-component imports | n/a | No import is added. |
| 8 | Judgment in agents, mechanism in code | pass | Every step is mechanical: the pin, the merge gates, the apply and the install. |
| 9 | Fix the cause; no arbitrary caps or unrequested defense in depth | n/a | No cap, threshold or extra guard is added. |
| 10 | Good enough for personal software | pass | Personal profile only; the install reads its registry token at run time. |
| 11 | Prior art before building | n/a | No new capability; it uses the published agent-kit package and the existing install script. |
| 12 | Verified from the outside | pass | tests/release-pins/test_agent_kit_bump.py drives the real script to the apply and the version read-back; after the merge the installed version is read back (log step verify). |
| 13 | Resolve intent tensions and preserve design freedom | n/a | No promised outcome changes; the merge runs under the standing dotfiles grant (playbook rule 7c57de5a). |
| 14 | Logs that replay the user's experience | pass | One JSON line per step, tied by one run id, in ~/.local/state/agent-kit-bump/log.jsonl. |
| 15 | Fast proof | n/a | A pin bump runs no journey; the proof is the PR's CI run. |
| 16 | Built to last | pass | The script changes only the pins; nothing it replaces is left behind. |

Profiles: both. The pins land on personal and axon-work-computer. The script runs only on personal: it refuses any other profile, and `.chezmoiignore` leaves it out of the work profile.

On merge the script applies only these two files, runs the install (65) and reads the installed version back.

Decisions: none material

