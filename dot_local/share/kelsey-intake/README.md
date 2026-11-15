# Kelsey intake

Kelsey sends a link or a note from her phone; Michael's agents pick it up and look into it. Personal Linux only (the board lives there).

- **Page:** a shartifacts html artifact, `https://shartifacts.internal.cartwmic.com/view/474a4545350b9e099b354152`. Source: `page.html` here. It stores each submission in the page's own database as `submissions/<id>` = `{text, ask, status, created}`. `status` is `new`, `picked_up` or `answered`. Republish after an edit: `PUT /api/artifacts/474a4545350b9e099b354152` with `{"base_version": N, "content": <page.html>}` (skill `using-shartifacts`).
- **Pickup:** `~/.local/user_scripts/kelsey_intake.py`, run every 15 minutes by `kelsey-intake.timer`. It files each `new` submission as a `BD` line in the board's New box (`board add BD --tag agent`, the note carries the submission id), then sets the submission to `picked_up` with its `board_ref`. Log: `journalctl --user -u kelsey-intake`. Run by hand with `--dry-run` to see what it would file.
- **Answering** is the normal agent workflow: whoever answers sets `status` to `answered` and writes the reply into the submission's `answer` field (`artifact_db` op `update`); the page shows it under the item.
- **Reach:** household Wi-Fi reaches only what `k8s/household-gate` (homelab repo) serves, so her phone needs shartifacts allowed there.
- Check: `python3 -m unittest discover -s tests/kelsey-intake` (fake shartifacts server, fake board CLI).
