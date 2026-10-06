# passage-review — agent instructions

## Scope and authority

This file covers the standalone reviewer at
`dot_local/share/passage-review/passage_review.py` and its source-local tests.
The desktop wrapper is `dot_local/bin/executable_passage-review`; Termux also
has `bin/executable_passage-review`, which delegates to its phone-local
`~/.local/bin/passage-review`. The repo-root `AGENTS.md` controls chezmoi source,
apply, and secrets. This directory's `README.md` owns human review usage.
The Pi `/review` extension supplies input; it does not own this library.

## Workflow

- Snapshot UTF-8 input before opening the reviewer. Keep its SHA-256 check
  before open, note, and export; a changed snapshot must fail closed. Store
  review data under `${XDG_DATA_HOME:-$HOME/.local/share}/passage-review/`
  with user-private files. Desktop and phone libraries stay separate.
- Notes have independent IDs, exact quote and 1-based line-range anchors.
  `export` takes explicit pending note IDs, writes attributed quoted feedback,
  and leaves state pending. `archive` and `delete` are separate explicit
  mutations. Do not edit the source or send feedback to an agent on export.
- `passage_review.lua` is the Neovim view. It is used when the editor command
  is `nvim`; it only talks to the CLI through `new --no-open`, `note`,
  `show`, and `delete` (to replace a re-saved draft), never the JSON files.
  Keep normal Neovim behavior: one global `<leader>zc` mapping that acts
  only in review buffers (source or md-render view), no remapped built-in
  keys, and comment drafts in real temporary files. Zen and md-render swap
  buffers between windows without the usual events, so the header and key
  must not depend on per-buffer or per-window setup at attach time. `dot_config/nvim/plugin/passage_review.lua`
  only loads the deployed module for `:PassageReview`.
- Choose interaction path up front: with `/dev/tty`, opening a review can
  prompt for passages and run `$VISUAL`, `$EDITOR`, or `vi`. Without a
  controlling terminal it only prints the saved snapshot and notes; reopen
  the ID interactively to add one. A missing clipboard command or rejected
  OSC 52 leaves the saved Markdown export and printed feedback available.
- The Termux profile deploys its own `~/bin/passage-review` and local
  library. Keep it independent of Pi and Herdr. The phone connects to a
  desktop over SSH for remote output; no plugin executes on the phone.
- Treat schema-1 JSON as local storage. The CLI is the supported interface;
  keep storage migrations and pending-note semantics covered by
  `test_passage_review.py`. For source checks, run the source wrapper at
  `dot_local/bin/executable_passage-review` with its adjacent implementation.
  The wrapper can fall back to the installed library if its source-relative
  implementation is absent; an installed `passage-review` result may exercise
  older home files. Check the selected path before citing it as source proof.

## Validation

From the chezmoi source root, run the standalone tests and the portable review
journey. They use a temporary library and editor; a live Pi or Herdr process
is unnecessary.

```sh
dot_local/bin/executable_passage-review --help
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s dot_local/share/passage-review -p 'test_*.py' -v
python3 tests/herdr-overview/proof.py review
chezmoi apply --dry-run --verbose ~/.local/bin/passage-review ~/.local/share/passage-review
```

For a Termux profile change, inspect `.chezmoiignore` and the phone bootstrap,
then run the phone-targeted dry-run on a host whose active profile is `termux`:

```sh
chezmoi execute-template '{{ .profile }}'
chezmoi apply --dry-run --verbose ~/bin/passage-review ~/.local/bin/passage-review ~/.local/share/passage-review
```

`python3 tests/herdr-overview/proof.py chezmoi-dry-run` checks profile-gated
mappings without a phone apply. If no Termux host is available, report that
phone destination check as pending. Ask before applying to the phone or
touching an owner's library.

## Completion and handoff

Name changed source paths, snapshot or note/export invariants affected, the
checks actually run, and any untested TTY, clipboard, or phone path. Say
whether a live apply was skipped and that existing reviews stayed untouched.
