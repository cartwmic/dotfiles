# pi-patch: cursor-provider (retired)

This patch is **retired**. Both chezmoi profiles install the maintained fork
[`https://github.com/cartwmic/pi-sub`](https://github.com/cartwmic/pi-sub)
instead of `npm:@marckrenn/pi-sub-bar`. That fork has an in-tree Cursor
provider and reads Cursor remaining/spend from `metricSet` in
`~/.pi/agent/pi-sub-bar-settings.json`. The work-only runtime splice is not
part of desired state.

## Desired state

Unpatched on **every** profile, including `axon-work-computer`:

- Restore leftover splices in `~/.pi/agent/npm/node_modules/@marckrenn/pi-sub-{shared,core,bar}` from `<file>.orig.chezmoi-pi-patch` (or reverse the closed-union edits).
- Remove dropped `pi-sub-core/src/providers/impl/cursor.ts`.
- Do **not** apply the splice.

`PI_CHEZMOI_PROFILE` is ignored for apply-versus-restore. Sibling patches are
unchanged and still run from `apply_pi_patches.sh`.

`--check` exits 0 when leftover `@marckrenn/pi-sub-*` files are unspliced (or
the tree is absent in apply mode). It exits non-zero if splices or dropped
`cursor.ts` are still present.

## Why it existed

On the work profile, Cursor current-cycle spend against an included cap used
to be a runtime customization of the upstream widget: drop `payload/cursor.ts`
and splice closed provider unions. Widget upgrades wiped that tree, and the
splice could not be the shared vehicle for personal remaining plus work spend.

The fork replaces that path. Cursor remaining percent and spend dollars come
from Cursor dashboard APIs (`/api/usage-summary`, team/hard-limit, aggregated
events). Profile `metricSet` chooses remaining percent vs remaining dollars;
there is no chezmoi dollar cap and no compiled pi-sub constant.

## What the leftover payload still contains

`patch.mjs` and `payload/cursor.ts` remain so a machine that still has the
old splice can restore to upstream `@marckrenn` sources. They are not a
delivery vehicle. Do not re-enable `wantPatched`.

**Former target (leftover only):**

`~/.pi/agent/npm/node_modules/@marckrenn/pi-sub-{shared,core,bar}`

Not `@earendil-works/pi-coding-agent/dist/`, and not the GitHub-installed
`cartwmic/pi-sub` tree.

## Verify

```sh
PI_CHEZMOI_PROFILE=axon-work-computer node patch.mjs           # restore / no-op
PI_CHEZMOI_PROFILE=axon-work-computer node patch.mjs --check   # exit 0 when unspliced
PI_CHEZMOI_PROFILE=personal node patch.mjs --check
```

After restore, `grep chezmoi-pi-patch:cursor-provider` on the leftover
`@marckrenn/pi-sub-*` sources should find no hits, and dropped `cursor.ts`
should be absent.

## Removal

This directory can stay so chezmoi apply keeps restoring leftovers. Deleting
it is optional once no machine still has the spliced npm tree. Reinstalling
the old `@marckrenn/pi-sub-*` packages is not required for the fork.
