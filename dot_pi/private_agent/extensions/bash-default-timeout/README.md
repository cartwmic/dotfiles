# bash-default-timeout (Pi extension)

Pi's `bash` tool has no timeout unless the model passes one. A command that hangs holds the agent until someone
notices: an `op item get` waiting on a locked 1Password app sat 17 minutes, and a recursive `grep` over
`~/Library/Application Support` ran 4 h 19 m (retro proposal #4).

This extension gives every `bash` call that sets no `timeout` a default one. Pi kills the command's whole process tree
when it expires and returns "Command timed out after N seconds". The extension adds one line telling the model the limit
was a default and that it can run the command again with a larger `timeout`.

- **Limit:** `defaultTimeoutSeconds` in `~/.pi/agent/extensions/bash-default-timeout/config.json`, default **600**.
  The file is seeded once by [create_config.json](./create_config.json); later applies leave your edit alone.
  A missing file, or a value that is not a positive number up to 2,000,000, falls back to 600.
- **A call that sets its own `timeout` is untouched**, so builds and gates that need an hour ask for one.
- **Covers** the model's `bash` calls, including those made from `codemode` scripts. It does not touch the `!` / `!!`
  commands you type yourself.
- **Restart Pi** after changing the file (the limit is read when the extension loads).

Tests: `node --test dot_pi/private_agent/extensions/bash-default-timeout/index.test.ts` (helpers and handlers) and
`python3 tests/bash-default-timeout/proof.py` (a real Pi runs a bash call past the limit; it uses a scripted model and a
private agent directory, not `~/.pi`).
