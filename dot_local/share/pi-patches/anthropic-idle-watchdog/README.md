# Anthropic SSE idle watchdog

This chezmoi-managed patch adds a per-read idle timeout and forwards Anthropic
`ping` events. Revision 2 is tested against Pi 0.99.1 and applies unchanged to Pi 1.2.0 through 1.5.0 (see below).

## Why it exists

The Anthropic SSE iterator still awaits `reader.read()` without its own
per-chunk watchdog. A stalled response can leave a request waiting for the
transport's longer timeout. The event filter also drops Anthropic keep-alive
pings. The original investigation concerned
[upstream issue #3020](https://github.com/badlogic/pi-mono/issues/3020).

Pi 0.99.1 added `onProviderStreamEvent` to the normalization loop; that callback
is not an idle watchdog. Revision 1's exact anchor no longer matches it.
Revision 2 preserves the callback and runs it before handling pings.

Pi 1.5.0 rewrote the statements just before the CLI bundle's event loop (`let blocks=output.content;` became `let openBlocks=new Map,...`).
The edit never touched them, so the "CLI stream" anchor is now the loop head alone
(`for await(let event of iterateAnthropicEvents(response,options?.signal))if(await options?.onProviderStreamEvent?.(event,model),event.type==="message_start")`).
It is still exactly once in the Anthropic chunk of Pi 1.2.0, 1.3.0, 1.4.0 and 1.5.0, and the patched text is byte-identical to before,
so there is no versioned payload and no revision bump; trees already patched by the earlier anchor still verify.

## Runtime targets

Both copies of the provider need the same three edits:

- Nested `@earendil-works/pi-ai/dist/api/anthropic-messages.js`, used by SDK
  consumers.
- The discovered `pi-coding-agent/dist/bundle/chunks/anthropic-messages-*.js`,
  used by the installed CLI.

Each receives the ping event filter, an idle watchdog around `reader.read()`,
and ping forwarding through `AssistantMessageEventStream`. Patching only the
standalone pi-ai file does not protect normal bundled CLI sessions.

The default timeout is **90 seconds**. Override it with
`PI_STREAM_IDLE_TIMEOUT_MS=120000`; `0` disables this watchdog. A timeout
cancels the reader and reaches Pi as an assistant error. Pi's configured retry
policy decides whether to retry.

All anchors and both rewritten JavaScript files are checked before either
runtime target is replaced. Reapplying unchanged files is a no-op. Missing,
ambiguous, incomplete, or stale blocks fail closed.

## Deployment

The shared [patch guide](../README.md) owns deployment. The existing
`run_onchange_after_30_apply_pi_patches.sh.tmpl` hashes this payload and the
installed package versions. After an upgrade or reinstall, obtain approval
and reapply through that mechanism. A same-version reinstall may not change
the onchange hash; invoke the approved apply script explicitly if necessary.

The receipt is `~/.local/state/chezmoi-pi-patches/anthropic-idle-watchdog.json`.
It records both targets. Adjacent `.orig.chezmoi-pi-patch` files are diagnostic
backups, not an automatic migration mechanism: the SDK provider is shared
with `empty-turn-retry`. Never restore an entire backup over sibling edits.

## Validation

From the chezmoi source root:

```sh
node dot_local/share/pi-patches/anthropic-idle-watchdog/patch.mjs --check
python3 tests/pi-patches/anthropic_watchdog.py
```

The proof reads the global npm Pi (`npm root -g`) and expects Pi 0.99.1. To run it against another Pi, point npm at a private global install and
name the version: `npm install -g --prefix "$P" --ignore-scripts @earendil-works/pi-coding-agent@1.5.0`, then
`npm_config_prefix="$P" PI_WATCHDOG_PROOF_VERSION=1.5.0 python3 tests/pi-patches/anthropic_watchdog.py`.

The first command checks the installed SDK and CLI copies without writes. The
second copies Pi 0.99.1 privately, patches that copy, and drives its real CLI
against a local scripted Anthropic backend. It checks a successful response
with ping delivery to provider observers, a stalled body that terminates with
the watchdog error, and a delayed response that completes with the watchdog
disabled. It also checks reapplication, stale/partial refusal, sibling-marker
preservation, and that the installed provider and bundle remain unchanged.
No live provider or owner credentials are used.

`PI_ANTHROPIC_IDLE_WATCHDOG_PACKAGE` selects a copied Pi package for isolated
checks and suppresses installed-package receipts. An invalid override fails;
it never falls back to the installed target.

## Failures and retirement

- **Changed anchor:** inspect both installed runtime surfaces. Update exact
  edits and bump the revision only after establishing whether upstream supplied
  equivalent behavior. Then rerun the isolated CLI proof.
- **Stale or partial revision:** the patch leaves files untouched. Reinstall
  the current Pi version through the owner's package manager, then reapply
  **all** managed patches. Do not restore shared-file backups.
- **Syntax failure:** no runtime target is replaced before every generated
  file passes `node --check`. Fix the payload, then repeat the proof.
- **Upstream fixes the behavior:** retire only this patch and its hash line
  in the shared onchange wrapper. Inspect deployed copies and arrange an
  approved clean reinstall/reapply. Keep the shared apply script, wrapper,
  other patches, and their receipts.
