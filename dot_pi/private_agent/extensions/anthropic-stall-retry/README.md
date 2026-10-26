# anthropic-stall-retry

Work profile only (`axon-work-computer`; gated in the repo-root `.chezmoiignore`).

On the work profile the `anthropic` provider sometimes keeps a request open, sending pings but no content. The [pi-response-visibility](https://github.com/cartwmic/pi-response-visibility) widget shows `Quiet: waiting, no content progress`. The `anthropic-idle-watchdog` Pi patch does not fire, because each ping resets it. The manual fix is Esc, then `continue`. This extension does that automatically.

## Behavior

- **Signal:** it reads pi-response-visibility's read-only observer handle (`Symbol.for('pi.response-visibility.observer.v1')`) once a second during an `anthropic` request. A request counts as stalled when `snapshot().quiet.absent === 'content progress'` and `quiet.ageMs` reaches the timeout. Content means reasoning, text or tool-call deltas; pings do not count. Without the handle the extension warns once and does nothing.
- **Retry:** it shows a warning (`Anthropic: no content progress for 90s. Aborting and sending "continue" (retry 1/2).`), aborts the request, and sends `continue` once the aborted run has settled. Pi leaves the aborted reply out of the next request, so the original prompt is not duplicated.
- **No double-send:** if the reply finishes before the abort lands, Pi reports a normal settle and nothing is sent. Your own Esc, queued input, and other providers are left alone.
- **Cap:** at most `PI_ANTHROPIC_STALL_RETRY_MAX` retries in a row. A completed reply or a new prompt from you resets the count. At the cap it shows a warning and leaves the request to you.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `PI_ANTHROPIC_STALL_RETRY_MS` | `90000` | Content silence before a retry; `0` disables |
| `PI_ANTHROPIC_STALL_RETRY_MAX` | `2` | Consecutive retries before giving up |

Invalid values fall back to the default with a warning. The timeout only takes effect once pi-response-visibility reports the request as quiet, so it cannot be shorter than that package's `quietMs` (default 30000).

## Validation

```sh
cd dot_pi/private_agent/extensions/anthropic-stall-retry && node --test
python3 tests/anthropic-stall-retry/stall_retry.py   # from the chezmoi source root
```

The second command runs the installed Pi CLI read-only with a private `HOME` and agent directory against a local scripted Anthropic backend. It covers stall then recovery, a healthy reply, a persistent stall stopping at the cap, `0` disabling it, a missing observer handle, and the TUI notice. It loads pi-response-visibility from `RESPONSE_VISIBILITY_ROOT` (default `~/git/pi-response-visibility`), which must include the observer handle.
