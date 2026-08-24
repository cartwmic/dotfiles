# codex-fast-luna

Always send Codex Fast (`service_tier: "priority"`) for
`openai-codex/gpt-5.6-luna`. Other models are not changed.

Chezmoi deploys this directory to `~/.pi/agent/extensions/codex-fast-luna`.

## Why a local extension

The `pi-codex-fast` package Fast-ifies every supported Codex model once it is
enabled (`/codex-fast` or `pi --fast`), including sol and terra. This extension
is Luna-only and always on, so switching models cannot leak Fast onto the rest
of the Codex roster.

## Behavior

- `before_provider_request`: if the session model or payload model is Luna,
  replace the payload with the same body plus `service_tier: "priority"`.
- Status bar shows `Fast` while Luna is selected (TUI only).
- No toggle, no settings key, no CLI flag.

## Tests

```sh
cd ~/.local/share/chezmoi/dot_pi/private_agent/extensions/codex-fast-luna && node --test
```
