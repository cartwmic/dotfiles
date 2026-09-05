# Headless extension compaction drain

Pi 0.85.0's `--print` host awaits `session.prompt()` but does not own the
fire-and-forget `ctx.compact()` or `pi.sendUserMessage()` work started by
extensions. Auto-compact aborts the current run at an inter-turn threshold.
That settles the original prompt; print mode reads its aborted assistant
message and disposes the runtime before summarization and the continuation
finish. Final-turn compaction can also be lost during shutdown.

The deterministic reproduction matches the reported native failure: an
assistant reports 120557 tokens, its read returns 12371 characters, usage
reaches 123650/272000 (45.46%), and the next turn aborts. Without this patch,
print exits 1 with no summary, post-compaction action, or final stdout.

## Correction

Track extension compaction promises through their callbacks and extension
user-message promises through their resumed runs. After each public print
prompt, drain those promises, including work spawned by completion/error
callbacks, before inspecting output or disposing the runtime. Rejected
extension work fails the print invocation.

This drain is deliberately **separate from `waitForIdle()`**. Manual
compaction awaits `abort()`, which awaits idle; making idle await the
compaction promise would deadlock. TUI/RPC idle and abort behavior is unchanged.
The extension still owns its threshold, continuation, and breaker. Native
auto-compaction stays disabled. No configuration values are rewritten.

## Deployment

`patch.mjs` patches both the CLI-load-bearing `dist/bundle/chunks/*.js` and
the equivalent unbundled `dist/core/agent-session.js` and
`dist/modes/print-mode.js`. The chunk is discovered by its print-mode function,
not its hashed filename. Exact anchors and complete replacement blocks are
checked; unexpected upstream changes fail rather than applying a partial guess.
All rewritten files pass `node --check` before replacement. Existing unrelated
patches in the bundle are preserved.

The shared chezmoi apply loop runs this patch on every profile. Its hash is
included in `run_onchange_after_30_apply_pi_patches.sh.tmpl`. Backups use
`.orig.chezmoi-pi-patch`; the state receipt is
`~/.local/state/chezmoi-pi-patches/headless-extension-drain.json`. The receipt
also enables pi-patch-guard to detect a wiped CLI patch after an upgrade.

```sh
node dot_local/share/pi-patches/headless-extension-drain/patch.mjs --check
```

For an isolated package copy, set `PI_HEADLESS_PATCH_PACKAGE=/path/to/copy`.
It suppresses the installed-package state receipt. Never restore an old bundle
backup over newer independent patches; reinstall Pi and reapply the patch loop.
Remove this patch when upstream owns extension compaction and its continuation
through print shutdown; rerun the proof before removing it.

## Black-box proof

From the chezmoi source root:

```sh
python3 dot_local/share/pi-patches/headless-extension-drain/prove.py \
  --artifacts /tmp/compaction-proof-inter-turn

for scenario in final-turn summary-error resume-error; do
  python3 dot_local/share/pi-patches/headless-extension-drain/prove.py \
    --scenario "$scenario" --artifacts "/tmp/compaction-proof-$scenario"
done

bun test dot_pi/private_agent/extensions/auto-compact/index.test.ts
```

Each artifact directory must be new. `--pi /path/to/dist/bundle/cli.js` tests
an isolated candidate; `--extension /path/to/index.ts` selects source or deployed
extension. The default is the deployed `~/.pi/agent/extensions/auto-compact/index.ts`,
including its machine-local configuration.

The fixture uses the public `--print --no-skills --no-extensions -e ...` CLI,
a local OpenAI-compatible HTTP server, isolated settings/auth, native tools,
real native summarization requests, and saved native session JSONL. A warmup
prompt supplies enough history for Pi's normal 20000-token keep budget. The
observer records events only; it never replaces compaction or resumes work.
No live model or credentials are used.

Inter-turn proof requires a saved compaction before the persisted continuation,
a completed native write of `POST_COMPACTION_ACTION`, final `PROOF_DONE` stdout,
and exit 0. Final-turn proof requires compaction but no resumed work. Summary
HTTP failure must resume; resumed assistant HTTP failure must exit nonzero.
Command argv, HTTP requests, stdout/stderr, lifecycle events, native sessions,
and receipt are retained. Missing proof is a failure, not a skipped success.
