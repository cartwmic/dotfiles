Import of the v0.58.0 skill bundles and the five Loop Engine pins (loop-engine, lean-change, policy-document, research, bookends-check), made by `loop_engine_bump.py v0.58.0` (playbook rule 7c57de5a).

```
tag v0.58.0 of cartwmic/loop-engine = commit 77decd437e84819a16c8dd007db2f58c8e69e116; 6 bundles, 29 files, every file matches its tree hash
coordinating-loop-engine           +0 added  ~0 changed  -0 orphan  =1 same
using-generate-prd                 +0 added  ~0 changed  -0 orphan  =2 same
using-lean-change-provider         +0 added  ~1 changed  -0 orphan  =1 same
    change  using-lean-change-provider/SKILL.md
using-loop-engine                  +0 added  ~1 changed  -0 orphan  =4 same
    change  using-loop-engine/SKILL.md
using-policy-document-provider     +0 added  ~1 changed  -0 orphan  =5 same
    change  using-policy-document-provider/SKILL.md
using-research-provider            +0 added  ~1 changed  -0 orphan  =12 same
    change  using-research-provider/SKILL.md
pins: 0.57.0 -> 0.58.0 (dot_config/mise/config.toml)
applied to /tmp/loop-engine-bump-_sn52j0e/wt
next: review git diff; chezmoi --source /tmp/loop-engine-bump-_sn52j0e/wt apply --dry-run --verbose ~/.local/share/agent-harness/canonical/skills ~/.config/mise/config.toml,
      get approval, apply those targets, then run: import_release_skills.py verify-deployed --source /tmp/loop-engine-bump-_sn52j0e/wt
```

Profiles: both. The pins and canonical skills land on personal and axon-work-computer; the script applies them on personal only, and the work Mac gets them with its own chezmoi update.

Principles (`~/.local/share/agent-harness/design-principles.md`):

| # | Principle | Result | Evidence |
|---|---|---|---|
| 1 | Composable components | n/a | No component is added; the import copies skill bundles and moves five pins. |
| 2 | Kernel and adapters | n/a | No component is added or changed. |
| 3 | Clean architecture inside each component | n/a | No code layer is added or changed. |
| 4 | YAGNI and KISS | pass | The apply writes only the PR's own targets; the drift check stops on anything else. |
| 5 | Written contracts and invariants | n/a | No contract changes. |
| 6 | Conformance suites | n/a | No adapter changes. |
| 7 | No cross-component imports | n/a | No import is added. |
| 8 | Judgment in agents, mechanism in code | pass | The import, the pins and the apply are mechanical; the skill text is the release's own. |
| 9 | Fix the cause; no arbitrary caps or unrequested defense in depth | n/a | No cap, threshold or extra guard is added. |
| 10 | Good enough for personal software | pass | Personal profile only for the apply; the work Mac takes the merged pins with its own chezmoi update. |
| 11 | Prior art before building | n/a | No new capability; the bundles come from the Loop Engine release. |
| 12 | Verified from the outside | pass | The verify step runs verify-deployed on the changed bundles and reads the active mise versions back (log step verify). |
| 13 | Resolve intent tensions and preserve design freedom | n/a | No promised outcome changes; the merge runs under the standing dotfiles grant (playbook rule 7c57de5a). |
| 14 | Logs that replay the user's experience | pass | One JSON line per step, tied by one run id, in ~/.local/state/loop-engine-bump/log.jsonl. |
| 15 | Fast proof | n/a | The import runs no journey; the proof is the PR's CI run. |
| 16 | Built to last | pass | The script replaces the pins and shipped skills in place; nothing old is left behind. |

Decisions: none material

