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
