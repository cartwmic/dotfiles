# Claude Compat prompt guard

Personal-profile companion to `vazzma/pi-claude-request-compat` 0.2.1, pinned
in Pi settings to commit `d915546395e31e6a6a6b49268d21c2b9e50cf10a`.
Pi 0.99.2 supplies the public provider lookup and native registration APIs.

The companion is the sole loader for the pinned upstream extension; the package
stays installed with `extensions: []`. Its factory wraps Compat's raw native
`stream` and `streamSimple` before upstream serialization and billing checksum
generation, so auth and model listing work before session startup. Every call checks
the actual requested provider **and** API: `claude-compat` /
`claude-compat-messages`. Session model selection is not used for scope.

Only built-in `<docs>` instructions receive these fixed substitutions:

- `about pi itself, its SDK` → `about Pi itself, its SDK`
- `, pi packages (docs/packages.md),` → `, Pi packages (docs/packages.md),`

System messages are copied, including historical section updates and flattened
checkpoints. Other sections, tools, paths, commands, conversation messages and
saved sessions remain unchanged. Ambiguous or absent docs blocks pass through.
There is no automatic variant search, retry, global prompt rewrite or dependency
patch. Server acceptance can change; a passing local guard test is not live proof.

The personal models template adds exact Sonnet 5.5 metadata because this upstream
catalog lacks it. Upstream still caps request output at 64,000 tokens.
Authentication reuses Pi's existing **Anthropic OAuth** login. No separate Compat
credential is created. Native Pi auth resolves and refreshes only `anthropic`
under its existing storage lock; the companion never copies refresh tokens.
Availability checks inspect auth metadata without refreshing. Every request
resolves the owner again, ignoring token overrides and rejecting paid API keys.
The native API-key resolver slot is only an ambient-auth adapter: it reports
OAuth availability, and upstream still sends OAuth-only subscription requests.
If login is needed, use `/login anthropic`. A separate Compat credential fails
closed; remove it through `/logout claude-compat`, not by copying token pairs.
Extra usage must remain disabled; this integration does not enable it.

Restart Pi after an approved targeted apply (or use `/reload`).
Codex remains the default. `/claude-compat-status` is the upstream status command.
Removing the companion leaves upstream Compat unguarded, not disabled.

## Proxy mode (separate provider)

`claude-compat-proxy` is a second, separate provider. It is loaded from the
cartwmic fork `cartwmic/pi-claude-request-compat`, pinned in Pi settings to
commit `b322f9d81530d80230483213470674ba8cf048dc` (package `extensions: []`).
It sends the same validated Claude Code request to the CLIProxyAPI hub at
`https://cliproxy.internal.cartwmic.com`, which holds the Claude logins.

- Its only credential is a CLIProxyAPI client key (`cpa_…`), read at request
  time through `op_read_cached.sh` from 1Password item
  `h4x7srdscdac36wnvuq4xawr5u` field `laptop-pi` (vault `developer`). It never
  touches the Anthropic login, and Anthropic tokens and API keys are rejected.
- The same docs guard applies to `claude-compat-proxy` / `claude-compat-proxy-messages`.
- `PROXY_ORIGIN` in `load.mjs` must match the `baseUrl` in
  `private_models.json.tmpl`; a test checks this.
- If the fork is not installed, the proxy is skipped. A proxy load failure shows
  a warning and never disables `claude-compat`.
- `claude-compat`, its models and its settings pin are unchanged.
- Extra usage must stay off on every account the hub holds.

Check from the dotfiles root:

```sh
node --test dot_pi/private_agent/extensions/claude-compat-guard/*.test.mjs
```

Source and live apply procedure belongs to the repository `AGENTS.md`.
