# Standing-reminder proof

Product behavior and usage live in the [extension README](../../dot_pi/private_agent/extensions/standing-reminder/README.md). These are source-only validation drivers; `.chezmoiignore` excludes `tests/` from home deployment.

## Commands

From the chezmoi source root:

```sh
node --test dot_pi/private_agent/extensions/standing-reminder/index.test.ts
python3 tests/standing-reminder/isolated_pi.py -- python3 tests/standing-reminder/proof.py
chezmoi --source "$PWD" apply --dry-run --verbose --force \
  ~/.pi/agent/extensions/standing-reminder \
  ~/.local/share/pi-patches/standing-reminder-origin
```

Run `proof.py` through `isolated_pi.py` as above. The runner patches a private
copy of real Pi 0.87.1; `proof.py` then drives it in an isolated PTY with a
local scripted OpenAI-compatible provider and a gate-controlled editor. It
uses temporary agent, project, and session directories, makes no external
provider calls, and reads no user provider credentials. The journey checks exact
model-visible delivery, an intermediate editor draft that stays inactive until
successful close, and an active-response edit contrast: the new saved preview
and next-request cue appear before queued steering is processed, the in-flight
request retains its old snapshot, and the queued request gets only the new
reminder. It requires every streamed response chunk to redraw in order after
the editor closes, and sends another operator request after an unsuccessful
editor exit to prove the old reminder remains active. It also checks identical
operator/extension text with distinct provenance, a canceled same-text queue
neighbor, prompt-template expansion, and a mixed-origin `steeringMode=all`
batch where both queued operator messages need one reminder and the extension
message gets none. A separate real-Pi journey drives threshold compaction
between tool steps of one operator request, tolerates repeated summaries,
requires an ordinary same-work request after compaction, rejects a fresh
reminder on every summary and continuation, waits for operator work to settle,
then checks the next operator's reminder and visible answer. Other checks cover
extension-generated follow-up exclusion, tool-only continuation, editor
rollback and empty-file clear, status cues, `/reload`, manual `/compact`,
saved-session resume, `/tree`, an older-point `/fork`, `/clone`, independent
session state, noninteractive reuse, and corrupt- and missing-state warnings
with completed requests in TUI, print, JSON, and RPC. It checks the staged
runtime patch before starting Pi and verifies original user text is unchanged
and no provenance marker or reminder projection enters the saved transcript.

For the public hook/editor feasibility probe, run it through the isolated Pi
package runner:

```sh
python3 tests/standing-reminder/isolated_pi.py -- \
  python3 tests/standing-reminder/feasibility.py
python3 tests/standing-reminder/isolated_pi.py -- \
  python3 tests/standing-reminder/feasibility.py --extension dot_pi/private_agent/extensions/standing-reminder/index.ts
```

The runner privately stages and patches Pi, checks both desktop profile values,
reapplication, Termux exclusion, and coexistence with
`headless-extension-drain`, then sets `PI_BIN` for the child scenario. It never
writes to installed Pi. The probe contrasts identical cross-origin text, a
canceled same-text extension input, prompt-template expansion, extension
follow-up, and tool-only continuation while the scripted editor closes during
streaming.

The cache driver's first on-arm sidecar creation, cache-counter rejection,
and ten-call reserve regressions run without a provider:

```sh
python3 tests/standing-reminder/cache_proof.py --self-test
```

The separate live cache proof uses the same isolated patched Pi copy and only
the exact `openai-codex/gpt-6-sol` model. This is the frozen cache-live
command; it may make billable requests, so run it only for the final owner
validation:

```sh
python3 tests/standing-reminder/isolated_pi.py -- \
  python3 tests/standing-reminder/cache_proof.py --cap-usd 5
```

This frozen command enforces a `$5.00` total reported-spend cap for the exact
`openai-codex/gpt-6-sol` model. The run reserves at most `$2.28840` for ten
bounded calls at the approved maximum rates; `--cap-usd` may lower but never
raise the script's `$5.00` hard cap. The script refuses to run without the
staged origin patch, applies private temporary 45,000-input/256-output-token
limits, reserves worst-case cost for every request before starting, checks
reported spend after each response, and requires usable
input/cacheRead/cost counters plus nonzero warm and measured cache reads in both
arms. Missing or zero aggregate cache evidence leaves the criterion unproven
and blocks the comparison; prefix/request-shape evidence is not a fallback.

## Proven boundary

The chezmoi runtime bridge carries `input.source` on the actual user-message
object through Pi's queue and expansion path, then exposes it as optional
`message_start.source` to extensions. It uses object identity, not message text
or queue position; the message content and persisted transcript are unchanged.
The real-Pi journey requires interactive provenance for queued steering and a
prompt-template-expanded message, extension provenance for identical text,
and no processed message for a canceled neighbor. It verifies the pre-processing
edit/status cue, old in-flight snapshot, new queued-message reminder, failed
editor rollback on the next request, missing-sidecar warning without stale
delivery, provider-boundary reminder pairing, and complete output catch-up
after the editor closes during streaming. Anchor drift, missing origin, or a failed path blocks
the proof. Re-run after every Pi upgrade.
