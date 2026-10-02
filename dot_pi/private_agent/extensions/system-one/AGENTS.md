# Working on the System One Pi integration

## Scope and authority

This directory is chezmoi documentation for the single Git package in
`dot_pi/private_agent/private_settings.json.tmpl`, not an extension entry point.
Pi loads code from `cartwmic/system-one-tools`; runtime changes belong there
under its repository procedure. Never add `index.js` or `index.ts`: that would
register tools twice. Repo-root `AGENTS.md` owns source naming, profiles, apply,
secrets and Git; the global home guide is a separate policy, not this file.
[README.md](README.md) owns product setup and native usage.

Owner-authorized source policy includes personal and axon-work-computer;
Termux excludes `.pi`. Keep one unconditional System One Git package entry
and docs mapping for both desktops. Do not move personal OpenRouter gate/plus
or unrelated profile gates. Native first-delivery targets are macOS, Pi 0.99.2+
and Node.js 22.19+; preserve the CLI's Node.js 20+ macOS/Linux contract and
existing public platform claims without claiming untested Linux Pi delivery.

## Source-only checks

Work from the current source worktree. Before any chezmoi source command,
inspect the effective config and `hooks.read-source-state.pre` risk; a dry-run
can execute that hook. Do not invoke the owner's hook or replace their config.
Inspect `.chezmoiremove` too, including persistent directories. Settings render
reads live JSON to preserve lastChangelogVersion, theme and hideThinkingBlock;
read it independently and privately. Work data `privatePiGlmProviderRef` can
invoke `op read`; omit it in controlled proofs. No secret lookup is needed.

Run only the isolated profile proof for source reconciliation:

```sh
REPO="$(git rev-parse --show-toplevel)"
python3 "$REPO/tests/system-one/profile-proof.py" --profile personal
python3 "$REPO/tests/system-one/profile-proof.py" --profile axon-work-computer
git -C "$REPO" diff --check
```

It uses explicit worktree `--source`, isolated HOME/destination/config/cache/
state, hook-free config and seeded valid settings; it runs managed/source-path/
cat and targeted `apply --dry-run` only for settings and these two docs. Even
in a temporary home, do not perform real apply or Pi Git package installation.
Unchanged destinations may be absent from dry-run output. Root AGENTS/README
and tests stay mechanically ignored; the global home guide is not edited.
Check new-file whitespace separately without staging. Inspect actual touched
live files privately for drift; report only structural/redacted findings,
never choose source-vs-live or apply as part of reconciliation.

## Runtime and rollout boundaries

Pi owns native provider/auth and classifier operations; `/so settings` owns
Pi preferences, not the CLI catalog. Default/session/owner-only one-call selection
and native object/choice/bool/score forms are in README. `/so off` gates only
`system_one`, not direct native codemode; manual use is private with separate
accounting. One 30-second logical deadline spans all operations and waits;
`maxRetries:2` applies to each native HTTP operation, not the whole evaluation.

A real apply, regular install/update, commit/push or paid call needs separate
owner approval. No such action is authorized by a source proof. Before a later
approved deployment, follow root preflight and inspect exact rendered/live
settings independently without logging credentials, then preview the exact
settings and doc destinations from this source. After approval and restart,
`pi list` verifies configuration and fresh `/so status` verifies command loading,
not native callability. The Git URL is unpinned; record before/after installed
revisions for a separately approved update and verify the exact new revision
in a disposable consumer without modifying installed caches by hand.

Choose proof by claim: source dry-run, actual command loading, real agent turns,
PTY manual/session/privacy/accounting, native retry/deadline/cancellation, and
CLI/public packaging are distinct obligations. Old CLI/provider evidence cannot
substitute for native Pi proof. Name the provider/model/route/caller before any
separately approved bounded paid test. Stop and ask if native integration needs
substantial glue or runtime patches.

## Completion and handoff

Name changed chezmoi source paths/destinations, both profiles, exact controlled
commands/results, ignored root docs, private drift conclusions and pending runtime
proofs. State no-hook/no-secret/no-apply/no-install and actual Git disposition.
Preserve unrelated changes and prior gate evidence. Source success is not delivery
or public-provider acceptance.
