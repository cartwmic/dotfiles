# Native BTW session support (Pi 1.1.0, 1.2.0, 1.3.0, 1.4.0+)

Checked source blocks provide synchronous conversation capture, source-entry provenance,
exclusive overlay input, and hosted native UI visibility/cancellation with paused dialog
countdowns. Current session identity is atomically published at replacement binding and before/after normal shutdown cleanup, not only by the control poll. SDK and bundled frontend counterparts are patched together. These hooks do
not create a side session or change configured tools/resources.

Desktop profiles `personal` and `axon-work-computer` apply the patch. Other profiles
reverse only matching owned blocks; unknown drift fails without a whole-file restore.
`--check` stages/validates changes without writing; `--rollback` reverses owned blocks.
`patch.mjs` selects by Pi minor series (`../pi-select.mjs`): `patch.pi-1.1.mjs` + `edits.json` for exact Pi 1.1.0,
`patch.pi-1.2.mjs` + `edits.pi-1.2.json` for exact Pi 1.2.0, `patch.pi-1.3.mjs` + `edits.pi-1.3.json` for exact Pi 1.3.0,
`patch.pi-1.4.mjs` + `edits.pi-1.4.json` for Pi 1.4.0 and later (anchor-gated; bundle chunks found by content, not name). Each payload preserves unrelated sibling edits outside its
checked anchors. An anchor conflict requires inspection, not replacement of installed files.

Local development checks must set `PI_ROOT` to an owned private copy. Do not run the
global apply script, chezmoi, or patch the installed runtime under a local-test approval.
The native popup milestone and any live deployment require separate validation/approval.

The maintained popup is intentionally text-only for child image display. Child images are unsupported; stored conversation/model images remain intact. Main-session image lines may still obscure popup rows: the parent compositor is not changed by this support patch. No native/profile fidelity clearance is implied. The failed 18-entry image delta was removed while preserving the exact 100-entry predecessor patch.
