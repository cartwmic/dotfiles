# Standing-reminder source instructions

## Scope and authority

This guide applies when editing `dot_pi/private_agent/extensions/standing-reminder/`
in the chezmoi source tree. It is source-only: `.chezmoiignore` excludes its
`~/.pi/agent/extensions/standing-reminder/AGENTS.md` destination. Pi loads it
when the cwd is inside this source directory, on top of the repo-root and
Pi-global instructions. Repo-root `AGENTS.md` owns chezmoi operations and Git
rules; the shared `dot_pi/private_agent/extensions/README.md` owns extension
conventions. [README.md](./README.md) is the user-facing behavior guide, and
`tests/standing-reminder/README.md` owns the full proof commands. Keep this
file to extension-specific traps and validation choices.

## Workflow

Edit source here. Change the bridge at
`dot_local/share/pi-patches/standing-reminder-origin/patch.mjs` when Pi input
provenance needs repair; leave installed Pi files alone. The extension needs
`message_start.source` from that patch. Admit only `interactive` and `rpc`
messages. Missing or unknown provenance must warn and omit the reminder;
message text cannot establish origin.

Keep one current value per saved session. Snapshot latest wording at normal
context assembly for operator input, pending edits/clears or selected events.
Default refresh is only tool-result:ask_user_question, including nested/error
execution ends. Ordinary tools and UI notifications do not refresh. Exact
message:CUSTOM_TYPE selectors use occurrence baselines at startup/tree/compaction.
Baseline `SessionManager.buildSessionContext().messages` with the per-call ctx:
raw native `custom_message` entries are not `message` entries with role `custom`.
Preserve normalized type/timestamp/count keys; historical replay cannot refresh.
Idle warming and compaction summaries are not delivery. Superseded revision
anchors retire at the next normal request; no saved reminder messages or durable
trigger backlog is allowed. `/tree` keeps the
current value; `/fork` and `/clone` copy it into independent sessions. Editor
writes are drafts until a successful close; failed or canceled edits leave the
old value active. A missing marked sidecar or unreadable state must warn and
continue without stale text. Keep the status preview and pending cue. Avoid
changing the stable prompt prefix; cache reuse has a separate capped proof.

From the chezmoi source root, run focused tests after source changes. The
isolated runner stages a private copy of the installed Pi package and patches
that copy; it does not alter installed Pi or call a live model. It requires
Node, Python, and an installed `@earendil-works/pi-coding-agent` package.
A full-tree dry-run previews the Pi-patch onchange script as well as the
extension and patch destinations; a targeted dry-run omits that trigger.
Start with the unforced preview so merge/live drift is visible:

```sh
node --test dot_pi/private_agent/extensions/standing-reminder/index.test.ts
python3 tests/standing-reminder/isolated_pi.py -- python3 tests/standing-reminder/proof.py
chezmoi --source "$PWD" apply --dry-run --verbose
chezmoi --source "$PWD" managed --include files | grep -F 'standing-reminder/'
```

The managed list must include the extension README and code but omit its
source-only `AGENTS.md`. If the unforced preview fails at a non-TTY merge
prompt, inspect the live drift and ask when the source-side choice is unclear.
Only then preview that source side with
`chezmoi --source "$PWD" apply --dry-run --verbose --force`; do not take a real
source-side merge or apply without owner approval. For documentation-only
edits, run `git diff --check` and the chezmoi checks above. The
policy-document deterministic local-reference gate checks local Markdown
links when that workflow is used. Rerun behavior tests if the prose changes
a behavior claim.
The proof pins Pi 0.99.2 and uses `openai-codex/gpt-6.1-sol` for separate
live cache evidence. After upgrades, review native nested execution/error paths
and exact origin-patch anchors before changing the pin; unit tests do not prove
runtime compatibility. Workers run assigned focused checks. One designated
proof owner runs the full stable-tree matrix and owner-approved billable proof.
`cache-self` is offline; `cache-live` requires a finite explicit cap and
reserves native capacity. The backend rejects the artificial short-token
override; do not claim an enforced 256-token ceiling. See the proof README for
commands and the rate-dependent reserve. Live deployment and Git operations
remain separately gated.

## Completion and handoff

Report the source paths changed, focused checks and their outcomes, profile
(`personal` or `axon-work-computer`; Termux excludes `.pi`), and any unverified
behavior. Leave deployment, installed Pi, Git staging, commit, and push to
separate owner decisions. Confirm that this guide remains absent from
`chezmoi managed` while the extension README and code remain managed.
