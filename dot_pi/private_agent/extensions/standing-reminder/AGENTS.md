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

Keep one current value per saved session. Capture it when Pi processes an
operator message, including queued steering. Tool steps, extension follow-ups,
and within-work compaction do not create another delivery. `/tree` keeps the
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
The separate cache proof uses `openai-codex/gpt-6-sol` and can spend up to $5.
Run it only with owner approval when cache behavior needs fresh proof. The
non-billable isolated proof pins Pi 0.99.1, and the origin patch uses exact
anchors. The separate billable cache proof remains pinned to 0.87.1; do not
relax its gates or claim cache reuse on 0.99.1 without a new approved proof. After
a Pi upgrade, review/update the patch anchors and version-pinned proof first;
then run the isolated journey. A version-blocked run proves nothing about the
upgraded Pi.

## Completion and handoff

Report the source paths changed, focused checks and their outcomes, profile
(`personal` or `axon-work-computer`; Termux excludes `.pi`), and any unverified
behavior. Leave deployment, installed Pi, Git staging, commit, and push to
separate owner decisions. Confirm that this guide remains absent from
`chezmoi managed` while the extension README and code remain managed.
