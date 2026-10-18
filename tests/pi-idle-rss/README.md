# Pi idle-memory measurement (cartwmic/dotfiles#14)

`pi_idle_rss.py` starts **disposable interactive Pi sessions** in a pseudo-terminal, one at a time, waits for
memory to settle and records resident memory (RSS, `ps`) and footprint (`footprint`, includes compressed and
swapped pages) separately, for the Pi process and for the **owned set** (Pi plus everything it started: MCP servers,
recap workers, helper apps). It never touches a session it did not start, and never reads session contents.

This directory is source-only (`./tests/` is ignored by `chezmoi apply`).

## Use

```sh
python3 tests/pi-idle-rss/pi_idle_rss.py preflight --variant full --json     # isolation check, no Pi launched
python3 tests/pi-idle-rss/pi_idle_rss.py measure --variants core,full --samples 3 --out DIR
python3 tests/pi-idle-rss/pi_idle_rss.py measure --variants attribution --samples 1 --out DIR
python3 tests/pi-idle-rss/pi_idle_rss.py aged --variant full --sizes small,medium,large --samples 3 --out DIR
python3 tests/pi-idle-rss/pi_idle_rss.py report --in DIR --out DIR/report.md
python3 tests/pi-idle-rss/pi_idle_rss.py scan-post DIR/report.md                # before posting anything
python3 -m unittest discover -s tests/pi-idle-rss                                # seam tests; not outcome proof
```

Variants: `core` (empty config), `full` (the deployed config), `full-nomcp`, `full-pkg:SUBSTR`, `full-mcp:NAME`,
`full-ext:a+b` / `full-ext:*`; combine with `/`. `attribution` expands to core, full, full minus each package, each MCP
server and halves of the local extensions.

Lazy MCP variants (the pi-mcp-lazy stand-in, see dot_local/share/pi-mcp-lazy/README.md): `full-lazy` renders the MCP entries with
the real Pi rendering step (apply_harness_config.sh) in a scratch home, so the three local servers are wrapped and their state
copies are built by the refresh mode; `full-lazy-nostate` is the same without the state copies (the shipped seed is served);
`full-lazy-failedrefresh` is rendered with a refresh that fails (wrapped, no state copy). The report adds a table of MCP server
processes per accepted sample (stand-ins counted apart from real servers and their npm wrappers).

A sample is **settled** when owned RSS varies by 3% or less over three 10 s readings (after a minimum settle time).
Reported figures are medians of three readings per session, then per-variant median, min and max over sessions.

## Isolation (why not just PI_CODING_AGENT_DIR)

Several local extensions read `~/.pi/agent/auth.json` through the home directory and one reads the macOS Keychain with
`security find-generic-password`, so every session gets:

1. a **throwaway HOME** (`~/.pi/agent` inside it is the throwaway config; credential files are never copied; large package
   checkouts and the offline npx cache are APFS clones, so nothing writes to the originals);
2. an **allowlisted environment** (no tokens, API keys, 1Password or cloud variables) and a PATH whose first entries are
   failing stubs for `security` and `op`;
3. a **scripted loopback model backend** (no provider traffic, no credentials; `synthetic-not-a-credential` placeholders);
4. an **isolation check** run in the exact launch environment: HOME resolves to the throwaway dir, no credential-looking
   file or variable is reachable, a Keychain lookup fails, and the recap CLI works against the throwaway store.
   Output is pass/fail and counts only. A failed check aborts the variant before Pi starts;
5. **process ownership by a per-sample environment marker** (not process group, not name): recap and some helpers start
   detached workers. Teardown signals only marker-owned processes, then verifies none remain; otherwise the run halts.

## What a sample must satisfy to count

- **Settled:** owned RSS varies by 3% or less over three 10 s readings; an unsettled sample is discarded and retried (three attempts, then the run stops).
- **Dependencies accounted for:** the preflight scans the local extensions for home-relative paths and credential references and fails the variant if any is unaccounted for (a credential helper that resolves to a real binary, a credential-looking file, a missing recap CLI). `security`, `op` and `ssh-agent` are stubbed.
- **Registered commands (first sample of each variant):** the editor's command menu is the record of what the loaded extensions registered. The tool types one representative command per loaded extension or package (every literal command for `full`) and requires the menu to list it; commands that call themselves internal are skipped; nothing is executed. Every extension and package must also appear in Pi's own startup `[Extensions]` header (which lists commandless, hook-only owners too), and any load-error marker rejects the sample. For variants that remove a part, a command that stops registering because its owner depended on the removed part is recorded as a variant effect instead of rejecting the sample. This shows each kept extension loaded and registered, not that its commands work. The recap CLI is additionally exercised for real. Credential-backed behaviour is not exercised.
- **Extension groups:** the two `full-ext:` attribution groups follow the relative-import graph between extensions (for example `standing-reminder` imports `inspect-prompt`), so removing one group never breaks a survivor.
- **Aged stages:** `/compact` must leave a compaction entry in the session file; `/reload` must be verified from process state: an extension-owned child process existed before it, at least one of those is gone afterwards, and at least one new one has started (a child that merely exits is not a reload). Otherwise the sample is discarded. A `/reload` typed as the very first command of a session leaves the children unchanged and cannot be verified, so the reload-only case is run as one turn then `/reload` (tag `[turn+reload]`). Runs with a different stage set carry a distinct tag (for example `aged-large[reload]`) and are never pooled with the full sequence.
- **Report:** rows with fewer than three samples are flagged; the numeric unexplained remainder is (full - core) minus the parts whose removal saves more than the full configuration's noise floor.

Memory pressure is checked before each launch and before each heavy in-session step (load, `/compact`, `/reload`);
a watcher discards the sample and backs off if pressure rises.

## Limitations (read before quoting numbers)

- The scripted backend means provider-specific extensions (for example Claude Compat) are installed but inactive and
  recall hooks have no credentials, so fresh-session figures differ from a live session.
- Stdio MCP servers (`npm exec` trees) start in the throwaway HOME and are larger there than in a live session;
  use the Pi-process figures for conclusions and the owned-set figures only as an upper bound.
- Aged sessions are synthetic and content-free; they are sized from byte count and message count of the longest real
  session idle for an hour (metadata only). Real content shape (tool results, images) is not reproduced.
- Credential-backed extensions are smoke-checked only to "loads without error"; their own hermetic tests (for example
  `dot_pi/private_agent/extensions/web-search/codex.test.ts`) are the functional evidence when such an extension changes.

Results of the first investigation (Pi 1.2.0, 2026-10-17): [RESULTS-pi-1.2.0-2026-10-17.md](./RESULTS-pi-1.2.0-2026-10-17.md). A short summary is on cartwmic/dotfiles#14; this README is the authoritative description of the procedure.
